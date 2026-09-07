"""Public Binance Spot and USDⓈ-M Futures data adapters.

Endpoints and update semantics follow Binance's published REST documentation.  The
adapter deliberately exposes rate limiting and malformed provider replies instead
of retrying into an unknown freshness state.
"""

from __future__ import annotations

import json
from datetime import datetime, UTC
from decimal import Decimal
from enum import StrEnum
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .models import RawPayload, ensure_utc


class ProviderResponseError(RuntimeError):
    def __init__(self, status_code: int, message: str, body: bytes = b"") -> None:
        super().__init__(f"Binance response {status_code}: {message}")
        self.status_code = status_code
        self.body = body


class ProviderRateLimited(ProviderResponseError):
    def __init__(self, status_code: int, retry_after_seconds: int | None, body: bytes) -> None:
        super().__init__(status_code, "rate limited", body)
        self.retry_after_seconds = retry_after_seconds


class BinanceMarket(StrEnum):
    SPOT = "spot"
    USD_M_PERPETUAL = "usd_m_perpetual"


class BinanceKline(BaseModel):
    model_config = ConfigDict(frozen=True)

    open_time: datetime
    close_time: datetime
    open: Decimal = Field(gt=0)
    high: Decimal = Field(gt=0)
    low: Decimal = Field(gt=0)
    close: Decimal = Field(gt=0)
    volume: Decimal = Field(ge=0)
    quote_volume: Decimal = Field(ge=0)
    trade_count: int = Field(ge=0)
    complete: bool

    _utc = field_validator("open_time", "close_time")(ensure_utc)

    @model_validator(mode="after")
    def valid_ohlc_range(self) -> BinanceKline:
        if not self.low <= min(self.open, self.close) <= self.high or self.open > self.high:
            raise ValueError("kline OHLC values violate their reported range")
        if self.close_time < self.open_time:
            raise ValueError("kline close time precedes open time")
        return self


class BinanceKlinePage(BaseModel):
    model_config = ConfigDict(frozen=True)

    market: BinanceMarket
    symbol: str
    interval: str
    klines: tuple[BinanceKline, ...]
    raw_payload: RawPayload
    next_start_time_ms: int | None


class BinanceInstrument(BaseModel):
    """Live metadata only; callers must save it as an effective-dated spec snapshot."""

    model_config = ConfigDict(frozen=True)

    market: BinanceMarket
    symbol: str
    status: str
    base_asset: str
    quote_asset: str
    margin_asset: str | None = None
    contract_type: str | None = None
    filters: dict[str, dict[str, str]]
    raw_payload: RawPayload

    @property
    def tick_size(self) -> Decimal:
        return Decimal(self.filters["PRICE_FILTER"]["tickSize"])

    @property
    def lot_size(self) -> Decimal:
        filter_ = self.filters.get("LOT_SIZE") or self.filters["MARKET_LOT_SIZE"]
        return Decimal(filter_["stepSize"])

    @property
    def min_notional(self) -> Decimal | None:
        filter_ = self.filters.get("MIN_NOTIONAL") or self.filters.get("NOTIONAL")
        if filter_ is None:
            return None
        value = filter_.get("minNotional")
        return Decimal(value) if value is not None else None


class BinanceDerivativeReference(BaseModel):
    """Published futures price definitions remain distinct in downstream evaluation."""

    model_config = ConfigDict(frozen=True)

    symbol: str
    mark_price: Decimal = Field(gt=0)
    index_price: Decimal = Field(gt=0)
    last_funding_rate: Decimal
    next_funding_time: datetime
    raw_payload: RawPayload

    _utc = field_validator("next_funding_time")(ensure_utc)


