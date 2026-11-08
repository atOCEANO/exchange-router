import pytest

from exchange_router import exchanges as registry
from exchange_router._warnings import RouterDataWarning
from exchange_router.models import FundingDeadline

from fake_exchange import FakeExchange


class NewKinds(FakeExchange):

    async def get_ticker(self, market_type, symbol):
        row = await super().get_ticker(market_type, symbol)
        return row.model_copy(update={"price_source": "auction", "time_source": "exchange_gateway"})


    async def get_mark_price(self, market_type, symbol):
        row     = await super().get_mark_price(market_type, symbol)
        funding = row.funding.model_copy(update={"valid_until": FundingDeadline(kind="halted_until", ts=row.funding.valid_until.ts)})
        return row.model_copy(update={"funding": funding})


async def test_a_ticker_and_a_mark_price_name_each_value_they_do_not_know(router, monkeypatch):
    monkeypatch.setitem(registry.EXCHANGE_REGISTRY, "fake", NewKinds())

    with pytest.warns(RouterDataWarning) as caught:
        ticker = await router.get_ticker("fake", "linear", "BTCUSDT", verbose=True)
        mark   = await router.get_mark_price("fake", "linear", "BTCUSDT", verbose=True)

    said = [str(w.message) for w in caught if "is not a value this version knows" in str(w.message)]
    assert said == [
        "ticker fake/linear/BTCUSDT: price_source 'auction' is not a value this version knows; .raw holds the record as sent",
        "ticker fake/linear/BTCUSDT: time_source 'exchange_gateway' is not a value this version knows; .raw holds the record as sent",
        "mark_price fake/linear/BTCUSDT: funding_valid_until_kind 'halted_until' is not a value this version knows; .raw holds the record as sent",
    ]
    assert (ticker.price_source, mark.funding_valid_until_kind) == ("auction", "halted_until")
