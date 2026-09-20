import pandas as pd
import pytest

from fake_exchange import BASE_TS, CONTRACT_SIZE, FUNDING_CYCLE_MS, INTERVAL_MS
from exchange_router.models import MarketType


EX = "fake"

MARKETS = [
    ("spot",    "BTCUSDT", "USDT", "base",     None),
    ("linear",  "BTCUSDT", "USDT", "base",     None),
    ("inverse", "BTCUSD",  "USD",  "contract", CONTRACT_SIZE),
]

DERIVATIVES = [m for m in MARKETS if m[0] != "spot"]

ALL_IDS = [m[0] for m in MARKETS]

DERIV_IDS = [m[0] for m in DERIVATIVES]


def expected_usd(native, unit, price):
    return native * CONTRACT_SIZE if unit == "contract" else native * price


@pytest.mark.parametrize("market_type,symbol,quote,unit,size", MARKETS, ids=ALL_IDS)
async def test_ticker_flattens_the_nested_volume_into_native_usd_and_unit(router, market_type, symbol, quote, unit, size):
    row = await router.get_ticker(EX, market_type, symbol)

    assert row.symbol               == symbol
    assert row.market_type          == market_type
    assert row.quote                == quote
    assert row.price                == 100.0
    assert row.open_24h             == 95.0
    assert row.high_24h             == 105.0
    assert row.low_24h              == 94.0
    assert row.volume_24h           == 1234.5
    assert row.volume_24h_unit      == unit
    assert row.volume_24h_usd       == expected_usd(1234.5, unit, 100.0)
    assert row.price_change_percent == 5.26
    assert row.timestamp            == BASE_TS
    assert row.raw["volume_24h"]["unit"] == unit


@pytest.mark.parametrize("market_type,symbol,quote,unit,size", MARKETS, ids=ALL_IDS)
async def test_book_ticker_carries_both_sides_and_one_shared_qty_unit(router, market_type, symbol, quote, unit, size):
    row = await router.get_book_ticker(EX, market_type, symbol)

    assert row.bid_price   == 99.5
    assert row.ask_price   == 100.5
    assert row.bid_qty     == 2.0
    assert row.ask_qty     == 3.0
    assert row.qty_unit    == unit
    assert row.bid_qty_usd == expected_usd(2.0, unit, 99.5)
    assert row.ask_qty_usd == expected_usd(3.0, unit, 100.5)
    assert row.timestamp   == BASE_TS


@pytest.mark.parametrize("market_type,symbol,quote,unit,size", DERIVATIVES, ids=DERIV_IDS)
async def test_mark_price_derives_funding_per_hour_from_the_cycle(router, market_type, symbol, quote, unit, size):
    row   = await router.get_mark_price(EX, market_type, symbol)
    cycle = FUNDING_CYCLE_MS[MarketType(market_type)]
    kind  = "discrete" if market_type == "linear" else "continuous"

    assert row.mark_price        == 100.25
    assert row.index_price       == 100.2
    assert row.funding_kind      == kind
    assert row.funding_per_cycle == 0.0001
    assert row.funding_cycle_ms  == cycle
    assert row.funding_per_hour  == pytest.approx(0.0001 / (cycle / 3_600_000))


@pytest.mark.parametrize("market_type,symbol,quote,unit,size", MARKETS, ids=ALL_IDS)
async def test_symbol_info_flattens_funding_and_keeps_the_qty_unit(router, market_type, symbol, quote, unit, size):
    row = await router.get_symbol_info(EX, market_type, symbol)

    assert row.symbol        == symbol
    assert row.base_asset    == symbol[:-len(quote)]
    assert row.quote_asset   == quote
    assert row.qty_unit      == unit
    assert row.contract_size == size
    assert row.funding_kind  == (None if market_type == "spot" else ("discrete" if market_type == "linear" else "continuous"))


@pytest.mark.parametrize("market_type,symbol,quote,unit,size", MARKETS, ids=ALL_IDS)
async def test_markets_lists_every_symbol_in_the_lite_projection(router, market_type, symbol, quote, unit, size):
    data = await router.get_markets(EX, market_type)

    assert data["exchange"] == EX
    assert [m["symbol"] for m in data["markets"]] == [symbol, symbol.replace("BTC", "ETH")]

    first = data["markets"][0]
    assert first["qty_unit"]      == unit
    assert first["contract_size"] == size
    assert set(first) == {"symbol", "base_asset", "quote_asset", "qty_unit", "contract_size", "funding"}


@pytest.mark.parametrize("market_type,symbol,quote,unit,size", MARKETS, ids=ALL_IDS)
async def test_orderbook_stacks_bids_then_asks_with_one_row_per_level(router, market_type, symbol, quote, unit, size):
    df = await router.get_orderbook(EX, market_type, symbol, depth=5)

    assert list(df.columns)       == ["side", "price", "qty"]
    assert len(df)                == 10
    assert list(df["side"][:5])   == ["bid"] * 5
    assert list(df["side"][5:])   == ["ask"] * 5
    assert df["price"].iloc[0]    == 99.5
    assert df["price"].iloc[5]    == 100.5
    assert df.attrs["qty_unit"]   == unit
    assert df.attrs["quote"]      == quote
    assert df.attrs["exchange"]   == EX


