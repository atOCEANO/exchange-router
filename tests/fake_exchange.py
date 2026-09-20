from typing import Any, AsyncGenerator, Dict, List, Optional

from exchange_router.exchanges.base import (
    BaseExchange,
    build_funding_convention,
    build_funding_current,
    build_funding_historical,
    build_oi_value,
    build_qty_value,
    build_volume_value,
)
from exchange_router.models import (
    AggTrade,
    BookTicker,
    Candle,
    FundingRate,
    Liquidation,
    LongShortRatio,
    MarkPrice,
    MarketType,
    OpenInterest,
    OrderBook,
    SymbolInfo,
    Ticker,
    Trade,
)


BASE_TS = 1_700_000_000_000

INTERVAL_MS = {
    "1m":  60_000,
    "5m":  300_000,
    "15m": 900_000,
    "1h":  3_600_000,
    "4h":  14_400_000,
    "1d":  86_400_000,
}

INTERVALS   = ["1m", "5m", "15m", "1h", "4h", "1d"]
OI_PERIODS  = ["5m", "1h", "1d"]
LSR_PERIODS = ["5m", "1h"]
DEPTHS      = [5, 10, 20, 50]

CONTRACT_SIZE = 100.0

SYMBOLS = {
    MarketType.SPOT:    ["BTCUSDT", "ETHUSDT"],
    MarketType.LINEAR:  ["BTCUSDT", "ETHUSDT"],
    MarketType.INVERSE: ["BTCUSD", "ETHUSD"],
}

QUOTES = {
    MarketType.SPOT:    "USDT",
    MarketType.LINEAR:  "USDT",
    MarketType.INVERSE: "USD",
}

FUNDING_KIND = {
    MarketType.LINEAR:  "discrete",
    MarketType.INVERSE: "continuous",
}

FUNDING_CYCLE_MS = {
    MarketType.LINEAR:  28_800_000,
    MarketType.INVERSE: 3_600_000,
}


def qty_unit_for(market_type: MarketType) -> str:
    return "contract" if market_type == MarketType.INVERSE else "base"


def contract_size_for(market_type: MarketType) -> Optional[float]:
    return CONTRACT_SIZE if market_type == MarketType.INVERSE else None


def _point(market_type: MarketType, route: str) -> Dict[str, Any]:
    return {"rest": True, "ws": True}


def _series(market_type: MarketType, intervals: Optional[List[str]] = None, paginated: bool = False) -> Dict[str, Any]:
    block: Dict[str, Any] = {"rest": True, "ws": False, "paginated": paginated}
    if intervals is not None:
        block["intervals"] = intervals
    return block


_SPOT_CAPS = {
    "ticker":      _point(MarketType.SPOT, "ticker"),
    "book_ticker": _point(MarketType.SPOT, "book_ticker"),
    "orderbook":   {"rest": True, "ws": True, "depths": DEPTHS},
    "trades":      _series(MarketType.SPOT),
    "agg_trades":  _series(MarketType.SPOT, paginated=True),
    "candles":     _series(MarketType.SPOT, intervals=INTERVALS, paginated=True),
}

_LINEAR_CAPS = {
    "ticker":            _point(MarketType.LINEAR, "ticker"),
    "book_ticker":       _point(MarketType.LINEAR, "book_ticker"),
    "mark_price":        _point(MarketType.LINEAR, "mark_price"),
    "orderbook":         {"rest": True, "ws": True, "depths": DEPTHS},
    "trades":            _series(MarketType.LINEAR),
    "agg_trades":        _series(MarketType.LINEAR, paginated=True),
    "candles":           _series(MarketType.LINEAR, intervals=INTERVALS, paginated=True),
    "funding_rate":      _series(MarketType.LINEAR, paginated=True),
    "open_interest":     _series(MarketType.LINEAR, intervals=OI_PERIODS, paginated=True),
    "liquidations":      _series(MarketType.LINEAR),
    "long_short_ratio":  _series(MarketType.LINEAR, intervals=LSR_PERIODS),
}

