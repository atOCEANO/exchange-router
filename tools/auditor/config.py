import os
import re
from typing import Dict, Iterable, List, Optional, Tuple


API_URL = os.getenv("API_URL", "http://localhost:8040")

TIMEOUT          = float(os.getenv("TIMEOUT",          "60.0"))
WS_TEST_DURATION = float(os.getenv("WS_TEST_DURATION", "180.0"))
WS_OPEN_TIMEOUT  = float(os.getenv("WS_OPEN_TIMEOUT",  "15.0"))

MAX_CONCURRENT_EXCHANGES         = int  (os.getenv("MAX_CONCURRENT_EXCHANGES",         "5"))
MAX_CONCURRENT_REST_PER_EXCHANGE = int  (os.getenv("MAX_CONCURRENT_REST_PER_EXCHANGE", "4"))
MAX_CONCURRENT_WS_PER_EXCHANGE   = int  (os.getenv("MAX_CONCURRENT_WS_PER_EXCHANGE",   "32"))
MIN_REST_INTERVAL_MS             = float(os.getenv("MIN_REST_INTERVAL_MS",             "250"))

REST_INTERVAL_MS: Dict[str, float] = {
    "hyperliquid": 3000.0,
}

LATENCY_WARN_MS       = float(os.getenv("LATENCY_WARN_MS",       "5000"))
SNAPSHOT_FRESHNESS_MS = int  (os.getenv("SNAPSHOT_FRESHNESS_MS", "300000"))
THEORETICAL_MAX_RATIO = 0.9
CROSS_DRIFT_THRESHOLD = 0.0075

SAMPLE_MAX_ITEMS        = 200
HTML_PRE_MAX_CHARS      = 30_000
HTTP_BODY_PREVIEW_CHARS = 200

BIG_LIMITS: Dict[str, int] = {
    "candles":          3000,
    "agg_trades":       1000,
    "funding_rate":      500,
    "liquidations":      500,
    "open_interest":     500,
    "long_short_ratio":  500,
}

WS_MIN_FRAMES: Dict[str, int] = {
    "orderbook":    10,
    "ticker":       5,
    "book_ticker":  5,
    "trades":       1,
    "agg_trades":   1,
    "mark_price":   1,
    "liquidations": 0,
}

FRESHNESS_OVERRIDE_MS: Dict[Tuple[str, str, str], int] = {
    ("kucoin", "inverse", "1m"): 600_000,
}

ROUTER_STAMPED = {
    ("hyperliquid", "spot", "ticker"),
    ("hyperliquid", "linear", "ticker"),
    ("hyperliquid", "linear", "mark_price"),
    ("kraken", "spot", "ticker"),
    ("kraken", "spot", "book_ticker"),
    ("kraken", "spot", "orderbook"),
    ("kucoin", "linear", "ticker"),
    ("kucoin", "inverse", "ticker"),
    ("binance", "spot", "book_ticker"),
    ("binance", "spot", "orderbook"),
}

GRID_INTERVALS = ("6h", "8h", "12h", "1d")

VENUE_MIN_INTERVAL_MS = 250

DEADLINES: Dict[Tuple[str, str], Tuple[str, Dict[str, str], Tuple]] = {
    ("binance", "linear"):  ("https://fapi.binance.com/fapi/v1/premiumIndex", {"symbol": "{native}"}, ("nextFundingTime",)),
    ("binance", "inverse"): ("https://dapi.binance.com/dapi/v1/premiumIndex", {"symbol": "{native}"}, (0, "nextFundingTime")),
    ("bybit", "linear"):    ("https://api.bybit.com/v5/market/tickers", {"category": "linear", "symbol": "{native}"}, ("result", "list", 0, "nextFundingTime")),
    ("bybit", "inverse"):   ("https://api.bybit.com/v5/market/tickers", {"category": "inverse", "symbol": "{native}"}, ("result", "list", 0, "nextFundingTime")),
    ("okx", "linear"):      ("https://www.okx.com/api/v5/public/funding-rate", {"instId": "{native}"}, ("data", 0, "fundingTime")),
    ("okx", "inverse"):     ("https://www.okx.com/api/v5/public/funding-rate", {"instId": "{native}"}, ("data", 0, "fundingTime")),
}

PRICE_SLACK = 0.001

