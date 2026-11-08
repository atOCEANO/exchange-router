import types

import pytest

from exchange_router.exchanges.base import UpstreamDataError
from exchange_router.exchanges.binance.adapter import BinanceAdapter
from exchange_router.exchanges.bybit.adapter import BybitAdapter
from exchange_router.exchanges.hyperliquid.adapter import HyperliquidAdapter
from exchange_router.exchanges.kraken.adapter import KrakenAdapter
from exchange_router.exchanges.kucoin.adapter import KucoinAdapter
from exchange_router.models import MarketType


def binance_pair(symbol, status, base, tick, step, min_qty, max_qty):
    return {
        "symbol":             symbol,
        "status":             status,
        "baseAsset":          base,
        "quoteAsset":         "USDT",
        "quotePrecision":     8,
        "baseAssetPrecision": 8,
        "filters": [
            {"filterType": "PRICE_FILTER", "tickSize": tick},
            {"filterType": "LOT_SIZE", "minQty": min_qty, "maxQty": max_qty, "stepSize": step},
            {"filterType": "NOTIONAL", "minNotional": "5.00000000"},
        ],
    }


BINANCE_SPOT = [
    binance_pair("BTCUSDT", "TRADING", "BTC", "0.01000000", "0.00001000", "0.00001000", "9000.00000000"),
    binance_pair("EOSUSDT", "BREAK", "EOS", "0.00010000", "0.10000000", "0.10000000", "900000.00000000"),
]


def bybit_perp(symbol, status, base, quote, tick, max_qty):
    return {
        "symbol":          symbol,
        "contractType":    "LinearPerpetual",
        "status":          status,
        "baseCoin":        base,
        "quoteCoin":       quote,
        "settleCoin":      quote,
        "fundingInterval": 480,
        "priceFilter":     {"tickSize": tick},
        "lotSizeFilter":   {"qtyStep": "0.001", "minOrderQty": "0.001", "maxOrderQty": max_qty, "minNotionalValue": "5"},
    }


BYBIT_TRADING   = [bybit_perp("BTCPERP", "Trading", "BTC", "USDC", "0.10", "1000.000")]
BYBIT_PRELAUNCH = [bybit_perp("OPENAIUSDT", "PreLaunch", "OPENAI", "USDT", "0.01", "156.000")]

KUCOIN_SPOT = {
    "symbol":         "BTC-USDT",
    "baseCurrency":   "BTC",
    "quoteCurrency":  "USDT",
    "baseMinSize":    "0.00001",
    "baseMaxSize":    "10000000000",
    "baseIncrement":  "0.00000001",
    "priceIncrement": "0.1",
    "minFunds":       "0.1",
    "enableTrading":  True,
}

BYBIT_RISK_LIMIT = [
    {"id": 1, "riskLimitValue": "300000", "maintenanceMargin": "0.0033", "initialMargin": "0.0066", "maxLeverage": "150.00", "mmDeduction": ""},
    {"id": 2, "riskLimitValue": "2000000", "maintenanceMargin": "0.005", "initialMargin": "0.01", "maxLeverage": "100.00", "mmDeduction": "510"},
]

KRAKEN_PAIRS = {
    "ACXUSD": {
        "altname":       "ACXUSD",
        "wsname":        "ACX/USD",
        "base":          "ACX",
        "quote":         "ZUSD",
        "pair_decimals": 5,
        "lot_decimals":  5,
        "ordermin":      "130",
        "costmin":       "0.5",
        "tick_size":     "0.00001",
        "status":        "cancel_only",
    },
    "XXBTZUSD": {
        "altname":       "XBTUSD",
        "wsname":        "XBT/USD",
        "base":          "XXBT",
        "quote":         "ZUSD",
        "pair_decimals": 1,
        "lot_decimals":  8,
        "ordermin":      "0.00006",
        "costmin":       "0.5",
        "tick_size":     "0.1",
        "status":        "online",
    },
}

HYPERLIQUID_UNIVERSE = [
    {"szDecimals": 5, "name": "BTC", "maxLeverage": 40, "marginTableId": 56},
    {"szDecimals": 1, "name": "MATIC", "maxLeverage": 20, "marginTableId": 20, "isDelisted": True},
]


async def on(adapter, answer, call):
    adapter._make_request = answer
    try:
        return await call(adapter)
    finally:
        await adapter.shutdown()


async def listing(adapter, market_type, *symbols):
    names = [await adapter.listed_symbol(market_type, symbol) for symbol in symbols]
    shown = [info.symbol for info in await adapter.get_exchange_info(market_type)]
    return names, shown


async def test_binance_serves_a_halted_pair_and_lists_it_only_when_asked():
    async def answer(method, url, params=None):
        return {"symbols": BINANCE_SPOT}

    async def read(adapter):
        names, shown = await listing(adapter, MarketType.SPOT, "eos-usdt")
        halted       = await adapter.get_symbol_info(MarketType.SPOT, "EOSUSDT")
        every        = [info.symbol for info in await adapter.get_exchange_info(MarketType.SPOT, "all")]
        only         = [info.symbol for info in await adapter.get_exchange_info(MarketType.SPOT, "halted")]
        return names, shown, halted.status, halted.quote, every, only

    assert await on(BinanceAdapter(), answer, read) == (["EOSUSDT"], ["BTCUSDT"], "halted", "USDT", ["BTCUSDT", "EOSUSDT"], ["EOSUSDT"])


