import inspect
import pathlib
import re

import httpx
import pytest
import pytest_asyncio

from exchange_router import _core
from exchange_router.capabilities import route_block
from exchange_router.exchanges import base
from exchange_router.models import MarketType
from exchange_router.service import app


ROOT = pathlib.Path(__file__).resolve().parent.parent

STRING_KEYED = {
    "markets": {
        "linear": {"candles": {"rest": True, "intervals": ["1h", "4h"]}},
    }
}

ENUM_KEYED = {
    "markets": {
        MarketType.LINEAR: {"candles": {"rest": True, "intervals": ["1h", "4h"]}},
    }
}


def test_a_string_keyed_map_reads_with_a_string():
    assert route_block(STRING_KEYED, "linear", "candles")["intervals"] == ["1h", "4h"]


def test_an_enum_keyed_map_reads_with_an_enum():
    assert route_block(ENUM_KEYED, MarketType.LINEAR, "candles")["intervals"] == ["1h", "4h"]


def test_an_enum_keyed_map_reads_with_the_enum_value_too():
    assert route_block(STRING_KEYED, MarketType.LINEAR, "candles")["intervals"] == ["1h", "4h"]


@pytest.mark.parametrize("capabilities", [None, {}, {"markets": None}, {"markets": {}}])
def test_a_missing_map_is_an_empty_block_rather_than_a_raise(capabilities):
    assert route_block(capabilities, "linear", "candles") == {}


def test_an_unknown_market_type_or_route_is_an_empty_block():
    assert route_block(STRING_KEYED, "inverse", "candles") == {}
    assert route_block(STRING_KEYED, "linear", "nosuch") == {}


def test_the_sdk_route_block_delegates_rather_than_reimplementing():
    source = inspect.getsource(_core.AsyncCore._route_block)
    assert "route_block(" in source
    assert "markets" not in source


def test_the_interval_check_reads_through_the_same_lookup():
    source = inspect.getsource(base.validate_interval)
    assert "route_block(" in source
    assert "markets" not in source


def test_the_service_no_longer_carries_its_own_copy_of_any_of_it():
    main = (ROOT / "exchange_router" / "service" / "main.py").read_text(encoding="utf-8")

    for gone in ("def validate_interval", "def _symbol_info_to_lite", "_PERIOD_MS", "def _period_to_ms"):
        assert gone not in main

    assert "def validate_request" in main


@pytest_asyncio.fixture
async def wire():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://router.test") as http:
        yield http


async def test_the_exchange_overview_still_renders_a_capability_block_per_market_type(wire):
    body = (await wire.get("/fake")).json()

    assert body["exchange"] == "fake"
    assert body["status"]   == "ok"
    assert [m["name"] for m in body["market_types"]] == ["spot", "linear", "inverse"]

    by_name = {m["name"]: m for m in body["market_types"]}
    assert by_name["spot"]["symbol_count"] == 2
    assert by_name["linear"]["capabilities"]["candles"]["intervals"] == ["1m", "5m", "15m", "1h", "4h", "1d"]
    assert by_name["inverse"]["capabilities"]["liquidations"] == {"rest": False, "ws": False}
    assert "mark_price" not in by_name["spot"]["capabilities"]


def test_only_one_module_reads_the_markets_block_out_of_a_capabilities_map():
    pattern = re.compile(r'\.get\(\s*"markets"')
    found   = set()

    for path in (ROOT / "exchange_router").rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        if pattern.search(path.read_text(encoding="utf-8")):
            found.add(path.relative_to(ROOT).as_posix())

    assert found == {"exchange_router/capabilities.py"}
