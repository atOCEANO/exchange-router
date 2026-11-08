from typing import Optional


class _BaseMarket:

    def __init__(self, client, exchange: str, market_type: str, symbol: str):
        self._client     = client
        self.exchange    = exchange
        self.market_type = market_type
        self.symbol      = symbol


    def candles(self, interval: str = "1h", limit: int = 100, end: Optional[int] = None, verbose: Optional[bool] = None):
        return self._client.get_candles(self.exchange, self.market_type, self.symbol, interval=interval, limit=limit, end=end, verbose=verbose)


    def trades(self, limit: int = 100, verbose: Optional[bool] = None):
        return self._client.get_trades(self.exchange, self.market_type, self.symbol, limit=limit, verbose=verbose)


    def agg_trades(self, limit: int = 500, end: Optional[int] = None, verbose: Optional[bool] = None):
        return self._client.get_agg_trades(self.exchange, self.market_type, self.symbol, limit=limit, end=end, verbose=verbose)


    def funding_rate(self, limit: int = 100, end: Optional[int] = None, verbose: Optional[bool] = None):
        return self._client.get_funding_rate(self.exchange, self.market_type, self.symbol, limit=limit, end=end, verbose=verbose)


    def open_interest(self, interval: Optional[str] = None, limit: int = 30, end: Optional[int] = None, verbose: Optional[bool] = None):
        return self._client.get_open_interest(self.exchange, self.market_type, self.symbol, interval=interval, limit=limit, end=end, verbose=verbose)


    def liquidations(self, limit: int = 100, end: Optional[int] = None, verbose: Optional[bool] = None):
        return self._client.get_liquidations(self.exchange, self.market_type, self.symbol, limit=limit, end=end, verbose=verbose)


    def long_short_ratio(self, interval: Optional[str] = None, limit: int = 30, end: Optional[int] = None, verbose: Optional[bool] = None):
        return self._client.get_long_short_ratio(self.exchange, self.market_type, self.symbol, interval=interval, limit=limit, end=end, verbose=verbose)


    def ticker(self, verbose: Optional[bool] = None):
        return self._client.get_ticker(self.exchange, self.market_type, self.symbol, verbose)


    def book_ticker(self, verbose: Optional[bool] = None):
        return self._client.get_book_ticker(self.exchange, self.market_type, self.symbol, verbose)


    def mark_price(self, verbose: Optional[bool] = None):
        return self._client.get_mark_price(self.exchange, self.market_type, self.symbol, verbose)


    def orderbook(self, depth: int = 20, verbose: Optional[bool] = None):
        return self._client.get_orderbook(self.exchange, self.market_type, self.symbol, depth, verbose)


    def margin_tiers(self, verbose: Optional[bool] = None):
        return self._client.get_margin_tiers(self.exchange, self.market_type, self.symbol, verbose)


    def info(self):
        return self._client.get_symbol_info(self.exchange, self.market_type, self.symbol)


    def __repr__(self) -> str:
        return f"Market({self.exchange}/{self.market_type}/{self.symbol})"


class AsyncMarket(_BaseMarket):
    pass


class SyncMarket(_BaseMarket):

    def __init__(self, client, exchange: str, market_type: str, symbol: str):
        super().__init__(client, exchange, market_type, symbol)
        self._info = None


    def info(self):
        if self._info is None:
            self._info = self._client.get_symbol_info(self.exchange, self.market_type, self.symbol)

        return self._info


    @property
    def quote(self) -> Optional[str]:
        return self.info().get("quote")


    @property
    def funding_kind(self) -> Optional[str]:
        return self.info().get("funding_kind")