class BinanceMarketDataClient:
    """REST client with explicit source provenance for every public response."""

    BASE_URLS = {
        BinanceMarket.SPOT: "https://api.binance.com",
        BinanceMarket.USD_M_PERPETUAL: "https://fapi.binance.com",
    }

    def __init__(self, market: BinanceMarket, client: httpx.AsyncClient | None = None) -> None:
        self.market = market
        self._client = client or httpx.AsyncClient(base_url=self.BASE_URLS[market], timeout=20.0)
        self._owns_client = client is None

    async def __aenter__(self) -> BinanceMarketDataClient:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    @property
    def _prefix(self) -> str:
        return "/api/v3" if self.market == BinanceMarket.SPOT else "/fapi/v1"

    async def _get(self, path: str, params: dict[str, Any] | None = None) -> tuple[Any, RawPayload]:
        response = await self._client.get(path, params=params)
        body = response.content
        if response.status_code in {418, 429}:
            retry_after = response.headers.get("Retry-After")
            try:
                seconds = int(retry_after) if retry_after is not None else None
            except ValueError:
                seconds = None
            raise ProviderRateLimited(response.status_code, seconds, body)
        if response.status_code >= 400:
            try:
                message = response.json().get("msg", response.reason_phrase)
            except (json.JSONDecodeError, ValueError):
                message = response.reason_phrase
            raise ProviderResponseError(response.status_code, message, body)
        try:
            data = response.json()
        except (json.JSONDecodeError, ValueError) as error:
            raise ProviderResponseError(response.status_code, "invalid JSON", body) from error
        retrieved_at = datetime.now(UTC)
        raw = RawPayload.from_bytes(
            provider="binance",
            uri=str(response.request.url),
            content=body,
            retrieved_at=retrieved_at,
            transport_metadata={
                key.lower(): value
                for key, value in response.headers.items()
                if key.lower().startswith("x-mbx-used-weight") or key.lower() == "retry-after"
            },
        )
        return data, raw

    async def server_time(self) -> tuple[datetime, RawPayload]:
        data, raw = await self._get(f"{self._prefix}/time")
        try:
            return datetime.fromtimestamp(int(data["serverTime"]) / 1000, tz=UTC), raw
        except (KeyError, TypeError, ValueError) as error:
            raise ProviderResponseError(200, "missing or invalid serverTime") from error

    async def exchange_info(self, symbol: str | None = None) -> tuple[BinanceInstrument, ...]:
        params = {"symbol": symbol.upper()} if symbol else None
        data, raw = await self._get(f"{self._prefix}/exchangeInfo", params)
        try:
            symbols = data["symbols"]
        except (KeyError, TypeError) as error:
            raise ProviderResponseError(200, "exchangeInfo missing symbols") from error
        instruments: list[BinanceInstrument] = []
        for item in symbols:
            try:
                filters = {filter_["filterType"]: filter_ for filter_ in item.get("filters", [])}
                if (
                    "PRICE_FILTER" not in filters
                    or not {"LOT_SIZE", "MARKET_LOT_SIZE"} & filters.keys()
                ):
                    raise ValueError("exchangeInfo symbol has required filters missing")
                instruments.append(
                    BinanceInstrument(
                        market=self.market,
                        symbol=item["symbol"],
                        status=item["status"],
                        base_asset=item["baseAsset"],
                        quote_asset=item["quoteAsset"],
                        margin_asset=item.get("marginAsset"),
                        contract_type=item.get("contractType"),
                        filters=filters,
                        raw_payload=raw,
                    )
                )
            except (KeyError, TypeError, ValueError) as error:
                raise ProviderResponseError(200, "malformed exchangeInfo symbol") from error
        return tuple(instruments)

    async def fetch_klines(
        self,
        *,
        symbol: str,
        interval: str,
        start_time_ms: int,
        end_time_ms: int,
        limit: int = 1000,
    ) -> BinanceKlinePage:
        if start_time_ms < 0 or end_time_ms <= start_time_ms or not 1 <= limit <= 1500:
            raise ValueError("invalid bounded Binance kline request")
        data, raw = await self._get(
            f"{self._prefix}/klines",
            {
                "symbol": symbol.upper(),
                "interval": interval,
                "startTime": start_time_ms,
                "endTime": end_time_ms,
                "limit": limit,
            },
        )
        if not isinstance(data, list):
            raise ProviderResponseError(200, "klines response is not an array")
        klines: list[BinanceKline] = []
        for row in data:
            if not isinstance(row, list) or len(row) < 9:
                raise ProviderResponseError(200, "malformed kline row")
            try:
                klines.append(
                    BinanceKline(
                        open_time=datetime.fromtimestamp(int(row[0]) / 1000, tz=UTC),
                        open=Decimal(str(row[1])),
                        high=Decimal(str(row[2])),
                        low=Decimal(str(row[3])),
                        close=Decimal(str(row[4])),
                        volume=Decimal(str(row[5])),
                        close_time=datetime.fromtimestamp(int(row[6]) / 1000, tz=UTC),
                        quote_volume=Decimal(str(row[7])),
                        trade_count=int(row[8]),
                        complete=int(row[6]) < int(datetime.now(UTC).timestamp() * 1000),
                    )
                )
            except (ArithmeticError, IndexError, TypeError, ValueError) as error:
                raise ProviderResponseError(200, "invalid numeric kline field") from error
        next_start = int(data[-1][6]) + 1 if len(data) == limit else None
        return BinanceKlinePage(
            market=self.market,
            symbol=symbol.upper(),
            interval=interval,
            klines=tuple(klines),
            raw_payload=raw,
            next_start_time_ms=next_start,
        )

    async def paginate_klines(
        self,
        *,
        symbol: str,
        interval: str,
        start_time_ms: int,
        end_time_ms: int,
        limit: int = 1000,
    ) -> tuple[BinanceKlinePage, ...]:
        """Request non-overlapping pages; caller persists each raw payload before use."""
        pages: list[BinanceKlinePage] = []
        next_start = start_time_ms
        while next_start < end_time_ms:
            page = await self.fetch_klines(
                symbol=symbol,
                interval=interval,
                start_time_ms=next_start,
                end_time_ms=end_time_ms,
                limit=limit,
            )
            pages.append(page)
            if page.next_start_time_ms is None or page.next_start_time_ms <= next_start:
                break
            next_start = page.next_start_time_ms
        return tuple(pages)

    async def funding_rates(
        self, *, symbol: str, start_time_ms: int, end_time_ms: int, limit: int = 1000
    ) -> tuple[tuple[dict[str, str], ...], RawPayload]:
        if self.market != BinanceMarket.USD_M_PERPETUAL:
            raise ValueError("funding rates only apply to USDⓈ-M perpetuals")
        data, raw = await self._get(
            "/fapi/v1/fundingRate",
            {
                "symbol": symbol.upper(),
                "startTime": start_time_ms,
                "endTime": end_time_ms,
                "limit": limit,
            },
        )
        if not isinstance(data, list):
            raise ProviderResponseError(200, "funding rate response is not an array")
        return tuple({str(key): str(value) for key, value in row.items()} for row in data), raw

    async def premium_index(self, symbol: str) -> BinanceDerivativeReference:
        if self.market != BinanceMarket.USD_M_PERPETUAL:
            raise ValueError("premium index only applies to USDⓈ-M perpetuals")
        data, raw = await self._get("/fapi/v1/premiumIndex", {"symbol": symbol.upper()})
        try:
            return BinanceDerivativeReference(
                symbol=data["symbol"],
                mark_price=Decimal(data["markPrice"]),
                index_price=Decimal(data["indexPrice"]),
                last_funding_rate=Decimal(data["lastFundingRate"]),
                next_funding_time=datetime.fromtimestamp(
                    int(data["nextFundingTime"]) / 1000, tz=UTC
                ),
                raw_payload=raw,
            )
        except (KeyError, TypeError, ValueError) as error:
            raise ProviderResponseError(200, "invalid premium index response") from error
