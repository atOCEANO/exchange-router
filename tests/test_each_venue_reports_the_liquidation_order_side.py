from exchange_router.exchanges.binance.adapter import BinanceAdapter
from exchange_router.exchanges.bybit.adapter import BybitAdapter
from exchange_router.exchanges.okx.adapter import OkxAdapter
from exchange_router.models import MarketType


BINANCE_LONG_LIQUIDATED = {
    "e": "forceOrder",
    "E": 1794092286078,
    "o": {
        "s":  "SIGNUSDT",
        "S":  "SELL",
        "o":  "LIMIT",
        "f":  "IOC",
        "q":  "19216",
        "p":  "0.0085100",
        "ap": "0.0086550",
        "X":  "FILLED",
        "l":  "19216",
        "z":  "19216",
        "T":  1794092285134,
        "ps": "SIGNUSDT",
        "st": 1,
    },
}

BINANCE_SHORT_LIQUIDATED = {
    "e": "forceOrder",
    "E": 1794092210212,
    "o": {
        "s":  "ARBUSDT",
        "S":  "BUY",
        "o":  "LIMIT",
        "f":  "IOC",
        "q":  "12057.6",
        "p":  "0.169090",
        "ap": "0.168126",
        "X":  "FILLED",
        "l":  "1604.4",
        "z":  "12057.6",
        "T":  1794092209205,
        "ps": "ARBUSDT",
        "st": 1,
    },
}

BYBIT_SHORTS_LIQUIDATED = {
    "topic": "allLiquidation.AKEUSDT",
    "type":  "snapshot",
    "ts":    1794091801243,
    "data": [
        {"T": 1794091800954, "s": "AKEUSDT", "S": "Sell", "v": "123000", "p": "0.0056960"},
        {"T": 1794091801189, "s": "AKEUSDT", "S": "Sell", "v": "17900", "p": "0.0056880"},
    ],
}

OKX_INSTRUMENT = {
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

OKX_LONG_LIQUIDATED = {
    "instFamily": "BTC-USDT",
    "instId":     "BTC-USDT-SWAP",
    "instType":   "SWAP",
    "uly":        "BTC-USDT",
    "details": [
        {"bkLoss": "0", "bkPx": "75742.8", "ccy": "", "posSide": "long", "side": "sell", "sz": "0.5", "time": 1794088895454, "ts": "1794088895454"},
    ],
}


def feed(*messages):
    async def connect(market_type, params):
        for message in messages:
            yield message
    return connect


async def streamed(adapter, symbol, answer, messages):
    adapter._make_request = answer
    adapter._ws_connect   = feed(*messages)
    try:
        return [row async for row in adapter.stream_liquidations(MarketType.LINEAR, symbol)]
    finally:
        await adapter.shutdown()


async def binance_answer(method, url, params=None):
    return [] if url.endswith("/fundingInfo") else {"symbols": []}


async def bybit_answer(method, endpoint, params=None):
    return {"list": [], "nextPageCursor": ""}


async def okx_answer(method, endpoint, params=None):
    if endpoint == "/api/v5/public/instruments":
        return [OKX_INSTRUMENT] if params["instType"] == "SWAP" else []
    if endpoint == "/api/v5/public/liquidation-orders":
        return [OKX_LONG_LIQUIDATED]
    raise AssertionError(endpoint)


async def test_binance_sends_the_order_side_and_the_router_keeps_it():
    long_rows  = await streamed(BinanceAdapter(), "SIGNUSDT", binance_answer, [BINANCE_LONG_LIQUIDATED])
    short_rows = await streamed(BinanceAdapter(), "ARBUSDT", binance_answer, [BINANCE_SHORT_LIQUIDATED])

    assert [row.side for row in long_rows]  == ["sell"]
    assert [row.side for row in short_rows] == ["buy"]


async def test_bybit_sends_the_position_side_and_the_router_turns_it_into_the_order_side():
    rows = await streamed(BybitAdapter(), "AKEUSDT", bybit_answer, [BYBIT_SHORTS_LIQUIDATED])

    assert [row.side for row in rows]  == ["buy", "buy"]
    assert [row.price for row in rows] == [0.005696, 0.005688]


async def test_okx_sends_the_order_side_beside_the_position_side():
    adapter = OkxAdapter()
    adapter._make_request = okx_answer
    try:
        rows = await adapter.get_liquidations(MarketType.LINEAR, "BTCUSDT")
    finally:
        await adapter.shutdown()

    assert [row.side for row in rows]       == ["sell"]
    assert [row.qty.native for row in rows] == [0.005]
