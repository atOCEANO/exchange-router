import copy

from exchange_router.exchanges.binance.adapter import BinanceAdapter
from exchange_router.exchanges.bybit.adapter import BybitAdapter
from exchange_router.exchanges.hyperliquid.adapter import HyperliquidAdapter
from exchange_router.exchanges.kraken.adapter import KrakenAdapter
from exchange_router.exchanges.kucoin.adapter import KucoinAdapter
from exchange_router.exchanges.okx.adapter import OkxAdapter
from exchange_router.models import MarketType


BINANCE_LINEAR = {
    "symbol":            "BTCUSDT",
    "status":            "TRADING",
    "contractType":      "PERPETUAL",
    "baseAsset":         "BTC",
    "quoteAsset":        "USDT",
    "pricePrecision":    2,
    "quantityPrecision": 3,
    "filters": [
        {"filterType": "PRICE_FILTER", "tickSize": "0.10"},
        {"filterType": "LOT_SIZE", "minQty": "0.001", "maxQty": "1000", "stepSize": "0.001"},
        {"filterType": "MIN_NOTIONAL", "notional": "50"},
    ],
}

BINANCE_INVERSE = {
    "symbol":            "BTCUSD_PERP",
    "contractStatus":    "TRADING",
    "contractType":      "PERPETUAL",
    "baseAsset":         "BTC",
    "quoteAsset":        "USD",
    "pricePrecision":    1,
    "quantityPrecision": 0,
    "contractSize":      100,
    "filters": [
        {"filterType": "PRICE_FILTER", "tickSize": "0.1"},
        {"filterType": "LOT_SIZE", "minQty": "1", "maxQty": "1000000", "stepSize": "1"},
    ],
}

BINANCE_SPOT = {
    "symbol":             "BTCUSDT",
    "status":             "TRADING",
    "baseAsset":          "BTC",
    "quoteAsset":         "USDT",
    "quotePrecision":     8,
    "baseAssetPrecision": 8,
    "filters": [
        {"filterType": "PRICE_FILTER", "tickSize": "0.01000000"},
        {"filterType": "LOT_SIZE", "minQty": "0.00001000", "maxQty": "9000.00000000", "stepSize": "0.00001000"},
        {"filterType": "NOTIONAL", "minNotional": "5.00000000"},
    ],
}

BYBIT_SPOT = {
    "symbol":      "BTCUSDT",
    "status":      "Trading",
    "baseCoin":    "BTC",
    "quoteCoin":   "USDT",
    "priceFilter": {"tickSize": "0.1"},
    "lotSizeFilter": {
        "basePrecision": "0.000001",
        "minOrderQty":   "0.000001",
        "maxOrderQty":   "230",
        "minOrderAmt":   "5",
    },
}

BYBIT_LINEAR = {
    "symbol":          "BTCUSDT",
    "status":          "Trading",
    "contractType":    "LinearPerpetual",
    "baseCoin":        "BTC",
    "quoteCoin":       "USDT",
    "fundingInterval": 480,
    "priceFilter":     {"tickSize": "0.10"},
    "lotSizeFilter": {
        "qtyStep":          "0.001",
        "minOrderQty":      "0.001",
        "maxOrderQty":      "1500.000",
        "minNotionalValue": "5",
    },
}

BYBIT_LOTS_OF_100 = {
    "symbol":          "1000BONKUSDT",
    "status":          "Trading",
    "contractType":    "LinearPerpetual",
    "baseCoin":        "1000BONK",
    "quoteCoin":       "USDT",
    "fundingInterval": 240,
    "priceFilter":     {"tickSize": "0.0000010"},
    "lotSizeFilter": {
        "qtyStep":          "100",
        "minOrderQty":      "100",
        "maxOrderQty":      "60000000",
        "minNotionalValue": "5",
    },
}

OKX_DOGE_SWAP = {
    "instId":   "DOGE-USDT-SWAP",
    "state":    "live",
    "ctType":   "linear",
    "uly":      "DOGE-USDT",
    "ctVal":    "1000",
    "tickSz":   "0.00001",
    "lotSz":    "0.01",
    "minSz":    "0.01",
    "maxLmtSz": "100000000",
}