async def binance_empty_ticker(symbol, status):
    async def answer(method, url, params=None):
        return {}

    async def listed(market_type, name):
        return types.SimpleNamespace(quote="USDT", status=status)

    async def read(adapter):
        adapter._info_for = listed
        return await adapter.get_ticker(MarketType.LINEAR, symbol)

    return await on(BinanceAdapter(), answer, read)


async def test_binance_answers_a_settled_perpetual_it_sends_no_ticker_for_with_nulls_on_the_routers_clock():
    ticker = await binance_empty_ticker("OMGUSDT", "halted")

    assert (ticker.price, ticker.open_24h, ticker.high_24h, ticker.low_24h, ticker.volume_24h, ticker.price_change_percent) == (None,) * 6
    assert (ticker.symbol, ticker.quote, ticker.price_source, ticker.time_source) == ("OMGUSDT", "USDT", "last_trade", "router")


async def test_binance_still_refuses_an_empty_ticker_for_a_market_that_trades():
    with pytest.raises(UpstreamDataError, match="24h ticker of BTCUSDT arrived without symbol"):
        await binance_empty_ticker("BTCUSDT", "trading")


async def test_bybit_names_a_usdc_perpetual_by_base_and_quote_and_still_takes_its_own_name():
    asked = []

    async def answer(method, endpoint, params=None):
        asked.append(params.get("status"))
        return {"list": BYBIT_PRELAUNCH if params.get("status") == "PreLaunch" else [] if params.get("status") else BYBIT_TRADING, "nextPageCursor": ""}

    async def read(adapter):
        names, shown = await listing(adapter, MarketType.LINEAR, "BTCPERP", "btc-usdc", "OPENAIUSDT")
        return names, shown, adapter.get_api_symbol("BTCUSDC", MarketType.LINEAR)

    assert await on(BybitAdapter(), answer, read) == (["BTCUSDC", "BTCUSDC", "OPENAIUSDT"], ["BTCUSDC"], "BTCPERP")
    assert asked == [None, "PreLaunch", "Delivering"]


async def test_bybit_serves_the_margin_tiers_of_a_contract_before_it_trades():
    async def answer(method, endpoint, params=None):
        if endpoint == "/v5/market/risk-limit":
            return {"list": BYBIT_RISK_LIMIT, "nextPageCursor": ""}
        return {"list": BYBIT_PRELAUNCH if params.get("status") == "PreLaunch" else [] if params.get("status") else BYBIT_TRADING, "nextPageCursor": ""}

    tiers = await on(BybitAdapter(), answer, lambda a: a.get_margin_tiers(MarketType.LINEAR, "OPENAIUSDT"))

    assert (tiers.symbol, tiers.quote, [tier.up_to for tier in tiers.tiers]) == ("OPENAIUSDT", "USDT", [300000.0, 2000000.0])


async def test_kraken_takes_the_names_kraken_itself_answers_to():
    async def answer(method, url, params=None):
        return KRAKEN_PAIRS

    names, shown = await on(KrakenAdapter(), answer, lambda a: listing(a, MarketType.SPOT, "BTCUSD", "XXBTZUSD", "BTC/USD", "acx/usd"))

    assert names == ["XBTUSD", "XBTUSD", "XBTUSD", "ACXUSD"]
    assert shown == ["XBTUSD"]


async def test_kucoin_serves_a_spot_pair_listed_after_its_first_read():
    listed = [KUCOIN_SPOT]

    async def answer(method, base, endpoint, params=None):
        return list(listed)

    async def read(adapter):
        before = await adapter._resolve_symbol("BTCUSDT", MarketType.SPOT)
        listed.append(dict(KUCOIN_SPOT, symbol="ETH-USDT", baseCurrency="ETH"))
        name = await adapter.listed_symbol(MarketType.SPOT, "ETHUSDT")
        return before, name, await adapter._resolve_symbol(name, MarketType.SPOT)

    assert await on(KucoinAdapter(), answer, read) == ("BTC-USDT", "ETHUSDT", "ETH-USDT")


def test_kucoin_drops_the_m_after_a_usdc_quote_as_it_does_after_usdt():
    adapter = KucoinAdapter()

    assert [adapter.get_model_symbol(native, MarketType.LINEAR) for native in ("XBTUSDTM", "XBTUSDCM")] == ["XBTUSDT", "XBTUSDC"]
    assert adapter.get_api_symbol("XBTUSDC", MarketType.LINEAR) == "XBTUSDCM"


async def test_hyperliquid_serves_a_delisted_perpetual_and_leaves_it_out_of_the_market_list():
    async def answer(info_type, body):
        if info_type == "metaAndAssetCtxs":
            return [{"universe": HYPERLIQUID_UNIVERSE, "marginTables": []}, [{}, {}]]
        if info_type == "perpDexs":
            return [None]
        raise AssertionError(info_type)

    names, shown = await on(HyperliquidAdapter(), answer, lambda a: listing(a, MarketType.LINEAR, "MATIC", "BTCUSDC"))

    assert names == ["MATICUSDC", "BTCUSDC"]
    assert shown == ["BTCUSDC"]
