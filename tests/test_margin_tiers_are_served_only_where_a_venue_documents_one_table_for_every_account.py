import httpx
import pytest

from exchange_router import AsyncRouter
from exchange_router.backend import Backend, RemoteBackend
from exchange_router.errors import NotSupported
from exchange_router.exchanges.binance.adapter import BinanceAdapter
from exchange_router.exchanges.bybit.adapter import BybitAdapter
from exchange_router.exchanges.hyperliquid.adapter import HyperliquidAdapter
from exchange_router.exchanges.kraken.adapter import KrakenAdapter
from exchange_router.exchanges.kucoin.adapter import KucoinAdapter
from exchange_router.exchanges.okx.adapter import OkxAdapter
from exchange_router.service import app


SERVED = {
    "bybit":       {"linear", "inverse"},
    "okx":         {"linear", "inverse"},
    "hyperliquid": {"linear"},
}

ADAPTERS = [BinanceAdapter, BybitAdapter, HyperliquidAdapter, KrakenAdapter, KucoinAdapter, OkxAdapter]

OFF = [BinanceAdapter, KrakenAdapter, KucoinAdapter]


class OlderService(Backend):

    async def fetch(self, route, exchange=None, market_type=None, symbol=None, **params):
        if route == "version":
            return {"version": "3.1.0", "schema_version": 3}
        if route == "exchanges":
            return {"count": 1, "exchanges": ["bybit"]}
        if route == "capabilities":
            return {"markets": {"linear": {"ticker": {"rest": True, "ws": True}}}}
        raise AssertionError(f"an older service was asked for {route}")


@pytest.mark.parametrize("adapter_class", ADAPTERS, ids=lambda cls: cls.__name__)
async def test_the_capability_says_rest_exactly_where_the_adapter_serves_tiers(adapter_class):
    adapter = adapter_class()
    try:
        markets = adapter.get_capabilities()["markets"]
        served  = {market.value for market, block in markets.items() if block["margin_tiers"]["rest"]}

        assert served == SERVED.get(adapter.name, set())
        assert all(block["margin_tiers"]["ws"] is False for block in markets.values())
    finally:
        await adapter.shutdown()


@pytest.mark.parametrize("adapter_class", OFF, ids=lambda cls: cls.__name__)
async def test_a_venue_whose_tiers_are_off_refuses_them_on_every_market(adapter_class):
    adapter = adapter_class()
    try:
        for market_type in adapter.supported_market_types:
            with pytest.raises(NotImplementedError, match=f"^margin_tiers is not served on {adapter.name} {market_type.value}$"):
                await adapter.get_margin_tiers(market_type, "BTCUSDT")
    finally:
        await adapter.shutdown()


async def test_the_service_answers_501_for_a_market_without_tiers():
    backend = RemoteBackend("http://router.test", http=httpx.AsyncClient(transport=httpx.ASGITransport(app=app), timeout=30))
    try:
        with pytest.raises(NotSupported) as caught:
            await backend.fetch("margin_tiers", "fake", "spot", "BTCUSDT")
    finally:
        await backend.close()

    assert caught.value.status == 501
    assert caught.value.detail == "margin_tiers is not served on fake spot"


async def test_an_older_service_is_named_instead_of_answering_not_found():
    router = AsyncRouter.service("http://router.test", ["bybit"], verbose=False, backend=OlderService())

    with pytest.raises(NotSupported) as caught:
        await router.get_margin_tiers("bybit", "linear", "BTCUSDT")

    assert "3.1.0" in caught.value.detail
    assert "3.2.0" in caught.value.detail