PRICES: Dict[Tuple[str, str, str], Tuple[str, Dict[str, str], Tuple]] = {
    ("binance", "spot", "last_trade"):    ("https://api.binance.com/api/v3/ticker/price", {"symbol": "{native}"}, ("price",)),
    ("binance", "linear", "last_trade"):  ("https://fapi.binance.com/fapi/v1/ticker/price", {"symbol": "{native}"}, ("price",)),
    ("binance", "inverse", "last_trade"): ("https://dapi.binance.com/dapi/v1/ticker/price", {"symbol": "{native}"}, (0, "price")),
    ("bybit", "spot", "last_trade"):      ("https://api.bybit.com/v5/market/tickers", {"category": "spot", "symbol": "{native}"}, ("result", "list", 0, "lastPrice")),
    ("bybit", "linear", "last_trade"):    ("https://api.bybit.com/v5/market/tickers", {"category": "linear", "symbol": "{native}"}, ("result", "list", 0, "lastPrice")),
    ("bybit", "inverse", "last_trade"):   ("https://api.bybit.com/v5/market/tickers", {"category": "inverse", "symbol": "{native}"}, ("result", "list", 0, "lastPrice")),
    ("okx", "spot", "last_trade"):        ("https://www.okx.com/api/v5/market/ticker", {"instId": "{native}"}, ("data", 0, "last")),
    ("okx", "linear", "last_trade"):      ("https://www.okx.com/api/v5/market/ticker", {"instId": "{native}"}, ("data", 0, "last")),
    ("okx", "inverse", "last_trade"):     ("https://www.okx.com/api/v5/market/ticker", {"instId": "{native}"}, ("data", 0, "last")),
    ("kucoin", "spot", "last_trade"):     ("https://api.kucoin.com/api/v1/market/orderbook/level1", {"symbol": "{native}"}, ("data", "price")),
    ("kucoin", "linear", "last_trade"):   ("https://api-futures.kucoin.com/api/v1/ticker", {"symbol": "{native}"}, ("data", "price")),
    ("kucoin", "inverse", "last_trade"):  ("https://api-futures.kucoin.com/api/v1/ticker", {"symbol": "{native}"}, ("data", "price")),
    ("kraken", "spot", "last_trade"):     ("https://api.kraken.com/0/public/Ticker", {"pair": "{native}"}, ("result", "*", "c", 0)),
    ("kraken", "linear", "last_trade"):   ("https://futures.kraken.com/derivatives/api/v3/tickers/{native}", {}, ("ticker", "last")),
    ("kraken", "inverse", "last_trade"):  ("https://futures.kraken.com/derivatives/api/v3/tickers/{native}", {}, ("ticker", "last")),
    ("hyperliquid", "spot", "mid"):       ("POST https://api.hyperliquid.xyz/info", {"type": "allMids"}, ("{native}",)),
    ("hyperliquid", "linear", "mid"):     ("POST https://api.hyperliquid.xyz/info", {"type": "allMids"}, ("{native}",)),
}

_BINANCE_SPOT    = ("symbols", 0, "filters")
_BINANCE_FUTURES = ("symbols", {"symbol": "{native}"}, "filters")
_BYBIT           = ("result", "list", 0)
_KRAKEN_FUTURES  = ("instruments", {"symbol": "{native}"})

