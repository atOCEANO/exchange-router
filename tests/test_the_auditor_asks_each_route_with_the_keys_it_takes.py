import httpx
import pytest_asyncio

from exchange_router.service import app
from tools.auditor import runner
from tools.auditor.probes import base, exchange_probes, market_probes


@pytest_asyncio.fixture
async def audit(monkeypatch):
    monkeypatch.setattr(base, "MIN_REST_INTERVAL_MS", 0)
    refused = []

    async def keep_refusals(response):
        if response.status_code == 400:
            await response.aread()
            refused.append(f"{response.request.url.path} {response.json()['detail']}")

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), event_hooks={"response": [keep_refusals]}) as client:
        yield client, refused


async def test_every_rest_probe_asks_with_keys_its_route_takes(audit):
    client, refused = audit
    caps    = (await client.get("http://router.test/fake/capabilities")).json()
    results = []

    await runner._overview(client, "fake", results.append)
    for probe in exchange_probes():
        results.extend(await probe.run(base.ProbeContext(client=client, exchange="fake", market_type=None, symbol=None, caps=caps, caps_slice=None, now_ms=base.now_ms())))

    for market_type, block in caps["market_types"].items():
        symbol = await runner._pick_symbol_for_market(client, "fake", market_type, results.append)
        ctx    = base.ProbeContext(client=client, exchange="fake", market_type=market_type, symbol=symbol, caps=caps, caps_slice=block, now_ms=base.now_ms())
        for probe in market_probes(block):
            if probe.kind == "rest" and probe.applies(ctx):
                results.extend(await probe.run(ctx))

    assert [said for said in refused if " route takes " in said] == []
    assert [(r.probe, r.status) for r in results if r.probe in ("overview", "markets:list")] == [("overview", "pass"), ("markets:list", "pass"), ("markets:list", "pass"), ("markets:list", "pass")]
    assert {r.status for r in results if r.probe.startswith("error:")} == {"pass"}
