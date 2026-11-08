import types

from exchange_router.exchanges.kraken.adapter import KrakenAdapter
from exchange_router.models import MarketType


def spot_trade(trade_id, stamp=None):
    trade = {"symbol": "BTC/USD", "side": "buy", "price": 75657.0, "qty": 0.01, "trade_id": trade_id}
    if stamp is not None:
        trade["timestamp"] = stamp
    return trade


SPOT_FRAMES = [
    {"channel": "trade", "type": "update", "data": [spot_trade(1, "2026-11-07T18:00:00.000000Z"), spot_trade(2)]},
    {"channel": "trade", "type": "update", "data": [spot_trade(3, "2026-11-07T18:00:01.000000Z")]},
]

FUTURES_FRAMES = [
    {"feed": "trade", "product_id": "PF_XBTUSD", "uid": "a", "side": "sell", "price": 75657.0, "qty": 0.5},
    {"feed": "trade", "product_id": "PF_XBTUSD", "uid": "b", "side": "sell", "price": 75657.0, "qty": 0.5, "time": 1794074400000},
]


def kraken(*frames):
    async def connect(*args):
        for frame in frames:
            yield frame

    async def known(market_type, symbol):
        return types.SimpleNamespace(quote="USD", qty=types.SimpleNamespace(contract_size=None))

    async def ws_symbol(api_symbol):
        return "BTC/USD"

    adapter = KrakenAdapter()
    adapter._ws_connect     = connect
    adapter._info_for       = known
    adapter._spot_ws_symbol = ws_symbol
    return adapter


async def test_a_spot_trade_with_no_time_is_dropped_and_the_stream_goes_on():
    adapter = kraken(*SPOT_FRAMES)
    try:
        trades = [trade async for trade in adapter.stream_trades(MarketType.SPOT, "XBTUSD")]
    finally:
        await adapter.shutdown()

    assert [trade.id for trade in trades]        == ["1", "3"]
    assert [trade.timestamp for trade in trades] == [1794074400000, 1794074401000]


async def test_a_futures_trade_with_no_time_is_dropped_and_the_stream_goes_on():
    adapter = kraken(*FUTURES_FRAMES)
    try:
        trades = [trade async for trade in adapter.stream_trades(MarketType.LINEAR, "XBTUSD")]
    finally:
        await adapter.shutdown()

    assert [(trade.id, trade.timestamp) for trade in trades] == [("b", 1794074400000)]
