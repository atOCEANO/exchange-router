import asyncio
import json
import logging
import random
from typing import Any, AsyncGenerator, Dict, List, Optional

import httpx
import websockets
from pydantic import ValidationError
from pydantic_core import to_jsonable_python
from websockets.exceptions import InvalidHandshake

from ._warnings import emit
from .capabilities import market_block
from .errors import (
    BadRequest,
    NotFound,
    NotSupported,
    RouterError,
    RouterUnreachable,
    UpstreamUnavailable,
    error_for_status,
)
from .exchanges import EXCHANGE_REGISTRY, get_adapter, load_exchanges
from .exchanges.base import (
    UpstreamUnavailableError,
    join_open_interest_basis,
    symbol_info_to_lite,
    validate_interval,
)
from .models import MarketType
from .version import SCHEMA_VERSION, VERSION


logger = logging.getLogger(__name__)

MAX_SLEEP_S = 60.0

FATAL_CLOSE_CODES = (1003, 1008)

STREAM_RETRYABLE = (websockets.ConnectionClosed, websockets.WebSocketException, OSError)

SERVICE_ROUTES = ("status", "version", "exchanges")

EXCHANGE_ROUTES = ("capabilities", "market_types")

POINT_METHODS = {
    "ticker":      "get_ticker",
    "book_ticker": "get_book_ticker",
    "mark_price":  "get_mark_price",
    "symbol_info": "get_symbol_info",
}

SERIES_METHODS = {
    "trades":           "get_trades",
    "agg_trades":       "get_agg_trades",
    "candles":          "get_candles",
    "funding_rate":     "get_funding_rate",
    "open_interest":    "get_open_interest",
    "liquidations":     "get_liquidations",
    "long_short_ratio": "get_long_short_ratio",
}

INTERVAL_ROUTES = {
    "candles":          ("interval", "Interval"),
    "open_interest":    ("period",   "Period"),
    "long_short_ratio": ("period",   "Period"),
}


def error_for_fault(exc: Exception) -> RouterError:
    if isinstance(exc, UpstreamUnavailableError):
        return UpstreamUnavailable(str(exc), 503, getattr(exc, "retry_after", None))

    if isinstance(exc, ValidationError):
        return RouterError(str(exc), 502)

    if isinstance(exc, NotImplementedError):
        return NotSupported(str(exc), 501)

    if isinstance(exc, ValueError):
        return BadRequest(str(exc), 400)

    return RouterError(str(exc), 500)


def _is_fatal_close(error: Exception) -> bool:
    rcvd = getattr(error, "rcvd", None)
    code = getattr(rcvd, "code", None) if rcvd is not None else getattr(error, "code", None)
    return code in FATAL_CLOSE_CODES


def is_retryable_stream_error(error: Exception) -> bool:
    return isinstance(error, STREAM_RETRYABLE) and not _is_fatal_close(error)


def error_for_close(error: Exception, exchange: str, market_type: str,
                    channel: str) -> Optional[RouterError]:
    if not _is_fatal_close(error):
        return None

    rcvd   = getattr(error, "rcvd", None)
    code   = getattr(rcvd, "code", None) if rcvd is not None else getattr(error, "code", None)
    reason = (getattr(rcvd, "reason", "") if rcvd is not None else "") or ""

    if code == 1003:
        unstreamed = (
            f"channel '{channel}' is not streamed on {exchange}/{market_type}; "
            f"get_capabilities lists the channels that are"
        )
        return NotSupported(reason or unstreamed, 501)

    refused = f"channel '{channel}' was refused by {exchange}/{market_type}; subscribe again"
    return BadRequest(reason or refused, 400)


def _detail(response: httpx.Response) -> str:
    try:
        body = response.json()
        return body.get("detail") or body.get("error") or str(body)
    except Exception:
        return response.text or f"HTTP {response.status_code}"


def _retry_after(response: httpx.Response) -> Optional[float]:
    raw = response.headers.get("Retry-After")
    if raw is None:
        return None

    try:
        return float(raw)
    except ValueError:
        return None


def _sleep_for(attempt: int, retry_after: Optional[float]) -> float:
    if retry_after is not None:
        return min(retry_after, MAX_SLEEP_S)

    base = 1.0
    return base * attempt + random.uniform(0, base)


