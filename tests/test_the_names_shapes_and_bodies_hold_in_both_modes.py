import inspect
import threading
import warnings
from collections.abc import Mapping

import httpx
import pandas as pd
import pytest

from exchange_router import AsyncRouter, ExchangeRouterClient, Router
from exchange_router import exchanges as registry
from exchange_router import frames, router as sync_router
from exchange_router._warnings import RouterDataWarning
from exchange_router.backend import _endpoint
from exchange_router.batch import BatchResult
from exchange_router.errors import BadRequest
from exchange_router.exchanges.binance.adapter import BinanceAdapter
from exchange_router.exchanges.bybit.adapter import BybitAdapter
from exchange_router.exchanges.hyperliquid.adapter import HyperliquidAdapter
from exchange_router.exchanges.kraken.adapter import KrakenAdapter
from exchange_router.exchanges.kucoin.adapter import KucoinAdapter
from exchange_router.exchanges.okx.adapter import OkxAdapter
from exchange_router.funding import funding_paid
from exchange_router.models import MarginTier, MarginTiers, MarketType
from exchange_router.service import app
from exchange_router.version import SCHEMA_VERSION

from fake_exchange import FakeExchange


def service():
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://router.test")


async def test_every_error_body_names_its_error_and_every_answer_its_schema():
    async with service() as client:
        unknown = await client.get("/nosuch/spot/ticker/BTCUSDT")
        invalid = await client.get("/fake/spot/candles/BTCUSDT", params={"limit": 0})
        fine    = await client.get("/fake/spot/ticker/BTCUSDT")

    assert unknown.status_code == 404
    assert unknown.json() == {"error": "Not Found", "detail": "exchange 'nosuch' is not enabled; / lists the exchanges"}
    assert invalid.status_code == 400
    assert invalid.json() == {"error": "Invalid Request", "detail": "limit: must be 1 or more, got 0"}
    assert [r.headers["Schema-Version"] for r in (unknown, invalid, fine)] == [str(SCHEMA_VERSION)] * 3


async def test_an_unreadable_answer_and_a_router_fault_each_name_their_error_and_schema(monkeypatch):
    async def unreadable(market_type, symbol):
        raise KeyError("lastPrice")

    async def faulty(market_type, symbol):
        raise RuntimeError("the router lost its place")

    answers = []
    for broken in (unreadable, faulty):
        monkeypatch.setattr(registry.EXCHANGE_REGISTRY["fake"], "get_ticker", broken)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app, raise_app_exceptions=False), base_url="http://router.test") as client:
            answers.append(await client.get("/fake/spot/ticker/BTCUSDT"))

    assert [(a.status_code, a.json()) for a in answers] == [
        (502, {"error": "Bad Upstream Response", "detail": "'lastPrice'"}),
        (500, {"error": "Internal Server Error", "detail": "the router lost its place"}),
    ]
    assert {a.headers["Schema-Version"] for a in answers} == {str(SCHEMA_VERSION)}


async def test_interval_and_end_are_the_only_spellings_in_both_modes(router):
    read = await router.get_open_interest("fake", "linear", "BTCUSDT", limit=3, interval="5m", end=1_700_000_000_000)

    assert read.attrs["interval"] == "5m"
    for name in ("get_candles", "get_agg_trades", "get_funding_rate", "get_open_interest", "get_liquidations", "get_long_short_ratio", "candles_many", "open_interest_many", "long_short_ratio_many"):
        for cls in (AsyncRouter, Router):
            assert {"period", "start"}.isdisjoint(inspect.signature(getattr(cls, name)).parameters), name

    async with service() as client:
        aliased = await client.get("/fake/linear/open_interest/BTCUSDT", params={"interval": "5m", "limit": 3})
    assert {row["interval"] for row in aliased.json()} == {"5m"}


async def test_fetch_many_refuses_a_keyword_its_route_does_not_take_before_fanning_out(router):
    with pytest.raises(BadRequest, match="keyword 'periodd' is not taken by open_interest"):
        await router.fetch_many("open_interest", "fake", "linear", ["BTCUSDT", "ETHUSDT"], periodd="5m")


def test_an_empty_frame_is_built_like_a_full_one():
    df, _ = frames.build("open_interest", [], {"exchange": "fake", "market_type": "linear", "symbol": "BTCUSDT"})

    assert isinstance(df.index, pd.DatetimeIndex) and str(df.index.tz) == "UTC" and df.index.name == "datetime"
    assert list(df.dtypes) == ["float64", "float64"]
    assert {"quote", "interval", "open_interest_unit", "contract_size", "notional_basis", "time_source"} <= set(df.attrs)
    assert "oi_unit" not in df.attrs


