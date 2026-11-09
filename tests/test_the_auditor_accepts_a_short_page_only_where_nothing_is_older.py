import httpx

from exchange_router import exchanges as registry
from exchange_router.models import Candle, MarketType
from exchange_router.service import app
from tools.auditor import runner
from tools.auditor.probes import base
from tools.auditor.probes.paginated import PaginatedProbe

from fake_exchange import BASE_TS, FakeExchange


HOUR = 3_600_000


class ShortHistory(FakeExchange):

    def __init__(self, held, served):
        super().__init__()
        self.held   = held
        self.served = served


    async def get_candles(self, market_type, symbol, interval, start_time=None, limit=100):
        rows = await super().get_candles(market_type, symbol, interval, None, self.held)
        if start_time is not None:
            rows = [row for row in rows if row.timestamp <= start_time]
        return rows[-min(limit, self.served):]


class NoInverse(FakeExchange):

    async def _fetch_exchange_info(self, market_type):
        return [] if market_type == MarketType.INVERSE else await super()._fetch_exchange_info(market_type)


async def audit_candles(monkeypatch, adapter):
    monkeypatch.setitem(registry.EXCHANGE_REGISTRY, "fake", adapter)
    monkeypatch.setattr(base, "MIN_REST_INTERVAL_MS", 0)

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app)) as client:
        caps    = (await client.get("http://router.test/fake/capabilities")).json()
        ctx     = base.ProbeContext(client=client, exchange="fake", market_type="linear", symbol="BTCUSDT", caps=caps, caps_slice=caps["market_types"]["linear"], now_ms=BASE_TS + 40 * HOUR)
        results = await PaginatedProbe("candles", Candle, big_limit=3000, period="1h", period_param="interval").run(ctx)
        return {r.probe: r for r in results}["candles:1h:recent"]


async def test_a_short_page_passes_where_the_venue_holds_nothing_older(monkeypatch):
    recent = await audit_candles(monkeypatch, ShortHistory(held=40, served=40))

    assert (recent.status, recent.evidence["nothing_older"]) == ("pass", BASE_TS)


async def test_a_short_page_fails_where_the_venue_holds_rows_before_it(monkeypatch):
    recent = await audit_candles(monkeypatch, ShortHistory(held=40, served=25))

    assert (recent.status, recent.message, recent.evidence["older_rows"]) == ("fail", "got 25/3000 while the venue holds rows before the first", 5)


async def test_an_empty_market_list_is_nothing_to_audit(monkeypatch):
    monkeypatch.setitem(registry.EXCHANGE_REGISTRY, "fake", NoInverse())
    monkeypatch.setattr(base, "MIN_REST_INTERVAL_MS", 0)
    results = []

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app)) as client:
        symbol = await runner._pick_symbol_for_market(client, "fake", "inverse", results.append)

    assert (symbol, [(r.status, r.message) for r in results]) == (None, [("skip", "the market list is empty; nothing to audit")])