OKX_BTC_SWAP = {
    "instId":   "BTC-USDT-SWAP",
    "state":    "live",
    "ctType":   "linear",
    "uly":      "BTC-USDT",
    "ctVal":    "0.01",
    "tickSz":   "0.1",
    "lotSz":    "0.01",
    "minSz":    "0.01",
    "maxLmtSz": "100000000",
}

OKX_BTC_INVERSE = {
    "instId":   "BTC-USD-SWAP",
    "state":    "live",
    "ctType":   "inverse",
    "uly":      "BTC-USD",
    "ctVal":    "100",
    "tickSz":   "0.1",
    "lotSz":    "0.1",
    "minSz":    "0.1",
    "maxLmtSz": "100000000",
}

OKX_BTC_SPOT = {
    "instId":   "BTC-USDT",
    "state":    "live",
    "baseCcy":  "BTC",
    "quoteCcy": "USDT",
    "tickSz":   "0.1",
    "lotSz":    "0.00000001",
    "minSz":    "0.00001",
    "maxLmtSz": "9999999999",
}

OKX_SWAPS = [OKX_DOGE_SWAP, OKX_BTC_SWAP, OKX_BTC_INVERSE]
OKX_SPOT  = [OKX_BTC_SPOT]

KRAKEN_XBTUSD = {
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
}

KRAKEN_CELRUSD = {
    "altname":       "CELRUSD",
    "wsname":        "CELR/USD",
    "base":          "CELR",
    "quote":         "ZUSD",
    "pair_decimals": 7,
    "lot_decimals":  8,
    "ordermin":      "2000",
    "costmin":       "0.5",
    "tick_size":     "0.000001",
    "status":        "online",
}

KRAKEN_PF_XBTUSD = {
    "symbol":                      "PF_XBTUSD",
    "type":                        "flexible_futures",
    "tradeable":                   True,
    "tickSize":                    1,
    "contractSize":                1,
    "contractValueTradePrecision": 4,
}

KRAKEN_PF_PEPEUSD = {
    "symbol":                      "PF_PEPEUSD",
    "type":                        "flexible_futures",
    "tradeable":                   True,
    "tickSize":                    1e-10,
    "contractSize":                1,
    "contractValueTradePrecision": -3,
}

KRAKEN_PF_MOGUSD = {
    "symbol":                      "PF_MOGUSD",
    "type":                        "flexible_futures",
    "tradeable":                   True,
    "tickSize":                    1e-11,
    "contractSize":                1,
    "contractValueTradePrecision": -3,
}

KRAKEN_PAIRS       = {"XXBTZUSD": KRAKEN_XBTUSD, "CELRUSD": KRAKEN_CELRUSD}
KRAKEN_INSTRUMENTS = [KRAKEN_PF_XBTUSD, KRAKEN_PF_PEPEUSD, KRAKEN_PF_MOGUSD]

KUCOIN_BTC_SPOT = {
    "symbol":         "BTC-USDT",
    "baseCurrency":   "BTC",
    "quoteCurrency":  "USDT",
    "enableTrading":  True,
    "baseMinSize":    "0.00001",
    "baseMaxSize":    "10000000000",
    "quoteMinSize":   "0.1",
    "minFunds":       "0.1",
    "priceIncrement": "0.1",
    "baseIncrement":  "0.00000001",
}

KUCOIN_DOGE_LINEAR = {
    "symbol":                 "DOGEUSDTM",
    "status":                 "Open",
    "isInverse":              False,
    "multiplier":             100,
    "fundingRateGranularity": 28_800_000,
    "baseCurrency":           "DOGE",
    "quoteCurrency":          "USDT",
    "lotSize":                1,
    "maxOrderQty":            1_000_000,
    "tickSize":               0.00001,
}

