import asyncio
import json

import pytest

from exchange_router import AsyncRouter
from exchange_router import exchanges as registry
from exchange_router.backend import LocalBackend
from exchange_router.errors import BadRequest
from exchange_router.exchanges.base import StreamHub, stream_events
from exchange_router.exchanges.bybit.adapter import BybitAdapter
from exchange_router.models import MarketType
from exchange_router.service.stream_manager import StreamManager

from fake_exchange import FakeExchange


TOPIC = "publicTrade.BTCUSDT"

REFUSED = "fake refused trades:BTCUSDT: the pair was delisted"


class Venue:

    def __init__(self, accepts):
        self.accepts = accepts
        self.inbox   = asyncio.Queue()


    async def send(self, text):
        payload = json.loads(text)
        if payload.get("op") == "subscribe":
            answer = {"success": True, "ret_msg": ""} if self.accepts else {"success": False, "ret_msg": "error:handler not found,topic:publicTrade.BTCUSDT"}
            await self.inbox.put(json.dumps(dict(answer, req_id=payload["req_id"], op="subscribe")))


    def __aiter__(self):
        return self


    async def __anext__(self):
        frame = await self.inbox.get()
        if frame is None:
            raise StopAsyncIteration
        return frame


    async def close(self):
        await self.inbox.put(None)


class Refused(FakeExchange):

    async def stream_trades(self, market_type, symbol):
        event  = stream_events.get()
        trades = await self.get_trades(market_type, symbol, 1)
        event("subscribed", 1_000)
        yield trades[0]
        event("lost", 2_000)
        event("refused", 3_000, REFUSED)
        await asyncio.sleep(10)


class Client:

    def __init__(self):
        self.sent   = []
        self.closed = None


    async def send_text(self, text):
        self.sent.append(json.loads(text))


    async def send_json(self, data):
        self.sent.append(data)


    async def close(self, code=1000, reason=""):
        self.closed = (code, reason)


async def test_the_hub_tells_a_refusal_on_resubscription_with_the_venues_reason():
    venues = [Venue(accepts=True), Venue(accepts=False)]
    heard  = []
    told   = asyncio.Event()

    async def connect():
        return venues.pop(0)

    def subscriber(kind, ts, reason=None):
        heard.append((kind, reason))
        if kind == "refused":
            told.set()

    streams = StreamHub(
        name                = "bybit_test",
        connect             = connect,
        subscribe_payload   = lambda ts: [{"op": "subscribe", "args": ts, "req_id": f"sub-{ts[0]}"}],
        unsubscribe_payload = lambda ts: [{"op": "unsubscribe", "args": ts}],
        route               = lambda msg: msg.get("topic"),
        answer              = BybitAdapter._answer,
    )
    async def drain(q):
        while True:
            await streams.next(q)

    first = venues[0]
    stream_events.set(subscriber)
    reader = None
    try:
        reader = asyncio.create_task(drain(await streams.subscribe(TOPIC)))
        await first.close()
        await asyncio.wait_for(told.wait(), timeout=5)
    finally:
        if reader is not None:
            reader.cancel()
        await streams.close()

    assert [kind for kind, _ in heard] == ["subscribed", "lost", "refused"]
    assert heard[-1][1] == f"bybit_test refused {TOPIC}: error:handler not found,topic:{TOPIC}"


async def test_the_service_ends_the_stream_with_the_refusal_body():
    manager = StreamManager()
    client  = Client()

    await manager.subscribe("fake:spot:trades:BTCUSDT", client, Refused(), MarketType.SPOT, "trades", "BTCUSDT")
    await asyncio.sleep(0.3)

    assert client.sent[-1] == {"error": "Invalid Request", "detail": REFUSED}
    assert client.closed   == (1003, REFUSED)


async def test_local_mode_raises_the_refusal_after_the_data_it_carried(monkeypatch):
    monkeypatch.setitem(registry.EXCHANGE_REGISTRY, "fake", Refused())
    router   = AsyncRouter.local(["fake"], verbose=False, backend=LocalBackend())
    received = []

    try:
        with pytest.raises(BadRequest, match="the pair was delisted"):
            async for message in router.stream("fake", "spot", "trades", "BTCUSDT"):
                received.append(message)
    finally:
        await router.close()

    assert [message["id"] for message in received] == ["9000"]
