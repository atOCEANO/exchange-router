import httpx
import pytest
import pytest_asyncio

from fake_exchange import BASE_TS, CONTRACT_SIZE, INTERVAL_MS
from exchange_router.service import app


EX     = "fake"
PERIOD = "1h"
LIMIT  = 5


@pytest_asyncio.fixture
async def wire():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://router.test") as http:
        yield http


async def _rows(wire, market_type, symbol):
    response = await wire.get(
        f"/{EX}/{market_type}/open_interest/{symbol}",
        params = {"interval": PERIOD, "limit": LIMIT},
    )
    response.raise_for_status()
    return response.json()


async def test_the_linear_join_fills_every_row_except_the_first(wire):
    rows = await _rows(wire, "linear", "BTCUSDT")
    step = INTERVAL_MS[PERIOD]

    assert len(rows) == LIMIT
    assert [r["timestamp"] for r in rows] == [BASE_TS + i * step for i in range(LIMIT)]

    first = rows[0]["open_interest"]
    assert first["native"]         == 1000.0
    assert first["unit"]           == "base"
    assert first["notional"]       is None
    assert first["notional_basis"] == {"method": "candle_close", "price": None, "ts": None}

    for i in range(1, LIMIT):
        value = rows[i]["open_interest"]
        close = 100.0 + (i - 1)
        assert value["native"]         == 1000.0 + i
        assert value["notional"]       == pytest.approx((1000.0 + i) * close)
        assert value["notional_basis"] == {
            "method": "candle_close",
            "price":  close,
            "ts":     BASE_TS + i * step,
        }


async def test_the_first_row_cannot_join_because_no_candle_precedes_it(wire):
    rows = await _rows(wire, "linear", "BTCUSDT")

    unfilled = [r for r in rows if r["open_interest"]["notional"] is None]
    filled   = [r for r in rows if r["open_interest"]["notional"] is not None]

    assert len(unfilled) == 1
    assert len(filled)   == LIMIT - 1
    assert unfilled[0]["timestamp"] == min(r["timestamp"] for r in rows)


async def test_an_inverse_market_needs_no_join_because_the_contract_carries_the_notional(wire):
    rows = await _rows(wire, "inverse", "BTCUSD")

    assert len(rows) == LIMIT
    for i, row in enumerate(rows):
        value = row["open_interest"]
        assert value["native"]         == 1000.0 + i
        assert value["unit"]           == "contract"
        assert value["contract_size"]  == CONTRACT_SIZE
        assert value["notional"]       == pytest.approx((1000.0 + i) * CONTRACT_SIZE)
        assert value["notional_basis"] == {"method": "contract_size", "price": None, "ts": None}


async def test_the_sdk_frame_reports_the_same_notionals_the_wire_does(router):
    df       = await router.get_open_interest(EX, "linear", "BTCUSDT", interval=PERIOD, limit=LIMIT)
    notional = list(df["open_interest_notional"])

    assert notional[0] != notional[0]
    assert notional[1:] == pytest.approx([(1000.0 + i) * (100.0 + i - 1) for i in range(1, LIMIT)])
    assert df.attrs["notional_basis"] == "candle_close"
    assert df.attrs["time_source"] == "venue"


async def test_a_spot_market_has_no_open_interest_at_all(wire):
    response = await wire.get(f"/{EX}/spot/open_interest/BTCUSDT", params={"interval": PERIOD, "limit": LIMIT})
    assert response.status_code == 501
