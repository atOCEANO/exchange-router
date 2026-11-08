import asyncio
import logging
import uuid
from http import HTTPStatus
from fastapi import Depends, FastAPI, HTTPException, WebSocket, WebSocketDisconnect, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.requests import HTTPConnection
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
from pydantic import ValidationError
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Optional
from exchange_router.capabilities import KNOWN_WS_CHANNELS, market_block, route_block
from exchange_router.exchanges import EXCHANGE_REGISTRY, get_adapter, shutdown_exchanges, startup_exchanges
from exchange_router.exchanges.base import UNREADABLE, RequestError, UnknownSymbolError, UpstreamUnavailableError, join_open_interest_basis, series_interval, symbol_info_to_lite
from exchange_router.models import (
    AggTrade, BookTicker, Candle, ErrorBody, ExchangeList, ExchangeOverview, FundingRate, Liquidation, LongShortRatio,
    MarginTiers, MarkPrice, MarketList, MarketType, MarketTypeList, OpenInterest, OrderBook, ServiceRoot, ServiceStatus,
    ServiceVersion, SymbolInfo, Ticker, Trade,
)
from exchange_router.service.answers import TITLES, refuse, status_of
from exchange_router.service.stream_manager import StreamManager
from exchange_router.version import SCHEMA_VERSION, VERSION


logging.basicConfig(level=logging.INFO, format="%(levelname)s:     %(name)s - %(message)s")

stream_manager = StreamManager()

WS_HANDSHAKE_TIMEOUT_S = 10.0

RENAMED = {"period": "interval", "start": "end"}

ERRORS = {status: {"model": ErrorBody} for status in (400, 404, 501, 502, 503, 500)}


def refuse_unknown_keys(connection: HTTPConnection) -> None:
    route = connection.scope.get("route")
    if connection.scope["type"] != "http" or route is None:
        return

    taken   = [param.alias for param in route.dependant.query_params]
    literal = [part for part in route.path.split("/") if part and not part.startswith("{")]
    name    = literal[-1] if literal else route.path

    for key in connection.query_params:
        if key in taken:
            continue
        if RENAMED.get(key) in taken:
            raise RequestError(f"{key}: the {name} route takes {RENAMED[key]}, not {key}")
        if taken:
            raise RequestError(f"{key}: the {name} route takes {', '.join(taken)}, not {key}")
        raise RequestError(f"{key}: the {name} route takes no query keys")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    logging.info("Starting Exchange Router Service...")
    await startup_exchanges()
    yield
    logging.info("Shutting down. Closing exchange connections...")
    await stream_manager.shutdown()
    await shutdown_exchanges()


app = FastAPI(title="Exchange Router Service", version=VERSION, lifespan=lifespan, dependencies=[Depends(refuse_unknown_keys)])

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


def published() -> dict:
    if app.openapi_schema is None:
        schema = get_openapi(
            title   = app.title,
            version = app.version,
            routes  = app.routes,
        )
        for path in schema["paths"].values():
            for operation in path.values():
                operation["responses"].pop("422", None)
        for name in ("HTTPValidationError", "ValidationError"):
            schema["components"]["schemas"].pop(name, None)
        app.openapi_schema = schema
    return app.openapi_schema


app.openapi = published


@app.middleware("http")
async def schema_version_header(request: Request, call_next):
    response = await call_next(request)
    response.headers["Schema-Version"] = str(SCHEMA_VERSION)
    return response


def error_body(status: int, detail: str, error: Optional[str] = None, headers: Optional[dict] = None) -> JSONResponse:
    return JSONResponse(
        status_code = status,
        content     = {"error": error or TITLES[status], "detail": detail},
        headers     = headers,
    )


def validation_sentence(error: dict) -> str:
    name  = error["loc"][-1]
    given = error.get("input")
    if error["type"] == "greater_than_equal":
        return f"{name}: must be {error['ctx']['ge']} or more, got {given}"
    if name == "market_type":
        return f"market_type: '{given}' is not a market type; give spot, linear or inverse"
    return f"{name}: {error['msg'][0].lower()}{error['msg'][1:]}, got {given!r}"


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    if exc.detail == HTTPStatus(exc.status_code).phrase:
        return error_body(404, f"no route {request.method} {request.url.path}")
    return error_body(exc.status_code, exc.detail, headers=getattr(exc, "headers", None))


@app.exception_handler(RequestValidationError)
async def request_validation_exception_handler(_request: Request, exc: RequestValidationError):
    return error_body(400, validation_sentence(exc.errors()[0]))


