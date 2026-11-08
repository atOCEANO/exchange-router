import copy
import time

import httpx

from exchange_router import exchanges as registry
from exchange_router.models import MarketType, OpenInterest
from exchange_router.service import app
from tools.auditor.probes import base
from tools.auditor.probes.paginated import PaginatedProbe, clock_findings, open_bar_findings

from fake_exchange import FakeExchange


HOUR = 3_600_000

OPENED = 1794009600000


class LiveReading(FakeExchange):

    def __init__(self, interval=None):
        super().__init__()
        self.interval = interval


    def get_capabilities(self):
        caps = copy.deepcopy(super().get_capabilities())
        caps["market_types"][MarketType.LINEAR]["open_interest"].update(intervals=None, paginated=False, max_limit=1)
        return caps


    async def get_open_interest(self, market_type, symbol, period="1h", start_time=None, limit=30):
        rows = await super().get_open_interest(market_type, symbol, "1h", None, 1)
        return [row.model_copy(update={"interval": self.interval, "timestamp": int(time.time() * 1000), "time_source": "router"}) for row in rows]


def bars(*closed):
    return [{"timestamp": OPENED + i * HOUR, "closed": flag} for i, flag in enumerate(closed)]


async def audit_open_interest(monkeypatch, adapter):
    monkeypatch.setitem(registry.EXCHANGE_REGISTRY, "fake", adapter)
    monkeypatch.setattr(base, "MIN_REST_INTERVAL_MS", 0)

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app)) as client:
        caps  = (await client.get("http://router.test/fake/capabilities")).json()
        ctx   = base.ProbeContext(client=client, exchange="fake", market_type="linear", symbol="BTCUSDT", caps=caps, caps_slice=caps["market_types"]["linear"], now_ms=base.now_ms())
        probe = PaginatedProbe("open_interest", OpenInterest, big_limit=500, period=None, period_param="interval")
        return {r.probe: r.status for r in await probe.run(ctx)}


def test_only_the_newest_bar_may_be_open():
    assert open_bar_findings(bars(True, True, False)) == []
    assert open_bar_findings(bars(True, True, True)) == []
    assert open_bar_findings(bars(True, False, False)) == [OPENED + HOUR]
    assert open_bar_findings([]) == []


def test_a_live_reading_carries_the_routers_clock_and_a_history_row_the_venues():
    live    = {"timestamp": OPENED, "interval": None, "time_source": "router"}
    history = {"timestamp": OPENED, "interval": "1h", "time_source": "venue"}

    assert clock_findings([live, history]) == []
    assert clock_findings([dict(history, time_source="router"), dict(live, time_source="venue")]) == [
        {"timestamp": OPENED, "interval": "1h", "time_source": "router"},
        {"timestamp": OPENED, "interval": None, "time_source": "venue"},
    ]


async def test_a_route_that_declares_no_intervals_is_read_as_a_live_reading(monkeypatch):
    live     = await audit_open_interest(monkeypatch, LiveReading())
    windowed = await audit_open_interest(monkeypatch, LiveReading(interval="1h"))

    assert (live["open_interest:clock"], live["open_interest:live_stamp"]) == ("pass", "pass")
    assert (windowed["open_interest:clock"], windowed["open_interest:live_stamp"]) == ("fail", "fail")
