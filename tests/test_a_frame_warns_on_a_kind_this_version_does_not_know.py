import pytest

from exchange_router import exchanges as registry
from exchange_router._warnings import RouterDataWarning

from fake_exchange import FakeExchange


class NewKinds(FakeExchange):

    async def get_long_short_ratio(self, market_type, symbol, period="5m", start_time=None, limit=30):
        rows = await super().get_long_short_ratio(market_type, symbol, period, start_time, limit)
        return [row.model_copy(update={"account_scope": "verified_accounts"}) for row in rows]


    async def get_margin_tiers(self, market_type, symbol):
        table = await super().get_margin_tiers(market_type, symbol)
        return table.model_copy(update={"up_to_unit": "notional"})


async def test_a_series_and_a_tier_table_name_each_kind_they_do_not_know(router, monkeypatch):
    monkeypatch.setitem(registry.EXCHANGE_REGISTRY, "fake", NewKinds())

    with pytest.warns(RouterDataWarning) as caught:
        ratio = await router.get_long_short_ratio("fake", "linear", "BTCUSDT", interval="5m", limit=3, verbose=True)
        tiers = await router.get_margin_tiers("fake", "linear", "BTCUSDT", verbose=True)

    said = [str(w.message) for w in caught if "is not a value this version knows" in str(w.message)]
    assert said == [
        "long_short_ratio fake/linear/BTCUSDT: account_scope 'verified_accounts' is not a value this version knows; the frame keeps it as sent",
        "margin_tiers fake/linear/BTCUSDT: up_to_unit 'notional' is not a value this version knows; the frame keeps it as sent",
    ]
    assert (ratio.attrs["account_scope"], tiers.attrs["up_to_unit"]) == ("verified_accounts", "notional")
