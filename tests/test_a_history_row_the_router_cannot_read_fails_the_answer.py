import types

import pytest

from exchange_router.exchanges.base import UpstreamDataError
from exchange_router.exchanges.kucoin.adapter import KucoinAdapter
from exchange_router.exchanges.okx.adapter import OkxAdapter
from exchange_router.models import MarketType


OPENED = 1794175200000


def listed():
    async def known(market_type, symbol):
        return types.SimpleNamespace(quote="USDT", qty=types.SimpleNamespace(contract_size=None))
    return known


async def okx(read, rows):
    async def answer(method, endpoint, params=None):
        return rows

    async def resolve(symbol, market_type):
        return "BTC-USDT-SWAP"

    adapter = OkxAdapter()
    adapter._make_request   = answer
    adapter._resolve_symbol = resolve
    adapter._info_for       = listed()
    try:
        return await read(adapter)
    finally:
        await adapter.shutdown()


async def kucoin(read, rows):
    async def answer(method, base, endpoint, params=None):
        return rows

    async def multiplier(market_type, symbol):
        return 0.001

    adapter = KucoinAdapter()
    adapter._make_request   = answer
    adapter._info_for       = listed()
    adapter._multiplier_for = multiplier
    try:
        return await read(adapter)
    finally:
        await adapter.shutdown()


async def test_an_okx_bar_without_its_close_fails_the_answer_instead_of_leaving_a_gap():
    rows = [[str(OPENED), "75818.9", "76216.8", "75367.8", "", "29054.0421", "29054.0421", "2200120243.4", "1"]]

    with pytest.raises(UpstreamDataError, match="OKX sent a row it cannot read for BTC-USDT-SWAP"):
        await okx(lambda adapter: adapter.get_candles(MarketType.LINEAR, "BTCUSDT", "1h", limit=1), rows)


async def test_an_okx_long_short_row_without_its_ratio_fails_the_answer():
    with pytest.raises(UpstreamDataError, match="OKX sent a row it cannot read for BTCUSDT"):
        await okx(lambda adapter: adapter.get_long_short_ratio(MarketType.LINEAR, "BTCUSDT", "1h", None, 1), [[str(OPENED), ""]])


async def test_a_kucoin_bar_without_its_time_fails_the_answer():
    with pytest.raises(UpstreamDataError, match="KuCoin sent a row it cannot read for XBTUSDTM"):
        await kucoin(lambda adapter: adapter.get_candles(MarketType.LINEAR, "XBTUSDT", "1d", None, 1), [[0, "6400", "6500", "6300", "6450", "1000"]])
