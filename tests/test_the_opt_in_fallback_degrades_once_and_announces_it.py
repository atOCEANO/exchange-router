import pytest

from exchange_router import AsyncRouter
from exchange_router._warnings import RouterDataWarning
from exchange_router.backend import Backend, FallbackBackend
from exchange_router.errors import RouterUnreachable


class Dead(Backend):

    def __init__(self):
        self.url   = "http://router.test"
        self.calls = 0


    async def fetch(self, route, exchange=None, market_type=None, symbol=None, **params):
        self.calls += 1
        raise RouterUnreachable("ConnectError: nothing is listening")


    async def stream(self, exchange, market_type, channel, symbol):
        raise ConnectionRefusedError("nothing is listening")
        yield


class Alive(Backend):

    def __init__(self):
        self.calls  = 0
        self.warmed = []


    async def fetch(self, route, exchange=None, market_type=None, symbol=None, **params):
        self.calls += 1

        if route == "version":
            return {"version": "9.9.9", "schema_version": 3}

        if route == "exchanges":
            return {"count": 1, "exchanges": ["fake"]}

        return {"markets": {}}


    async def stream(self, exchange, market_type, channel, symbol):
        yield {"source": "local"}


    async def warm(self, names):
        self.warmed = list(names)


def build():
    dead, alive = Dead(), Alive()
    return FallbackBackend(dead, alive), dead, alive


async def test_an_unreachable_service_degrades_and_says_so():
    backend, dead, alive = build()

    with pytest.warns(RouterDataWarning, match="unreachable"):
        await backend.fetch("status")

    assert backend.degraded is True
    assert alive.calls == 1


async def test_a_stream_falls_back_where_it_used_to_retry_a_dead_socket_forever():
    backend, dead, alive = build()

    with pytest.warns(RouterDataWarning):
        messages = [message async for message in backend.stream("fake", "spot", "trades", "BTCUSDT")]

    assert messages == [{"source": "local"}]
    assert backend.degraded is True


async def test_degradation_happens_once_and_does_not_bounce_back():
    backend, dead, alive = build()

    with pytest.warns(RouterDataWarning):
        await backend.fetch("status")

    before = dead.calls
    await backend.fetch("status")

    assert dead.calls == before
    assert alive.calls == 2


async def test_a_degraded_router_admits_it():
    backend, dead, alive = build()
    router = AsyncRouter.service("http://router.test", ["fake"], verbose=False, backend=backend)

    assert router.degraded is False

    await router.get_status()

    assert router.degraded is True


async def test_warming_after_degradation_reaches_the_adapters_that_are_serving():
    backend, dead, alive = build()
    router = AsyncRouter.service("http://router.test", ["fake"], verbose=False, backend=backend)

    await router.warm()

    assert alive.warmed == ["fake"]
