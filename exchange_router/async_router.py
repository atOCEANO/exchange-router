import warnings
from typing import Any, List, Optional, Union

from ._core import AsyncCore
from .backend import Backend, FallbackBackend, LocalBackend, RemoteBackend
from .batch import BatchResult
from .errors import BadRequest, NotFound
from .handle import AsyncMarket


ALL = "all"

DEPRECATION = (
    "AsyncExchangeRouterClient is the 5.x name and keeps its localhost default; "
    "use AsyncRouter.service(url, exchanges=...) or AsyncRouter.local(exchanges=...)"
)


def resolve_scope(exchanges: Union[List[str], str], known: Optional[List[str]]) -> List[str]:
    if exchanges is None:
        raise BadRequest("exchanges is required; pass a list of names or 'all'")

    if isinstance(exchanges, str):
        if exchanges != ALL:
            raise BadRequest(f"exchanges '{exchanges}' is not a list of names; pass ['{exchanges}'] or 'all'")
        if known is None:
            return []
        return list(known)

    names = list(exchanges)
    if not names:
        raise BadRequest("exchanges is empty; name at least one exchange or pass 'all'")

    if known is not None:
        missing = [name for name in names if name not in known]
        if missing:
            raise NotFound(f"exchanges {missing} are not registered; this build carries {sorted(known)}", 404)

    return names


class AsyncRouter(AsyncCore):

    def __init__(self, *_args: Any, **_kwargs: Any):
        raise TypeError(
            "Router cannot be constructed directly; call Router.local(exchanges=[...]) to run "
            "the adapters in this process, or Router.service(url, exchanges=[...]) to use a "
            "running service"
        )


    @classmethod
    def _assemble(cls, backend: Backend, mode: str, scope: List[str], verbose: bool,
                  base_url: str = "", timeout: int = 30, max_retries: int = 3,
                  scope_all: bool = False) -> "AsyncRouter":
        router = object.__new__(cls)
        AsyncCore.__init__(
            router,
            base_url    = base_url or "http://localhost:8040",
            timeout     = timeout,
            max_retries = max_retries,
            verbose     = verbose,
            backend     = backend,
            mode        = mode,
            scope       = scope,
            scope_all   = scope_all,
        )
        router._start_warm()

        return router


    @classmethod
    def local(cls, exchanges: Union[List[str], str], *, verbose: bool = True,
              backend: Optional[Backend] = None) -> "AsyncRouter":
        chosen = backend if backend is not None else LocalBackend()
        scope  = resolve_scope(exchanges, chosen.known_exchanges())

        return cls._assemble(chosen, "local", scope, verbose)


    @classmethod
    def service(cls, url: str, exchanges: Union[List[str], str], *, fallback: Optional[str] = None,
                timeout: int = 30, max_retries: int = 3, verbose: bool = True,
                backend: Optional[Backend] = None) -> "AsyncRouter":
        if not url:
            raise BadRequest("url is required; Router.service needs the address of a running service")

        if fallback not in (None, "local"):
            raise BadRequest(f"fallback '{fallback}' is not a mode; the only opt-in fallback is 'local'")

        base   = url.rstrip("/")
        chosen = backend if backend is not None else RemoteBackend(base, timeout, max_retries)
        if fallback == "local":
            chosen = FallbackBackend(chosen, LocalBackend())

        # nothing here knows the roster, so "all" travels as a flag and the handshake fills it in
        scope = resolve_scope(exchanges, None)

        return cls._assemble(chosen, "service", scope, verbose, base, timeout, max_retries,
                             scope_all = exchanges == ALL)


    def market(self, exchange: str, market_type: str, symbol: str) -> AsyncMarket:
        return AsyncMarket(self, exchange, market_type, symbol)


    async def markets(self, exchange: str, market_type: str) -> List[AsyncMarket]:
        data = await self.get_markets(exchange, market_type)
        return [AsyncMarket(self, exchange, market_type, m["symbol"]) for m in data["markets"]]


    async def candles_many(self, exchange: str, market_type: str, symbols: List[str], interval: str = "1h", limit: int = 100, start: Optional[int] = None, verbose: Optional[bool] = None, max_concurrent: int = 8) -> BatchResult:
        return await self.fetch_many("candles", exchange, market_type, symbols, verbose=verbose, max_concurrent=max_concurrent, interval=interval, limit=limit, start=start)


    async def trades_many(self, exchange: str, market_type: str, symbols: List[str], limit: int = 100, verbose: Optional[bool] = None, max_concurrent: int = 8) -> BatchResult:
        return await self.fetch_many("trades", exchange, market_type, symbols, verbose=verbose, max_concurrent=max_concurrent, limit=limit)


    async def agg_trades_many(self, exchange: str, market_type: str, symbols: List[str], limit: int = 500, start: Optional[int] = None, verbose: Optional[bool] = None, max_concurrent: int = 8) -> BatchResult:
        return await self.fetch_many("agg_trades", exchange, market_type, symbols, verbose=verbose, max_concurrent=max_concurrent, limit=limit, start=start)


    async def funding_rate_many(self, exchange: str, market_type: str, symbols: List[str], limit: int = 100, start: Optional[int] = None, verbose: Optional[bool] = None, max_concurrent: int = 8) -> BatchResult:
        return await self.fetch_many("funding_rate", exchange, market_type, symbols, verbose=verbose, max_concurrent=max_concurrent, limit=limit, start=start)


    async def open_interest_many(self, exchange: str, market_type: str, symbols: List[str], period: str = "1h", limit: int = 30, start: Optional[int] = None, verbose: Optional[bool] = None, max_concurrent: int = 8) -> BatchResult:
        return await self.fetch_many("open_interest", exchange, market_type, symbols, verbose=verbose, max_concurrent=max_concurrent, period=period, limit=limit, start=start)


    async def liquidations_many(self, exchange: str, market_type: str, symbols: List[str], limit: int = 100, start: Optional[int] = None, verbose: Optional[bool] = None, max_concurrent: int = 8) -> BatchResult:
        return await self.fetch_many("liquidations", exchange, market_type, symbols, verbose=verbose, max_concurrent=max_concurrent, limit=limit, start=start)


    async def long_short_ratio_many(self, exchange: str, market_type: str, symbols: List[str], period: str = "5m", limit: int = 30, start: Optional[int] = None, verbose: Optional[bool] = None, max_concurrent: int = 8) -> BatchResult:
        return await self.fetch_many("long_short_ratio", exchange, market_type, symbols, verbose=verbose, max_concurrent=max_concurrent, period=period, limit=limit, start=start)


    async def __aenter__(self) -> "AsyncRouter":
        return self


    async def __aexit__(self, _exc_type, _exc_val, _exc_tb) -> None:
        await self.close()


class AsyncExchangeRouterClient(AsyncRouter):

    def __init__(self, base_url: str = "http://localhost:8040", timeout: int = 30, max_retries: int = 3,
                 verbose: bool = True, backend: Optional[Backend] = None):
        warnings.warn(DEPRECATION, DeprecationWarning, stacklevel=2)
        AsyncCore.__init__(
            self,
            base_url    = base_url,
            timeout     = timeout,
            max_retries = max_retries,
            verbose     = verbose,
            backend     = backend,
        )
