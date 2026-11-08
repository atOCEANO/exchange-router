import httpx
import pytest_asyncio

from fake_exchange import BASE_TS, CONTRACT_SIZE, INTERVAL_MS
from exchange_router.service import app


EX = "fake"


@pytest_asyncio.fixture
async def wire():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://router.test") as http:
        yield http


async def _get(wire, path, params=None):
    response = await wire.get(f"/{EX}/{path}", params=params)
    response.raise_for_status()
    return response.json()


async def test_a_ticker_values_its_volume_at_its_own_price_and_time(wire):
    volume = (await _get(wire, "linear/ticker/BTCUSDT"))["volume_24h"]

    assert volume["notional"]       == 1234.5 * 100.0
    assert volume["notional_basis"] == {"method": "row_price", "price": 100.0, "ts": BASE_TS}


async def test_a_candle_values_its_volume_at_its_own_close_and_time(wire):
    rows = await _get(wire, "linear/candles/BTCUSDT", {"interval": "1h", "limit": 3})

    for i, row in enumerate(rows):
        assert row["volume"]["notional"]       == (10.0 + i) * (100.0 + i)
        assert row["volume"]["notional_basis"] == {
            "method": "row_price",
            "price":  100.0 + i,
            "ts":     BASE_TS + i * INTERVAL_MS["1h"],
        }


async def test_contracts_are_valued_by_their_size_and_no_price(wire):
    ticker = await _get(wire, "inverse/ticker/BTCUSD")
    candle = (await _get(wire, "inverse/candles/BTCUSD", {"interval": "1h", "limit": 1}))[0]

    for volume, native in ((ticker["volume_24h"], 1234.5), (candle["volume"], 10.0)):
        assert volume["notional"]       == native * CONTRACT_SIZE
        assert volume["notional_basis"] == {"method": "contract_size", "price": None, "ts": None}


async def test_the_candles_frame_names_the_method_once_for_the_query(router):
    linear  = await router.get_candles(EX, "linear", "BTCUSDT", interval="1h", limit=3)
    inverse = await router.get_candles(EX, "inverse", "BTCUSD", interval="1h", limit=3)

    assert linear.attrs["notional_basis"]  == "row_price"
    assert inverse.attrs["notional_basis"] == "contract_size"
