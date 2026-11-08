import json

import pytest
import websockets

from exchange_router.backend import RemoteBackend
from exchange_router.errors import BadRequest
from exchange_router.service.main import websocket_endpoint
from exchange_router.version import SCHEMA_VERSION


REFUSED = f"schema_version: this service speaks schema {SCHEMA_VERSION}; send schema_version {SCHEMA_VERSION} with the subscription"


class Socket:

    def __init__(self, subscription):
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


class Venue:

    def __init__(self):
        self.sent = []


    async def __aenter__(self):
        return self


    async def __aexit__(self, *exc):
        return False


    async def send(self, text):
        self.sent.append(json.loads(text))


    async def recv(self):
        return json.dumps({"error": "Invalid Request", "detail": REFUSED})


@pytest.mark.parametrize("schema", [None, SCHEMA_VERSION - 1])
async def test_a_subscription_that_names_no_schema_or_another_is_refused_with_the_body(schema):
    subscription = {"channel": "ticker", "symbol": "BTCUSDT"}
    if schema is not None:
        subscription["schema_version"] = schema
    socket = Socket(subscription)

    await websocket_endpoint(socket, "fake", "linear")

    assert socket.sent   == [{"error": "Invalid Request", "detail": REFUSED}]
    assert socket.closed == (1003, REFUSED)


async def test_the_sdk_names_its_schema_in_every_subscription(monkeypatch):
    venue = Venue()
    monkeypatch.setattr(websockets, "connect", lambda url: venue)

    with pytest.raises(BadRequest):
        async for _ in RemoteBackend("http://router.test").stream("fake", "linear", "ticker", "BTCUSDT"):
            pass

    assert venue.sent == [{"channel": "ticker", "symbol": "BTCUSDT", "schema_version": SCHEMA_VERSION}]
