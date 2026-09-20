import pytest

from exchange_router.errors import BadRequest, NotFound, NotSupported, RouterError


EX = "fake"


async def test_an_unknown_exchange_is_not_found(router):
    with pytest.raises(NotFound):
        await router.get_ticker("nosuch", "spot", "BTCUSDT")


async def test_a_market_type_the_adapter_does_not_carry_is_a_bad_request(router):
    with pytest.raises(BadRequest):
        await router.get_ticker(EX, "linear", "NOSUCHUSDT")


async def test_a_symbol_the_exchange_does_not_list_is_a_bad_request(router):
    with pytest.raises(BadRequest):
        await router.get_ticker(EX, "spot", "NOSUCHUSDT")


async def test_an_interval_outside_the_capability_list_is_a_bad_request(router):
    with pytest.raises(BadRequest):
        await router.get_candles(EX, "spot", "BTCUSDT", interval="3s", limit=5)


async def test_a_period_outside_the_capability_list_is_a_bad_request(router):
    with pytest.raises(BadRequest):
        await router.get_open_interest(EX, "linear", "BTCUSDT", period="3s", limit=5)


async def test_a_route_the_market_does_not_implement_is_not_supported(router):
    with pytest.raises(NotSupported):
        await router.get_open_interest(EX, "spot", "BTCUSDT", limit=5)


async def test_funding_on_spot_is_not_supported(router):
    with pytest.raises(NotSupported):
        await router.get_funding_rate(EX, "spot", "BTCUSDT", limit=5)


async def test_a_route_declared_rest_false_is_refused_before_the_request(router):
    with pytest.raises(NotSupported):
        await router.get_liquidations(EX, "inverse", "BTCUSD", limit=5)


async def test_liquidations_on_a_market_that_raises_are_not_supported(router):
    with pytest.raises(NotSupported):
        await router.get_liquidations(EX, "spot", "BTCUSDT", limit=5)


async def test_every_one_of_these_is_catchable_as_a_router_error(router):
    for call in (
        router.get_ticker("nosuch", "spot", "BTCUSDT"),
        router.get_candles(EX, "spot", "BTCUSDT", interval="3s", limit=5),
        router.get_open_interest(EX, "spot", "BTCUSDT", limit=5),
    ):
        with pytest.raises(RouterError):
            await call
