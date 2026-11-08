import httpx

from exchange_router import exchanges as registry
from exchange_router.models import Ticker
from exchange_router.service import app
from tools.auditor.probes import base
from tools.auditor.probes.base import unknown_kind
from tools.auditor.probes.snapshot import SnapshotProbe

from fake_exchange import FakeExchange


class NewKinds(FakeExchange):

    async def get_ticker(self, market_type, symbol):
        row = await super().get_ticker(market_type, symbol)
        return row.model_copy(update={"price_source": "auction"})


def test_a_kind_is_read_wherever_its_route_nests_it_and_a_field_a_route_lacks_is_not_one():
    ticker = {"price": 101.5, "price_source": "auction", "time_source": "venue", "volume_24h": {"unit": "base", "notional_basis": {"method": "row_price"}}}
    bars   = [{"volume": {"unit": "base", "notional_basis": {"method": "row_price"}}}, {"volume": {"unit": "lot", "notional_basis": {"method": "row_price"}}}]
    mark   = {"funding": {"kind": "discrete", "valid_until": {"kind": "halted_until"}}, "time_source": "venue"}

    assert unknown_kind(ticker)[:3:2] == ("warn", "price_source 'auction' is not a value the auditor knows")
    assert unknown_kind(bars)[2] == "volume.unit 'lot' is not a value the auditor knows"
    assert unknown_kind(mark)[2] == "funding.valid_until.kind 'halted_until' is not a value the auditor knows"
    assert unknown_kind({"up_to_unit": "notional"})[2] == "up_to_unit 'notional' is not a value the auditor knows"
    assert unknown_kind(dict(ticker, price_source="mid")) is None


async def test_a_snapshot_carrying_a_new_kind_is_flagged_not_failed(monkeypatch):
    monkeypatch.setitem(registry.EXCHANGE_REGISTRY, "fake", NewKinds())
    monkeypatch.setattr(base, "MIN_REST_INTERVAL_MS", 0)

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app)) as client:
        ctx      = base.ProbeContext(client=client, exchange="fake", market_type="linear", symbol="BTCUSDT", caps={}, caps_slice={"ticker": {"rest": True}}, now_ms=base.now_ms())
        [result] = await SnapshotProbe("ticker", Ticker).run(ctx)

    assert (result.status, result.message) == ("warn", "price_source 'auction' is not a value the auditor knows")