@app.exception_handler(RequestError)
async def request_error_exception_handler(_request: Request, exc: RequestError):
    return error_body(400, str(exc), "Unknown Symbol" if isinstance(exc, UnknownSymbolError) else None)


@app.exception_handler(UpstreamUnavailableError)
async def upstream_unavailable_exception_handler(_request: Request, exc: UpstreamUnavailableError):
    headers = {}
    if exc.retry_after is not None:
        headers["Retry-After"] = str(max(int(exc.retry_after), 1))
    return error_body(503, str(exc), headers=headers)


async def upstream_data_exception_handler(_request: Request, exc: Exception):
    return error_body(502, str(exc))


for unreadable in UNREADABLE:
    app.add_exception_handler(unreadable, upstream_data_exception_handler)


@app.exception_handler(NotImplementedError)
async def not_implemented_exception_handler(_request: Request, exc: NotImplementedError):
    return error_body(501, str(exc))


@app.exception_handler(ValidationError)
async def validation_error_exception_handler(_request: Request, exc: ValidationError):
    logging.exception("Upstream response failed validation")
    return error_body(502, str(exc))


@app.exception_handler(Exception)
async def unhandled_exception_handler(_request: Request, exc: Exception):
    logging.exception("Unhandled error")
    return error_body(500, str(exc), headers={"Schema-Version": str(SCHEMA_VERSION)})


def validate_request(exchange: str, market_type: MarketType = None):
    adapter = get_adapter(exchange)
    if not adapter:
        raise HTTPException(status_code=404, detail=f"exchange '{exchange}' is not enabled; / lists the exchanges")
    if market_type and market_type not in adapter.supported_market_types:
        raise RequestError(f"market_type: '{market_type.value}' is not offered on {exchange}; /{exchange}/market_types lists them")
    return adapter


async def validate_market(exchange: str, market_type: MarketType, symbol: str):
    adapter = validate_request(exchange, market_type)
    return adapter, await adapter.listed_symbol(market_type, symbol)


@app.get(
    "/",
    responses = {200: {"model": ServiceRoot}, **ERRORS},
)
async def service_root():
    return {
        "service":        "exchange-router-service",
        "version":        VERSION,
        "schema_version": SCHEMA_VERSION,
        "exchanges": [
            {
                "name":         name,
                "market_types": [mt.value for mt in adapter.supported_market_types],
            }
            for name, adapter in EXCHANGE_REGISTRY.items()
        ],
    }


@app.get(
    "/status",
    responses = {200: {"model": ServiceStatus}, **ERRORS},
)
def service_status():
    return {"status": "ok", "service": "exchange-router-service"}


@app.get(
    "/version",
    responses = {200: {"model": ServiceVersion}, **ERRORS},
)
def service_version():
    return {"version": VERSION, "schema_version": SCHEMA_VERSION}


@app.get(
    "/exchanges",
    responses = {200: {"model": ExchangeList}, **ERRORS},
)
def list_exchanges():
    return {"count": len(EXCHANGE_REGISTRY), "exchanges": list(EXCHANGE_REGISTRY.keys())}


@app.get(
    "/{exchange}",
    responses = {200: {"model": ExchangeOverview}, **ERRORS},
)
async def exchange_overview(exchange: str):
    adapter      = validate_request(exchange)
    capabilities = adapter.get_capabilities()

    async def _symbol_count(mt):
        try:
            info_list = await adapter.get_exchange_info(mt)
            return len(info_list)
        except Exception:
            logging.exception(f"symbol_count fetch failed for {exchange}/{mt.value}")
            return None

    market_types = adapter.supported_market_types
    counts       = await asyncio.gather(*[_symbol_count(mt) for mt in market_types])

    market_types_payload = [
        {
            "market_type":  mt.value,
            "symbol_count": count,
            "capabilities": market_block(capabilities, mt),
        }
        for mt, count in zip(market_types, counts)
    ]

    return {
        "exchange":     exchange,
        "market_types": market_types_payload,
    }


@app.get(
    "/{exchange}/capabilities",
    responses = {200: {"model": Dict[str, Any]}, **ERRORS},
)
def exchange_capabilities(exchange: str):
    adapter = validate_request(exchange)
    return adapter.get_capabilities()


@app.get(
    "/{exchange}/market_types",
    responses = {200: {"model": MarketTypeList}, **ERRORS},
)
def list_market_types(exchange: str):
    adapter = validate_request(exchange)
    return {"market_types": adapter.supported_market_types}