KUCOIN_XBT_INVERSE = {
    "symbol":                 "XBTUSDM",
    "status":                 "Open",
    "isInverse":              True,
    "multiplier":             -1,
    "fundingRateGranularity": 28_800_000,
    "baseCurrency":           "XBT",
    "quoteCurrency":          "USD",
    "lotSize":                1,
    "maxOrderQty":            1_000_000,
    "tickSize":               0.1,
}

KUCOIN_SPOT      = [KUCOIN_BTC_SPOT]
KUCOIN_CONTRACTS = [KUCOIN_DOGE_LINEAR, KUCOIN_XBT_INVERSE]

HYPERLIQUID_BTC = {
    "szDecimals":    5,
    "name":          "BTC",
    "maxLeverage":   40,
    "marginTableId": 56,
}

HYPERLIQUID_HYPE = {
    "tokens":      [150, 0],
    "name":        "@107",
    "index":       107,
    "isCanonical": False,
}

HYPERLIQUID_META = {"universe": [HYPERLIQUID_BTC], "marginTables": []}

HYPERLIQUID_SPOT = {
    "tokens": [
        {"index": 150, "name": "HYPE", "szDecimals": 2},
        {"index": 0, "name": "USDC", "szDecimals": 8},
    ],
    "universe": [HYPERLIQUID_HYPE],
}


async def listed(adapter, market_type, answer):
    adapter._make_request = answer
    try:
        infos = await adapter._fetch_exchange_info(market_type)
    finally:
        await adapter.shutdown()
    return {info.symbol: info for info in infos}


def grid(info):
    return info.tick_size, info.qty_step, info.price_precision, info.quantity_precision


def binance(symbols):
    async def answer(method, url, params=None):
        return [] if url.endswith("/fundingInfo") else {"symbols": symbols}
    return answer


def bybit(rows):
    async def answer(method, endpoint, params=None):
        return {"list": rows, "nextPageCursor": ""}
    return answer


def okx(rows):
    async def answer(method, endpoint, params=None):
        return rows
    return answer


def kraken(pairs, instruments):
    async def answer(method, url, params=None):
        return pairs if url.endswith("/AssetPairs") else {"instruments": instruments}
    return answer


def kucoin(rows):
    async def answer(method, base, endpoint, params=None):
        return rows
    return answer


def hyperliquid(meta, spot):
    async def answer(info_type, body):
        if info_type == "perpDexs":
            return [None]
        if info_type == "spotMeta":
            return spot
        return [meta, [{}]]
    return answer


async def test_binance_reads_the_tick_and_the_step_from_its_filters():
    linear  = await listed(BinanceAdapter(), MarketType.LINEAR, binance([BINANCE_LINEAR]))
    inverse = await listed(BinanceAdapter(), MarketType.INVERSE, binance([BINANCE_INVERSE]))
    spot    = await listed(BinanceAdapter(), MarketType.SPOT, binance([BINANCE_SPOT]))

    assert grid(linear["BTCUSDT"]) == (0.1, 0.001, 2, 3)
    assert grid(inverse["BTCUSD"]) == (0.1, 1.0, 1, 0)
    assert grid(spot["BTCUSDT"])   == (0.01, 0.00001, 2, 5)

    assert linear["BTCUSDT"].min_notional  == 50.0
    assert inverse["BTCUSD"].contract_size == 100.0


async def test_bybit_spot_reads_its_own_step_and_minimum_notional():
    spot   = await listed(BybitAdapter(), MarketType.SPOT, bybit([BYBIT_SPOT]))
    linear = await listed(BybitAdapter(), MarketType.LINEAR, bybit([BYBIT_LINEAR, BYBIT_LOTS_OF_100]))

    assert grid(spot["BTCUSDT"])        == (0.1, 0.000001, 1, 6)
    assert grid(linear["BTCUSDT"])      == (0.1, 0.001, 1, 3)
    assert grid(linear["1000BONKUSDT"]) == (0.000001, 100.0, 6, 0)

    assert spot["BTCUSDT"].min_notional   == 5.0
    assert linear["BTCUSDT"].min_notional == 5.0


