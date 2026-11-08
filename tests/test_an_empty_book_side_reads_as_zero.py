import time

from exchange_router.exchanges.bybit.adapter import BybitAdapter
from exchange_router.exchanges.hyperliquid.adapter import HyperliquidAdapter
from exchange_router.exchanges.kraken.adapter import KrakenAdapter
from exchange_router.exchanges.okx.adapter import OkxAdapter
from exchange_router.models import MarketType


BYBIT_SOLBRL_TICKER = {
    "symbol":       "SOLBRL",
    "bid1Price":    "",
    "bid1Size":     "",
    "ask1Price":    "",
    "ask1Size":     "",
    "lastPrice":    "510",
    "prevPrice24h": "548.9",
    "price24hPcnt": "-0.0709",
    "highPrice24h": "548.9",
    "lowPrice24h":  "500.8",
    "turnover24h":  "57978.38369",
    "volume24h":    "110.5554",
}

BYBIT_SOLBRL_SNAPSHOT = {
    "topic": "orderbook.1.SOLBRL",
    "ts":    1794096672808,
    "type":  "snapshot",
    "data":  {"s": "SOLBRL", "b": [], "a": [], "u": 1, "seq": -1},
    "cts":   1793612988807,
}

KRAKEN_ACXUSD_PAIR = {
    "altname":       "ACXUSD",
    "wsname":        "ACX/USD",
    "base":          "ACX",
    "quote":         "ZUSD",
    "pair_decimals": 5,
    "lot_decimals":  5,
    "ordermin":      "130",
    "costmin":       "0.5",
    "tick_size":     "0.00001",
    "status":        "cancel_only",
}

KRAKEN_ACXUSD_SNAPSHOT = {
    "channel": "ticker",
    "type":    "snapshot",
    "data": [{
        "symbol":     "ACX/USD",
        "bid":        0.0,
        "bid_qty":    0.0,
        "ask":        0.0,
        "ask_qty":    0.0,
        "last":       0.0,
        "volume":     0.0,
        "vwap":       0.0,
        "low":        0.0,
        "high":       0.0,
        "change":     0.0,
        "change_pct": 0.0,
        "trades":     0,
        "timestamp":  "1970-01-01T00:00:00.000000Z",
    }],
}

HYPERLIQUID_USPYX_META = {
    "tokens": [
        {"name": "USDC", "szDecimals": 8, "weiDecimals": 8, "index": 0},
        {"name": "USPYX", "szDecimals": 2, "weiDecimals": 8, "index": 312},
    ],
    "universe": [{"tokens": [312, 0], "name": "@189", "index": 189, "isCanonical": False}],
}

HYPERLIQUID_USPYX_BOOK = {"coin": "@189", "time": 1794097123445, "levels": [[], []]}

OKX_AUDF_INSTRUMENT = {
    "instId":   "AUDF-USDT",
    "instType": "SPOT",
    "baseCcy":  "AUDF",
    "quoteCcy": "USDT",
    "state":    "live",
    "tickSz":   "0.0001",
    "lotSz":    "0.001",
    "minSz":    "1",
    "maxLmtSz": "999999999999999",
}

OKX_AUDF_EMPTY = {
    "arg":  {"channel": "bbo-tbt", "instId": "AUDF-USDT"},
    "data": [{"asks": [], "bids": [], "ts": "1794096675300", "seqId": 696923}],
}

OKX_TEST002_NO_BIDS = {
    "arg":  {"channel": "bbo-tbt", "instId": "TEST002-USDT"},
    "data": [{"asks": [["6.7", "0.9992", "0", "1"]], "bids": [], "ts": "1794096675308", "seqId": 18}],
}


KRAKEN_XBTUSD_BOOK = {
    "feed":       "book_snapshot",
    "product_id": "PF_XBTUSD",
    "timestamp":  1794105486263,
    "seq":        336111557,
    "tickSize":   None,
    "bids":       [{"price": 75657.0, "qty": 1.0998}],
    "asks":       [{"price": 75658.0, "qty": 0.0477}],
}

KRAKEN_XBTUSD_BID_TAKEN = {"feed": "book", "product_id": "PF_XBTUSD", "side": "buy", "seq": 82539481, "price": 75657.0, "qty": 0.0, "timestamp": 1794105509340}


def feed(*messages):
    async def connect(*args):
        for message in messages:
            yield message
    return connect


def sides(row):
    return [row.bid_price, row.bid_qty.native, row.bid_qty.usd, row.ask_price, row.ask_qty.native, row.ask_qty.usd]


