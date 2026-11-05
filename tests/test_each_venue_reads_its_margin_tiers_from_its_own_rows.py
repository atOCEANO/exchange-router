import copy

import pytest

from fake_exchange import FakeExchange
from exchange_router.exchanges.base import UpstreamUnavailableError
from exchange_router.exchanges.bybit.adapter import BybitAdapter
from exchange_router.exchanges.hyperliquid.adapter import HyperliquidAdapter
from exchange_router.exchanges.okx.adapter import OkxAdapter
from exchange_router.models import MarketType


BYBIT_INSTRUMENTS = {
    "linear": [{
        "symbol":          "BTCUSDT",
        "status":          "Trading",
        "contractType":    "LinearPerpetual",
        "baseCoin":        "BTC",
        "quoteCoin":       "USDT",
        "fundingInterval": 480,
        "priceFilter":     {"tickSize": "0.10"},
        "lotSizeFilter":   {"qtyStep": "0.001", "minOrderQty": "0.001", "maxOrderQty": "1190"},
    }],
    "inverse": [{
        "symbol":          "BTCUSD",
        "status":          "Trading",
        "contractType":    "InversePerpetual",
        "baseCoin":        "BTC",
        "quoteCoin":       "USD",
        "fundingInterval": 480,
        "priceFilter":     {"tickSize": "0.10"},
        "lotSizeFilter":   {"qtyStep": "1", "minOrderQty": "1", "maxOrderQty": "1000000"},
    }],
}

BYBIT_RISK_LIMITS = {
    ("linear", "BTCUSDT"): [
        {"id": 1, "riskLimitValue": "300000", "maintenanceMargin": "0.0033", "initialMargin": "0.0066", "maxLeverage": "150.00", "mmDeduction": ""},
        {"id": 2, "riskLimitValue": "2000000", "maintenanceMargin": "0.005", "initialMargin": "0.01", "maxLeverage": "100.00", "mmDeduction": "510"},
        {"id": 35, "riskLimitValue": "1200000000", "maintenanceMargin": "0.6", "initialMargin": "1", "maxLeverage": "1.00", "mmDeduction": "242382510"},
    ],
    ("inverse", "BTCUSD"): [
        {"id": 1, "riskLimitValue": "150", "maintenanceMargin": "0.005", "initialMargin": "0.01", "maxLeverage": "100.00", "mmDeduction": ""},
        {"id": 2, "riskLimitValue": "300", "maintenanceMargin": "0.01", "initialMargin": "0.015", "maxLeverage": "66.67", "mmDeduction": "0.75"},
    ],
}

OKX_SWAPS = [
    {
        "instId":   "BTC-USDT-SWAP",
        "state":    "live",
        "ctType":   "linear",
        "uly":      "BTC-USDT",
        "ctVal":    "0.01",
        "tickSz":   "0.1",
        "lotSz":    "0.01",
        "minSz":    "0.01",
        "maxLmtSz": "100000000",
    },
    {
        "instId":   "BTC-USD-SWAP",
        "state":    "live",
        "ctType":   "inverse",
        "uly":      "BTC-USD",
        "ctVal":    "100",
        "tickSz":   "0.1",
        "lotSz":    "0.1",
        "minSz":    "0.1",
        "maxLmtSz": "100000000",
    },
]

OKX_POSITION_TIERS = {
    "BTC-USDT": [
        {"tier": "1", "minSz": "0", "maxSz": "1000", "mmr": "0.004", "imr": "0.01", "maxLever": "100"},
        {"tier": "2", "minSz": "1000.01", "maxSz": "5000", "mmr": "0.005", "imr": "0.015", "maxLever": "66.66"},
    ],
    "BTC-USD": [
        {"tier": "1", "minSz": "0", "maxSz": "2000", "mmr": "0.004", "imr": "0.01", "maxLever": "100"},
    ],
}

HYPERLIQUID_META = {
    "universe": [
        {"szDecimals": 5, "name": "BTC", "maxLeverage": 40, "marginTableId": 56},
        {"szDecimals": 2, "name": "ATOM", "maxLeverage": 5, "marginTableId": 5},
    ],
    "marginTables": [
        [50, {"description": "", "marginTiers": [{"lowerBound": "0.0", "maxLeverage": 50}]}],
        [56, {"description": "tiered 40x", "marginTiers": [{"lowerBound": "0.0", "maxLeverage": 40}, {"lowerBound": "150000000.0", "maxLeverage": 20}]}],
    ],
}

