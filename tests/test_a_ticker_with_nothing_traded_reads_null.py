import time
import types

from exchange_router.exchanges.hyperliquid.adapter import HyperliquidAdapter
from exchange_router.exchanges.kraken.adapter import KrakenAdapter
from exchange_router.exchanges.okx.adapter import OkxAdapter
from exchange_router.models import MarketType


KRAKEN_ACAUSD_TICKER = {
    "ACAUSD": {
        "a": ["0.03100", "1000", "1000.000"],
        "b": ["0.00010", "5000", "5000.000"],
        "c": ["0.00000", "0.00000000"],
        "v": ["0.00000000", "0.00000000"],
        "l": ["0.00000", "0.00000"],
        "h": ["0.00000", "0.00000"],
        "o": "0.00000",
    },
}

OKX_XSHLD_TICKER = {
    "instId":  "XSHLD-USDT",
    "last":    "58.38",
    "open24h": "58.38",
    "high24h": "58.38",
    "low24h":  "58.38",
    "vol24h":  "0",
    "ts":      "1794085533268",
}

KRAKEN_NO_TRADE_FRAME = {
    "channel": "ticker",
    "type":    "snapshot",
    "data":    [{"symbol": "ACA/USD", "bid": 0.0001, "bid_qty": 5000.0, "ask": 0.031, "ask_qty": 1000.0, "last": 0.0, "volume": 0.0, "low": 0.0, "high": 0.0, "change": 0.0, "change_pct": 0.0, "timestamp": "1970-01-01T00:00:00.000000Z"}],
}

KRAKEN_UNSTAMPED_FRAME = {
    "channel": "ticker",
    "type":    "update",
    "data":    [{"symbol": "ACA/USD", "bid": 0.0001, "bid_qty": 5000.0, "ask": 0.031, "ask_qty": 1000.0}],
}


def quote(name):
    async def known(market_type, symbol):
        return types.SimpleNamespace(quote=name, qty=types.SimpleNamespace(contract_size=None))
    return known


def feed(*messages):
    async def connect(*args):
        for message in messages:
            yield message
    return connect


async def test_a_pair_with_no_trade_it_remembers_has_no_price_and_no_day():
    async def answer(method, url, params=None):
        return KRAKEN_ACAUSD_TICKER

    adapter = KrakenAdapter()
    adapter._make_request = answer
    adapter._info_for     = quote("USD")
    try:
        row = await adapter.get_ticker(MarketType.SPOT, "ACAUSD")
    finally:
        await adapter.shutdown()

    assert [row.price, row.open_24h, row.high_24h, row.low_24h, row.price_change_percent] == [None] * 5
    assert (row.volume_24h.native, row.volume_24h.notional) == (0.0, None)
    assert row.volume_24h.notional_basis.model_dump() == {"method": "row_price", "price": None, "ts": None}
    assert (row.price_source, row.time_source) == ("last_trade", "router")


async def test_a_quiet_day_keeps_the_last_price_and_drops_the_range_the_venue_repeats():
    async def answer(method, endpoint, params=None):
        return [OKX_XSHLD_TICKER]

    async def resolve(symbol, market_type):
        return "XSHLD-USDT"

    adapter = OkxAdapter()
    adapter._make_request   = answer
    adapter._resolve_symbol = resolve
    adapter._info_for       = quote("USDT")
    try:
        row = await adapter.get_ticker(MarketType.SPOT, "XSHLDUSDT")
    finally:
        await adapter.shutdown()

    assert row.price == 58.38
    assert [row.open_24h, row.high_24h, row.low_24h, row.price_change_percent] == [None] * 4
    assert row.volume_24h.notional == 0.0
    assert row.volume_24h.notional_basis.model_dump() == {"method": "row_price", "price": 58.38, "ts": 1794085533268}
    assert row.time_source == "venue"


async def test_hyperliquid_prices_a_market_with_no_mid_at_its_mark_and_says_so():
    async def lookup(market_type, symbol):
        return symbol, "@189", "USDC"

    async def asset_ctx(market_type, coin):
        return {"markPx": "1.002", "prevDayPx": "1.0", "dayBaseVlm": "12.0"}

    async def day_range(coin):
        return 1.0, 1.01, 0.99

    adapter = HyperliquidAdapter()
    adapter._lookup           = lookup
    adapter._asset_ctx        = asset_ctx
    adapter._day_range_cached = day_range
    try:
        row = await adapter.get_ticker(MarketType.SPOT, "USPYXUSDC")
    finally:
        await adapter.shutdown()

    assert (row.price, row.price_source, row.time_source) == (1.002, "mark", "router")


async def test_krakens_stream_stamps_a_frame_without_a_time_by_the_routers_clock():
    async def ws_symbol(api_symbol):
        return "ACA/USD"

    before  = int(time.time() * 1000)
    adapter = KrakenAdapter()
    adapter._info_for       = quote("USD")
    adapter._spot_ws_symbol = ws_symbol
    try:
        adapter._ws_connect = feed(KRAKEN_NO_TRADE_FRAME)
        tickers = [row async for row in adapter.stream_ticker(MarketType.SPOT, "ACAUSD")]
        adapter._ws_connect = feed(KRAKEN_UNSTAMPED_FRAME)
        books = [row async for row in adapter.stream_book_ticker(MarketType.SPOT, "ACAUSD")]
    finally:
        await adapter.shutdown()

    for row in tickers + books:
        assert row.time_source == "router"
        assert row.timestamp   >= before
    assert tickers[0].price is None


async def test_the_ticker_row_puts_the_source_beside_the_price_and_the_clock_last(router):
    row = await router.get_ticker("fake", "linear", "BTCUSDT")

    assert list(row)[3:5] == ["price", "price_source"]
    assert list(row)[-2:] == ["timestamp", "time_source"]
    assert (row.price_source, row.time_source) == ("last_trade", "venue")
