import pytest

from exchange_router import AsyncRouter, Router
from exchange_router import exchanges as registry
from exchange_router.backend import LocalBackend
from exchange_router.errors import RouterError

from fake_exchange import FakeExchange


def local_router():
    return Router.local(["fake"], verbose=False, backend=LocalBackend())


async def test_closing_a_local_router_empties_the_registry():
    router = AsyncRouter.local(["fake"], verbose=False, backend=LocalBackend())
    await router.close()

    assert registry.EXCHANGE_REGISTRY == {}


async def test_the_next_local_router_builds_a_new_adapter_rather_than_reusing_a_closed_one(monkeypatch):
    built = []

    def rebuild():
        adapter = FakeExchange()
        built.append(adapter)
        registry.EXCHANGE_REGISTRY["fake"] = adapter

    monkeypatch.setattr("exchange_router.backend.load_exchanges", rebuild)

    first = AsyncRouter.local(["fake"], verbose=False, backend=LocalBackend())
    await first.close()

    second = AsyncRouter.local(["fake"], verbose=False, backend=LocalBackend())
    row    = await second.get_ticker("fake", "spot", "BTCUSDT")

    assert len(built) == 1
    assert row.symbol == "BTCUSDT"

    await second.close()


def test_a_call_after_close_raises_instead_of_blocking():
    router = local_router()
    router.close()

    with pytest.raises(RouterError) as caught:
        router.get_status()

    assert "closed" in str(caught.value)


def test_a_stream_after_close_raises_instead_of_blocking():
    router = local_router()
    router.close()

    with pytest.raises(RouterError):
        next(router.stream("fake", "spot", "trades", "BTCUSDT"))


def test_closing_twice_is_harmless():
    router = local_router()

    router.close()
    router.close()


def test_a_with_block_tolerates_an_explicit_close_inside_it():
    with local_router() as router:
        router.close()


async def test_the_async_router_can_be_closed_twice_as_well():
    router = AsyncRouter.local(["fake"], verbose=False, backend=LocalBackend())

    await router.close()
    await router.close()


async def test_an_async_call_after_close_raises_instead_of_reloading_the_registry():
    router = AsyncRouter.local(["fake"], verbose=False, backend=LocalBackend())
    await router.close()

    with pytest.raises(RouterError) as caught:
        await router.get_ticker("fake", "spot", "BTCUSDT")

    assert "closed" in str(caught.value)
    assert registry.EXCHANGE_REGISTRY == {}


async def test_an_async_stream_after_close_raises_too():
    router = AsyncRouter.local(["fake"], verbose=False, backend=LocalBackend())
    await router.close()

    with pytest.raises(RouterError):
        async for _ in router.subscribe("fake", "spot", "trades", "BTCUSDT"):
            pass


async def test_warming_a_closed_router_raises():
    router = AsyncRouter.local(["fake"], verbose=False, backend=LocalBackend())
    await router.close()

    with pytest.raises(RouterError):
        await router.warm()
