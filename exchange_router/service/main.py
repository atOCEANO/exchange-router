import asyncio
import logging
import uuid
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect, Query, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import ValidationError
from contextlib import asynccontextmanager
from typing import Optional
from exchange_router.capabilities import market_block, route_block
from exchange_router.exchanges import EXCHANGE_REGISTRY, get_adapter, shutdown_exchanges, startup_exchanges
from exchange_router.exchanges.base import UpstreamUnavailableError, join_open_interest_basis, symbol_info_to_lite, validate_interval
from exchange_router.models import MarketType
from exchange_router.service.stream_manager import StreamManager
from exchange_router.version import SCHEMA_VERSION, SERVICE_VERSION


logging.basicConfig(level=logging.INFO, format="%(levelname)s:     %(name)s - %(message)s")

stream_manager = StreamManager()

KNOWN_WS_CHANNELS = {"ticker", "book_ticker", "mark_price", "agg_trades", "trades", "orderbook", "liquidations"}

WS_HANDSHAKE_TIMEOUT_S = 10.0


@asynccontextmanager
async def lifespan(_app: FastAPI):
    logging.info("Starting Exchange Router Service...")
    await startup_exchanges()
    yield
    logging.info("Shutting down. Closing exchange connections...")
    await stream_manager.shutdown()
    await shutdown_exchanges()


