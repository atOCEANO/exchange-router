import httpx
import pytest
import pytest_asyncio

from exchange_router.async_router import AsyncRouter
from exchange_router.backend import LocalBackend, RemoteBackend
from exchange_router import exchanges as registry
from exchange_router.service import app

from fake_exchange import FakeExchange


BACKENDS = ["local", "service"]

EXCHANGE = "fake"


@pytest.fixture(autouse=True)
def fake_registry(monkeypatch):
    monkeypatch.setitem(registry.EXCHANGE_REGISTRY, EXCHANGE, FakeExchange())


@pytest.fixture(params=BACKENDS)
def backend(request):
    return request.param


def service_backend():
    return RemoteBackend(
        "http://router.test",
        http = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), timeout=30),
    )


@pytest_asyncio.fixture
async def router(backend):
    if backend == "local":
        client = AsyncRouter.local([EXCHANGE], verbose=False, backend=LocalBackend())
    else:
        client = AsyncRouter.service("http://router.test", [EXCHANGE], verbose=False, backend=service_backend())

    yield client
    await client.close()
