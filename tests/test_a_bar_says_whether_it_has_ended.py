import time
import types
from datetime import datetime, timezone

from exchange_router import frames
from exchange_router.exchanges.base import bar_closed
from exchange_router.exchanges.binance.adapter import BinanceAdapter
from exchange_router.exchanges.okx.adapter import OkxAdapter
from exchange_router.models import MarketType


HOUR = 3_600_000


def info(quote):
    async def known(market_type, symbol):
        return types.SimpleNamespace(quote=quote, qty=types.SimpleNamespace(contract_size=None))
    return known


def okx_bar(opened, confirm):
    return [str(opened), "75818.9", "76216.8", "75367.8", "75725.1", "29054.0421", "29054.0421", "2200120243.42671", confirm]


def binance_bar(opened):
    return [opened, "76050.0", "76381.4", "74810.8", "75810.1", "151584.803", opened + HOUR - 1, "0", 0, "0", "0", "0"]


def month_start(months_back):
    now   = datetime.now(timezone.utc)
    index = now.year * 12 + now.month - 1 - months_back
    return int(datetime(index // 12, index % 12 + 1, 1, tzinfo=timezone.utc).timestamp() * 1000)


async def test_okx_says_itself_which_bar_has_ended():
    opened = int(time.time() * 1000) // HOUR * HOUR - 5 * HOUR

    async def answer(method, endpoint, params=None):
        return [okx_bar(opened + HOUR, "0"), okx_bar(opened, "1")]

    async def resolve(symbol, market_type):
        return "BTC-USDT-SWAP"

    adapter = OkxAdapter()
    adapter._make_request   = answer
    adapter._resolve_symbol = resolve
    adapter._info_for       = info("USDT")
    try:
        bars = await adapter.get_candles(MarketType.LINEAR, "BTCUSDT", "1h", limit=2)
    finally:
        await adapter.shutdown()

    assert [(bar.timestamp, bar.closed) for bar in bars] == [(opened, True), (opened + HOUR, False)]


async def test_a_bar_with_no_flag_has_ended_once_its_end_has_passed():
    newest = int(time.time() * 1000) // HOUR * HOUR

    async def answer(method, url, params=None):
        return [binance_bar(newest - HOUR), binance_bar(newest)]

    adapter = BinanceAdapter()
    adapter._make_request = answer
    adapter._info_for     = info("USDT")
    try:
        bars = await adapter.get_candles(MarketType.LINEAR, "BTCUSDT", "1h", limit=2)
    finally:
        await adapter.shutdown()

    assert [bar.closed for bar in bars] == [True, False]


def test_a_month_bar_ends_on_the_first_of_the_next_month():
    assert bar_closed(month_start(1), "1M") is True
    assert bar_closed(month_start(0), "1M") is False
    assert bar_closed(month_start(14), "1M") is True


def test_the_candles_frame_leads_with_closed_and_keeps_it_boolean():
    ctx      = {"exchange": "fake", "market_type": "linear", "symbol": "BTCUSDT"}
    row      = {"symbol": "BTCUSDT", "market_type": "linear", "quote": "USDT", "interval": "1h", "timestamp": 1_794_096_000_000, "closed": False, "open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0, "volume": {"native": 0.0, "unit": "base", "contract_size": None, "notional": 0.0, "notional_basis": {"method": "row_price", "price": 1.0, "ts": 1_794_096_000_000}}}
    full, _  = frames.build("candles", [row], ctx)
    empty, _ = frames.build("candles", [], ctx)

    assert list(full.columns)[0] == "closed"
    assert full["closed"].dtype == bool and not full["closed"].iloc[0]
    assert empty["closed"].dtype == bool
