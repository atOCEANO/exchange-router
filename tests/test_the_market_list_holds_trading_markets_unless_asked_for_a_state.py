import pytest

from exchange_router.errors import BadRequest
from exchange_router.exchanges.binance.adapter import BinanceAdapter
from exchange_router.models import MarketType


BINANCE_SPOT = [
    {
        "symbol":     "BTCUSDT",
        "status":     "TRADING",
        "baseAsset":  "BTC",
        "quoteAsset": "USDT",
        "filters": [
            {"filterType": "PRICE_FILTER", "tickSize": "0.01000000"},
            {"filterType": "LOT_SIZE", "minQty": "0.00001000", "maxQty": "9000.00000000", "stepSize": "0.00001000"},
        ],
    },
    {
        "symbol":     "EOSUSDT",
        "status":     "BREAK",
        "baseAsset":  "EOS",
        "quoteAsset": "USDT",
        "filters": [
            {"filterType": "PRICE_FILTER", "tickSize": "0.00010000"},
            {"filterType": "LOT_SIZE", "minQty": "0.10000000", "maxQty": "900000.00000000", "stepSize": "0.10000000"},
        ],
    },
]


async def test_the_list_holds_trading_markets_and_every_state_when_asked(router):
    trading = await router.get_markets("fake", "linear")
    every   = await router.get_markets("fake", "linear", "all")
    halted  = await router.get_markets("fake", "linear", "halted")

    assert [m["symbol"] for m in trading] == ["BTCUSDT", "ETHUSDT"]
    assert [m["status"] for m in trading] == ["trading", "trading"]
    assert every  == trading
    assert halted == []


async def test_a_state_the_router_does_not_know_is_refused(router):
    with pytest.raises(BadRequest, match="status: 'paused' is not a market state; give all, trading, halted, pre_trading or delisted"):
        await router.get_markets("fake", "linear", "paused")


async def test_a_read_by_symbol_refreshes_a_record_older_than_five_minutes():
    reads = []

    async def answer(method, url, params=None):
        reads.append(url)
        return {"symbols": BINANCE_SPOT}

    adapter = BinanceAdapter()
    adapter._make_request = answer
    try:
        first = await adapter.get_symbol_info(MarketType.SPOT, "EOSUSDT")
        again = await adapter.get_symbol_info(MarketType.SPOT, "EOSUSDT")
        adapter._info_cache_at[MarketType.SPOT] -= adapter.INFO_RECORD_S
        later = await adapter.get_symbol_info(MarketType.SPOT, "EOSUSDT")
    finally:
        await adapter.shutdown()

    assert len(reads) == 2
    assert again.timestamp == first.timestamp
    assert later.timestamp >= first.timestamp
    assert (later.status, later.time_source) == ("halted", "router")
