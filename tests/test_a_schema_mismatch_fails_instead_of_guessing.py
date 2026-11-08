import pytest

from exchange_router import AsyncRouter
from exchange_router.backend import Backend
from exchange_router.errors import NotFound, RouterError, RouterUnreachable, SchemaMismatch
from exchange_router.version import SCHEMA_VERSION


class StubService(Backend):

    def __init__(self, schema=SCHEMA_VERSION, exchanges=("fake",), unreachable=False):
        self.schema      = schema
        self.exchanges   = list(exchanges)
        self.unreachable = unreachable
        self.calls       = []


    async def fetch(self, route, exchange=None, market_type=None, symbol=None, **params):
        self.calls.append(route)

        if self.unreachable:
            raise RouterUnreachable("ConnectError: nothing is listening")

        if route == "version":
            return {"version": "9.9.9", "schema_version": self.schema}

        if route == "exchanges":
            return {"count": len(self.exchanges), "exchanges": self.exchanges}

        if route == "capabilities":
            return {"market_types": {}}

        return {}


def build(**kwargs):
    stub   = StubService(**kwargs)
    router = AsyncRouter.service("http://router.test", ["fake"], verbose=False, backend=stub)
    return router, stub


def test_a_matching_schema_is_silent():
    router, stub = build(schema=SCHEMA_VERSION)
    assert router.schema_version == SCHEMA_VERSION


async def test_a_mismatch_is_fatal_and_names_both_numbers():
    router, stub = build(schema=SCHEMA_VERSION + 1)

    with pytest.raises(SchemaMismatch) as caught:
        await router.get_ticker("fake", "spot", "BTCUSDT")

    error = caught.value
    assert error.sdk_schema     == SCHEMA_VERSION
    assert error.service_schema == SCHEMA_VERSION + 1
    assert f"schema {SCHEMA_VERSION}" in str(error)
    assert f"upgrade the SDK or pin the service to a schema {SCHEMA_VERSION} release" in str(error)


async def test_an_older_service_is_told_apart_from_an_older_sdk():
    router, stub = build(schema=SCHEMA_VERSION - 1)

    with pytest.raises(SchemaMismatch) as caught:
        await router.get_ticker("fake", "spot", "BTCUSDT")

    assert f"upgrade the service or pin the SDK to a schema {SCHEMA_VERSION - 1} release" in str(caught.value)


async def test_the_mismatch_surfaces_on_the_first_call_and_not_at_construction():
    router, stub = build(schema=SCHEMA_VERSION + 1)

    assert stub.calls == []

    with pytest.raises(SchemaMismatch):
        await router.get_candles("fake", "spot", "BTCUSDT", interval="1h", limit=1)

    assert "version" in stub.calls


async def test_the_same_mismatch_raises_again_rather_than_passing_the_second_time():
    router, stub = build(schema=SCHEMA_VERSION + 1)

    for _ in range(2):
        with pytest.raises(SchemaMismatch):
            await router.get_ticker("fake", "spot", "BTCUSDT")


async def test_a_schema_mismatch_is_catchable_as_a_router_error():
    router, stub = build(schema=SCHEMA_VERSION + 1)

    with pytest.raises(RouterError):
        await router.get_ticker("fake", "spot", "BTCUSDT")


async def test_the_handshake_costs_no_extra_round_trip_once_it_has_run():
    router, stub = build(schema=SCHEMA_VERSION)

    await router.get_ticker("fake", "spot", "BTCUSDT")
    first = stub.calls.count("version")

    await router.get_ticker("fake", "spot", "BTCUSDT")
    assert stub.calls.count("version") == first == 1


async def test_a_scope_the_service_does_not_carry_fails_on_the_first_call():
    stub   = StubService(exchanges=["binance"])
    router = AsyncRouter.service("http://router.test", ["fake"], verbose=False, backend=stub)

    with pytest.raises(NotFound) as caught:
        await router.get_ticker("fake", "spot", "BTCUSDT")

    assert "fake" in str(caught.value)
    assert "binance" in str(caught.value)


async def test_an_unreachable_service_fails_and_does_not_fall_back_on_its_own():
    stub   = StubService(unreachable=True)
    router = AsyncRouter.service("http://router.test", ["fake"], verbose=False, backend=stub)

    with pytest.raises(RouterUnreachable):
        await router.get_ticker("fake", "spot", "BTCUSDT")


DISCOVERY = [
    ("get_status",            ()),
    ("get_version",           ()),
    ("get_exchanges",         ()),
    ("get_market_types",      ("fake",)),
    ("get_exchange_overview", ("fake",)),
    ("get_markets",           ("fake", "spot")),
    ("get_symbol_info",       ("fake", "spot", "BTCUSDT")),
]


@pytest.mark.parametrize("method, args", DISCOVERY)
async def test_a_mismatch_arrives_even_when_the_first_call_is_a_discovery_route(method, args):
    router, stub = build(schema=SCHEMA_VERSION + 1)

    with pytest.raises(SchemaMismatch):
        await getattr(router, method)(*args)
