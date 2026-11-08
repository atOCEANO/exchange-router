import httpx
import pytest
import pytest_asyncio

from exchange_router import exchanges as registry
from exchange_router.exchanges.binance.adapter import BinanceAdapter
from exchange_router.exchanges.bybit.adapter import BybitAdapter
from exchange_router.exchanges.hyperliquid.adapter import HyperliquidAdapter
from exchange_router.exchanges.kraken.adapter import KrakenAdapter
from exchange_router.exchanges.kucoin.adapter import KucoinAdapter
from exchange_router.exchanges.okx.adapter import OkxAdapter
from exchange_router.exchanges.base import UpstreamUnavailableError
from exchange_router.models import MarketType
from exchange_router.service import app

from fake_exchange import FakeExchange


class UnlistedLinear(FakeExchange):

    async def get_exchange_info(self, market_type, status="trading"):
        if market_type == MarketType.LINEAR:
            raise UpstreamUnavailableError("fake instruments are down")
        return await super().get_exchange_info(market_type, status)


@pytest_asyncio.fixture
async def wire():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://router.test") as http:
        yield http


@pytest.mark.parametrize("adapter_class", [BinanceAdapter, BybitAdapter, HyperliquidAdapter, KrakenAdapter, KucoinAdapter, OkxAdapter])
async def test_every_venue_maps_its_market_types_with_margin_tiers_first(adapter_class):
    adapter = adapter_class()
    try:
        caps = adapter.get_capabilities()
    finally:
        await adapter.shutdown()

    assert "markets" not in caps
    assert {list(block)[0] for block in caps["market_types"].values()} == {"margin_tiers"}


async def test_the_root_drops_the_status_nothing_computes_and_the_exchange_status_route_is_gone(wire):
    root   = (await wire.get("/")).json()
    status = await wire.get("/fake/status")

    assert list(root) == ["service", "version", "schema_version", "exchanges"]
    assert (status.status_code, status.json()) == (404, {"error": "Not Found", "detail": "no route GET /fake/status"})


async def test_an_overview_says_null_where_it_could_not_count_in_both_modes(router, monkeypatch):
    monkeypatch.setitem(registry.EXCHANGE_REGISTRY, "fake", UnlistedLinear())

    overview = await router.get_exchange_overview("fake")

    assert [(m["market_type"], m["symbol_count"]) for m in overview["market_types"]] == [("spot", 2), ("linear", None), ("inverse", 2)]