async def test_bybit_reads_empty_strings_as_an_empty_book():
    async def answer(method, endpoint, params=None):
        if endpoint == "/v5/market/tickers":
            return {"list": [BYBIT_SOLBRL_TICKER]}
        return {"list": [], "nextPageCursor": ""}

    adapter = BybitAdapter()
    adapter._make_request = answer
    adapter._ws_connect   = feed(BYBIT_SOLBRL_SNAPSHOT)
    try:
        polled   = await adapter.get_book_ticker(MarketType.SPOT, "SOLBRL")
        streamed = [row async for row in adapter.stream_book_ticker(MarketType.SPOT, "SOLBRL")]
    finally:
        await adapter.shutdown()

    assert sides(polled)                       == [0.0] * 6
    assert [sides(row) for row in streamed]    == [[0.0] * 6]
    assert [row.timestamp for row in streamed] == [1794096672808]


async def test_kraken_answers_a_cancel_only_book_and_stamps_it_when_read():
    async def answer(method, url, params=None):
        if url.endswith("/AssetPairs"):
            return {"ACXUSD": KRAKEN_ACXUSD_PAIR}
        if url.endswith("/Depth"):
            return {"ACXUSD": {"asks": [], "bids": []}}
        raise AssertionError(url)

    adapter = KrakenAdapter()
    adapter._make_request = answer
    adapter._ws_connect   = feed(KRAKEN_ACXUSD_SNAPSHOT)
    before = int(time.time() * 1000)
    try:
        polled   = await adapter.get_book_ticker(MarketType.SPOT, "ACXUSD")
        streamed = [row async for row in adapter.stream_book_ticker(MarketType.SPOT, "ACXUSD")]
    finally:
        await adapter.shutdown()
    after = int(time.time() * 1000)

    assert sides(polled) == [0.0] * 6
    assert before <= polled.timestamp <= after
    assert [sides(row) for row in streamed] == [[0.0] * 6]
    assert all(before <= row.timestamp <= after for row in streamed)


async def test_kraken_streams_a_futures_book_whose_last_bid_is_taken():
    async def answer(method, url, params=None):
        if url.endswith("/instruments"):
            return {"instruments": []}
        raise AssertionError(url)

    adapter = KrakenAdapter()
    adapter._make_request = answer
    adapter._ws_connect   = feed(KRAKEN_XBTUSD_BOOK, KRAKEN_XBTUSD_BID_TAKEN)
    try:
        rows = [row async for row in adapter.stream_orderbook(MarketType.LINEAR, "XBTUSD")]
    finally:
        await adapter.shutdown()

    assert [([list(level) for level in row.bids], [list(level) for level in row.asks]) for row in rows] == [
        ([[75657.0, 1.0998]], [[75658.0, 0.0477]]),
        ([], [[75658.0, 0.0477]]),
    ]
    assert [row.timestamp for row in rows] == [1794105486263, 1794105509340]


async def test_hyperliquid_answers_an_empty_book_at_the_venues_time():
    async def answer(info_type, body):
        if info_type == "spotMeta":
            return HYPERLIQUID_USPYX_META
        if info_type == "l2Book":
            return HYPERLIQUID_USPYX_BOOK
        raise AssertionError(info_type)

    adapter = HyperliquidAdapter()
    adapter._make_request = answer
    try:
        polled = await adapter.get_book_ticker(MarketType.SPOT, "USPYXUSDC")
    finally:
        await adapter.shutdown()

    assert sides(polled)    == [0.0] * 6
    assert polled.quote     == "USDC"
    assert polled.timestamp == 1794097123445


async def test_okx_streams_a_side_with_no_orders_as_zero():
    async def answer(method, endpoint, params=None):
        if endpoint == "/api/v5/public/instruments":
            return [OKX_AUDF_INSTRUMENT] if params["instType"] == "SPOT" else []
        raise AssertionError(endpoint)

    rows = []
    for symbol, frame in (("AUDFUSDT", OKX_AUDF_EMPTY), ("TEST002USDT", OKX_TEST002_NO_BIDS)):
        adapter = OkxAdapter()
        adapter._make_request = answer
        adapter._ws_connect   = feed(frame)
        try:
            rows += [row async for row in adapter.stream_book_ticker(MarketType.SPOT, symbol)]
        finally:
            await adapter.shutdown()

    assert [sides(row) for row in rows]    == [[0.0] * 6, [0.0, 0.0, 0.0, 6.7, 0.9992, 6.7 * 0.9992]]
    assert [row.timestamp for row in rows] == [1794096675300, 1794096675308]
