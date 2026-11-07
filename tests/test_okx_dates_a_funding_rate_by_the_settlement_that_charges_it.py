from exchange_router.exchanges.okx.adapter import OkxAdapter
from exchange_router.models import MarketType


INSTRUMENT = {
    "instId":   "BTC-USDT-SWAP",
    "state":    "live",
    "ctType":   "linear",
    "uly":      "BTC-USDT",
    "ctVal":    "0.01",
    "tickSz":   "0.1",
    "lotSz":    "0.01",
    "minSz":    "0.01",
    "maxLmtSz": "100000000",
}

MARK_PRICE = {
    "instId":   "BTC-USDT-SWAP",
    "instType": "SWAP",
    "markPx":   "75749",
    "ts":       "1794091713589",
}

FUNDING_RATE = {
    "instId":          "BTC-USDT-SWAP",
    "instType":        "SWAP",
    "method":          "current_period",
    "fundingRate":     "0.0001000000000000",
    "fundingTime":     "1794096000000",
    "nextFundingTime": "1794124800000",
    "prevFundingTime": "1794067200000",
    "settFundingRate": "0.0000650816220143",
    "settState":       "settled",
    "ts":              "1794091706449",
}

INDEX = {
    "instId": "BTC-USDT",
    "idxPx":  "75782",
    "ts":     "1794091713360",
}


def okx():
    async def answer(method, endpoint, params=None):
        if endpoint == "/api/v5/public/instruments":
            return [INSTRUMENT] if params["instType"] == "SWAP" else []
        if endpoint == "/api/v5/public/mark-price":
            return [MARK_PRICE]
        if endpoint == "/api/v5/public/funding-rate":
            return [FUNDING_RATE]
        if endpoint == "/api/v5/market/index-tickers":
            return [INDEX]
        raise AssertionError(endpoint)
    return answer


async def test_the_deadline_is_the_settlement_that_charges_the_rate():
    adapter = OkxAdapter()
    adapter._make_request = okx()
    try:
        mark = await adapter.get_mark_price(MarketType.LINEAR, "BTCUSDT")
    finally:
        await adapter.shutdown()

    assert mark.funding.valid_until_ts == 1_794_096_000_000
    assert mark.funding.per_cycle      == 0.0001
    assert mark.funding.cycle_ms       == 8 * 3_600_000