HYPERLIQUID_XYZ_META = {
    "universe":     [{"szDecimals": 3, "name": "xyz:NVDA", "maxLeverage": 20, "marginTableId": 20}],
    "marginTables": [[50, {"description": "", "marginTiers": [{"lowerBound": "0.0", "maxLeverage": 50}]}]],
}


def bybit(instruments, limits):
    async def answer(method, endpoint, params=None):
        if endpoint.endswith("/instruments-info"):
            return {"list": instruments[params["category"]], "nextPageCursor": ""}
        rows = limits[(params["category"], params["symbol"])]
        if params.get("cursor") == "next":
            return {"list": rows[2:], "nextPageCursor": ""}
        return {"list": rows[:2], "nextPageCursor": "next" if len(rows) > 2 else ""}
    return answer


def okx(swaps, tiers):
    async def answer(method, endpoint, params=None):
        if endpoint.endswith("/position-tiers"):
            assert (params["instType"], params["tdMode"]) == ("SWAP", "cross")
            return tiers[params["instFamily"]]
        return swaps
    return answer


def hyperliquid(meta, builder_meta):
    async def answer(info_type, body):
        if info_type == "perpDexs":
            return [None, {"name": "xyz"}]
        if body.get("dex") == "xyz":
            return [builder_meta, [{}]]
        return [meta, [{}, {}]]
    return answer


def bounds(table):
    return [(tier.up_to, tier.max_leverage) for tier in table.tiers]


async def test_bybit_reads_risk_limit_in_the_quote_on_linear_and_the_coin_on_inverse():
    adapter = BybitAdapter()
    adapter._make_request = bybit(BYBIT_INSTRUMENTS, BYBIT_RISK_LIMITS)
    try:
        linear  = await adapter.get_margin_tiers(MarketType.LINEAR, "BTCUSDT")
        inverse = await adapter.get_margin_tiers(MarketType.INVERSE, "BTCUSD")
    finally:
        await adapter.shutdown()

    assert linear.up_to_unit  == "quote"
    assert inverse.up_to_unit == "base"
    assert linear.quote       == "USDT"

    assert bounds(linear)  == [(300_000.0, 150.0), (2_000_000.0, 100.0), (1_200_000_000.0, 1.0)]
    assert bounds(inverse) == [(150.0, 100.0), (300.0, 66.67)]

    assert linear.tiers[0].maintenance_deduction is None
    assert linear.tiers[1].maintenance_deduction == 510.0
    assert linear.tiers[0].maintenance_margin_rate == 0.0033
    assert linear.tiers[0].initial_margin_rate     == 0.0066


async def test_okx_counts_a_linear_tier_in_the_coin_and_an_inverse_one_in_contracts():
    adapter = OkxAdapter()
    adapter._make_request = okx(OKX_SWAPS, OKX_POSITION_TIERS)
    try:
        linear  = await adapter.get_margin_tiers(MarketType.LINEAR, "BTCUSDT")
        inverse = await adapter.get_margin_tiers(MarketType.INVERSE, "BTCUSD")
    finally:
        await adapter.shutdown()

    assert linear.up_to_unit  == "base"
    assert inverse.up_to_unit == "contract"

    assert bounds(linear)  == [(10.0, 100.0), (50.0, 66.66)]
    assert bounds(inverse) == [(2000.0, 100.0)]

    assert linear.tiers[0].maintenance_margin_rate == 0.004
    assert all(tier.maintenance_deduction is None for tier in linear.tiers + inverse.tiers)


