import asyncio

import httpx
import pytest

from liki.data.binance import BinanceMarket, BinanceMarketDataClient, ProviderRateLimited


def test_binance_pagination_and_dynamic_filters():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if request.url.path.endswith("exchangeInfo"):
            return httpx.Response(
                200,
                json={
                    "symbols": [
                        {
                            "symbol": "BTCUSDT",
                            "status": "TRADING",
                            "baseAsset": "BTC",
                            "quoteAsset": "USDT",
                            "filters": [
                                {"filterType": "PRICE_FILTER", "tickSize": "0.01"},
                                {"filterType": "LOT_SIZE", "stepSize": "0.001"},
                                {"filterType": "MIN_NOTIONAL", "minNotional": "10"},
                            ],
                        }
                    ]
                },
            )
        start = int(request.url.params["startTime"])
        rows = (
            [
                [start, "1", "2", "1", "1.5", "3", start + 1, "4", 5],
                [start + 2, "1.5", "3", "1", "2", "3", start + 3, "4", 5],
            ]
            if start == 0
            else []
        )
        return httpx.Response(200, json=rows)

    async def run():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler), base_url="https://api.binance.com"
        ) as http:
            client = BinanceMarketDataClient(BinanceMarket.SPOT, http)
            instrument = (await client.exchange_info("BTCUSDT"))[0]
            assert str(instrument.tick_size) == "0.01"
            return await client.paginate_klines(
                symbol="BTCUSDT", interval="1m", start_time_ms=0, end_time_ms=10, limit=2
            )

    pages = asyncio.run(run())
    assert len(pages) == 2 and pages[0].next_start_time_ms == 4


def test_binance_rate_limit_is_exposed():
    async def run():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda _: httpx.Response(429, headers={"Retry-After": "7"})
            ),
            base_url="https://api.binance.com",
        ) as http:
            with pytest.raises(ProviderRateLimited) as error:
                await BinanceMarketDataClient(BinanceMarket.SPOT, http).server_time()
            return error

    error = asyncio.run(run())
    assert error.value.retry_after_seconds == 7
