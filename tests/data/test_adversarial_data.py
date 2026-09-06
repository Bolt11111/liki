"""Malformed-provider, schema, timestamp, and gap checks for data admission."""

import asyncio
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal

import httpx
import pytest

from liki.data import (
    BinanceMarket,
    BinanceMarketDataClient,
    CanonicalMarketRecord,
    DatasetValidator,
    PriceKind,
    ProviderResponseError,
)


NOW = datetime(2026, 1, 1, tzinfo=UTC)


def test_binance_rejects_malformed_json_and_kline_rows_instead_of_inventing_data():
    async def malformed_json() -> None:
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda _: httpx.Response(200, content=b"not-json")),
            base_url="https://api.binance.com",
        ) as http:
            with pytest.raises(ProviderResponseError, match="invalid JSON"):
                await BinanceMarketDataClient(BinanceMarket.SPOT, http).server_time()

    async def malformed_kline() -> None:
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda _: httpx.Response(200, json=[[1, "1"]])),
            base_url="https://api.binance.com",
        ) as http:
            with pytest.raises(ProviderResponseError, match="malformed kline"):
                await BinanceMarketDataClient(BinanceMarket.SPOT, http).fetch_klines(
                    symbol="BTCUSDT", interval="1m", start_time_ms=0, end_time_ms=10
                )

    asyncio.run(malformed_json())
    asyncio.run(malformed_kline())


def test_binance_rejects_malformed_exchange_metadata_schema():
    async def malformed_metadata() -> None:
        response = {
            "symbols": [
                {
                    "symbol": "BTCUSDT",
                    "status": "TRADING",
                    "baseAsset": "BTC",
                    "quoteAsset": "USDT",
                    "filters": [],
                }
            ]
        }
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda _: httpx.Response(200, json=response)),
            base_url="https://api.binance.com",
        ) as http:
            with pytest.raises(ProviderResponseError, match="malformed exchangeInfo"):
                await BinanceMarketDataClient(BinanceMarket.SPOT, http).exchange_info("BTCUSDT")

    asyncio.run(malformed_metadata())


def test_timestamp_and_gap_checks_fail_closed_without_forward_fill():
    with pytest.raises(ValueError, match="UTC"):
        CanonicalMarketRecord(
            instrument_id="binance:BTCUSDT",
            event_time=NOW.astimezone(timezone(timedelta(hours=-5))),
            available_at=NOW,
            price=Decimal("100"),
            quantity=Decimal("1"),
            price_kind=PriceKind.TRADE,
            raw_payload_hash="sha256:" + "a" * 64,
        )
    records = [
        CanonicalMarketRecord(
            instrument_id="binance:BTCUSDT",
            event_time=NOW + timedelta(minutes=minute),
            available_at=NOW + timedelta(minutes=minute),
            price=Decimal("100"),
            quantity=Decimal("1"),
            price_kind=PriceKind.TRADE,
            raw_payload_hash="sha256:" + "a" * 64,
        )
        for minute in (0, 10)
    ]
    findings = DatasetValidator(
        max_gap=timedelta(minutes=1), max_staleness=timedelta(hours=1)
    ).validate(records)
    assert [finding.kind.value for finding in findings] == ["gap"]
