import httpx
import pytest
import pytest_asyncio

from exchange_router import __version__ as client_version
from exchange_router.service import app
from exchange_router.version import SCHEMA_VERSION, VERSION


@pytest_asyncio.fixture
async def wire():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://router.test") as http:
        yield http


def test_the_wire_contract_is_three():
    assert SCHEMA_VERSION == 3


def test_the_release_number_and_the_wire_contract_are_separate_values():
    assert VERSION != SCHEMA_VERSION
    assert isinstance(VERSION, str)
    assert isinstance(SCHEMA_VERSION, int)


def test_there_is_exactly_one_release_number():
    assert client_version == VERSION


def test_the_package_metadata_reports_the_same_number_the_module_does():
    from importlib.metadata import version as installed_version

    try:
        assert installed_version("exchange-router") == VERSION
    except Exception:
        pytest.skip("the package is not installed in this interpreter; the tree is on sys.path instead")


async def test_the_version_route_serves_both_numbers(wire):
    body = (await wire.get("/version")).json()

    assert body["schema_version"] == SCHEMA_VERSION
    assert body["version"]        == VERSION


async def test_every_frame_stamps_the_schema_version_it_was_built_against(router):
    df = await router.get_candles("fake", "linear", "BTCUSDT", interval="1h", limit=3)
    assert df.attrs["schema_version"] == SCHEMA_VERSION