async def test_a_value_the_venue_leaves_blank_reads_null_and_keeps_the_instrument():
    blank_linear = copy.deepcopy(BYBIT_LINEAR)
    blank_linear["lotSizeFilter"]["qtyStep"] = ""
    blank_linear["priceFilter"] = {}

    blank_spot = copy.deepcopy(BYBIT_SPOT)
    blank_spot["lotSizeFilter"]["minOrderAmt"] = ""

    linear = await listed(BybitAdapter(), MarketType.LINEAR, bybit([blank_linear]))
    spot   = await listed(BybitAdapter(), MarketType.SPOT, bybit([blank_spot]))

    assert linear["BTCUSDT"].qty_step  is None
    assert linear["BTCUSDT"].tick_size is None
    assert linear["BTCUSDT"].min_qty   == 0.001

    assert spot["BTCUSDT"].min_notional is None
    assert spot["BTCUSDT"].qty_step     == 0.000001


async def test_okx_steps_a_linear_lot_by_the_contract_value():
    linear  = await listed(OkxAdapter(), MarketType.LINEAR, okx(OKX_SWAPS))
    inverse = await listed(OkxAdapter(), MarketType.INVERSE, okx(OKX_SWAPS))
    spot    = await listed(OkxAdapter(), MarketType.SPOT, okx(OKX_SPOT))

    assert grid(linear["DOGEUSDT"]) == (0.00001, 10.0, 5, 0)
    assert grid(linear["BTCUSDT"])  == (0.1, 0.0001, 1, 4)
    assert grid(inverse["BTCUSD"])  == (0.1, 0.1, 1, 1)
    assert grid(spot["BTCUSDT"])    == (0.1, 0.00000001, 1, 8)

    assert inverse["BTCUSD"].contract_size == 100.0


async def test_kraken_futures_take_their_precision_from_the_field_kraken_sends():
    linear = await listed(KrakenAdapter(), MarketType.LINEAR, kraken(KRAKEN_PAIRS, KRAKEN_INSTRUMENTS))
    spot   = await listed(KrakenAdapter(), MarketType.SPOT, kraken(KRAKEN_PAIRS, KRAKEN_INSTRUMENTS))

    assert grid(linear["XBTUSD"])  == (1.0, 0.0001, 0, 4)
    assert grid(linear["PEPEUSD"]) == (1e-10, 1000.0, 10, 0)
    assert grid(linear["MOGUSD"])  == (1e-11, 1000.0, 11, 0)
    assert grid(spot["XBTUSD"])    == (0.1, 0.00000001, 1, 8)
    assert grid(spot["CELRUSD"])   == (0.000001, 0.00000001, 7, 8)


async def test_kucoin_counts_the_decimals_of_a_tick_written_in_exponent_form():
    linear  = await listed(KucoinAdapter(), MarketType.LINEAR, kucoin(KUCOIN_CONTRACTS))
    inverse = await listed(KucoinAdapter(), MarketType.INVERSE, kucoin(KUCOIN_CONTRACTS))
    spot    = await listed(KucoinAdapter(), MarketType.SPOT, kucoin(KUCOIN_SPOT))

    assert grid(linear["DOGEUSDT"]) == (0.00001, 100.0, 5, 0)
    assert grid(inverse["XBTUSD"])  == (0.1, 1.0, 1, 0)
    assert grid(spot["BTCUSDT"])    == (0.1, 0.00000001, 1, 8)

    assert linear["DOGEUSDT"].min_qty      == 100.0
    assert inverse["XBTUSD"].contract_size == 1.0


async def test_hyperliquid_has_no_tick_and_steps_by_its_size_decimals():
    linear = await listed(HyperliquidAdapter(), MarketType.LINEAR, hyperliquid(HYPERLIQUID_META, HYPERLIQUID_SPOT))
    spot   = await listed(HyperliquidAdapter(), MarketType.SPOT, hyperliquid(HYPERLIQUID_META, HYPERLIQUID_SPOT))

    assert grid(linear["BTCUSDC"]) == (None, 0.00001, 1, 5)
    assert grid(spot["HYPEUSDC"])  == (None, 0.01, 6, 2)
