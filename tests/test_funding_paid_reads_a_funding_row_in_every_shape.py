import pandas as pd
import pytest

from exchange_router import frames
from exchange_router.funding import funding_paid, per_hour_view


HOUR = 3_600_000

ROWS = [
    {"symbol": "BTCUSDT", "market_type": "linear", "quote": "USDT", "funding": {"kind": "discrete", "per_cycle": 0.0001, "cycle_ms": 8 * HOUR}, "timestamp": 8 * HOUR},
    {"symbol": "BTCUSDT", "market_type": "linear", "quote": "USDT", "funding": {"kind": "discrete", "per_cycle": -0.0002, "cycle_ms": 8 * HOUR}, "timestamp": 16 * HOUR},
]


def test_wire_rows_flattened_rows_and_the_sdk_frame_pay_the_same():
    sdk, _ = frames.build("funding_rate", ROWS, {"exchange": "fake", "market_type": "linear", "symbol": "BTCUSDT"})
    flat   = pd.json_normalize(ROWS, sep="_")
    flat.index = pd.to_datetime(flat["timestamp"], unit="ms", utc=True)

    for shape in (ROWS, flat, sdk):
        assert funding_paid(shape, 0, 16 * HOUR, 1_000.0) == pytest.approx(-0.1)
        assert funding_paid(shape, 9 * HOUR, 16 * HOUR, 1_000.0) == pytest.approx(-0.2)


def test_a_wire_row_and_a_frame_row_give_the_same_hourly_rate():
    sdk, _ = frames.build("funding_rate", ROWS, {"exchange": "fake", "market_type": "linear", "symbol": "BTCUSDT"})

    assert per_hour_view(ROWS[0]) == pytest.approx(0.0000125)
    assert per_hour_view(sdk.iloc[0]) == pytest.approx(0.0000125)