def _endpoint(route: str, exchange: Optional[str], market_type: Optional[str], symbol: Optional[str]) -> str:
    if route in SERVICE_ROUTES:
        return route

    if route == "overview":
        return f"{exchange}"

    if route == "exchange_status":
        return f"{exchange}/status"

    if route in EXCHANGE_ROUTES:
        return f"{exchange}/{route}"

    if route == "markets":
        return f"{exchange}/{market_type}/markets"

    if route == "symbol_info":
        return f"{exchange}/{market_type}/markets/{symbol}"

    return f"{exchange}/{market_type}/{route}/{symbol}"


class Backend:

    async def fetch(self, route: str, exchange: Optional[str] = None, market_type: Optional[str] = None,
                    symbol: Optional[str] = None, **params: Any) -> Any:
        raise NotImplementedError


    async def stream(self, exchange: str, market_type: str, channel: str, symbol: str) -> AsyncGenerator[Dict, None]:
        raise NotImplementedError
        yield


    def known_exchanges(self) -> Optional[List[str]]:
        return None


    async def warm(self, names: List[str]) -> None:
        return None


    async def close(self) -> None:
        return None


class RemoteBackend(Backend):

    def __init__(self, url: str, timeout: int = 30, max_retries: int = 3, http: Optional[httpx.AsyncClient] = None):
        self.url         = url.rstrip("/")
        self.timeout     = timeout
        self.max_retries = max_retries
        self._http       = http


    def _ensure_http(self) -> httpx.AsyncClient:
        if self._http is None:
            from .version import __version__

            self._http = httpx.AsyncClient(
                timeout = self.timeout,
                headers = {"User-Agent": f"exchange-router/{__version__}"},
            )

        return self._http


    async def close(self) -> None:
        if self._http is not None:
            await self._http.aclose()


    async def fetch(self, route: str, exchange: Optional[str] = None, market_type: Optional[str] = None,
                    symbol: Optional[str] = None, **params: Any) -> Any:
        url     = f"{self.url}/{_endpoint(route, exchange, market_type, symbol)}"
        attempt = 0

        while True:
            try:
                response = await self._ensure_http().request("GET", url, params=params or None)
                response.raise_for_status()
                return response.json()

            except httpx.HTTPStatusError as e:
                status      = e.response.status_code
                detail      = _detail(e.response)
                retry_after = _retry_after(e.response)

                if status not in (429, 500, 502, 503, 504):
                    raise error_for_status(status, detail, retry_after)

                attempt += 1
                if attempt > self.max_retries:
                    raise error_for_status(status, detail, retry_after)

                await asyncio.sleep(_sleep_for(attempt, retry_after))

            except httpx.TransportError as e:
                attempt += 1
                if attempt > self.max_retries:
                    raise RouterUnreachable(f"{type(e).__name__}: {e}")

                await asyncio.sleep(_sleep_for(attempt, None))

            except httpx.HTTPError as e:
                raise RouterUnreachable(f"{type(e).__name__}: {e}")


    async def stream(self, exchange: str, market_type: str, channel: str, symbol: str) -> AsyncGenerator[Dict, None]:
        ws_url = self.url.replace("http", "ws", 1) + f"/ws/{exchange}/{market_type}"

        try:
            async with websockets.connect(ws_url) as ws:
                await ws.send(json.dumps({"channel": channel, "symbol": symbol}))

                while True:
                    message = await ws.recv()
                    yield json.loads(message)

        except websockets.ConnectionClosed as exc:
            error = error_for_close(exc, exchange, market_type, channel)
            if error is None:
                raise
            raise error from exc

        except InvalidHandshake as exc:
            raise NotFound(
                f"exchange '{exchange}' or market_type '{market_type}' is not streamed by "
                f"{self.url}; check both against get_exchanges and get_market_types",
                404,
            ) from exc


