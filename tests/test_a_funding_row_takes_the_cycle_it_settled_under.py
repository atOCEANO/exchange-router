import pytest

from exchange_router.exchanges.base import stamp_funding_cycles
from exchange_router.exchanges.bybit.adapter import BybitAdapter
from exchange_router.models import FundingHistorical, FundingRate, MarketType


HOUR = 3_600_000

BYBIT_CAT = {
    "symbol":          "1000CATUSDT",
    "status":          "Trading",
    "contractType":    "LinearPerpetual",
    "baseCoin":        "1000CAT",
    "quoteCoin":       "USDT",
    "fundingInterval": 60,
    "priceFilter":     {"tickSize": "0.0000010"},
    "lotSizeFilter": {
        "qtyStep":          "1",
        "minOrderQty":      "1",
        "maxOrderQty":      "15500000",
        "minNotionalValue": "5",
    },
}

BYBIT_CAT_ROWS = [
    [1793631600000, "-0.00876513"],
    [1793628000000, "-0.01013928"],
    [1793624400000, "-0.01375371"],
    [1793620800000, "-0.02"],
    [1793606400000, "0.00005"],
    [1793592000000, "-0.00107514"],
    [1793577600000, "-0.00142009"],
    [1793563200000, "-0.00060983"],
    [1793548800000, "0.00005"],
]


def settlements(*stamps):
    return [FundingRate(
        symbol      = "BTCUSDT",
        market_type = MarketType.LINEAR,
        quote       = "USDT",
        rate        = FundingHistorical(kind="discrete", per_cycle=0.0001, cycle_ms=0),
        timestamp   = stamp,
    ) for stamp in stamps]


def hours(rows):
    return [row.rate.cycle_ms / HOUR for row in rows]


def test_a_steady_cycle_stays_what_it_is():
    rows = settlements(*(i * 8 * HOUR for i in range(5)))

    assert hours(stamp_funding_cycles(rows, 8 * HOUR)) == [8, 8, 8, 8, 8]


def test_each_run_keeps_its_own_cycle_across_two_changes():
    stamps = [0, 8, 16, 24, 25, 26, 27, 31, 35]
    rows   = settlements(*(s * HOUR for s in stamps))

    assert hours(stamp_funding_cycles(rows, 4 * HOUR)) == [8, 8, 8, 8, 1, 1, 1, 4, 4]


def test_a_lone_longer_gap_is_a_pause_and_keeps_its_neighbours_cycle():
    stamps = [0, 4, 8, 16, 20, 24]
    rows   = settlements(*(s * HOUR for s in stamps))

    assert hours(stamp_funding_cycles(rows, 4 * HOUR)) == [4, 4, 4, 4, 4, 4]


def test_a_settlement_a_few_milliseconds_late_counts_to_the_second():
    rows = settlements(0, HOUR + 4, 2 * HOUR + 5, 3 * HOUR)

    assert hours(stamp_funding_cycles(rows, HOUR)) == [1, 1, 1, 1]


def test_the_newest_row_after_a_change_takes_the_cycle_the_venue_states():
    stamps = [0, 8, 16, 24, 25]
    rows   = settlements(*(s * HOUR for s in stamps))

    assert hours(stamp_funding_cycles(rows, HOUR)) == [8, 8, 8, 8, 1]


def test_a_cycle_no_row_and_no_venue_can_tell_is_refused():
    assert hours(stamp_funding_cycles(settlements(0), 8 * HOUR)) == [8]

    with pytest.raises(ValueError, match="stamp_funding_cycles"):
        stamp_funding_cycles(settlements(0), None)


async def test_bybit_history_keeps_four_hours_before_the_switch_to_one():
    async def answer(method, endpoint, params=None):
        if endpoint == "/v5/market/instruments-info":
            return {"list": [BYBIT_CAT], "nextPageCursor": ""}
        rows = [r for r in BYBIT_CAT_ROWS if "endTime" not in params or r[0] <= params["endTime"]]
        return {"list": [{"symbol": "1000CATUSDT", "fundingRate": r[1], "fundingRateTimestamp": str(r[0])} for r in rows[:params["limit"]]], "nextPageCursor": ""}

    adapter = BybitAdapter()
    adapter._make_request = answer
    try:
        rows = await adapter.get_funding_rate(MarketType.LINEAR, "1000CATUSDT", None, 8)
    finally:
        await adapter.shutdown()

    assert [row.timestamp for row in rows] == [r[0] for r in reversed(BYBIT_CAT_ROWS[:8])]
    assert hours(rows) == [4, 4, 4, 4, 4, 1, 1, 1]
