import asyncio
import threading

import pytest

from exchange_router import Router
from exchange_router import exchanges as registry
from exchange_router.backend import Backend, LocalBackend
from exchange_router.errors import BadRequest

from fake_exchange import FakeExchange


class LoopRecordingExchange(FakeExchange):

    def __init__(self):
        super().__init__()
        self.loops = set()


    @property
    def name(self):
        return "recorder"


    async def _fetch_exchange_info(self, market_type):
        self.loops.add(asyncio.get_running_loop())
        return await super()._fetch_exchange_info(market_type)


class LoopRecordingBackend(Backend):

    def __init__(self):
        self.loops = set()


    async def fetch(self, route, exchange=None, market_type=None, symbol=None, **params):
        self.loops.add(asyncio.get_running_loop())
        if route == "version":
            return {"version": "3.0.1", "schema_version": 3}
        if route == "exchanges":
            return {"exchanges": ["recorder"]}
        return {"markets": {}}


@pytest.fixture
def recorder(monkeypatch):
    adapter = LoopRecordingExchange()
    monkeypatch.setitem(registry.EXCHANGE_REGISTRY, "recorder", adapter)
    return adapter


def built_inside(loop, build):
    async def cell():
        return build()

    router = loop.run_until_complete(cell())
    loop.run_until_complete(asyncio.sleep(0.05))
    return router


def test_a_local_router_built_inside_a_running_loop_warms_on_its_own(recorder):
    caller = asyncio.new_event_loop()
    router = built_inside(caller, lambda: Router.local(["recorder"], verbose=False,
                                                       backend=LocalBackend()))

    async def later_cell():
        return router.get_ticker("recorder", "spot", "BTCUSDT")

    row = caller.run_until_complete(later_cell())
    router.warm()

    assert router._core._warm_task.get_loop() is router._loop._loop
    assert row.symbol == "BTCUSDT"
    assert recorder.loops == {router._loop._loop}

    router.close()
    caller.close()


def test_a_service_router_built_inside_a_running_loop_shakes_hands_on_its_own():
    caller  = asyncio.new_event_loop()
    backend = LoopRecordingBackend()
    router  = built_inside(caller, lambda: Router.service("http://router.test", ["recorder"],
                                                          verbose=False, backend=backend))

    router.warm()

    assert router._core._warm_task.get_loop() is router._loop._loop
    assert backend.loops == {router._loop._loop}

    router.close()
    caller.close()


def test_a_scope_refused_at_construction_leaves_no_loop_thread_behind():
    before = set(threading.enumerate())

    with pytest.raises(BadRequest):
        Router.local([], verbose=False)

    assert set(threading.enumerate()) <= before