class FallbackBackend(Backend):

    def __init__(self, primary: Backend, secondary: Backend):
        self._primary   = primary
        self._secondary = secondary
        self.degraded   = False


    def _pick(self) -> Backend:
        return self._secondary if self.degraded else self._primary


    def _degrade(self, error: Exception) -> None:
        self.degraded = True
        where         = getattr(self._primary, "url", "the service")

        emit([
            f"{where} is unreachable ({type(error).__name__}: {error}); this router now runs "
            f"on local adapters with a private per-process rate budget, and stays there",
        ], True)


    async def fetch(self, route: str, exchange: Optional[str] = None, market_type: Optional[str] = None,
                    symbol: Optional[str] = None, **params: Any) -> Any:
        try:
            return await self._pick().fetch(route, exchange, market_type, symbol, **params)

        except RouterUnreachable as error:
            if self.degraded:
                raise
            self._degrade(error)
            return await self._secondary.fetch(route, exchange, market_type, symbol, **params)


    async def stream(self, exchange: str, market_type: str, channel: str, symbol: str) -> AsyncGenerator[Dict, None]:
        try:
            async for message in self._pick().stream(exchange, market_type, channel, symbol):
                yield message

        except (RouterUnreachable, OSError) as error:
            if self.degraded:
                raise
            self._degrade(error)
            async for message in self._secondary.stream(exchange, market_type, channel, symbol):
                yield message


    def known_exchanges(self) -> Optional[List[str]]:
        return None


    async def warm(self, names: List[str]) -> None:
        await self._pick().warm(names)


    async def close(self) -> None:
        await self._primary.close()
        await self._secondary.close()


