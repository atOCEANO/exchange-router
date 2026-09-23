import inspect

from fastapi.routing import APIRoute, APIWebSocketRoute

from exchange_router.async_router import AsyncRouter
from exchange_router.router import Router
from exchange_router.service import app


ROUTE_TO_METHOD = {
    "/":                                          None,
    "/status":                                    "get_status",
    "/version":                                   "get_version",
    "/exchanges":                                 "get_exchanges",
    "/{exchange}":                                "get_exchange_overview",
    "/{exchange}/status":                         "get_exchange_status",
    "/{exchange}/capabilities":                   "get_capabilities",
    "/{exchange}/market_types":                   "get_market_types",
    "/{exchange}/{market_type}/markets":          "get_markets",
    "/{exchange}/{market_type}/markets/{symbol}": "get_symbol_info",
    "/{exchange}/{market_type}/ticker/{symbol}":            "get_ticker",
    "/{exchange}/{market_type}/book_ticker/{symbol}":       "get_book_ticker",
    "/{exchange}/{market_type}/mark_price/{symbol}":        "get_mark_price",
    "/{exchange}/{market_type}/orderbook/{symbol}":         "get_orderbook",
    "/{exchange}/{market_type}/trades/{symbol}":            "get_trades",
    "/{exchange}/{market_type}/agg_trades/{symbol}":        "get_agg_trades",
    "/{exchange}/{market_type}/candles/{symbol}":           "get_candles",
    "/{exchange}/{market_type}/open_interest/{symbol}":     "get_open_interest",
    "/{exchange}/{market_type}/funding_rate/{symbol}":      "get_funding_rate",
    "/{exchange}/{market_type}/liquidations/{symbol}":      "get_liquidations",
    "/{exchange}/{market_type}/long_short_ratio/{symbol}":  "get_long_short_ratio",
    "/ws/{exchange}/{market_type}":                         "stream",
}

KNOWN_GAPS = {
    "/": "service metadata; get_status and get_exchanges already carry all of it",
}

COMPOSITES = {
    "market", "markets", "fetch_many", "subscribe",
    "candles_many", "trades_many", "agg_trades_many", "funding_rate_many",
    "open_interest_many", "liquidations_many", "long_short_ratio_many",
}

LIFECYCLE = {"close", "warm"}

CONSTRUCTORS = ("local", "service")


def served_paths():
    return {
        route.path
        for route in app.routes
        if isinstance(route, (APIRoute, APIWebSocketRoute))
    }


def sdk_methods():
    return {
        name
        for name, value in inspect.getmembers(AsyncRouter, inspect.isfunction)
        if not name.startswith("_")
    }


def sync_methods():
    return {
        name
        for name, value in inspect.getmembers(Router, inspect.isfunction)
        if not name.startswith("_")
    }


def test_the_route_table_describes_exactly_the_routes_the_app_serves():
    assert served_paths() == set(ROUTE_TO_METHOD)


def test_every_route_with_a_method_names_a_method_that_exists():
    named = {m for m in ROUTE_TO_METHOD.values() if m is not None}
    assert named <= sdk_methods()


def test_the_only_route_without_a_method_is_the_one_recorded_gap():
    gaps = {path for path, method in ROUTE_TO_METHOD.items() if method is None}
    assert gaps == set(KNOWN_GAPS)


def test_every_sdk_method_is_a_route_or_a_declared_composite():
    covered = {m for m in ROUTE_TO_METHOD.values() if m is not None}
    assert sdk_methods() - covered == COMPOSITES | LIFECYCLE


def test_no_gap_is_recorded_without_a_reason():
    for path, reason in KNOWN_GAPS.items():
        assert reason and isinstance(reason, str)


def test_the_two_constructors_are_classmethods_and_not_ordinary_methods():
    for name in CONSTRUCTORS:
        assert isinstance(inspect.getattr_static(AsyncRouter, name), classmethod)

    assert name not in sdk_methods()


async def test_the_two_routes_that_used_to_be_gaps_now_answer_through_both_backends(router):
    overview = await router.get_exchange_overview("fake")
    assert overview["exchange"] == "fake"
    assert [m["name"] for m in overview["market_types"]] == ["spot", "linear", "inverse"]
    assert overview["market_types"][0]["symbol_count"] == 2

    status = await router.get_exchange_status("fake")
    assert status == {"status": "online", "exchange": "fake"}


def test_the_sync_router_offers_exactly_the_methods_the_async_one_does():
    assert sync_methods() == sdk_methods()
