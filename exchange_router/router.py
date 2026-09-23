import asyncio
import queue
import threading
import warnings
from typing import Any, Dict, List, Optional

import pandas as pd

from ._core import AsyncCore
from ._warnings import emit
from .async_router import AsyncRouter
from .batch import BatchResult
from .errors import RouterError
from .handle import SyncMarket
from .rows import Row


STREAM_BUFFER_MAX = 1024

DEPRECATION = (
    "ExchangeRouterClient is the 5.x name and keeps its localhost default; "
    "use Router.service(url, exchanges=...) or Router.local(exchanges=...)"
)

CLOSED = (
    "this router is closed; build another with Router.local(exchanges=[...]) or "
    "Router.service(url, exchanges=[...])"
)

DROPPING = (
    "stream: the {size} message buffer is full and the oldest are being dropped; "
    "consume faster or buffer the messages yourself"
)

DROPPED = "stream: {count} messages were dropped while this stream ran"


async def _kick_warm(core: AsyncCore) -> None:
    core._start_warm()


class _LoopThread:

    def __init__(self):
        self._loop   = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._closed = False
        self._thread.start()


    def _run(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()


    @property
    def closed(self) -> bool:
        return self._closed


    def run(self, coro) -> Any:
        if self._closed:
            # nothing will ever await it, and an unawaited coroutine warns at collection
            coro.close()
            raise RouterError(CLOSED)

        return asyncio.run_coroutine_threadsafe(coro, self._loop).result()


    def iterate(self, async_gen):
        if self._closed:
            raise RouterError(CLOSED)

        sentinel = object()
        items: "queue.Queue" = queue.Queue(maxsize=STREAM_BUFFER_MAX)
        handle: Dict[str, Any] = {"dropped": 0}

        def offer(item):
            while True:
                try:
                    items.put_nowait(item)
                    return
                except queue.Full:
                    try:
                        items.get_nowait()
                        handle["dropped"] += 1
                        # data loss is not a verbosity matter, so it warns either way
                        if handle["dropped"] == 1:
                            emit([DROPPING.format(size=STREAM_BUFFER_MAX)], True)
                    except queue.Empty:
                        pass

        async def pump():
            handle["task"] = asyncio.current_task()
            try:
                async for item in async_gen:
                    offer(item)
            except Exception as error:
                offer(error)
            finally:
                await async_gen.aclose()
                offer(sentinel)

        future = asyncio.run_coroutine_threadsafe(pump(), self._loop)

        try:
            while True:
                item = items.get()
                if item is sentinel:
                    break
                if isinstance(item, BaseException):
                    raise item
                yield item
        finally:
            future.cancel()
            task = handle.get("task")
            # a generator left open across close() is finalized later, against a loop that is gone
            if task is not None and not self._closed:
                self._loop.call_soon_threadsafe(task.cancel)

            if handle["dropped"]:
                emit([DROPPED.format(count=handle["dropped"])], True)


    def stop(self) -> None:
        if self._closed:
            return

        self._closed = True
        self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join(timeout=5)

        # closing a loop that is still running raises, and the join above can time out
        if not self._thread.is_alive():
            self._loop.close()


class Router:

    def __init__(self, *_args, **_kwargs):
        raise TypeError(
            "Router cannot be constructed directly; call Router.local(exchanges=[...]) to run "
            "the adapters in this process, or Router.service(url, exchanges=[...]) to use a "
            "running service"
        )


    @classmethod
    def _wrap(cls, core: AsyncCore) -> "Router":
        router       = object.__new__(cls)
        router._loop = _LoopThread()
        router._core = core
        router._loop.run(_kick_warm(core))

        return router


    @classmethod
    def local(cls, exchanges, *, verbose: bool = True, backend=None) -> "Router":
        return cls._wrap(AsyncRouter.local(exchanges, verbose=verbose, backend=backend))


    @classmethod
    def service(cls, url: str, exchanges, *, fallback=None, timeout: int = 30, max_retries: int = 3,
                verbose: bool = True, backend=None) -> "Router":
        return cls._wrap(AsyncRouter.service(
            url,
            exchanges,
            fallback    = fallback,
            timeout     = timeout,
            max_retries = max_retries,
            verbose     = verbose,
            backend     = backend,
        ))


    @property
    def mode(self) -> str:
        return self._core.mode


    @property
    def schema_version(self) -> int:
        return self._core.schema_version


    @property
    def scope(self):
        return self._core.scope


    @property
    def degraded(self) -> bool:
        return self._core.degraded


    def warm(self, exchange=None) -> None:
        self._loop.run(self._core.warm(exchange))


    @property
    def verbose(self) -> bool:
        return self._core.verbose


    @verbose.setter
    def verbose(self, value: bool) -> None:
        self._core.verbose = value


    def close(self) -> None:
        if self._loop.closed:
            return

        self._loop.run(self._core.close())
        self._loop.stop()


    def __enter__(self) -> "Router":
        return self


    def __exit__(self, _exc_type, _exc_val, _exc_tb) -> None:
        self.close()


    def get_status(self) -> Dict:
        return self._loop.run(self._core.get_status())


    def get_version(self) -> str:
        return self._loop.run(self._core.get_version())


    def get_exchanges(self) -> List[str]:
        return self._loop.run(self._core.get_exchanges())


    def get_market_types(self, exchange: str) -> List[str]:
        return self._loop.run(self._core.get_market_types(exchange))


    def get_exchange_overview(self, exchange: str) -> Dict:
        return self._loop.run(self._core.get_exchange_overview(exchange))


    def get_exchange_status(self, exchange: str) -> Dict:
        return self._loop.run(self._core.get_exchange_status(exchange))


    def get_capabilities(self, exchange: str) -> Dict:
        return self._loop.run(self._core.get_capabilities(exchange))


    def get_markets(self, exchange: str, market_type: str) -> Dict:
        return self._loop.run(self._core.get_markets(exchange, market_type))


    def get_symbol_info(self, exchange: str, market_type: str, symbol: str) -> Row:
        return self._loop.run(self._core.get_symbol_info(exchange, market_type, symbol))


    def get_ticker(self, exchange: str, market_type: str, symbol: str, verbose: Optional[bool] = None) -> Row:
        return self._loop.run(self._core.get_ticker(exchange, market_type, symbol, verbose))


    def get_book_ticker(self, exchange: str, market_type: str, symbol: str, verbose: Optional[bool] = None) -> Row:
        return self._loop.run(self._core.get_book_ticker(exchange, market_type, symbol, verbose))


    def get_mark_price(self, exchange: str, market_type: str, symbol: str, verbose: Optional[bool] = None) -> Row:
        return self._loop.run(self._core.get_mark_price(exchange, market_type, symbol, verbose))


    def get_orderbook(self, exchange: str, market_type: str, symbol: str, depth: int = 20, verbose: Optional[bool] = None) -> pd.DataFrame:
        return self._loop.run(self._core.get_orderbook(exchange, market_type, symbol, depth, verbose))


    def get_candles(self, exchange: str, market_type: str, symbol: str, interval: str = "1h", limit: int = 100, start: Optional[int] = None, verbose: Optional[bool] = None) -> pd.DataFrame:
        return self._loop.run(self._core.get_candles(exchange, market_type, symbol, interval, limit, start, verbose))


    def get_trades(self, exchange: str, market_type: str, symbol: str, limit: int = 100, verbose: Optional[bool] = None) -> pd.DataFrame:
        return self._loop.run(self._core.get_trades(exchange, market_type, symbol, limit, verbose))


    def get_agg_trades(self, exchange: str, market_type: str, symbol: str, limit: int = 500, start: Optional[int] = None, verbose: Optional[bool] = None) -> pd.DataFrame:
        return self._loop.run(self._core.get_agg_trades(exchange, market_type, symbol, limit, start, verbose))


    def get_funding_rate(self, exchange: str, market_type: str, symbol: str, limit: int = 100, start: Optional[int] = None, verbose: Optional[bool] = None) -> pd.DataFrame:
        return self._loop.run(self._core.get_funding_rate(exchange, market_type, symbol, limit, start, verbose))


    def get_open_interest(self, exchange: str, market_type: str, symbol: str, period: str = "1h", limit: int = 30, start: Optional[int] = None, verbose: Optional[bool] = None) -> pd.DataFrame:
        return self._loop.run(self._core.get_open_interest(exchange, market_type, symbol, period, limit, start, verbose))


    def get_liquidations(self, exchange: str, market_type: str, symbol: str, limit: int = 100, start: Optional[int] = None, verbose: Optional[bool] = None) -> pd.DataFrame:
        return self._loop.run(self._core.get_liquidations(exchange, market_type, symbol, limit, start, verbose))


    def get_long_short_ratio(self, exchange: str, market_type: str, symbol: str, period: str = "5m", limit: int = 30, start: Optional[int] = None, verbose: Optional[bool] = None) -> pd.DataFrame:
        return self._loop.run(self._core.get_long_short_ratio(exchange, market_type, symbol, period, limit, start, verbose))


    def market(self, exchange: str, market_type: str, symbol: str) -> SyncMarket:
        return SyncMarket(self, exchange, market_type, symbol)


    def markets(self, exchange: str, market_type: str) -> List[SyncMarket]:
        data = self.get_markets(exchange, market_type)
        return [SyncMarket(self, exchange, market_type, m["symbol"]) for m in data["markets"]]


    def fetch_many(self, route: str, exchange: str, market_type: str, symbols: List[str], verbose: Optional[bool] = None, max_concurrent: int = 8, **kwargs) -> BatchResult:
        return self._loop.run(self._core.fetch_many(route, exchange, market_type, symbols, verbose=verbose, max_concurrent=max_concurrent, **kwargs))


    def candles_many(self, exchange: str, market_type: str, symbols: List[str], interval: str = "1h", limit: int = 100, start: Optional[int] = None, verbose: Optional[bool] = None, max_concurrent: int = 8) -> BatchResult:
        return self._loop.run(self._core.fetch_many("candles", exchange, market_type, symbols, verbose=verbose, max_concurrent=max_concurrent, interval=interval, limit=limit, start=start))


    def trades_many(self, exchange: str, market_type: str, symbols: List[str], limit: int = 100, verbose: Optional[bool] = None, max_concurrent: int = 8) -> BatchResult:
        return self._loop.run(self._core.fetch_many("trades", exchange, market_type, symbols, verbose=verbose, max_concurrent=max_concurrent, limit=limit))


    def agg_trades_many(self, exchange: str, market_type: str, symbols: List[str], limit: int = 500, start: Optional[int] = None, verbose: Optional[bool] = None, max_concurrent: int = 8) -> BatchResult:
        return self._loop.run(self._core.fetch_many("agg_trades", exchange, market_type, symbols, verbose=verbose, max_concurrent=max_concurrent, limit=limit, start=start))


    def funding_rate_many(self, exchange: str, market_type: str, symbols: List[str], limit: int = 100, start: Optional[int] = None, verbose: Optional[bool] = None, max_concurrent: int = 8) -> BatchResult:
        return self._loop.run(self._core.fetch_many("funding_rate", exchange, market_type, symbols, verbose=verbose, max_concurrent=max_concurrent, limit=limit, start=start))


    def open_interest_many(self, exchange: str, market_type: str, symbols: List[str], period: str = "1h", limit: int = 30, start: Optional[int] = None, verbose: Optional[bool] = None, max_concurrent: int = 8) -> BatchResult:
        return self._loop.run(self._core.fetch_many("open_interest", exchange, market_type, symbols, verbose=verbose, max_concurrent=max_concurrent, period=period, limit=limit, start=start))


    def liquidations_many(self, exchange: str, market_type: str, symbols: List[str], limit: int = 100, start: Optional[int] = None, verbose: Optional[bool] = None, max_concurrent: int = 8) -> BatchResult:
        return self._loop.run(self._core.fetch_many("liquidations", exchange, market_type, symbols, verbose=verbose, max_concurrent=max_concurrent, limit=limit, start=start))


    def long_short_ratio_many(self, exchange: str, market_type: str, symbols: List[str], period: str = "5m", limit: int = 30, start: Optional[int] = None, verbose: Optional[bool] = None, max_concurrent: int = 8) -> BatchResult:
        return self._loop.run(self._core.fetch_many("long_short_ratio", exchange, market_type, symbols, verbose=verbose, max_concurrent=max_concurrent, period=period, limit=limit, start=start))


    def stream(self, exchange: str, market_type: str, channel: str, symbol: str, reconnect: bool = True):
        return self._loop.iterate(self._core.stream(exchange, market_type, channel, symbol, reconnect))


    def subscribe(self, exchange: str, market_type: str, channel: str, symbol: str):
        return self._loop.iterate(self._core.subscribe(exchange, market_type, channel, symbol))


class ExchangeRouterClient(Router):

    def __init__(self, base_url: str = "http://localhost:8040", timeout: int = 30, max_retries: int = 3,
                 verbose: bool = True, backend=None):
        warnings.warn(DEPRECATION, DeprecationWarning, stacklevel=2)
        self._loop = _LoopThread()
        self._core = AsyncCore(base_url=base_url, timeout=timeout, max_retries=max_retries, verbose=verbose, backend=backend)