class LocalBackend(Backend):

    def known_exchanges(self) -> List[str]:
        if not EXCHANGE_REGISTRY:
            load_exchanges()

        return list(EXCHANGE_REGISTRY)


    async def warm(self, names: List[str]) -> None:
        problems: List[BaseException] = []

        for name in names:
            adapter = self._adapter(name)
            results = await asyncio.gather(
                *[adapter._ensure_info_cache(mt) for mt in adapter.supported_market_types],
                return_exceptions = True,
            )
            problems += [r for r in results if isinstance(r, BaseException)]

        for problem in problems:
            if isinstance(problem, asyncio.CancelledError):
                raise problem

        if problems:
            raise problems[0]


    def _adapter(self, exchange: Optional[str], market_type: Optional[MarketType] = None):
        if not EXCHANGE_REGISTRY:
            load_exchanges()

        adapter = get_adapter(exchange)
        if adapter is None:
            raise NotFound(f"Exchange '{exchange}' not found or not enabled", 404)

        if market_type is not None and market_type not in adapter.supported_market_types:
            raise BadRequest(f"Market type '{market_type.value}' not supported on {exchange}", 400)

        return adapter


    def _market_type(self, market_type: Optional[str]) -> Optional[MarketType]:
        if market_type is None or isinstance(market_type, MarketType):
            return market_type

        try:
            return MarketType(market_type)
        except ValueError:
            raise RouterError(
                f"market_type '{market_type}' is not a market type; use spot, linear or inverse",
                422,
            )


    async def fetch(self, route: str, exchange: Optional[str] = None, market_type: Optional[str] = None,
                    symbol: Optional[str] = None, **params: Any) -> Any:
        try:
            market = self._market_type(market_type)
            return await self._dispatch(route, exchange, market, symbol, params)

        except RouterError:
            raise

        except Exception as exc:
            raise error_for_fault(exc) from exc


    async def _dispatch(self, route: str, exchange: Optional[str], market_type: Optional[MarketType],
                        symbol: Optional[str], params: Dict[str, Any]) -> Any:
        if route == "status":
            return {"status": "ok", "service": "exchange-router-service"}

        if route == "version":
            return {"version": VERSION, "schema_version": SCHEMA_VERSION}

        if route == "exchanges":
            if not EXCHANGE_REGISTRY:
                load_exchanges()
            return {"count": len(EXCHANGE_REGISTRY), "exchanges": list(EXCHANGE_REGISTRY.keys())}

        if route == "exchange_status":
            return to_jsonable_python(await self._adapter(exchange).get_status())

        if route == "overview":
            return await self._overview(exchange)

        if route == "capabilities":
            return to_jsonable_python(self._adapter(exchange).get_capabilities())

        if route == "market_types":
            adapter = self._adapter(exchange)
            return {"market_types": [mt.value for mt in adapter.supported_market_types]}

        adapter = self._adapter(exchange, market_type)

        if route == "markets":
            info_list = await adapter.get_exchange_info(market_type)
            return {
                "exchange":    exchange,
                "market_type": market_type.value,
                "count":       len(info_list),
                "markets":     [to_jsonable_python(symbol_info_to_lite(i)) for i in info_list],
            }

        if route in INTERVAL_ROUTES:
            name, label = INTERVAL_ROUTES[route]
            value       = params.get(name)
            if value is not None:
                validate_interval(adapter, market_type, route, label, value)

        if route in POINT_METHODS:
            method = getattr(adapter, POINT_METHODS[route])
            return to_jsonable_python(await method(market_type, symbol))

        if route == "orderbook":
            depth = params.get("depth", 20)
            return to_jsonable_python(await adapter.get_orderbook(market_type, symbol, depth))

        if route in SERIES_METHODS:
            rows = await self._series(adapter, route, market_type, symbol, params)
            return to_jsonable_python(rows)

        raise NotSupported(
            f"route '{route}' is not served in local mode; it exists on the service only",
            501,
        )


    async def _symbol_count(self, adapter, market_type: MarketType) -> int:
        try:
            return len(await adapter.get_exchange_info(market_type))
        except Exception:
            logger.exception(f"symbol_count fetch failed for {adapter.name}/{market_type.value}")
            return 0


    async def _overview(self, exchange: str) -> Dict[str, Any]:
        adapter      = self._adapter(exchange)
        capabilities = adapter.get_capabilities()
        market_types = adapter.supported_market_types
        counts       = await asyncio.gather(*[self._symbol_count(adapter, m) for m in market_types])

        return {
            "exchange":     exchange,
            "status":       "ok",
            "market_types": [
                {
                    "name":         mt.value,
                    "symbol_count": count,
                    "capabilities": to_jsonable_python(market_block(capabilities, mt)),
                }
                for mt, count in zip(market_types, counts)
            ],
        }


    async def _series(self, adapter, route: str, market_type: MarketType, symbol: str,
                      params: Dict[str, Any]) -> List[Any]:
        start = params.get("start")

        if route == "trades":
            limit = params.get("limit", 100)
            return await adapter.get_trades(market_type, symbol, limit)

        if route == "agg_trades":
            limit = params.get("limit", 500)
            return await adapter.get_agg_trades(market_type, symbol, start, limit)

        if route == "candles":
            interval = params.get("interval", "1h")
            limit    = params.get("limit", 100)
            return await adapter.get_candles(market_type, symbol, interval, start, limit)

        if route == "funding_rate":
            limit = params.get("limit", 100)
            return await adapter.get_funding_rate(market_type, symbol, start, limit)

        if route == "liquidations":
            limit = params.get("limit", 100)
            return await adapter.get_liquidations(market_type, symbol, start, limit)

        if route == "long_short_ratio":
            period = params.get("period", "5m")
            limit  = params.get("limit", 30)
            return await adapter.get_long_short_ratio(market_type, symbol, period, start, limit)

        period  = params.get("period", "1h")
        limit   = params.get("limit", 30)
        oi_rows = await adapter.get_open_interest(market_type, symbol, period, start, limit)

        return await join_open_interest_basis(
            adapter, market_type, symbol, period, start, limit, oi_rows,
        )


    async def stream(self, exchange: str, market_type: str, channel: str, symbol: str) -> AsyncGenerator[Dict, None]:
        mt      = self._market_type(market_type)
        adapter = self._adapter(exchange, mt)

        method = getattr(adapter, f"stream_{channel}", None)
        if method is None:
            raise NotSupported(
                f"channel '{channel}' has no stream here; get_capabilities lists the ones served",
                501,
            )

        try:
            async for item in method(mt, symbol):
                yield to_jsonable_python(item)

        except RouterError:
            raise

        except Exception as exc:
            if is_retryable_stream_error(exc):
                raise
            raise error_for_fault(exc) from exc


    async def close(self) -> None:
        from .exchanges import shutdown_exchanges

        await shutdown_exchanges()
