import asyncio

import pytest

from exchange_router import AsyncRouter
from exchange_router import exchanges as registry
from exchange_router.backend import Backend, LocalBackend
from exchange_router.errors import UpstreamUnavailable
from exchange_router.models import MarketType

from fake_exchange import FakeExchange


class CountingExchange(FakeExchange):

    def __init__(self):
        super().__init__()
        self.info_calls = 0
        self.preloaded  = False


    @property
    def name(self):
        return "counter"


    async def _fetch_exchange_info(self, market_type):
        self.info_calls += 1
        return await super()._fetch_exchange_info(market_type)


    async def preload(self):
        self.preloaded = True
        await super().preload()


@pytest.fixture
def counter(monkeypatch):
    adapter = CountingExchange()
    monkeypatch.setitem(registry.EXCHANGE_REGISTRY, "counter", adapter)
    return adapter


async def test_a_declared_scope_warms_its_info_cache_and_nothing_else(counter):
    router = AsyncRouter.local(["counter"], verbose=False, backend=LocalBackend())
    await router.warm()

    assert counter.info_calls == len(MarketType)
    assert counter.preloaded is False

    await router.close()


async def test_warming_is_idempotent_because_the_info_cache_is_a_cache(counter):
    router = AsyncRouter.local(["counter"], verbose=False, backend=LocalBackend())

    await router.warm()
    after_first = counter.info_calls

    await router.warm()
    assert counter.info_calls == after_first

    await router.close()


async def test_an_undeclared_exchange_still_serves_because_scope_is_not_a_fence(counter):
    router = AsyncRouter.local(["fake"], verbose=False, backend=LocalBackend())

    row = await router.get_ticker("counter", "spot", "BTCUSDT")
    assert row.symbol == "BTCUSDT"
    assert router.scope == ["fake"]

    await router.close()


async def test_warming_one_exchange_by_name_works_whether_or_not_it_was_declared(counter):
    router = AsyncRouter.local(["fake"], verbose=False, backend=LocalBackend())

    await router.warm("counter")
    assert counter.info_calls == len(MarketType)

    await router.close()


async def test_construction_does_not_block_on_the_warm(counter):
    router = AsyncRouter.local(["counter"], verbose=False, backend=LocalBackend())

    assert counter.info_calls == 0

    await asyncio.sleep(0)
    await router.close()


async def test_the_background_warm_runs_without_anyone_awaiting_it(counter):
    router = AsyncRouter.local(["counter"], verbose=False, backend=LocalBackend())

    for _ in range(20):
        await asyncio.sleep(0)
        if counter.info_calls:
            break

    assert counter.info_calls > 0

    await router.close()


async def test_closing_cancels_a_warm_that_has_not_finished(counter):
    router = AsyncRouter.local(["counter"], verbose=False, backend=LocalBackend())
    task   = router._warm_task

    await router.close()

    assert router._warm_task is None
    assert task is None or task.cancelling() or task.cancelled() or task.done()


async def test_warming_in_service_mode_runs_the_handshake_instead_of_touching_adapters(counter):
    from exchange_router.backend import Backend

    class Stub(Backend):
        def __init__(self):
            self.calls = []

        async def fetch(self, route, exchange=None, market_type=None, symbol=None, **params):
            self.calls.append(route)
            if route == "version":
                return {"version": "2.5.7", "schema_version": 3}
            if route == "exchanges":
                return {"exchanges": ["counter"]}
            return {"markets": {}}

    stub   = Stub()
    router = AsyncRouter.service("http://router.test", ["counter"], verbose=False, backend=stub)

    await router.warm()

    assert "version" in stub.calls
    assert "capabilities" in stub.calls
    assert counter.info_calls == 0


class Roster(Backend):

    def __init__(self, exchanges=("alpha", "beta"), capability_faults=0):
        self.exchanges         = list(exchanges)
        self.capability_faults = capability_faults
        self.calls             = []


    async def fetch(self, route, exchange=None, market_type=None, symbol=None, **params):
        self.calls.append(route)

        if route == "version":
            return {"version": "9.9.9", "schema_version": 3}

        if route == "exchanges":
            return {"count": len(self.exchanges), "exchanges": self.exchanges}

        if route == "capabilities":
            if self.capability_faults:
                self.capability_faults -= 1
                raise UpstreamUnavailable("the service is busy", 503)
            return {"markets": {"spot": {"ticker": {"rest": True}}}}

        return {}


async def test_all_in_service_mode_resolves_to_the_roster_the_service_reports():
    stub   = Roster()
    router = AsyncRouter.service("http://router.test", "all", verbose=False, backend=stub)

    assert router.scope == []

    await router.warm()

    assert router.scope == ["alpha", "beta"]

    await router.close()


async def test_all_in_local_mode_still_resolves_at_construction(counter):
    router = AsyncRouter.local("all", verbose=False, backend=LocalBackend())

    assert "counter" in router.scope

    await router.close()


async def test_a_capability_fetch_that_failed_is_not_remembered_as_an_empty_block():
    stub   = Roster(capability_faults=1)
    router = AsyncRouter.service("http://router.test", ["alpha"], verbose=False, backend=stub)

    # the background warm would spend the one fault this test is about
    router._warm_task.cancel()

    with pytest.raises(UpstreamUnavailable):
        await router.get_capabilities("alpha")

    assert await router.get_capabilities("alpha") == {"markets": {"spot": {"ticker": {"rest": True}}}}

    await router.close()
