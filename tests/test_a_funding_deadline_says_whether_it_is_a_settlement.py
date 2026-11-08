from exchange_router.exchanges.hyperliquid.adapter import HyperliquidAdapter
from exchange_router.exchanges.kraken.adapter import KrakenAdapter
from exchange_router.models import MarketType


HOUR = 3_600_000

ASSET_CTX = {"markPx": "75777.0", "oraclePx": "75794.4", "funding": "0.0000125"}

KRAKEN_TICKERS = {
    "serverTime": "2026-11-07T17:59:53.425Z",
    "tickers":    [{"symbol": "PF_XBTUSD", "markPrice": 75707.01, "indexPrice": 75698.28, "fundingRate": 0.8734}],
}


async def hyperliquid_mark(coin):
    async def lookup(market_type, symbol):
        return symbol, coin, "USDC"

    async def asset_ctx(market_type, name):
        return ASSET_CTX

    async def cycle(market_type, symbol):
        return HOUR

    adapter = HyperliquidAdapter()
    adapter._lookup                  = lookup
    adapter._asset_ctx               = asset_ctx
    adapter._funding_interval_ms_for = cycle
    try:
        return await adapter.get_mark_price(MarketType.LINEAR, "BTCUSDC")
    finally:
        await adapter.shutdown()


async def test_hyperliquids_own_dex_settles_at_the_next_top_of_the_hour():
    mark = await hyperliquid_mark("BTC")

    assert mark.funding.valid_until.kind == "settlement"
    assert mark.funding.valid_until.ts   == (mark.timestamp // HOUR + 1) * HOUR
    assert mark.time_source              == "router"


async def test_a_builder_dex_deadline_is_an_estimate_an_hour_after_the_read():
    mark = await hyperliquid_mark("xyz:NVDA")

    assert mark.funding.valid_until.kind == "estimate"
    assert mark.funding.valid_until.ts   == mark.timestamp + HOUR


async def test_krakens_continuous_funding_is_an_estimate_on_krakens_own_clock():
    async def tickers():
        return KRAKEN_TICKERS

    async def no_info(market_type, symbol):
        return None

    adapter = KrakenAdapter()
    adapter._futures_tickers = tickers
    adapter._info_for        = no_info
    try:
        mark = await adapter.get_mark_price(MarketType.LINEAR, "XBTUSD")
    finally:
        await adapter.shutdown()

    assert mark.timestamp                == 1_794_074_393_425
    assert mark.time_source              == "venue"
    assert mark.funding.valid_until.kind == "estimate"
    assert mark.funding.valid_until.ts   == mark.timestamp + HOUR


async def test_the_mark_price_row_puts_the_deadline_kind_and_the_clock_beside_their_values(router):
    row = await router.get_mark_price("fake", "linear", "BTCUSDT")

    assert list(row)[-5:] == ["funding_per_hour", "funding_valid_until_ts", "funding_valid_until_kind", "timestamp", "time_source"]
    assert row.funding_valid_until_kind == "settlement"
    assert row.time_source              == "venue"