def test_an_empty_funding_frame_has_a_full_ones_dtypes():
    ctx      = {"exchange": "fake", "market_type": "linear", "symbol": "BTCUSDT"}
    row      = {"symbol": "BTCUSDT", "market_type": "linear", "quote": "USDT", "funding": {"kind": "discrete", "per_cycle": 0.0001, "cycle_ms": 28_800_000}, "timestamp": 1_794_096_000_000}
    empty, _ = frames.build("funding_rate", [], ctx)
    full, _  = frames.build("funding_rate", [row], ctx)

    assert dict(empty.dtypes) == dict(full.dtypes)


async def test_provenance_keeps_the_market_type_and_open_interest_names_its_unit(router):
    df = await router.get_open_interest("fake", "linear", "BTCUSDT", interval="1h", limit=2)

    assert df.attrs["open_interest_unit"] == "base"
    assert set(frames.with_provenance(df)["unit"]) == {"base"}
    assert set(frames.with_provenance(df)["market_type"]) == {"linear"}


async def test_funding_paid_says_so_when_a_frame_lost_the_kind_it_needs(router):
    df   = await router.get_funding_rate("fake", "linear", "BTCUSDT", limit=3)
    bare = df.copy()
    bare.attrs = {}

    with pytest.warns(RouterDataWarning, match="no funding_kind"):
        funding_paid(bare, 0, 2**62, 1_000.0)


class EuroTicker(FakeExchange):

    async def get_ticker(self, market_type, symbol):
        row = await super().get_ticker(market_type, symbol)
        return row.model_copy(update={"quote": "EUR"})


async def test_a_ticker_in_another_currency_carries_the_same_warning_a_frame_does(router, monkeypatch):
    monkeypatch.setitem(registry.EXCHANGE_REGISTRY, "fake", EuroTicker())
    router.verbose = True

    with pytest.warns(RouterDataWarning, match="quote='EUR'"):
        await router.get_ticker("fake", "spot", "BTCUSDT")


def test_a_batch_result_is_a_mapping():
    result = BatchResult({"BTCUSDT": 1}, {"ETHUSDT": (2, ["short"])}, {"XRPUSDT": ValueError("x")}, 3)

    assert isinstance(result, Mapping)
    assert dict(result) == {"BTCUSDT": 1, "ETHUSDT": 2}


def test_margin_tiers_lead_every_capability_block():
    for adapter in (BinanceAdapter(), BybitAdapter(), OkxAdapter(), KucoinAdapter(), KrakenAdapter(), HyperliquidAdapter()):
        for market_type, block in adapter.get_capabilities()["market_types"].items():
            assert list(block)[0] == "margin_tiers", f"{adapter.name} {market_type}"


def test_tiers_come_out_in_rising_order_whatever_order_a_venue_sends():
    tiers = MarginTiers(
        symbol      = "BTCUSDT",
        market_type = MarketType.LINEAR,
        quote       = "USDT",
        up_to_unit  = "quote",
        tiers       = [MarginTier(up_to=up_to, max_leverage=lev) for up_to, lev in ((2_000_000.0, 50.0), (None, 20.0), (1_000_000.0, 100.0))],
        timestamp   = 1_700_000_000_000,
    )

    assert [tier.up_to for tier in tiers.tiers] == [1_000_000.0, 2_000_000.0, None]


def test_the_deprecated_client_leaves_no_thread_behind_when_it_cannot_be_built(monkeypatch):
    def broken(*args, **kwargs):
        raise ValueError("no core")

    monkeypatch.setattr(sync_router, "AsyncCore", broken)
    before = threading.active_count()

    with warnings.catch_warnings(), pytest.raises(ValueError, match="no core"):
        warnings.simplefilter("ignore", DeprecationWarning)
        ExchangeRouterClient()

    assert threading.active_count() == before


def test_a_symbol_written_with_a_slash_reaches_its_route():
    assert _endpoint("ticker", "kraken", "spot", "BTC/USD") == "kraken/spot/ticker/BTCUSD"
    assert _endpoint("symbol_info", "kraken", "spot", "XBT/USD") == "kraken/spot/markets/XBTUSD"
