import httpx
import pytest
import pytest_asyncio

from exchange_router_client.async_client import AsyncExchangeRouterClient
from src import exchanges as registry
from src.main import app

from fake_exchange import FakeExchange


BACKENDS = ["local", "service"]

EXCHANGE = "fake"


@pytest.fixture(autouse=True)
def fake_registry(monkeypatch):
    monkeypatch.setitem(registry.EXCHANGE_REGISTRY, EXCHANGE, FakeExchange())


@pytest.fixture(params=BACKENDS)
def backend(request):
    return request.param


@pytest_asyncio.fixture
async def router(backend):
    if backend == "local":
        pytest.skip("local mode arrives in PART 4; this leg is the reason the suite is parametrised")

    client = AsyncExchangeRouterClient(base_url="http://router.test", verbose=False)
    client._http = httpx.AsyncClient(
        transport = httpx.ASGITransport(app=app),
        timeout   = 30,
    )

    yield client
    await client.close()
