import time
import types

from exchange_router.exchanges.binance.adapter import BinanceAdapter
from exchange_router.exchanges.kraken.adapter import KrakenAdapter
from exchange_router.exchanges.kucoin.adapter import KucoinAdapter
from exchange_router.models import MarketType


def info(quote, contract_size=None):
    return types.SimpleNamespace(quote=quote, qty=types.SimpleNamespace(contract_size=contract_size))


BINANCE_INVERSE_BOOK = {"E": 1794071994999, "T": 1794071994990, "bids": [["75666.6", "2869"]], "asks": [["75666.7", "627"]]}

BINANCE_SPOT_BOOK = {"lastUpdateId": 1, "bids": [["75762.4", "8.23"]], "asks": [["75762.5", "4.306"]]}

KRAKEN_SPOT_DEPTH = {"XXBTZUSD": {"bids": [["75657.0", "1.0998", 1700000000]], "asks": [["75658.0", "0.0477", 1700000001]]}}


async def binance_book(market_type, symbol, body, quote, size=None):
    async def answer(method, url, params=None):
        return body

    async def known(market_type, symbol):
        return info(quote, size)

    adapter = BinanceAdapter()
    adapter._make_request = answer
    adapter._info_for     = known
    try:
        return await adapter.get_orderbook(market_type, symbol, depth=5)
    finally:
        await adapter.shutdown()


async def test_a_contract_book_carries_the_size_of_one_contract_and_the_venues_stamp():
    book = await binance_book(MarketType.INVERSE, "BTCUSD", BINANCE_INVERSE_BOOK, "USD", 100.0)

    assert book.qty.unit          == "contract"
    assert book.qty.contract_size == 100.0
    assert book.bids[0]           == [75666.6, 2869.0]
    assert book.timestamp         == 1794071994999
    assert book.time_source       == "venue"


async def test_a_spot_book_with_no_time_takes_the_routers_clock_and_says_so():
    before = int(time.time() * 1000)
    book   = await binance_book(MarketType.SPOT, "BTCUSDT", BINANCE_SPOT_BOOK, "USDT")

    assert (book.qty.unit, book.qty.contract_size) == ("base", None)
    assert book.time_source == "router"
    assert book.timestamp   >= before


async def test_krakens_spot_book_is_stamped_when_read_not_by_its_best_bid():
    async def answer(method, url, params=None):
        return KRAKEN_SPOT_DEPTH

    async def known(market_type, symbol):
        return info("USD")

    before  = int(time.time() * 1000)
    adapter = KrakenAdapter()
    adapter._make_request = answer
    adapter._info_for     = known
    try:
        book = await adapter.get_orderbook(MarketType.SPOT, "XBTUSD", depth=5)
    finally:
        await adapter.shutdown()

    assert book.time_source == "router"
    assert book.timestamp   >= before


async def test_a_kucoin_book_frame_with_no_time_is_not_stamped_1970():
    async def resolve(symbol, market_type):
        return "BTC-USDT"

    async def known(market_type, symbol):
        return info("USDT")

    async def multiplier(market_type, symbol):
        return None

    async def frames(market_type, topic):
        yield {"data": {"bids": [["75000.0", "0.5"]], "asks": [["75001.0", "0.4"]]}}

    before  = int(time.time() * 1000)
    adapter = KucoinAdapter()
    adapter._resolve_symbol = resolve
    adapter._info_for       = known
    adapter._multiplier_for = multiplier
    adapter._ws_connect     = frames
    try:
        book = await adapter.stream_orderbook(MarketType.SPOT, "BTCUSDT", depth=5).__anext__()
    finally:
        await adapter.shutdown()

    assert book.time_source == "router"
    assert book.timestamp   >= before


async def test_the_book_frame_keeps_the_unit_the_size_and_the_clock_in_its_attrs(router):
    df = await router.get_orderbook("fake", "inverse", "BTCUSD", depth=5)

    assert df.attrs["qty_unit"]          == "contract"
    assert df.attrs["qty_contract_size"] == 100.0
    assert df.attrs["time_source"]       == "venue"
