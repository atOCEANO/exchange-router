from tools.auditor.probes import base, cross_route
from tools.auditor.probes.base import ProbeContext, judge_time
from tools.auditor.probes.cross_route import CrossRouteConsistencyProbe
from tools.auditor.probes.snapshot import _ticker_checks


HOUR = 3_600_000


def ctx(exchange, market_type="spot"):
    return ProbeContext(client=None, exchange=exchange, market_type=market_type, symbol="BTCUSDT", caps={}, caps_slice={}, now_ms=0)


def market_in(status):
    async def fetch(client, endpoint, params=None):
        return 200, {"status": status}, None
    return fetch


async def test_a_router_stamp_is_not_judged_for_age_and_is_expected_only_where_the_venue_sends_none():
    old = {"timestamp": 0, "time_source": "router"}

    assert await judge_time(ctx("binance"), "book_ticker", old) is None
    assert (await judge_time(ctx("okx"), "book_ticker", old))[:3:2] == ("warn", "router clock on okx spot book_ticker, which the venue stamps")


async def test_an_old_venue_stamp_warns_on_a_trading_market_and_is_the_answer_on_a_halted_one(monkeypatch):
    old   = {"timestamp": base.now_ms() - HOUR, "time_source": "venue"}
    fresh = {"timestamp": base.now_ms(), "time_source": "venue"}

    monkeypatch.setattr(base, "fetch", market_in("trading"))
    assert await judge_time(ctx("okx"), "ticker", fresh) is None
    assert (await judge_time(ctx("okx"), "ticker", old))[:3:2] == ("warn", "stale: 3600s old on a trading market")

    monkeypatch.setattr(base, "fetch", market_in("halted"))
    assert (await judge_time(ctx("binance", "linear"), "ticker", old))[:3:2] == ("pass", "the market is halted; its 3600s old stamp is the venue's last")


def test_a_zero_price_is_an_invented_value_and_fails():
    ticker = {"price": 0.0, "low_24h": None, "high_24h": None, "volume_24h": {"native": 0.0}, "price_source": "last_trade"}

    assert _ticker_checks(ticker, ctx("okx"))[:3:2] == ("fail", "non-positive price 0.0")


async def test_a_market_with_no_trade_reports_skip_for_the_ticker_against_the_book(monkeypatch):
    answers = {"ticker": {"price": None}, "book_ticker": {"bid_price": None, "ask_price": None}}

    async def fetch(client, endpoint, params=None):
        return 200, answers[endpoint.split("/")[3]], None

    monkeypatch.setattr(cross_route, "fetch", fetch)
    results = await CrossRouteConsistencyProbe().run(ctx("okx"))

    assert [(r.probe, r.status) for r in results] == [("cross:ticker_vs_book", "skip")]