@app.get(
    "/{exchange}/{market_type}/markets",
    responses = {200: {"model": MarketList}, **ERRORS},
)
async def get_markets(exchange: str, market_type: MarketType, status: str = "trading"):
    adapter   = validate_request(exchange, market_type)
    info_list = await adapter.get_exchange_info(market_type, status)
    return {
        "exchange":    exchange,
        "market_type": market_type.value,
        "count":       len(info_list),
        "markets":     [symbol_info_to_lite(info) for info in info_list],
    }


@app.get(
    "/{exchange}/{market_type}/markets/{symbol}",
    responses = {200: {"model": SymbolInfo}, **ERRORS},
)
async def get_market_symbol(exchange: str, market_type: MarketType, symbol: str):
    adapter = validate_request(exchange, market_type)
    return await adapter.get_symbol_info(market_type, symbol)


@app.get(
    "/{exchange}/{market_type}/ticker/{symbol}",
    responses = {200: {"model": Ticker}, **ERRORS},
)
async def get_ticker(exchange: str, market_type: MarketType, symbol: str):
    adapter, symbol = await validate_market(exchange, market_type, symbol)
    return await adapter.get_ticker(market_type, symbol)


@app.get(
    "/{exchange}/{market_type}/book_ticker/{symbol}",
    responses = {200: {"model": BookTicker}, **ERRORS},
)
async def get_book_ticker(exchange: str, market_type: MarketType, symbol: str):
    adapter, symbol = await validate_market(exchange, market_type, symbol)
    return await adapter.get_book_ticker(market_type, symbol)


@app.get(
    "/{exchange}/{market_type}/mark_price/{symbol}",
    responses = {200: {"model": MarkPrice}, **ERRORS},
)
async def get_mark_price(exchange: str, market_type: MarketType, symbol: str):
    adapter, symbol = await validate_market(exchange, market_type, symbol)
    return await adapter.get_mark_price(market_type, symbol)


@app.get(
    "/{exchange}/{market_type}/orderbook/{symbol}",
    responses = {200: {"model": OrderBook}, **ERRORS},
)
async def get_orderbook(exchange: str, market_type: MarketType, symbol: str, depth: int = Query(20, ge=1)):
    adapter, symbol = await validate_market(exchange, market_type, symbol)
    return await adapter.get_orderbook(market_type, symbol, depth)


@app.get(
    "/{exchange}/{market_type}/trades/{symbol}",
    responses = {200: {"model": List[Trade]}, **ERRORS},
)
async def get_trades(exchange: str, market_type: MarketType, symbol: str, limit: int = Query(100, ge=1)):
    adapter, symbol = await validate_market(exchange, market_type, symbol)
    return await adapter.get_trades(market_type, symbol, limit)


@app.get(
    "/{exchange}/{market_type}/agg_trades/{symbol}",
    responses = {200: {"model": List[AggTrade]}, **ERRORS},
)
async def get_agg_trades(exchange: str, market_type: MarketType, symbol: str, end: Optional[int] = None, limit: int = Query(500, ge=1)):
    adapter, symbol = await validate_market(exchange, market_type, symbol)
    return await adapter.get_agg_trades(market_type, symbol, end, limit)


@app.get(
    "/{exchange}/{market_type}/candles/{symbol}",
    responses = {200: {"model": List[Candle]}, **ERRORS},
)
async def get_candles(exchange: str, market_type: MarketType, symbol: str, interval: Optional[str] = None, end: Optional[int] = None, limit: int = Query(100, ge=1)):
    adapter  = validate_request(exchange, market_type)
    interval = series_interval(adapter, market_type, "candles", interval, end, "1h")
    symbol   = await adapter.listed_symbol(market_type, symbol)
    return await adapter.get_candles(market_type, symbol, interval, end, limit)


@app.get(
    "/{exchange}/{market_type}/open_interest/{symbol}",
    responses = {200: {"model": List[OpenInterest]}, **ERRORS},
)
async def get_open_interest(exchange: str, market_type: MarketType, symbol: str, interval: Optional[str] = None, end: Optional[int] = None, limit: int = Query(30, ge=1)):
    adapter  = validate_request(exchange, market_type)
    interval = series_interval(adapter, market_type, "open_interest", interval, end, "1h")
    symbol   = await adapter.listed_symbol(market_type, symbol)
    oi_rows  = await adapter.get_open_interest(market_type, symbol, interval, end, limit)

    return await join_open_interest_basis(adapter, market_type, symbol, interval, end, limit, oi_rows)