app = FastAPI(title="Exchange Router Service", version=SERVICE_VERSION, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(UpstreamUnavailableError)
async def upstream_unavailable_exception_handler(_request: Request, exc: UpstreamUnavailableError):
    headers = {}
    if exc.retry_after is not None:
        headers["Retry-After"] = str(max(int(exc.retry_after), 1))
    return JSONResponse(
        status_code=503,
        content={"error": "Upstream Unavailable", "detail": str(exc)},
        headers=headers,
    )


@app.exception_handler(ValueError)
async def value_error_exception_handler(_request: Request, exc: ValueError):
    return JSONResponse(
        status_code=400,
        content={"error": "Invalid Request", "detail": str(exc)},
    )


@app.exception_handler(NotImplementedError)
async def not_implemented_exception_handler(_request: Request, exc: NotImplementedError):
    return JSONResponse(
        status_code=501,
        content={"error": "Not Implemented", "detail": str(exc)},
    )


@app.exception_handler(ValidationError)
async def validation_error_exception_handler(_request: Request, exc: ValidationError):
    logging.exception("Upstream response failed validation")
    return JSONResponse(
        status_code=502,
        content={"error": "Bad Upstream Response", "detail": str(exc)},
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(_request: Request, exc: Exception):
    logging.exception("Unhandled error")
    return JSONResponse(
        status_code=500,
        content={"error": "Internal Server Error", "detail": str(exc)},
    )


def validate_request(exchange: str, market_type: MarketType = None):
    adapter = get_adapter(exchange)
    if not adapter:
        raise HTTPException(status_code=404, detail=f"Exchange '{exchange}' not found or not enabled")
    if market_type and market_type not in adapter.supported_market_types:
        raise HTTPException(status_code=400, detail=f"Market type '{market_type.value}' not supported on {exchange}")
    return adapter


@app.get("/")
async def service_root():
    return {
        "service":        "exchange-router-service",
        "version":        SERVICE_VERSION,
        "status":         "ok",
        "schema_version": SCHEMA_VERSION,
        "exchanges": [
            {
                "name":         name,
                "market_types": [mt.value for mt in adapter.supported_market_types],
            }
            for name, adapter in EXCHANGE_REGISTRY.items()
        ],
    }


@app.get("/status")
def service_status():
    return {"status": "ok", "service": "exchange-router-service"}


@app.get("/version")
def service_version():
    return {"version": SERVICE_VERSION, "schema_version": SCHEMA_VERSION}


@app.get("/exchanges")
def list_exchanges():
    return {"count": len(EXCHANGE_REGISTRY), "exchanges": list(EXCHANGE_REGISTRY.keys())}


@app.get("/{exchange}")
async def exchange_overview(exchange: str):
    adapter      = validate_request(exchange)
    capabilities = adapter.get_capabilities()

    async def _symbol_count(mt):
        try:
            info_list = await adapter.get_exchange_info(mt)
            return len(info_list)
        except Exception:
            logging.exception(f"symbol_count fetch failed for {exchange}/{mt.value}")
            return 0

    market_types = adapter.supported_market_types
    counts       = await asyncio.gather(*[_symbol_count(mt) for mt in market_types])

    market_types_payload = [
        {
            "name":         mt.value,
            "symbol_count": count,
            "capabilities": market_block(capabilities, mt),
        }
        for mt, count in zip(market_types, counts)
    ]

    return {
        "exchange":     exchange,
        "status":       "ok",
        "market_types": market_types_payload,
    }


@app.get("/{exchange}/status")
async def exchange_status(exchange: str):
    adapter = validate_request(exchange)
    return await adapter.get_status()


@app.get("/{exchange}/capabilities")
def exchange_capabilities(exchange: str):
    adapter = validate_request(exchange)
    return adapter.get_capabilities()


@app.get("/{exchange}/market_types")
def list_market_types(exchange: str):
    adapter = validate_request(exchange)
    return {"market_types": adapter.supported_market_types}


@app.get("/{exchange}/{market_type}/markets")
async def get_markets(exchange: str, market_type: MarketType):
    adapter   = validate_request(exchange, market_type)
    info_list = await adapter.get_exchange_info(market_type)
    return {
        "exchange":    exchange,
        "market_type": market_type.value,
        "count":       len(info_list),
        "markets":     [symbol_info_to_lite(info) for info in info_list],
    }


@app.get("/{exchange}/{market_type}/markets/{symbol}")
async def get_market_symbol(exchange: str, market_type: MarketType, symbol: str):
    adapter = validate_request(exchange, market_type)
    return await adapter.get_symbol_info(market_type, symbol)


@app.get("/{exchange}/{market_type}/ticker/{symbol}")
async def get_ticker(exchange: str, market_type: MarketType, symbol: str):
    adapter = validate_request(exchange, market_type)
    return await adapter.get_ticker(market_type, symbol)


@app.get("/{exchange}/{market_type}/book_ticker/{symbol}")
async def get_book_ticker(exchange: str, market_type: MarketType, symbol: str):
    adapter = validate_request(exchange, market_type)
    return await adapter.get_book_ticker(market_type, symbol)


@app.get("/{exchange}/{market_type}/mark_price/{symbol}")
async def get_mark_price(exchange: str, market_type: MarketType, symbol: str):
    adapter = validate_request(exchange, market_type)
    return await adapter.get_mark_price(market_type, symbol)


@app.get("/{exchange}/{market_type}/orderbook/{symbol}")
async def get_orderbook(exchange: str, market_type: MarketType, symbol: str, depth: int = Query(20, ge=1)):
    adapter = validate_request(exchange, market_type)
    return await adapter.get_orderbook(market_type, symbol, depth)


@app.get("/{exchange}/{market_type}/trades/{symbol}")
async def get_trades(exchange: str, market_type: MarketType, symbol: str, limit: int = Query(100, ge=1)):
    adapter = validate_request(exchange, market_type)
    return await adapter.get_trades(market_type, symbol, limit)


@app.get("/{exchange}/{market_type}/agg_trades/{symbol}")
async def get_agg_trades(exchange: str, market_type: MarketType, symbol: str, start: Optional[int] = None, limit: int = Query(500, ge=1)):
    adapter = validate_request(exchange, market_type)
    return await adapter.get_agg_trades(market_type, symbol, start, limit)


@app.get("/{exchange}/{market_type}/candles/{symbol}")
async def get_candles(exchange: str, market_type: MarketType, symbol: str, interval: str = "1h", start: Optional[int] = None, limit: int = Query(100, ge=1)):
    adapter = validate_request(exchange, market_type)
    validate_interval(adapter, market_type, "candles", "Interval", interval)
    return await adapter.get_candles(market_type, symbol, interval, start, limit)


@app.get("/{exchange}/{market_type}/open_interest/{symbol}")
async def get_open_interest(exchange: str, market_type: MarketType, symbol: str, period: str = Query("1h"), start: Optional[int] = None, limit: int = Query(30, ge=1)):
    adapter = validate_request(exchange, market_type)
    validate_interval(adapter, market_type, "open_interest", "Period", period)
    oi_rows = await adapter.get_open_interest(market_type, symbol, period, start, limit)

    return await join_open_interest_basis(adapter, market_type, symbol, period, start, limit, oi_rows)


@app.get("/{exchange}/{market_type}/funding_rate/{symbol}")
async def get_funding_rate(exchange: str, market_type: MarketType, symbol: str, start: Optional[int] = None, limit: int = Query(100, ge=1)):
    adapter = validate_request(exchange, market_type)
    return await adapter.get_funding_rate(market_type, symbol, start, limit)


@app.get("/{exchange}/{market_type}/liquidations/{symbol}")
async def get_liquidations(exchange: str, market_type: MarketType, symbol: str, start: Optional[int] = None, limit: int = Query(100, ge=1)):
    adapter = validate_request(exchange, market_type)
    return await adapter.get_liquidations(market_type, symbol, start, limit)


@app.get("/{exchange}/{market_type}/long_short_ratio/{symbol}")
async def get_long_short_ratio(exchange: str, market_type: MarketType, symbol: str, period: str = Query("5m"), start: Optional[int] = None, limit: int = Query(30, ge=1)):
    adapter = validate_request(exchange, market_type)
    validate_interval(adapter, market_type, "long_short_ratio", "Period", period)
    return await adapter.get_long_short_ratio(market_type, symbol, period, start, limit)


@app.websocket("/ws/{exchange}/{market_type}")
async def websocket_endpoint(websocket: WebSocket, exchange: str, market_type: MarketType):
    adapter = get_adapter(exchange)
    if not adapter or market_type not in adapter.supported_market_types:
        await websocket.close(code=1008)
        return

    await websocket.accept()

    key: Optional[str] = None
    client_id: Optional[uuid.UUID] = None

    try:
        data = await asyncio.wait_for(websocket.receive_json(), timeout=WS_HANDSHAKE_TIMEOUT_S)
        channel, symbol = data.get("channel"), data.get("symbol")
        if not channel or not symbol:
            await websocket.close(code=1003)
            return
        if channel not in KNOWN_WS_CHANNELS:
            await websocket.close(code=1003)
            return

        if not route_block(adapter.get_capabilities(), market_type, channel).get("ws"):
            await websocket.close(code=1003, reason=f"channel {channel!r} not supported on {exchange}/{market_type.value}")
            return

        key       = f"{exchange}:{market_type.value}:{channel}:{symbol}"
        client_id = await stream_manager.subscribe(key, websocket, adapter, market_type, channel, symbol)

        while True:
            await websocket.receive_text()

    except asyncio.TimeoutError:
        await websocket.close(code=1008, reason="no subscription received")
    except WebSocketDisconnect:
        pass
    except Exception as e:
        logging.error(f"WS Error: {e}")
    finally:
        if key and client_id:
            await stream_manager.unsubscribe(key, client_id)
