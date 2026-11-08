import time

from exchange_router.exchanges.base import join_open_interest_basis
from exchange_router.exchanges.hyperliquid.adapter import HyperliquidAdapter
from exchange_router.models import MarketType


BTC = {
    "szDecimals":    5,
    "name":          "BTC",
    "maxLeverage":   40,
    "marginTableId": 56,
}

CONTEXT = {
    "funding":      "0.0000125",
    "openInterest": "41522.0623",
    "prevDayPx":    "76045.0",
    "dayNtlVlm":    "555299506.9000798464",
    "premium":      "-0.0002520318",
    "oraclePx":     "75784.1",
    "markPx":       "75765.0",
    "midPx":        "75764.5",
    "impactPxs":    ["75764.0", "75765.0"],
    "dayBaseVlm":   "7319.36598",
}


def hyperliquid():
    async def answer(info_type, body):
        if info_type == "perpDexs":
            return [None]
        return [{"universe": [BTC], "marginTables": []}, [CONTEXT]]
    return answer


async def test_the_live_reading_is_stamped_when_read_not_at_the_last_boundary():
    adapter = HyperliquidAdapter()
    adapter._make_request = hyperliquid()
    try:
        before = int(time.time() * 1000)
        rows   = await adapter.get_open_interest(MarketType.LINEAR, "BTCUSDC", "1h", None, 1)
        after  = int(time.time() * 1000)
    finally:
        await adapter.shutdown()

    assert len(rows) == 1
    assert before <= rows[0].timestamp <= after
    assert rows[0].open_interest.native == 41522.0623
    assert (rows[0].interval, rows[0].time_source) == (None, "router")


async def test_the_live_reading_is_priced_at_the_mark_read_with_it_and_reads_no_candle():
    async def no_candles(*args, **kwargs):
        raise AssertionError("a reading priced at the mark reads no candle")

    adapter = HyperliquidAdapter()
    adapter._make_request = hyperliquid()
    adapter.get_candles   = no_candles
    try:
        rows   = await adapter.get_open_interest(MarketType.LINEAR, "BTCUSDC", "1h", None, 1)
        joined = await join_open_interest_basis(adapter, MarketType.LINEAR, "BTCUSDC", "1h", None, 1, rows)
    finally:
        await adapter.shutdown()

    value = joined[0].open_interest
    assert value.notional == 41522.0623 * 75765.0
    assert value.notional_basis.model_dump() == {"method": "mark", "price": 75765.0, "ts": joined[0].timestamp}


async def test_the_capability_lists_no_intervals_for_a_live_reading():
    adapter = HyperliquidAdapter()
    try:
        block = adapter.get_capabilities()["markets"][MarketType.LINEAR]["open_interest"]
    finally:
        await adapter.shutdown()

    assert block["intervals"] is None
    assert block["paginated"] is False
    assert block["max_limit"] == 1
