import asyncio
import json

import pytest
import websockets

from exchange_router.backend import RemoteBackend, is_retryable_stream_error
from exchange_router.errors import BadRequest, UpstreamUnavailable
from exchange_router.exchanges.base import UpstreamUnavailableError
from exchange_router.service.main import websocket_endpoint
from exchange_router.service.stream_manager import StreamManager
from exchange_router.version import SCHEMA_VERSION


class Socket:

    def __init__(self, subscription=None):
        self.subscription = subscription
        self.sent         = []
        self.closed       = None


    async def accept(self):
        return None


    async def receive_json(self):
        return self.subscription


    async def send_json(self, data):
        self.sent.append(data)


    async def close(self, code=1000, reason=""):
        self.closed = (code, reason)


class Failing:

    def __init__(self, fault):
        self.fault = fault


    async def stream_trades(self, market_type, symbol):
        if self.fault is not None:
            raise self.fault
        return
        yield


class Venue:

    def __init__(self, frame):
        self.frame = frame


    async def __aenter__(self):
        return self


    async def __aexit__(self, *exc):
        return False


    async def send(self, text):
        return None


    async def recv(self):
        return json.dumps(self.frame)


async def answered(subscription, exchange="fake", market_type="linear"):
    socket = Socket(dict(subscription, schema_version=SCHEMA_VERSION))
    await websocket_endpoint(socket, exchange, market_type)
    return socket.sent, socket.closed[0]


async def test_the_handshake_refuses_with_the_body_then_closes_by_cause():
    assert await answered({"channel": "ticker", "symbol": "BTCUSDT"}, exchange="nosuch") == (
        [{"error": "Not Found", "detail": "exchange 'nosuch' is not enabled; / lists the exchanges"}], 1003)
    assert await answered({"channel": "ticker", "symbol": "BTCUSDT"}, market_type="futures") == (
        [{"error": "Invalid Request", "detail": "market_type: 'futures' is not a market type; give spot, linear or inverse"}], 1003)
    assert await answered({"channel": "tickers", "symbol": "BTCUSDT"}) == (
        [{"error": "Invalid Request", "detail": "channel: 'tickers' is not a stream on fake linear; /fake/capabilities lists the channels"}], 1003)
    assert await answered({"channel": "liquidations", "symbol": "BTCUSD"}, market_type="inverse") == (
        [{"error": "Not Implemented", "detail": "liquidations is not streamed on fake inverse"}], 1003)


@pytest.mark.parametrize("fault, frame, code", [
    (UpstreamUnavailableError("fake gave no answer in 30 s to the subscription of trades"), {"error": "Upstream Unavailable", "detail": "fake gave no answer in 30 s to the subscription of trades"}, 1011),
    (NotImplementedError("trades is not streamed on fake spot"),                         {"error": "Not Implemented", "detail": "trades is not streamed on fake spot"}, 1003),
    (None,                                                                                {"error": "Upstream Unavailable", "detail": "the venue ended the trades stream of BTCUSDT; subscribe again"}, 1011),
])
async def test_an_upstream_that_ends_sends_every_client_the_body_before_the_close(fault, frame, code):
    manager = StreamManager()
    client  = Socket()

    await manager.subscribe("fake:spot:trades:BTCUSDT", client, Failing(fault), "spot", "trades", "BTCUSDT")
    await asyncio.sleep(0.1)

    assert client.sent      == [frame]
    assert client.closed[0] == code


async def test_the_sdk_raises_the_error_a_body_names_and_retries_an_unavailable_venue(monkeypatch):
    frames = [
        {"error": "Unknown Symbol", "detail": "NOSUCHUSDT is not listed on fake spot; /fake/spot/markets lists the symbols"},
        {"error": "Upstream Unavailable", "detail": "fake gave no answer in 30 s to the subscription of trades"},
    ]
    caught = []
    for frame in frames:
        monkeypatch.setattr(websockets, "connect", lambda url, frame=frame: Venue(frame))
        with pytest.raises((BadRequest, UpstreamUnavailable)) as error:
            async for _ in RemoteBackend("http://router.test").stream("fake", "spot", "trades", "NOSUCHUSDT"):
                pass
        caught.append(error.value)

    assert [(type(e), e.error, e.status) for e in caught] == [(BadRequest, "Unknown Symbol", 400), (UpstreamUnavailable, "Upstream Unavailable", 503)]
    assert [is_retryable_stream_error(e) for e in caught] == [False, True]
