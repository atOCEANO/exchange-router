import httpx
import pytest
import pytest_asyncio

from exchange_router import exchanges as registry
from exchange_router.errors import BadRequest, NotFound
from exchange_router.models import MarketType
from exchange_router.service import app

from fake_exchange import FakeExchange


UNKNOWN_SYMBOL = "NOSUCHUSDT is not listed on fake spot; /fake/spot/markets lists the symbols"

NOT_ENABLED = "exchange 'nosuch' is not enabled; / lists the exchanges"


class SpotOnly(FakeExchange):

    @property
    def supported_market_types(self):
        return [MarketType.SPOT]


@pytest_asyncio.fixture
async def wire():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://router.test") as http:
        yield http


async def test_the_callers_mistakes_answer_400_with_a_sentence_that_says_where_to_look(wire, monkeypatch):
    monkeypatch.setitem(registry.EXCHANGE_REGISTRY, "spotonly", SpotOnly())
    answers = {
        "/fake/spot/ticker/NOSUCHUSDT":                ("Unknown Symbol", UNKNOWN_SYMBOL),
        "/fake/spot/candles/BTCUSDT?interval=7m":      ("Invalid Request", "interval: '7m' is not offered on fake spot candles; /fake/capabilities lists the intervals"),
        "/fake/spot/candles/BTCUSDT?limit=0":          ("Invalid Request", "limit: must be 1 or more, got 0"),
        "/fake/futures/ticker/BTCUSDT":                ("Invalid Request", "market_type: 'futures' is not a market type; give spot, linear or inverse"),
        "/spotonly/linear/ticker/BTCUSDT":             ("Invalid Request", "market_type: 'linear' is not offered on spotonly; /spotonly/market_types lists them"),
    }

    for path, (error, detail) in answers.items():
        response = await wire.get(path)
        assert (path, response.status_code, response.json()) == (path, 400, {"error": error, "detail": detail})


async def test_an_unknown_exchange_or_route_answers_404_in_the_same_body(wire):
    for method, path, detail in (
        ("GET",  "/nosuch/linear/ticker/BTCUSDT",    NOT_ENABLED),
        ("GET",  "/fake/linear/nosuchroute/BTCUSDT", "no route GET /fake/linear/nosuchroute/BTCUSDT"),
        ("POST", "/fake/linear/ticker/BTCUSDT",      "no route POST /fake/linear/ticker/BTCUSDT"),
    ):
        response = await wire.request(method, path)
        assert (response.status_code, response.json()) == (404, {"error": "Not Found", "detail": detail})


async def test_the_sdk_carries_the_title_and_the_sentence_in_both_modes(router):
    with pytest.raises(BadRequest) as unknown:
        await router.get_ticker("fake", "spot", "NOSUCHUSDT")
    with pytest.raises(NotFound) as missing:
        await router.get_ticker("nosuch", "spot", "BTCUSDT")
    with pytest.raises(BadRequest) as typo:
        await router.get_ticker("fake", "futures", "BTCUSDT")

    assert (unknown.value.error, unknown.value.detail) == ("Unknown Symbol", UNKNOWN_SYMBOL)
    assert (missing.value.error, missing.value.detail) == ("Not Found", NOT_ENABLED)
    assert (typo.value.error, typo.value.detail)       == ("Invalid Request", "market_type: 'futures' is not a market type; give spot, linear or inverse")
