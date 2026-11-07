from exchange_router.exchanges.binance.adapter import BinanceAdapter
from exchange_router.models import MarketType


HOUR = 3_600_000

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

GTCUSDT_FUNDING_INFO = {
    "symbol":                   "GTCUSDT",
    "adjustedFundingRateCap":   "0.02000000",
    "adjustedFundingRateFloor": "-0.02000000",
    "fundingIntervalHours":     4,
    "disclaimer":               False,
    "updateTime":               1791950460152,
}

GTCUSDT_SETTLEMENTS = [
    [1791835200000, "-0.00066814"], [1791838800004, "-0.00100241"], [1791842400004, "-0.00097913"],
    [1791846000000, "-0.00090636"], [1791849600002, "-0.00078834"], [1791853200002, "-0.00070577"],
    [1791856800000, "-0.00036364"], [1791860400000, "-0.00039317"], [1791864000001, "-0.00024915"],
    [1791867600000, "-0.00036961"], [1791871200002, "-0.00050017"], [1791874800000, "-0.00059203"],
    [1791878400005, "-0.00044575"], [1791882000005, "-0.00046537"], [1791885600000, "-0.00057111"],
    [1791889200004, "-0.00046327"], [1791892800002, "-0.00031825"], [1791896400000, "-0.00023639"],
    [1791900000000, "-0.00020144"], [1791903600000, "-0.00012672"], [1791907200000, "-0.00009223"],
    [1791910800000, "-0.00003377"], [1791914400000, "-0.00004429"], [1791918000000, "-0.00000424"],
    [1791921600000, "-0.00001563"], [1791925200002, "-0.00003571"], [1791928800000, "-0.00005907"],
    [1791932400000, "-0.00006408"], [1791936000001, "-0.00010713"], [1791939600000, "-0.00009064"],
    [1791943200000, "-0.00006804"], [1791946800004, "0.00001250"], [1791950400005, "-0.00003168"],
    [1791964800001, "-0.00006988"], [1791979200000, "-0.00005128"],
]


async def binance(method, url, params=None):
    if url.endswith("/exchangeInfo"):
        return {"symbols": [GTCUSDT]}
    if url.endswith("/fundingInfo"):
        return [GTCUSDT_FUNDING_INFO]
    rows = GTCUSDT_SETTLEMENTS
    if "startTime" in params or "endTime" in params:
        window = [r for r in rows if params.get("startTime", 0) <= r[0] <= params.get("endTime", rows[-1][0])]
        chosen = window[:params["limit"]]
    else:
        chosen = rows[-params["limit"]:]
    return [{"symbol": "GTCUSDT", "fundingTime": r[0], "fundingRate": r[1]} for r in chosen]


async def test_a_page_ending_at_start_holds_the_newest_rows_before_it():
    adapter = BinanceAdapter()
    adapter._make_request = binance
    try:
        rows = await adapter.get_funding_rate(MarketType.LINEAR, "GTCUSDT", 1791979200000, 4)
    finally:
        await adapter.shutdown()

    assert [row.timestamp for row in rows]               == [1791946800004, 1791950400005, 1791964800001, 1791979200000]
    assert [row.rate.cycle_ms / HOUR for row in rows]    == [1, 1, 4, 4]
    assert [row.rate.per_cycle for row in rows]          == [0.0000125, -0.00003168, -0.00006988, -0.00005128]