_INVERSE_CAPS = {
    "ticker":        _point(MarketType.INVERSE, "ticker"),
    "book_ticker":   _point(MarketType.INVERSE, "book_ticker"),
    "mark_price":    _point(MarketType.INVERSE, "mark_price"),
    "orderbook":     {"rest": True, "ws": True, "depths": DEPTHS},
    "trades":        _series(MarketType.INVERSE),
    "agg_trades":    _series(MarketType.INVERSE, paginated=True),
    "candles":       _series(MarketType.INVERSE, intervals=INTERVALS, paginated=True),
    "funding_rate":  _series(MarketType.INVERSE, paginated=True),
    "open_interest": _series(MarketType.INVERSE, intervals=OI_PERIODS, paginated=True),
    "liquidations":  {"rest": False, "ws": False},
}

CAPABILITIES = {
    "markets": {
        MarketType.SPOT:    _SPOT_CAPS,
        MarketType.LINEAR:  _LINEAR_CAPS,
        MarketType.INVERSE: _INVERSE_CAPS,
    }
}


class FakeExchange(BaseExchange):

    @property
    def name(self) -> str:
        return "fake"


    @property
    def supported_market_types(self) -> List[MarketType]:
        return [MarketType.SPOT, MarketType.LINEAR, MarketType.INVERSE]


    def get_capabilities(self) -> Dict[str, Any]:
        return CAPABILITIES


    async def shutdown(self) -> None:
        return None


    def _known(self, market_type: MarketType, symbol: str) -> str:
        listed = SYMBOLS[market_type]
        if symbol not in listed:
            raise ValueError(f"symbol '{symbol}' is not listed on fake {market_type.value}; try {listed[0]}")
        return symbol


    async def get_exchange_info(self, market_type: MarketType) -> List[SymbolInfo]:
        cache = await self._ensure_info_cache(market_type)
        return list(cache.values())


    async def _fetch_exchange_info(self, market_type: MarketType) -> List[SymbolInfo]:
        quote   = QUOTES[market_type]
        funding = FUNDING_KIND.get(market_type)
        out     = []

        for symbol in SYMBOLS[market_type]:
            out.append(SymbolInfo(
                symbol             = symbol,
                native_symbol      = symbol.lower(),
                base_asset         = symbol[:-len(quote)],
                quote_asset        = quote,
                price_precision    = 2,
                quantity_precision = 3,
                min_qty            = 0.001,
                max_qty            = 1000.0,
                min_notional       = 5.0,
                qty_unit           = qty_unit_for(market_type),
                contract_size      = contract_size_for(market_type),
                funding            = build_funding_convention(funding) if funding else None,
            ))

        return out


    async def get_symbol_info(self, market_type: MarketType, symbol: str) -> SymbolInfo:
        self._known(market_type, symbol)
        for info in await self.get_exchange_info(market_type):
            if info.symbol == symbol:
                return info
        raise ValueError(f"symbol '{symbol}' is not listed on fake {market_type.value}")


    async def get_ticker(self, market_type: MarketType, symbol: str) -> Ticker:
        self._known(market_type, symbol)
        return Ticker(
            symbol               = symbol,
            market_type          = market_type,
            quote                = QUOTES[market_type],
            price                = 100.0,
            open_24h             = 95.0,
            high_24h             = 105.0,
            low_24h              = 94.0,
            volume_24h           = build_volume_value(1234.5, qty_unit_for(market_type), contract_size_for(market_type), 100.0),
            price_change_percent = 5.26,
            timestamp            = BASE_TS,
        )


    async def get_book_ticker(self, market_type: MarketType, symbol: str) -> BookTicker:
        self._known(market_type, symbol)
        unit = qty_unit_for(market_type)
        size = contract_size_for(market_type)
        return BookTicker(
            symbol      = symbol,
            market_type = market_type,
            quote       = QUOTES[market_type],
            bid_price   = 99.5,
            bid_qty     = build_qty_value(2.0, unit, size, 99.5),
            ask_price   = 100.5,
            ask_qty     = build_qty_value(3.0, unit, size, 100.5),
            timestamp   = BASE_TS,
        )


    async def get_mark_price(self, market_type: MarketType, symbol: str) -> MarkPrice:
        self._known(market_type, symbol)
        if market_type == MarketType.SPOT:
            raise NotImplementedError(f"Mark Price not supported on fake {market_type}")

        kind = FUNDING_KIND[market_type]
        return MarkPrice(
            symbol      = symbol,
            market_type = market_type,
            quote       = QUOTES[market_type],
            mark_price  = 100.25,
            index_price = 100.2,
            funding     = build_funding_current(kind, 0.0001, FUNDING_CYCLE_MS[market_type], BASE_TS + FUNDING_CYCLE_MS[market_type]),
            timestamp   = BASE_TS,
        )


    async def get_orderbook(self, market_type: MarketType, symbol: str, depth: int = 20) -> OrderBook:
        self._known(market_type, symbol)
        bids = [[99.5 - i * 0.5, 1.0 + i] for i in range(depth)]
        asks = [[100.5 + i * 0.5, 1.0 + i] for i in range(depth)]
        return OrderBook(
            symbol      = symbol,
            market_type = market_type,
            quote       = QUOTES[market_type],
            bids        = bids,
            asks        = asks,
            qty_unit    = qty_unit_for(market_type),
            timestamp   = BASE_TS,
        )


    async def get_trades(self, market_type: MarketType, symbol: str, limit: int = 100) -> List[Trade]:
        self._known(market_type, symbol)
        unit = qty_unit_for(market_type)
        size = contract_size_for(market_type)
        out  = []

        for i in range(limit):
            price = 100.0 + i * 0.1
            out.append(Trade(
                id          = str(9000 + i),
                symbol      = symbol,
                market_type = market_type,
                quote       = QUOTES[market_type],
                price       = price,
                qty         = build_qty_value(0.5 + i * 0.01, unit, size, price),
                side        = "buy" if i % 2 == 0 else "sell",
                timestamp   = BASE_TS + i * 1_000,
            ))

        return out


    async def get_agg_trades(self, market_type: MarketType, symbol: str, start_time: Optional[int] = None, limit: int = 500) -> List[AggTrade]:
        self._known(market_type, symbol)
        unit  = qty_unit_for(market_type)
        size  = contract_size_for(market_type)
        start = start_time if start_time is not None else BASE_TS
        out   = []

        for i in range(limit):
            price = 100.0 + i * 0.1
            out.append(AggTrade(
                agg_id         = str(5000 + i),
                symbol         = symbol,
                market_type    = market_type,
                quote          = QUOTES[market_type],
                price          = price,
                qty            = build_qty_value(0.5 + i * 0.01, unit, size, price),
                first_trade_id = str(9000 + i * 2),
                last_trade_id  = str(9001 + i * 2),
                side           = "buy" if i % 2 == 0 else "sell",
                timestamp      = start + i * 1_000,
            ))

        return out


    async def get_candles(self, market_type: MarketType, symbol: str, interval: str, start_time: Optional[int] = None, limit: int = 100) -> List[Candle]:
        self._known(market_type, symbol)
        step = INTERVAL_MS.get(interval)
        if step is None:
            raise ValueError(f"interval '{interval}' is not valid for fake {market_type.value} candles")

        unit  = qty_unit_for(market_type)
        size  = contract_size_for(market_type)
        start = start_time if start_time is not None else BASE_TS
        out   = []

        for i in range(limit):
            close = 100.0 + i
            out.append(Candle(
                symbol      = symbol,
                market_type = market_type,
                quote       = QUOTES[market_type],
                interval    = interval,
                timestamp   = start + i * step,
                open        = close - 0.5,
                high        = close + 1.0,
                low         = close - 1.0,
                close       = close,
                volume      = build_volume_value(10.0 + i, unit, size, close),
            ))

        return out


    async def get_funding_rate(self, market_type: MarketType, symbol: str, start_time: Optional[int] = None, limit: int = 100) -> List[FundingRate]:
        self._known(market_type, symbol)
        if market_type == MarketType.SPOT:
            raise NotImplementedError(f"Funding Rate not supported on fake {market_type}")

        kind  = FUNDING_KIND[market_type]
        cycle = FUNDING_CYCLE_MS[market_type]
        start = start_time if start_time is not None else BASE_TS
        out   = []

        for i in range(limit):
            out.append(FundingRate(
                symbol      = symbol,
                market_type = market_type,
                quote       = QUOTES[market_type],
                rate        = build_funding_historical(kind, 0.0001 + i * 0.00001, cycle),
                timestamp   = start + i * cycle,
            ))

        return out


    async def get_open_interest(self, market_type: MarketType, symbol: str, period: str = "1h", start_time: Optional[int] = None, limit: int = 30) -> List[OpenInterest]:
        self._known(market_type, symbol)
        if market_type == MarketType.SPOT:
            raise NotImplementedError(f"Open Interest not supported on fake {market_type}")

        step = INTERVAL_MS.get(period)
        if step is None:
            raise ValueError(f"period '{period}' is not valid for fake {market_type.value} open_interest")

        unit  = qty_unit_for(market_type)
        size  = contract_size_for(market_type)
        start = start_time if start_time is not None else BASE_TS
        out   = []

        for i in range(limit):
            out.append(OpenInterest(
                symbol        = symbol,
                market_type   = market_type,
                quote         = QUOTES[market_type],
                interval      = period,
                open_interest = build_oi_value(1000.0 + i, unit, size),
                timestamp     = start + i * step,
            ))

        return out


    async def get_liquidations(self, market_type: MarketType, symbol: str, start_time: Optional[int] = None, limit: int = 100) -> List[Liquidation]:
        self._known(market_type, symbol)
        if market_type != MarketType.LINEAR:
            raise NotImplementedError(f"Liquidations not supported on fake {market_type}")

        start = start_time if start_time is not None else BASE_TS
        out   = []

        for i in range(limit):
            price = 100.0 - i * 0.2
            out.append(Liquidation(
                symbol      = symbol,
                market_type = market_type,
                quote       = QUOTES[market_type],
                side        = "sell" if i % 2 == 0 else "buy",
                price       = price,
                qty         = build_qty_value(0.25 + i * 0.01, qty_unit_for(market_type), contract_size_for(market_type), price),
                timestamp   = start + i * 2_000,
            ))

        return out


    async def get_long_short_ratio(self, market_type: MarketType, symbol: str, period: str = "5m", start_time: Optional[int] = None, limit: int = 30) -> List[LongShortRatio]:
        self._known(market_type, symbol)
        if market_type != MarketType.LINEAR:
            raise NotImplementedError(f"L/S Ratio not supported on fake {market_type}")

        step = INTERVAL_MS.get(period)
        if step is None:
            raise ValueError(f"period '{period}' is not valid for fake {market_type.value} long_short_ratio")

        start = start_time if start_time is not None else BASE_TS
        out   = []

        for i in range(limit):
            longs = 0.5 + i * 0.01
            out.append(LongShortRatio(
                symbol        = symbol,
                market_type   = market_type,
                interval      = period,
                ratio         = longs / (1.0 - longs),
                long_account  = longs,
                short_account = 1.0 - longs,
                account_scope = "all_accounts",
                timestamp     = start + i * step,
            ))

        return out


    async def stream_ticker(self, market_type: MarketType, symbol: str) -> AsyncGenerator[Ticker, None]:
        for _ in range(2):
            yield await self.get_ticker(market_type, symbol)


    async def stream_book_ticker(self, market_type: MarketType, symbol: str) -> AsyncGenerator[BookTicker, None]:
        for _ in range(2):
            yield await self.get_book_ticker(market_type, symbol)


    async def stream_trades(self, market_type: MarketType, symbol: str) -> AsyncGenerator[Trade, None]:
        for trade in await self.get_trades(market_type, symbol, limit=2):
            yield trade


    async def stream_orderbook(self, market_type: MarketType, symbol: str, depth: int = 20, update_speed: str = "100ms") -> AsyncGenerator[OrderBook, None]:
        for _ in range(2):
            yield await self.get_orderbook(market_type, symbol, depth)
