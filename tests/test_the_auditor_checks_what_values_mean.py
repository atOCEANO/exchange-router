from tools.auditor.probes.base import ProbeContext
from tools.auditor.probes.paginated import cycle_findings, grid_findings, quiet_since
from tools.auditor.probes.snapshot import _book_ticker_checks, _ticker_checks, deadline_verdict
from tools.auditor.probes.websocket import silent_window_verdict


HOUR = 3_600_000

CAT_STAMPS = [1793548800000, 1793563200000, 1793577600000, 1793592000000, 1793606400000, 1793620800000, 1793624400000, 1793628000000, 1793631600000]

XBTUSDM_TRADES = [1794083908610, 1794107557357, 1794107557364, 1794107760386]


def ctx(exchange, market_type="linear"):
    return ProbeContext(client=None, exchange=exchange, market_type=market_type, symbol="BTCUSDT", caps={}, caps_slice={}, now_ms=0)


def funding_rows(cycles):
    return [{"timestamp": stamp, "funding": {"kind": "discrete", "per_cycle": 0.0001, "cycle_ms": cycle * HOUR}} for stamp, cycle in zip(CAT_STAMPS, cycles)]


def test_a_cycle_is_checked_against_its_gap_wherever_the_gap_repeats():
    settled = funding_rows([4, 4, 4, 4, 4, 4, 1, 1, 1])
    stamped = funding_rows([1, 1, 1, 1, 1, 1, 1, 1, 1])

    assert cycle_findings(settled) == []
    assert [f["timestamp"] for f in cycle_findings(stamped)] == CAT_STAMPS[1:6]


def test_a_bar_of_six_hours_or_more_is_checked_against_the_utc_grid():
    hong_kong = [{"timestamp": 1794009600000 + i * 24 * HOUR - 8 * HOUR} for i in range(3)]
    utc       = [{"timestamp": 1794009600000 + i * 24 * HOUR} for i in range(3)]

    assert grid_findings(hong_kong, "1d") == [row["timestamp"] for row in hong_kong]
    assert grid_findings(utc, "1d") == []


def test_a_deadline_one_cycle_off_is_read_again_and_one_that_matches_passes():
    settlement = 1794096000000

    assert deadline_verdict(settlement, settlement, 8 * HOUR) == "pass"
    assert deadline_verdict(settlement + 8 * HOUR, settlement, 8 * HOUR) == "settled"
    assert deadline_verdict(settlement + 3 * HOUR, settlement, 8 * HOUR) == "fail"
    assert deadline_verdict(settlement, None, 8 * HOUR) == "skip"


def test_the_range_is_checked_only_where_the_price_is_a_last_trade():
    ticker = {"price": 0.010045, "low_24h": 0.01003, "high_24h": 0.01003, "volume_24h": {"native": 1480.0}, "timestamp": 2**62}

    assert _ticker_checks(ticker, ctx("hyperliquid", "spot"))[0] == "pass"
    assert _ticker_checks(ticker, ctx("binance", "spot"))[0] == "warn"
    assert _ticker_checks(dict(ticker, price=None), ctx("kraken", "spot"))[:3:2] == ("warn", "no last trade (price null)")


def test_an_empty_side_warns_and_a_router_stamp_is_not_judged_for_age():
    empty = {"bid_price": None, "bid_qty": None, "ask_price": None, "ask_qty": None, "timestamp": 0}
    quoted = {"bid_price": 99.5, "bid_qty": {"native": 2.0}, "ask_price": 100.5, "ask_qty": {"native": 3.0}, "timestamp": 0}

    assert _book_ticker_checks(empty, ctx("okx", "spot"))[:3:2] == ("warn", "bid and ask side empty")
    assert _book_ticker_checks(quoted, ctx("binance", "spot"))[0] == "pass"
    assert _book_ticker_checks(quoted, ctx("okx", "spot"))[0] == "warn"


def test_a_silent_trade_stream_is_skipped_only_where_the_venue_did_not_trade():
    after   = (1794107760386 + 60_000, 1794107760386 + 240_000)
    during  = (1794107500000, 1794107680000)
    earlier = (1794083000000, 1794083180000)

    assert silent_window_verdict(XBTUSDM_TRADES, *after) == "quiet"
    assert silent_window_verdict(XBTUSDM_TRADES, *during) == "missed"
    assert silent_window_verdict(XBTUSDM_TRADES, *earlier) == "unknown"
    assert silent_window_verdict([], *after) == "unknown"


def test_a_stale_newest_bar_passes_only_where_the_venue_has_not_traded_since():
    bar_closes = 1794107760000 + 60_000

    assert quiet_since(XBTUSDM_TRADES, bar_closes)
    assert not quiet_since(XBTUSDM_TRADES + [1794108000000], bar_closes)
    assert not quiet_since([], bar_closes)
