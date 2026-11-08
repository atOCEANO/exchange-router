import httpx

from exchange_router import exchanges as registry
from exchange_router.exchanges.base import UpstreamDataError
from exchange_router.service import app
from tools.auditor.probes import base
from tools.auditor.probes.markets import HaltedMarketProbe

from fake_exchange import FakeExchange


LINEAR_ROUTES = ("margin_tiers", "ticker", "book_ticker", "mark_price", "orderbook", "trades", "agg_trades", "candles", "funding_rate", "open_interest", "liquidations", "long_short_ratio")


class HaltedEth(FakeExchange):

    async def _fetch_exchange_info(self, market_type):
        return [info.model_copy(update={"status": "halted"}) if info.symbol.startswith("ETH") else info for info in await super()._fetch_exchange_info(market_type)]


class HaltedEthWithNoBook(HaltedEth):

    async def get_orderbook(self, market_type, symbol, depth=20):
        raise UpstreamDataError(f"fake sent no book for {symbol}")


async def audit_halted(monkeypatch, adapter, market_type):
    monkeypatch.setitem(registry.EXCHANGE_REGISTRY, "fake", adapter)
    monkeypatch.setattr(base, "MIN_REST_INTERVAL_MS", 0)

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app)) as client:
        caps = (await client.get("http://router.test/fake/capabilities")).json()
        ctx  = base.ProbeContext(client=client, exchange="fake", market_type=market_type, symbol="BTCUSDT", caps=caps, caps_slice=caps["market_types"][market_type], now_ms=base.now_ms())
        return {r.probe: (r.symbol, r.status) for r in await HaltedMarketProbe().run(ctx)}


async def test_a_halted_market_says_so_and_answers_on_every_route_its_market_type_serves(monkeypatch):
    linear = await audit_halted(monkeypatch, HaltedEth(), "linear")

    assert set(linear) == {"markets:halted:symbol_info"} | {f"markets:halted:{route}" for route in LINEAR_ROUTES}
    assert set(linear.values()) == {("ETHUSDT", "pass")}


async def test_a_halted_market_that_errors_on_a_route_fails_there_and_a_list_with_none_skips(monkeypatch):
    broken = await audit_halted(monkeypatch, HaltedEthWithNoBook(), "spot")
    quiet  = await audit_halted(monkeypatch, FakeExchange(), "spot")

    assert broken["markets:halted:orderbook"] == ("ETHUSDT", "fail")
    assert quiet == {"markets:halted": ("BTCUSDT", "skip")}