async def test_hyperliquid_ends_each_tier_where_the_next_begins_and_derives_no_rate():
    adapter = HyperliquidAdapter()
    adapter._make_request = hyperliquid(HYPERLIQUID_META, HYPERLIQUID_XYZ_META)
    try:
        btc  = await adapter.get_margin_tiers(MarketType.LINEAR, "BTCUSDC")
        atom = await adapter.get_margin_tiers(MarketType.LINEAR, "ATOMUSDC")
        nvda = await adapter.get_margin_tiers(MarketType.LINEAR, "XYZNVDAUSDC")
    finally:
        await adapter.shutdown()

    assert bounds(btc)  == [(150_000_000.0, 40.0), (None, 20.0)]
    assert bounds(atom) == [(None, 5.0)]
    assert bounds(nvda) == [(None, 20.0)]

    assert btc.up_to_unit == "quote"
    assert btc.quote      == "USDC"
    assert btc.timestamp  == atom.timestamp > 0

    for tier in btc.tiers + atom.tiers + nvda.tiers:
        assert tier.maintenance_margin_rate is None
        assert tier.initial_margin_rate     is None
        assert tier.maintenance_deduction   is None


async def test_a_malformed_table_entry_reaches_neither_the_instruments_nor_another_assets_tiers():
    meta = copy.deepcopy(HYPERLIQUID_META)
    meta["marginTables"].append(["broken"])

    adapter = HyperliquidAdapter()
    adapter._make_request = hyperliquid(meta, HYPERLIQUID_XYZ_META)
    try:
        listed = {info.symbol for info in await adapter.get_exchange_info(MarketType.LINEAR)}
        btc    = await adapter.get_margin_tiers(MarketType.LINEAR, "BTCUSDC")
        atom   = await adapter.get_margin_tiers(MarketType.LINEAR, "ATOMUSDC")
    finally:
        await adapter.shutdown()

    assert listed == {"BTCUSDC", "ATOMUSDC", "XYZNVDAUSDC"}
    assert bounds(btc)  == [(150_000_000.0, 40.0), (None, 20.0)]
    assert bounds(atom) == [(None, 5.0)]


def drop_a_leverage(meta):
    del meta["marginTables"][1][1]["marginTiers"][1]["maxLeverage"]


def reshape_the_tables(meta):
    meta["marginTables"] = [{"id": 56, "marginTiers": []}]


@pytest.mark.parametrize("breaks, error", [(drop_a_leverage, KeyError), (reshape_the_tables, LookupError)],
                         ids=["drop_a_leverage", "reshape_the_tables"])
async def test_a_broken_tiered_table_fails_its_own_asset_and_reaches_nothing_else(breaks, error):
    meta = copy.deepcopy(HYPERLIQUID_META)
    breaks(meta)

    adapter = HyperliquidAdapter()
    adapter._make_request = hyperliquid(meta, HYPERLIQUID_XYZ_META)
    try:
        listed = {info.symbol for info in await adapter.get_exchange_info(MarketType.LINEAR)}
        atom   = await adapter.get_margin_tiers(MarketType.LINEAR, "ATOMUSDC")
        with pytest.raises(error):
            await adapter.get_margin_tiers(MarketType.LINEAR, "BTCUSDC")
    finally:
        await adapter.shutdown()

    assert listed == {"BTCUSDC", "ATOMUSDC", "XYZNVDAUSDC"}
    assert bounds(atom) == [(None, 5.0)]


async def test_a_table_is_read_once_a_day_and_kept_when_a_refresh_fails():
    adapter = FakeExchange()
    calls   = []

    async def fetch():
        calls.append(len(calls))
        if len(calls) > 1:
            raise UpstreamUnavailableError("the venue is down")
        return ["row"]

    first = await adapter._margin_table("key", fetch)
    again = await adapter._margin_table("key", fetch)

    assert again == first
    assert len(calls) == 1

    stamp, rows, read_at = adapter._margin_cache["key"]
    adapter._margin_cache["key"] = (stamp - adapter.INFO_REFRESH_S, rows, read_at)

    stale = await adapter._margin_table("key", fetch)

    assert stale == first
    assert len(calls) == 2

    await adapter._margin_table("key", fetch)

    assert len(calls) == 2

    stamp, rows, read_at = adapter._margin_cache["key"]
    adapter._margin_cache["key"] = (stamp - adapter.INFO_RETRY_S - 1, rows, read_at)

    await adapter._margin_table("key", fetch)

    assert len(calls) == 3


async def test_a_first_read_that_fails_raises_and_caches_nothing():
    adapter = FakeExchange()

    async def fetch():
        raise UpstreamUnavailableError("the venue is down")

    with pytest.raises(UpstreamUnavailableError):
        await adapter._margin_table("key", fetch)

    assert "key" not in adapter._margin_cache