INSTRUMENTS: Dict[Tuple[str, str], Tuple[str, Dict[str, str], Dict[str, List[Tuple]]]] = {
    ("binance", "spot"): ("https://api.binance.com/api/v3/exchangeInfo", {"symbol": "{native}"}, {
        "tick": [_BINANCE_SPOT + ({"filterType": "PRICE_FILTER"}, "tickSize")],
        "step": [_BINANCE_SPOT + ({"filterType": "LOT_SIZE"}, "stepSize")],
        "min":  [_BINANCE_SPOT + ({"filterType": "LOT_SIZE"}, "minQty")],
        "max":  [_BINANCE_SPOT + ({"filterType": "LOT_SIZE"}, "maxQty")],
    }),
    ("binance", "linear"): ("https://fapi.binance.com/fapi/v1/exchangeInfo", {}, {
        "tick": [_BINANCE_FUTURES + ({"filterType": "PRICE_FILTER"}, "tickSize")],
        "step": [_BINANCE_FUTURES + ({"filterType": "LOT_SIZE"}, "stepSize")],
        "min":  [_BINANCE_FUTURES + ({"filterType": "LOT_SIZE"}, "minQty")],
        "max":  [_BINANCE_FUTURES + ({"filterType": "LOT_SIZE"}, "maxQty")],
    }),
    ("binance", "inverse"): ("https://dapi.binance.com/dapi/v1/exchangeInfo", {}, {
        "tick":          [_BINANCE_FUTURES + ({"filterType": "PRICE_FILTER"}, "tickSize")],
        "step":          [_BINANCE_FUTURES + ({"filterType": "LOT_SIZE"}, "stepSize")],
        "min":           [_BINANCE_FUTURES + ({"filterType": "LOT_SIZE"}, "minQty")],
        "max":           [_BINANCE_FUTURES + ({"filterType": "LOT_SIZE"}, "maxQty")],
        "contract_size": [("symbols", {"symbol": "{native}"}, "contractSize")],
    }),
    ("bybit", "spot"): ("https://api.bybit.com/v5/market/instruments-info", {"category": "spot", "symbol": "{native}"}, {
        "tick": [_BYBIT + ("priceFilter", "tickSize")],
        "step": [_BYBIT + ("lotSizeFilter", "basePrecision")],
        "min":  [_BYBIT + ("lotSizeFilter", "minOrderQty")],
        "max":  [_BYBIT + ("lotSizeFilter", "maxOrderQty")],
    }),
    ("bybit", "linear"): ("https://api.bybit.com/v5/market/instruments-info", {"category": "linear", "symbol": "{native}"}, {
        "tick": [_BYBIT + ("priceFilter", "tickSize")],
        "step": [_BYBIT + ("lotSizeFilter", "qtyStep")],
        "min":  [_BYBIT + ("lotSizeFilter", "minOrderQty")],
        "max":  [_BYBIT + ("lotSizeFilter", "maxOrderQty")],
    }),
    ("bybit", "inverse"): ("https://api.bybit.com/v5/market/instruments-info", {"category": "inverse", "symbol": "{native}"}, {
        "tick": [_BYBIT + ("priceFilter", "tickSize")],
        "step": [_BYBIT + ("lotSizeFilter", "qtyStep")],
        "min":  [_BYBIT + ("lotSizeFilter", "minOrderQty")],
        "max":  [_BYBIT + ("lotSizeFilter", "maxOrderQty")],
    }),
    ("okx", "spot"): ("https://www.okx.com/api/v5/public/instruments", {"instType": "SPOT", "instId": "{native}"}, {
        "tick": [("data", 0, "tickSz")],
        "step": [("data", 0, "lotSz")],
        "min":  [("data", 0, "minSz")],
        "max":  [("data", 0, "maxLmtSz")],
    }),
    ("okx", "linear"): ("https://www.okx.com/api/v5/public/instruments", {"instType": "SWAP", "instId": "{native}"}, {
        "tick": [("data", 0, "tickSz")],
        "step": [("data", 0, "lotSz"), ("data", 0, "ctVal")],
        "min":  [("data", 0, "minSz"), ("data", 0, "ctVal")],
        "max":  [("data", 0, "maxLmtSz"), ("data", 0, "ctVal")],
    }),
    ("okx", "inverse"): ("https://www.okx.com/api/v5/public/instruments", {"instType": "SWAP", "instId": "{native}"}, {
        "tick":          [("data", 0, "tickSz")],
        "step":          [("data", 0, "lotSz")],
        "min":           [("data", 0, "minSz")],
        "max":           [("data", 0, "maxLmtSz")],
        "contract_size": [("data", 0, "ctVal")],
    }),
    ("kucoin", "spot"): ("https://api.kucoin.com/api/v2/symbols/{native}", {}, {
        "tick": [("data", "priceIncrement")],
        "step": [("data", "baseIncrement")],
        "min":  [("data", "baseMinSize")],
        "max":  [("data", "baseMaxSize")],
    }),
    ("kucoin", "linear"): ("https://api-futures.kucoin.com/api/v1/contracts/{native}", {}, {
        "tick": [("data", "tickSize")],
        "step": [("data", "lotSize"), ("data", "multiplier")],
        "min":  [("data", "lotSize"), ("data", "multiplier")],
        "max":  [("data", "maxOrderQty"), ("data", "multiplier")],
    }),
    ("kucoin", "inverse"): ("https://api-futures.kucoin.com/api/v1/contracts/{native}", {}, {
        "tick":          [("data", "tickSize")],
        "step":          [("data", "lotSize")],
        "min":           [("data", "lotSize")],
        "max":           [("data", "maxOrderQty")],
        "contract_size": [("data", "multiplier")],
    }),
    ("kraken", "spot"): ("https://api.kraken.com/0/public/AssetPairs", {"pair": "{native}"}, {
        "tick":     [("result", "*", "tick_size")],
        "decimals": [("result", "*", "lot_decimals")],
        "min":      [("result", "*", "ordermin")],
    }),
    ("kraken", "linear"): ("https://futures.kraken.com/derivatives/api/v3/instruments", {}, {
        "tick":     [_KRAKEN_FUTURES + ("tickSize",)],
        "decimals": [_KRAKEN_FUTURES + ("contractValueTradePrecision",)],
    }),
    ("kraken", "inverse"): ("https://futures.kraken.com/derivatives/api/v3/instruments", {}, {
        "tick":          [_KRAKEN_FUTURES + ("tickSize",)],
        "decimals":      [_KRAKEN_FUTURES + ("contractValueTradePrecision",)],
        "contract_size": [_KRAKEN_FUTURES + ("contractSize",)],
    }),
    ("hyperliquid", "linear"): ("POST https://api.hyperliquid.xyz/info", {"type": "meta"}, {
        "decimals": [("universe", {"name": "{native}"}, "szDecimals")],
    }),
}

