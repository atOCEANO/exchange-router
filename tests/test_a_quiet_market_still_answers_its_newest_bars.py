from exchange_router import frames
from exchange_router.exchanges.hyperliquid.adapter import HyperliquidAdapter
from exchange_router.exchanges.kucoin.adapter import KucoinAdapter
from exchange_router.models import MarketType


NOW_MS = 1794098727000

KUCOIN_RUNE = {
    "symbol":         "RUNE-USDC",
    "baseCurrency":   "RUNE",
    "quoteCurrency":  "USDC",
    "baseMinSize":    "0.1",
    "baseMaxSize":    "10000000000",
    "baseIncrement":  "0.0001",
    "priceIncrement": "0.0001",
    "minFunds":       "0.1",
    "enableTrading":  True,
}

KUCOIN_RUNE_NEWEST = [
    ["1794004860", "0.5914", "0.592", "0.592", "0.5914", "21.8594", "12.94076468"],
    ["1794004800", "0.5914", "0.5914", "0.5914", "0.5914", "0", "0"],
    ["1794004740", "0.5914", "0.5914", "0.5914", "0.5914", "0", "0"],
    ["1794004680", "0.5914", "0.5914", "0.5914", "0.5914", "0", "0"],
]

HYPERLIQUID_META = {
    "tokens": [
        {"name": "USDC", "szDecimals": 8, "weiDecimals": 8, "index": 0},
        {"name": "MANLET", "szDecimals": 0, "weiDecimals": 5, "index": 4},
    ],
    "universe": [{"tokens": [4, 0], "name": "@3", "index": 3, "isCanonical": False}],
}


def manlet(opened, price, volume, trades):
    return {"t": opened, "T": opened + 59_999, "s": "@3", "i": "1m", "o": price, "c": price, "h": price, "l": price, "v": volume, "n": trades}


HYPERLIQUID_MANLET_NEWEST = [
    manlet(1793706420000, "0.0010006", "0.0", 0),
    manlet(1793706480000, "0.0010006", "0.0", 0),
    manlet(1793706540000, "0.0010006", "0.0", 0),
    manlet(1793706600000, "0.0055", "2020.0", 1),
]


async def kucoin(method, base, endpoint, params=None):
    if endpoint == "/api/v1/symbols":
        return [KUCOIN_RUNE]
    return KUCOIN_RUNE_NEWEST if params["startAt"] == 1 else []


async def hyperliquid(info_type, body):
    if info_type == "spotMeta":
        return HYPERLIQUID_META
    return HYPERLIQUID_MANLET_NEWEST if body["req"]["startTime"] == 0 else []


async def candles(adapter, answer, symbol, start_time, limit):
    adapter._make_request = answer
    try:
        return await adapter.get_candles(MarketType.SPOT, symbol, "1m", start_time, limit)
    finally:
        await adapter.shutdown()


def closes(rows):
    return [(row.timestamp, row.close, row.volume.native) for row in rows]


async def test_kucoin_answers_a_pair_quiet_since_its_last_trade_with_its_newest_bars():
    latest = await candles(KucoinAdapter(), kucoin, "RUNEUSDC", None, 3)
    paged  = await candles(KucoinAdapter(), kucoin, "RUNEUSDC", NOW_MS, 3)

    expected = [(1794004740000, 0.5914, 0.0), (1794004800000, 0.5914, 0.0), (1794004860000, 0.592, 21.8594)]
    assert closes(latest) == expected
    assert closes(paged)  == expected


async def test_hyperliquid_answers_a_pair_quiet_since_its_last_trade_with_its_newest_bars():
    latest = await candles(HyperliquidAdapter(), hyperliquid, "MANLETUSDC", None, 3)

    assert closes(latest) == [(1793706480000, 0.0010006, 0.0), (1793706540000, 0.0010006, 0.0), (1793706600000, 0.0055, 2020.0)]


async def test_a_short_answer_says_the_venue_holds_nothing_older():
    rows = await candles(KucoinAdapter(), kucoin, "RUNEUSDC", None, 3)
    ctx  = {"exchange": "kucoin", "market_type": "spot", "symbol": "RUNEUSDC", "requested": 5, "paginated": True}

    _, warnings = frames.build("candles", [row.model_dump(mode="json") for row in rows], ctx)

    assert warnings == ["candles kucoin/spot/RUNEUSDC: got 3 of 5 requested; kucoin holds nothing older"]