@app.get(
    "/{exchange}/{market_type}/funding_rate/{symbol}",
    responses = {200: {"model": List[FundingRate]}, **ERRORS},
)
async def get_funding_rate(exchange: str, market_type: MarketType, symbol: str, end: Optional[int] = None, limit: int = Query(100, ge=1)):
    adapter, symbol = await validate_market(exchange, market_type, symbol)
    return await adapter.get_funding_rate(market_type, symbol, end, limit)


@app.get(
    "/{exchange}/{market_type}/liquidations/{symbol}",
    responses = {200: {"model": List[Liquidation]}, **ERRORS},
)
async def get_liquidations(exchange: str, market_type: MarketType, symbol: str, end: Optional[int] = None, limit: int = Query(100, ge=1)):
    adapter, symbol = await validate_market(exchange, market_type, symbol)
    return await adapter.get_liquidations(market_type, symbol, end, limit)


@app.get(
    "/{exchange}/{market_type}/long_short_ratio/{symbol}",
    responses = {200: {"model": List[LongShortRatio]}, **ERRORS},
)
async def get_long_short_ratio(exchange: str, market_type: MarketType, symbol: str, interval: Optional[str] = None, end: Optional[int] = None, limit: int = Query(30, ge=1)):
    adapter  = validate_request(exchange, market_type)
    interval = series_interval(adapter, market_type, "long_short_ratio", interval, end, "5m")
    symbol   = await adapter.listed_symbol(market_type, symbol)
    return await adapter.get_long_short_ratio(market_type, symbol, interval, end, limit)


@app.get(
    "/{exchange}/{market_type}/margin_tiers/{symbol}",
    responses = {200: {"model": MarginTiers}, **ERRORS},
)
async def get_margin_tiers(exchange: str, market_type: MarketType, symbol: str):
    adapter, symbol = await validate_market(exchange, market_type, symbol)
    return await adapter.get_margin_tiers(market_type, symbol)


@app.websocket("/ws/{exchange}/{market_type}")
async def websocket_endpoint(websocket: WebSocket, exchange: str, market_type: str):
    await websocket.accept()

    key: Optional[str] = None
    client_id: Optional[uuid.UUID] = None

    try:
        adapter = get_adapter(exchange)
        if not adapter:
            await refuse(websocket, 404, f"exchange '{exchange}' is not enabled; / lists the exchanges")
            return
        if market_type not in {mt.value for mt in MarketType}:
            await refuse(websocket, 400, f"market_type: '{market_type}' is not a market type; give spot, linear or inverse")
            return
        market = MarketType(market_type)
        if market not in adapter.supported_market_types:
            await refuse(websocket, 400, f"market_type: '{market_type}' is not offered on {exchange}; /{exchange}/market_types lists them")
            return

        try:
            data = await asyncio.wait_for(websocket.receive_json(), timeout=WS_HANDSHAKE_TIMEOUT_S)
        except asyncio.TimeoutError:
            await refuse(websocket, 400, f"no subscription arrived in {WS_HANDSHAKE_TIMEOUT_S:.0f} s; send channel and symbol after connecting")
            return
        except (ValueError, TypeError, KeyError):
            await refuse(websocket, 400, "the subscription must be a JSON object naming channel and symbol")
            return

        subscription = data if isinstance(data, dict) else {}
        if subscription.get("schema_version") != SCHEMA_VERSION:
            await refuse(websocket, 400, f"schema_version: this service speaks schema {SCHEMA_VERSION}; send schema_version {SCHEMA_VERSION} with the subscription")
            return

        channel = subscription.get("channel")
        symbol  = subscription.get("symbol")
        for name, given in (("channel", channel), ("symbol", symbol)):
            if not isinstance(given, str) or not given:
                await refuse(websocket, 400, f"{name}: missing; the subscription names channel and symbol")
                return
        if channel not in KNOWN_WS_CHANNELS:
            await refuse(websocket, 400, f"channel: '{channel}' is not a stream on {exchange} {market_type}; /{exchange}/capabilities lists the channels")
            return
        if not route_block(adapter.get_capabilities(), market, channel).get("ws"):
            await refuse(websocket, 501, f"{channel} is not streamed on {exchange} {market_type}")
            return

        try:
            symbol = await adapter.listed_symbol(market, symbol)
        except Exception as e:
            status, error = status_of(e)
            await refuse(websocket, status, str(e), error)
            return

        key       = f"{exchange}:{market_type}:{channel}:{symbol}"
        client_id = await stream_manager.subscribe(key, websocket, adapter, market, channel, symbol)

        while True:
            await websocket.receive_text()

    except WebSocketDisconnect:
        pass
    except Exception as e:
        logging.error(f"WS Error: {e}")
    finally:
        if key and client_id:
            await stream_manager.unsubscribe(key, client_id)
