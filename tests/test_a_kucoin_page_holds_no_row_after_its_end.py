import types

from exchange_router.exchanges.kucoin.adapter import KucoinAdapter
from exchange_router.models import MarketType


DAY = 86_400_000

FIRST = 1585526400000


def kline(opened):
    return [opened, "6400", "6500", "6300", "6450", "1000", "6450000"]


async def kucoin_page(read, rows):
    async def answer(method, base, endpoint, params=None):
        return rows

    async def listed(market_type, symbol):
        return types.SimpleNamespace(quote="USDT", qty=types.SimpleNamespace(contract_size=None))

    async def multiplier(market_type, symbol):
        return 0.001

    adapter = KucoinAdapter()
    adapter._make_request   = answer
    adapter._info_for       = listed
    adapter._multiplier_for = multiplier
    try:
        return await read(adapter)
    finally:
        await adapter.shutdown()


async def test_a_page_ending_before_kucoins_first_bar_holds_no_bar_after_its_end():
    bars = await kucoin_page(lambda adapter: adapter.get_candles(MarketType.LINEAR, "XBTUSDT", "1d", FIRST - 1, 5), [kline(FIRST)])

    assert bars == []


async def test_a_page_of_open_interest_holds_no_reading_after_its_end():
    rows = [{"ts": FIRST - DAY, "openInterest": "100"}, {"ts": FIRST, "openInterest": "120"}]
    oi   = await kucoin_page(lambda adapter: adapter.get_open_interest(MarketType.LINEAR, "XBTUSDT", "1d", FIRST - 1, 5), rows)

    assert [row.timestamp for row in oi] == [FIRST - DAY]
