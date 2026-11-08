from exchange_router.exchanges.hyperliquid.adapter import HyperliquidAdapter
from exchange_router.models import MarketType


HOUR = 3_600_000

SPOT_META = {
    "tokens": [
        {"name": "USDC", "szDecimals": 8, "weiDecimals": 8, "index": 0},
        {"name": "MANLET", "szDecimals": 0, "weiDecimals": 5, "index": 4},
        {"name": "ANSEM", "szDecimals": 0, "weiDecimals": 5, "index": 19},
    ],
    "universe": [
        {"tokens": [4, 0], "name": "@3", "index": 3, "isCanonical": False},
        {"tokens": [19, 0], "name": "@18", "index": 18, "isCanonical": False},
    ],
}

SPOT_CTXS = [
    {"prevDayPx": "0.0055", "dayNtlVlm": "0.0", "markPx": "0.0055", "midPx": "0.0052505", "coin": "@3", "dayBaseVlm": "0.0"},
    {"prevDayPx": "0.01003", "dayNtlVlm": "14.8444", "markPx": "0.01003", "midPx": "0.010045", "coin": "@18", "dayBaseVlm": "1480.0"},
]


def bar(opened, volume, trades):
    return {"t": opened, "T": opened + HOUR - 1, "s": "@18", "i": "1h", "o": "0.01003", "c": "0.01003", "h": "0.01003", "l": "0.01003", "v": volume, "n": trades}


ANSEM_BARS = [bar(1794009600000 + i * HOUR, "0.0", 0) for i in range(15)] + [bar(1794063600000, "1480.0", 1)]


async def hyperliquid(info_type, body):
    if info_type == "spotMeta":
        return SPOT_META
    if info_type == "spotMetaAndAssetCtxs":
        return [SPOT_META, SPOT_CTXS]
    if info_type == "candleSnapshot":
        return ANSEM_BARS if body["req"]["coin"] == "@18" else []
    raise AssertionError(info_type)


async def tickers(*symbols):
    adapter = HyperliquidAdapter()
    adapter._make_request = hyperliquid
    try:
        return [await adapter.get_ticker(MarketType.SPOT, symbol) for symbol in symbols]
    finally:
        await adapter.shutdown()


def day(row):
    return [row.price, row.open_24h, row.high_24h, row.low_24h]


async def test_no_trade_in_a_day_reads_as_no_range_beside_a_live_mid():
    manlet, = await tickers("MANLETUSDC")

    assert day(manlet) == [0.0052505, 0.0055, 0.0, 0.0]


async def test_a_mid_above_every_trade_is_not_the_days_high():
    ansem, = await tickers("ANSEMUSDC")

    assert day(ansem) == [0.010045, 0.01003, 0.01003, 0.01003]
