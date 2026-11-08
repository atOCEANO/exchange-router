import httpx

from exchange_router import exchanges as registry
from exchange_router.models import Liquidation
from exchange_router.service import app
from tools.auditor.probes import base
from tools.auditor.probes.paginated import PaginatedProbe

from fake_exchange import FakeExchange


class NoLiquidations(FakeExchange):

    async def get_liquidations(self, market_type, symbol, start_time=None, limit=100):
        self._known(market_type, symbol)
        return []


async def test_an_empty_window_reports_skip_where_emptiness_is_an_answer(monkeypatch):
    monkeypatch.setitem(registry.EXCHANGE_REGISTRY, "fake", NoLiquidations())
    monkeypatch.setattr(base, "MIN_REST_INTERVAL_MS", 0)

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app)) as client:
        caps    = (await client.get("http://router.test/fake/capabilities")).json()
        ctx     = base.ProbeContext(client=client, exchange="fake", market_type="linear", symbol="BTCUSDT", caps=caps, caps_slice=caps["market_types"]["linear"], now_ms=base.now_ms())
        results = await PaginatedProbe("liquidations", Liquidation, big_limit=500, allow_empty=True).run(ctx)

    said = {r.probe: (r.status, r.message) for r in results}
    assert said["liquidations:recent"] == said["liquidations:limit=1"] == said["liquidations:limit=5"] == ("skip", "an empty window; nothing to check")