@pytest.mark.parametrize("market_type,symbol,quote,unit,size", MARKETS, ids=ALL_IDS)
@pytest.mark.parametrize("interval", ["1m", "1h", "1d"])
async def test_candles_are_spaced_by_their_own_interval(router, market_type, symbol, quote, unit, size, interval):
    df = await router.get_candles(EX, market_type, symbol, interval=interval, limit=5)

    assert list(df.columns) == ["open", "high", "low", "close", "volume", "volume_usd"]
    assert len(df) == 5
    assert list(df["close"]) == [100.0, 101.0, 102.0, 103.0, 104.0]
    assert list(df["volume"]) == [10.0, 11.0, 12.0, 13.0, 14.0]
    assert df["volume_usd"].iloc[0] == expected_usd(10.0, unit, 100.0)

    step = INTERVAL_MS[interval]
    assert (df.index[1] - df.index[0]) == pd.Timedelta(milliseconds=step)
    assert df.attrs["interval"]    == interval
    assert df.attrs["volume_unit"] == unit
    assert df.attrs["quote"]       == quote


@pytest.mark.parametrize("market_type,symbol,quote,unit,size", MARKETS, ids=ALL_IDS)
async def test_trades_carry_a_side_and_a_usd_notional_per_row(router, market_type, symbol, quote, unit, size):
    df = await router.get_trades(EX, market_type, symbol, limit=4)

    assert list(df.columns) == ["price", "qty", "qty_usd", "side", "id"]
    assert len(df) == 4
    assert list(df["side"]) == ["buy", "sell", "buy", "sell"]
    assert df["price"].iloc[0] == 100.0
    assert df["qty"].iloc[0]   == 0.5
    assert df["qty_usd"].iloc[0] == expected_usd(0.5, unit, 100.0)
    assert df.attrs["qty_unit"] == unit


@pytest.mark.parametrize("market_type,symbol,quote,unit,size", MARKETS, ids=ALL_IDS)
async def test_agg_trades_keep_the_first_and_last_trade_ids(router, market_type, symbol, quote, unit, size):
    df = await router.get_agg_trades(EX, market_type, symbol, limit=3)

    assert list(df.columns) == ["price", "qty", "qty_usd", "side", "agg_id", "first_trade_id", "last_trade_id"]
    assert len(df) == 3
    assert list(df["agg_id"]) == ["5000", "5001", "5002"]
    assert list(df["first_trade_id"]) == ["9000", "9002", "9004"]
    assert list(df["last_trade_id"]) == ["9001", "9003", "9005"]


@pytest.mark.parametrize("market_type,symbol,quote,unit,size", DERIVATIVES, ids=DERIV_IDS)
async def test_funding_rate_reports_both_conventions_and_a_per_hour_column(router, market_type, symbol, quote, unit, size):
    df    = await router.get_funding_rate(EX, market_type, symbol, limit=3)
    cycle = FUNDING_CYCLE_MS[MarketType(market_type)]

    assert list(df.columns) == ["rate", "funding_per_hour", "cycle_ms"]
    assert len(df) == 3
    assert df["rate"].iloc[0] == 0.0001
    assert list(df["cycle_ms"]) == [cycle, cycle, cycle]
    assert df["funding_per_hour"].iloc[0] == pytest.approx(0.0001 / (cycle / 3_600_000))
    assert (df.index[1] - df.index[0]) == pd.Timedelta(milliseconds=cycle)


@pytest.mark.parametrize("market_type,symbol,quote,unit,size", DERIVATIVES, ids=DERIV_IDS)
@pytest.mark.parametrize("period", ["5m", "1h"])
async def test_open_interest_is_spaced_by_its_period(router, market_type, symbol, quote, unit, size, period):
    df = await router.get_open_interest(EX, market_type, symbol, period=period, limit=5)

    assert list(df.columns) == ["open_interest", "open_interest_usd"]
    assert len(df) == 5
    assert list(df["open_interest"]) == [1000.0, 1001.0, 1002.0, 1003.0, 1004.0]
    assert (df.index[1] - df.index[0]) == pd.Timedelta(milliseconds=INTERVAL_MS[period])


async def test_liquidations_are_linear_only_and_carry_a_side(router):
    df = await router.get_liquidations(EX, "linear", "BTCUSDT", limit=4)

    assert list(df.columns) == ["price", "qty", "qty_usd", "side"]
    assert len(df) == 4
    assert list(df["side"]) == ["sell", "buy", "sell", "buy"]
    assert df["price"].iloc[0] == 100.0


@pytest.mark.parametrize("period", ["5m", "1h"])
async def test_long_short_ratio_reports_both_account_sides(router, period):
    df = await router.get_long_short_ratio(EX, "linear", "BTCUSDT", period=period, limit=3)

    assert list(df.columns) == ["ratio", "long_account", "short_account"]
    assert len(df) == 3
    assert df["long_account"].iloc[0]  == pytest.approx(0.5)
    assert df["short_account"].iloc[0] == pytest.approx(0.5)
    assert df["ratio"].iloc[0]         == pytest.approx(1.0)
    assert (df.index[1] - df.index[0]) == pd.Timedelta(milliseconds=INTERVAL_MS[period])


async def test_the_service_metadata_routes_answer(router):
    assert await router.get_version() == "2.5.7"
    assert EX in await router.get_exchanges()
    assert await router.get_market_types(EX) == ["spot", "linear", "inverse"]

    caps = await router.get_capabilities(EX)
    assert set(caps["markets"]) == {"spot", "linear", "inverse"}
    assert caps["markets"]["linear"]["candles"]["intervals"] == list(INTERVAL_MS)


async def test_batch_reads_return_one_frame_per_symbol(router):
    result = await router.candles_many(EX, "linear", ["BTCUSDT", "ETHUSDT"], interval="1h", limit=3)

    assert set(result) == {"BTCUSDT", "ETHUSDT"}
    assert result.failed == {}
    assert result.requested == 2
    assert len(result["BTCUSDT"]) == 3
    assert list(result["ETHUSDT"]["close"]) == [100.0, 101.0, 102.0]
