from exchange_router.exchanges.binance.adapter import BinanceAdapter
from exchange_router.exchanges.okx.adapter import OkxAdapter
from exchange_router.models import MarketType


GTCUSDT = {
    "symbol":            "GTCUSDT",
    "status":            "TRADING",
    "contractType":      "PERPETUAL",
    "baseAsset":         "GTC",
    "quoteAsset":        "USDT",
    "pricePrecision":    6,
    "quantityPrecision": 1,
    "filters": [
        {"filterType": "PRICE_FILTER", "tickSize": "0.000010"},
        {"filterType": "LOT_SIZE", "minQty": "0.1", "maxQty": "6000000", "stepSize": "0.1"},
        {"filterType": "MIN_NOTIONAL", "notional": "5"},
    ],
}

FUNDING_RATE = {
    "instId":          "BTC-USDT-SWAP",
    "fundingRate":     "0.0001000000000000",
    "fundingTime":     "1794096000000",
    "nextFundingTime": "1794124800000",
}


async def test_binance_reads_the_interval_again_after_fundinginfo_fails():
    failures = [2]

    async def answer(method, url, params=None):
        if url.endswith("/exchangeInfo"):
            return {"symbols": [GTCUSDT]}
        if failures[0]:
            failures[0] -= 1
            raise ValueError("Binance API Error: -1001 internal error")
        return [{"symbol": "GTCUSDT", "fundingIntervalHours": 4}]

    adapter = BinanceAdapter()
    adapter._make_request = answer
    try:
        unknown = await adapter._funding_interval_ms_for(MarketType.LINEAR, "GTCUSDT")
        read    = await adapter._funding_interval_ms_for(MarketType.LINEAR, "GTCUSDT")
    finally:
        await adapter.shutdown()

    assert unknown is None
    assert read == 4 * 3_600_000


async def test_okx_reads_the_interval_again_after_funding_rate_fails():
    failures = [1]

    async def answer(method, endpoint, params=None):
        if failures[0]:
            failures[0] -= 1
            raise ValueError("OKX API Error: 50001 service temporarily unavailable")
        return [FUNDING_RATE]

    adapter = OkxAdapter()
    adapter._make_request = answer
    try:
        unknown = await adapter._funding_interval_ms_for("BTC-USDT-SWAP")
        read    = await adapter._funding_interval_ms_for("BTC-USDT-SWAP")
    finally:
        await adapter.shutdown()

    assert unknown is None
    assert read == 8 * 3_600_000
