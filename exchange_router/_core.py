import asyncio
from typing import Any, Dict, List, Optional

import pandas as pd

from . import frames
from . import rows
from .backend import Backend, RemoteBackend, is_retryable_stream_error
from .capabilities import route_block
from ._warnings import emit
from .batch import BatchResult
from .errors import BadRequest, NotFound, NotSupported, RouterError, SchemaMismatch
from .version import SCHEMA_VERSION, __version__


SERIES_ROUTES = ("candles", "trades", "agg_trades", "funding_rate", "open_interest", "liquidations", "long_short_ratio")

CLOSED = (
    "this router is closed; build another with AsyncRouter.local(exchanges=[...]) or "
    "AsyncRouter.service(url, exchanges=[...])"
)


class AsyncCore:

    def __init__(self, base_url: str = "http://localhost:8040", timeout: int = 30, max_retries: int = 3,
                 verbose: bool = True, backend: Optional[Backend] = None,
                 mode: str = "service", scope: Optional[List[str]] = None,
                 scope_all: bool = False):
        self.base_url    = base_url.rstrip("/")
        self.timeout     = timeout
        self.max_retries = max_retries
        self.verbose     = verbose
        self._backend    = backend if backend is not None else RemoteBackend(self.base_url, timeout, max_retries)
        self._mode       = mode
        self._scope      = list(scope) if scope else []
        self._scope_all  = scope_all
        self._capabilities: Dict[str, Dict] = {}
        self._handshake_done  = False
        self._handshake_error: Optional[RouterError] = None
        self._warm_task: Optional[asyncio.Task] = None
        self._closed = False


    @property
    def mode(self) -> str:
        return self._mode


    @property
    def schema_version(self) -> int:
        return SCHEMA_VERSION


    @property
    def scope(self) -> List[str]:
        return list(self._scope)


    @property
    def degraded(self) -> bool:
        return bool(getattr(self._backend, "degraded", False))


    async def close(self) -> None:
        if self._closed:
            return

        self._closed    = True
        task            = self._warm_task
        self._warm_task = None
        if task is not None and not task.done():
            task.cancel()

        await self._backend.close()


    def _check_open(self) -> None:
        if self._closed:
            raise RouterError(CLOSED)


    def _start_warm(self) -> None:
        if self._warm_task is not None or not (self._scope or self._scope_all):
            return

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return

        self._warm_task = loop.create_task(self._warm_quietly())


    async def _warm_quietly(self) -> None:
        try:
            await self.warm()
        except asyncio.CancelledError:
            raise
        except Exception as error:
            emit([f"warm: {type(error).__name__}: {error}; the first call pays the cost instead"], self.verbose)


    async def warm(self, exchange: Optional[str] = None) -> None:
        self._check_open()

        if self._mode == "service":
            # the handshake is what resolves an "all" scope, so the names are read after it
            await self._ensure_handshake()

        names = [exchange] if exchange is not None else list(self._scope)

        if self._mode == "service":
            for name in names:
                await self._ensure_capabilities(name)

        await self._backend.warm(names)


    async def _ensure_handshake(self) -> None:
        if self._handshake_error is not None:
            raise self._handshake_error

        if self._handshake_done or self._mode != "service":
            self._handshake_done = True
            return

        data   = await self._backend.fetch("version")
        theirs = data.get("schema_version")

        if theirs is not None and theirs != SCHEMA_VERSION:
            self._handshake_error = SchemaMismatch(
                f"this SDK speaks schema {SCHEMA_VERSION}, {self.base_url} speaks schema {theirs} "
                f"(sdk {__version__}, service {data.get('version')}); upgrade the SDK or pin the "
                f"service to a schema {SCHEMA_VERSION} release",
                SCHEMA_VERSION,
                theirs,
            )
            raise self._handshake_error

        if self._scope or self._scope_all:
            served = set((await self._backend.fetch("exchanges")).get("exchanges", []))

            if self._scope_all:
                self._scope = sorted(served)
            else:
                missing = [name for name in self._scope if name not in served]
                if missing:
                    self._handshake_error = NotFound(
                        f"exchanges {missing} are not served by {self.base_url}; it carries {sorted(served)}",
                        404,
                    )
                    raise self._handshake_error

        self._handshake_done = True


    async def _ensure_capabilities(self, exchange: str, quiet: bool = True) -> Dict:
        self._check_open()
        await self._ensure_handshake()

        if exchange not in self._capabilities:
            try:
                self._capabilities[exchange] = await self._backend.fetch("capabilities", exchange) or {}
            except RouterError:
                if not quiet:
                    raise
                # not cached: a block that failed once would otherwise disable preflight for good
                return {}

        return self._capabilities[exchange]


    async def _fetch(self, route: str, exchange: Optional[str] = None, market_type: Optional[str] = None,
                     symbol: Optional[str] = None, **params: Any) -> Any:
        self._check_open()
        await self._ensure_handshake()

        return await self._backend.fetch(route, exchange, market_type, symbol, **params)


    def _route_block(self, exchange: str, market_type: str, route: str) -> Dict:
        return route_block(self._capabilities.get(exchange), market_type, route)


    async def _preflight(self, exchange: str, market_type: str, route: str, symbol: Optional[str] = None,
                         interval: Optional[str] = None, interval_label: str = "Interval",
                         depth: Optional[int] = None, verbose: bool = False) -> None:
        caps  = await self._ensure_capabilities(exchange)
        block = self._route_block(exchange, market_type, route)

        if caps and block:
            if block.get("rest") is False:
                raise NotSupported(f"{route} is not exposed on {exchange}/{market_type}")

            intervals = block.get("intervals")
            if interval is not None and intervals and interval not in intervals:
                raise BadRequest(f"{interval_label} '{interval}' is not valid for {exchange} {market_type} {route}. valid: {', '.join(intervals)}")

            depths = block.get("depths")
            if depth is not None and depths and depth not in depths:
                emit([f"orderbook {exchange}/{market_type}/{symbol}: depth {depth} not in {depths}; the server snaps to the nearest"], verbose)


    def _ctx(self, exchange: str, market_type: str, symbol: str, requested: Optional[int], route: str) -> Dict[str, Any]:
        block = self._route_block(exchange, market_type, route)
        return {
            "exchange":    exchange,
            "market_type": market_type,
            "symbol":      symbol,
            "requested":   requested,
            "paginated":   bool(block.get("paginated")),
        }


    async def _series(self, route: str, exchange: str, market_type: str, symbol: str, params: Dict,
                      interval: Optional[str], interval_label: str, verbose: Optional[bool]) -> pd.DataFrame:
        v = self.verbose if verbose is None else verbose

        await self._preflight(exchange, market_type, route, symbol=symbol, interval=interval, interval_label=interval_label, verbose=v)

        rows = await self._fetch(route, exchange, market_type, symbol, **params)
        ctx  = self._ctx(exchange, market_type, symbol, params.get("limit"), route)

        df, warnings = frames.build(route, rows, ctx)
        emit(warnings, v)

        return df


    async def get_status(self) -> Dict:
        return await self._fetch("status")


    async def get_version(self) -> str:
        data = await self._fetch("version")
        return data.get("version", "")


    async def get_exchanges(self) -> List[str]:
        data = await self._fetch("exchanges")
        return data.get("exchanges", [])


    async def get_market_types(self, exchange: str) -> List[str]:
        data = await self._fetch("market_types", exchange)
        return [str(mt) for mt in data.get("market_types", [])]


    async def get_exchange_overview(self, exchange: str) -> Dict:
        return await self._fetch("overview", exchange)


    async def get_exchange_status(self, exchange: str) -> Dict:
        return await self._fetch("exchange_status", exchange)


    async def get_capabilities(self, exchange: str) -> Dict:
        return await self._ensure_capabilities(exchange, quiet=False)


    async def get_markets(self, exchange: str, market_type: str) -> Dict:
        return await self._fetch("markets", exchange, market_type)


    async def get_symbol_info(self, exchange: str, market_type: str, symbol: str) -> rows.Row:
        return rows.symbol_info_row(await self._fetch("symbol_info", exchange, market_type, symbol))


    async def get_ticker(self, exchange: str, market_type: str, symbol: str, verbose: Optional[bool] = None) -> rows.Row:
        v = self.verbose if verbose is None else verbose

        await self._preflight(exchange, market_type, "ticker", symbol=symbol, verbose=v)
        return rows.ticker_row(await self._fetch("ticker", exchange, market_type, symbol))


    async def get_book_ticker(self, exchange: str, market_type: str, symbol: str, verbose: Optional[bool] = None) -> rows.Row:
        v = self.verbose if verbose is None else verbose

        await self._preflight(exchange, market_type, "book_ticker", symbol=symbol, verbose=v)
        return rows.book_ticker_row(await self._fetch("book_ticker", exchange, market_type, symbol))


    async def get_mark_price(self, exchange: str, market_type: str, symbol: str, verbose: Optional[bool] = None) -> rows.Row:
        v = self.verbose if verbose is None else verbose

        await self._preflight(exchange, market_type, "mark_price", symbol=symbol, verbose=v)
        data = await self._fetch("mark_price", exchange, market_type, symbol)

        warnings = []
        if data.get("index_price") is None:
            warnings.append(f"mark_price {exchange}/{market_type}/{symbol}: index_price is null (upstream omitted it)")
        if data.get("funding") is None:
            warnings.append(f"mark_price {exchange}/{market_type}/{symbol}: funding is null (upstream omitted it)")
        emit(warnings, v)

        return rows.mark_price_row(data)


    async def get_orderbook(self, exchange: str, market_type: str, symbol: str, depth: int = 20, verbose: Optional[bool] = None) -> pd.DataFrame:
        v = self.verbose if verbose is None else verbose

        await self._preflight(exchange, market_type, "orderbook", symbol=symbol, depth=depth, verbose=v)
        data = await self._fetch("orderbook", exchange, market_type, symbol, depth=depth)

        ctx = {"exchange": exchange, "market_type": market_type, "symbol": symbol}
        return frames.orderbook(data, ctx)


    async def get_candles(self, exchange: str, market_type: str, symbol: str, interval: str = "1h", limit: int = 100, start: Optional[int] = None, verbose: Optional[bool] = None) -> pd.DataFrame:
        params = {"interval": interval, "limit": limit}
        if start is not None:
            params["start"] = start

        return await self._series("candles", exchange, market_type, symbol, params, interval, "Interval", verbose)


    async def get_trades(self, exchange: str, market_type: str, symbol: str, limit: int = 100, verbose: Optional[bool] = None) -> pd.DataFrame:
        return await self._series("trades", exchange, market_type, symbol, {"limit": limit}, None, "Interval", verbose)


    async def get_agg_trades(self, exchange: str, market_type: str, symbol: str, limit: int = 500, start: Optional[int] = None, verbose: Optional[bool] = None) -> pd.DataFrame:
        params = {"limit": limit}
        if start is not None:
            params["start"] = start

        return await self._series("agg_trades", exchange, market_type, symbol, params, None, "Interval", verbose)


    async def get_funding_rate(self, exchange: str, market_type: str, symbol: str, limit: int = 100, start: Optional[int] = None, verbose: Optional[bool] = None) -> pd.DataFrame:
        params = {"limit": limit}
        if start is not None:
            params["start"] = start

        return await self._series("funding_rate", exchange, market_type, symbol, params, None, "Interval", verbose)


    async def get_open_interest(self, exchange: str, market_type: str, symbol: str, period: str = "1h", limit: int = 30, start: Optional[int] = None, verbose: Optional[bool] = None) -> pd.DataFrame:
        params = {"period": period, "limit": limit}
        if start is not None:
            params["start"] = start

        return await self._series("open_interest", exchange, market_type, symbol, params, period, "Period", verbose)


    async def get_liquidations(self, exchange: str, market_type: str, symbol: str, limit: int = 100, start: Optional[int] = None, verbose: Optional[bool] = None) -> pd.DataFrame:
        params = {"limit": limit}
        if start is not None:
            params["start"] = start

        return await self._series("liquidations", exchange, market_type, symbol, params, None, "Interval", verbose)


    async def get_long_short_ratio(self, exchange: str, market_type: str, symbol: str, period: str = "5m", limit: int = 30, start: Optional[int] = None, verbose: Optional[bool] = None) -> pd.DataFrame:
        params = {"period": period, "limit": limit}
        if start is not None:
            params["start"] = start

        return await self._series("long_short_ratio", exchange, market_type, symbol, params, period, "Period", verbose)


    async def fetch_many(self, route: str, exchange: str, market_type: str, symbols: List[str], verbose: Optional[bool] = None, max_concurrent: int = 8, **kwargs) -> BatchResult:
        if route not in SERIES_ROUTES:
            raise ValueError(f"fetch_many supports {SERIES_ROUTES}, not '{route}'")

        v         = self.verbose if verbose is None else verbose
        semaphore = asyncio.Semaphore(max_concurrent)
        method    = getattr(self, f"get_{route}")

        await self._ensure_capabilities(exchange)

        async def one(symbol: str):
            async with semaphore:
                try:
                    df = await method(exchange, market_type, symbol, verbose=False, **kwargs)
                    return symbol, df, None
                except Exception as error:
                    return symbol, None, error

        gathered = await asyncio.gather(*[one(s) for s in symbols])

        ok, degraded, failed = {}, {}, {}
        for symbol, df, error in gathered:
            if error is not None:
                failed[symbol] = error
                continue

            messages = list(df.attrs.get("warnings", []))
            if messages:
                degraded[symbol] = (df, messages)
            else:
                ok[symbol] = df

        result = BatchResult(ok, degraded, failed, len(symbols))
        emit([f"{route}_many {exchange}/{market_type}: {result.summary()}. See .report()."], v and bool(degraded or failed))

        return result


    async def subscribe(self, exchange: str, market_type: str, channel: str, symbol: str):
        self._check_open()

        async for message in self._backend.stream(exchange, market_type, channel, symbol):
            yield message


    async def stream(self, exchange: str, market_type: str, channel: str, symbol: str, reconnect: bool = True):
        while True:
            try:
                async for message in self.subscribe(exchange, market_type, channel, symbol):
                    yield message

                if not reconnect:
                    return

            except Exception as error:
                if not reconnect or not is_retryable_stream_error(error):
                    raise

                await asyncio.sleep(2)
