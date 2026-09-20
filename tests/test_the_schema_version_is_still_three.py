import httpx
import pytest_asyncio

from exchange_router import __version__ as client_version
from exchange_router.service import app
from exchange_router.version import SCHEMA_VERSION, SERVICE_VERSION


@pytest_asyncio.fixture
async def wire():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://router.test") as http:
        yield http


def test_the_wire_contract_is_three():
    assert SCHEMA_VERSION == 3


def test_the_release_number_and_the_wire_contract_are_separate_values():
    assert SERVICE_VERSION != SCHEMA_VERSION
    assert isinstance(SERVICE_VERSION, str)
    assert isinstance(SCHEMA_VERSION, int)


def test_the_client_is_versioned_on_its_own_line():
    assert client_version != SERVICE_VERSION


async def test_the_version_route_serves_both_numbers(wire):
    body = (await wire.get("/version")).json()

    assert body["schema_version"] == SCHEMA_VERSION
    assert body["version"]        == SERVICE_VERSION


async def test_every_frame_stamps_the_schema_version_it_was_built_against(router):
    df = await router.get_candles("fake", "linear", "BTCUSDT", interval="1h", limit=3)
    assert df.attrs["schema_version"] == SCHEMA_VERSION