CRYPTO_EPOCH_MS = 1_262_304_000_000

INTERVAL_MS: Dict[str, int] = {
    "1m":  60_000,
    "3m":  180_000,
    "5m":  300_000,
    "15m": 900_000,
    "30m": 1_800_000,
    "1h":  3_600_000,
    "2h":  7_200_000,
    "4h":  14_400_000,
    "6h":  21_600_000,
    "8h":  28_800_000,
    "12h": 43_200_000,
    "1d":  86_400_000,
    "3d":  259_200_000,
    "1w":  604_800_000,
    "1M":  2_592_000_000,
}

_MONTHS    = "JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC"
_LEVERAGED = re.compile(r"(?:^|[^A-Z])(UP|DOWN|BULL|BEAR|\d+[LS])(?:[^A-Z]|$)")
_DATED_NUM = re.compile(r"[-_]?\d{6,8}(?:[-_]|$)")
_DATED_MON = re.compile(rf"\d{{1,2}}(?:{_MONTHS})\d{{0,4}}")


def interval_ms(interval: str) -> int:
    return INTERVAL_MS.get(interval, 0)


def freshness_threshold_ms(exchange: str, market_type: str, period: Optional[str], period_ms: int) -> int:
    if period and (exchange, market_type, period) in FRESHNESS_OVERRIDE_MS:
        return FRESHNESS_OVERRIDE_MS[(exchange, market_type, period)]
    return 3 * period_ms + 30_000


def _score_symbol(symbol: str) -> float:
    s = symbol.upper()

    if _LEVERAGED.search(s) or _DATED_NUM.search(s) or _DATED_MON.search(s):
        return -1.0

    if "BTC" in s or "XBT" in s:
        base_score = 100.0
    elif "ETH" in s:
        base_score = 50.0
    else:
        return -1.0

    quote_score = 0.0
    stripped    = re.sub(r"[-_/]?(PERP|PERPETUAL|SWAP)$", "", s)
    for quote, bonus in (("USDT", 30), ("USDC", 25), ("USD", 20)):
        if stripped.endswith(quote) or f"/{quote}" in stripped or f"-{quote}" in stripped or f"_{quote}" in stripped:
            quote_score = bonus
            break
    if quote_score == 0.0:
        return -1.0

    return base_score + quote_score - len(s) * 0.1


def pick_symbol(symbols: Iterable[str]) -> Optional[str]:
    best: Optional[str] = None
    best_score          = 0.0
    for sym in symbols:
        if not isinstance(sym, str):
            continue
        score = _score_symbol(sym)
        if score > best_score:
            best_score = score
            best       = sym
    return best


def theoretical_max(period_ms: int, big_limit: int, retention_ms: Optional[int], now_ms: int) -> int:
    if period_ms <= 0:
        return big_limit
    age_cap = (now_ms - CRYPTO_EPOCH_MS) // period_ms
    ceiling = min(big_limit, age_cap)
    if retention_ms is not None:
        retention_cap = retention_ms // period_ms
        ceiling       = min(ceiling, retention_cap)
    return max(ceiling, 1)
