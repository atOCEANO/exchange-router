import copy

import httpx
import pytest
import pytest_asyncio

from exchange_router import exchanges as registry
from exchange_router.errors import BadRequest
from exchange_router.models import MarketType
from exchange_router.service import app

from fake_exchange import FakeExchange


LIVE = "fake linear open_interest is a live reading, which takes no interval or end"


class LiveReading(FakeExchange):

    def get_capabilities(self):
        caps = copy.deepcopy(super().get_capabilities())
        caps["market_types"][MarketType.LINEAR]["open_interest"].update(intervals=None, paginated=False, max_limit=1)
        return caps


    async def get_open_interest(self, market_type, symbol, period="1h", start_time=None, limit=30):
        rows = await super().get_open_interest(market_type, symbol, "1h", None, 1)
        return [row.model_copy(update={"interval": None}) for row in rows]


@pytest_asyncio.fixture
async def wire():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://router.test") as http:
        yield http


async def test_a_removed_or_unknown_key_is_refused_with_the_name_the_route_takes(wire):
    answers = {
        "/fake/linear/candles/BTCUSDT?period=4h":              "period: the candles route takes interval, not period",
        "/fake/linear/candles/BTCUSDT?start=1700000000000":    "start: the candles route takes end, not start",
        "/fake/linear/open_interest/BTCUSDT?period=1h":        "period: the open_interest route takes interval, not period",
        "/fake/linear/candles/BTCUSDT?intervall=1h":           "intervall: the candles route takes interval, end, limit, not intervall",
        "/fake/linear/ticker/BTCUSDT?depth=5":                 "depth: the ticker route takes no query keys",
    }

    for path, detail in answers.items():
        response = await wire.get(path)
        assert (path, response.status_code, response.json()) == (path, 400, {"error": "Invalid Request", "detail": detail})

    listed = await wire.get("/fake/linear/markets", params={"status": "all"})
    assert listed.status_code == 200


async def test_a_live_reading_takes_no_interval_or_end_in_either_mode(router, monkeypatch):
    monkeypatch.setitem(registry.EXCHANGE_REGISTRY, "fake", LiveReading())

    for keywords in ({"interval": "1h"}, {"end": 1_700_000_000_000}):
        with pytest.raises(BadRequest) as refused:
            await router.get_open_interest("fake", "linear", "BTCUSDT", limit=1, **keywords)
        assert refused.value.detail == f"{next(iter(keywords))}: {LIVE}"

    read = await router.get_open_interest("fake", "linear", "BTCUSDT", limit=1)
    assert len(read) == 1


async def test_a_limit_below_one_is_the_same_sentence_in_both_modes(router):
    with pytest.raises(BadRequest) as refused:
        await router.get_candles("fake", "linear", "BTCUSDT", interval="1h", limit=0)

    assert (refused.value.error, refused.value.detail) == ("Invalid Request", "limit: must be 1 or more, got 0")
