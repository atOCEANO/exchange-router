import pandas as pd
import pytest

from exchange_router import with_provenance


EX = "fake"

SERIES_CALLS = [
    ("candles",          lambda r: r.get_candles(EX, "linear", "BTCUSDT", interval="1h", limit=4)),
    ("trades",           lambda r: r.get_trades(EX, "linear", "BTCUSDT", limit=4)),
    ("agg_trades",       lambda r: r.get_agg_trades(EX, "linear", "BTCUSDT", limit=4)),
    ("funding_rate",     lambda r: r.get_funding_rate(EX, "linear", "BTCUSDT", limit=4)),
    ("open_interest",    lambda r: r.get_open_interest(EX, "linear", "BTCUSDT", period="1h", limit=4)),
    ("liquidations",     lambda r: r.get_liquidations(EX, "linear", "BTCUSDT", limit=4)),
    ("long_short_ratio", lambda r: r.get_long_short_ratio(EX, "linear", "BTCUSDT", period="1h", limit=4)),
]

SERIES_IDS = [name for name, _ in SERIES_CALLS]


@pytest.mark.parametrize("route,call", SERIES_CALLS, ids=SERIES_IDS)
async def test_every_series_frame_is_indexed_by_a_sorted_utc_datetime(router, route, call):
    df = await call(router)

    assert isinstance(df.index, pd.DatetimeIndex)
    assert df.index.name == "datetime"
    assert str(df.index.tz) == "UTC"
    assert df.index.is_monotonic_increasing
    assert not df.index.has_duplicates


@pytest.mark.parametrize("route,call", SERIES_CALLS, ids=SERIES_IDS)
async def test_every_series_frame_carries_the_same_provenance_keys(router, route, call):
    df = await call(router)

    assert df.attrs["exchange"]       == EX
    assert df.attrs["market_type"]    == "linear"
    assert df.attrs["symbol"]         == "BTCUSDT"
    assert df.attrs["schema_version"] == 3
    assert isinstance(df.attrs["warnings"], list)


@pytest.mark.parametrize("route,call", SERIES_CALLS, ids=SERIES_IDS)
async def test_only_open_interest_warns_and_it_warns_about_the_row_that_cannot_join(router, route, call):
    df = await call(router)

    if route != "open_interest":
        assert df.attrs["warnings"] == []
        return

    assert len(df.attrs["warnings"]) == 1
    message = df.attrs["warnings"][0]
    assert "1 of 4 rows have usd=NaN" in message
    assert "join missed" in message
    assert "native is populated" in message


@pytest.mark.parametrize("route,call", SERIES_CALLS, ids=SERIES_IDS)
async def test_no_series_frame_leaks_a_timestamp_column_beside_its_index(router, route, call):
    df = await call(router)
    assert "timestamp" not in df.columns


async def test_numeric_columns_are_floats_and_identifier_columns_stay_text(router):
    trades = await router.get_trades(EX, "linear", "BTCUSDT", limit=4)

    assert trades["price"].dtype   == "float64"
    assert trades["qty"].dtype     == "float64"
    assert trades["qty_usd"].dtype == "float64"
    assert trades["side"].dtype    == object
    assert trades["id"].dtype      == object
    assert list(trades["id"]) == ["9000", "9001", "9002", "9003"]


async def test_with_provenance_moves_the_attrs_into_columns_without_losing_them(router):
    df   = await router.get_candles(EX, "linear", "BTCUSDT", interval="1h", limit=4)
    wide = with_provenance(df)

    assert list(wide["exchange"]) == [EX] * 4
    assert list(wide["symbol"])   == ["BTCUSDT"] * 4
    assert wide.attrs["exchange"] == EX
    assert list(df.columns) == ["open", "high", "low", "close", "volume", "volume_usd"]


async def test_a_frame_survives_a_round_trip_through_a_copy(router):
    df = await router.get_candles(EX, "linear", "BTCUSDT", interval="1h", limit=4)
    assert df.copy().attrs == df.attrs
