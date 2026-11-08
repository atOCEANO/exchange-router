import asyncio
import json

import pytest

from exchange_router import AsyncRouter
from exchange_router import exchanges as registry
from exchange_router._warnings import RouterDataWarning
from exchange_router.backend import LocalBackend
from exchange_router.exchanges.base import StreamHub, stream_events
from exchange_router.exchanges.bybit.adapter import BybitAdapter
from exchange_router.models import MarketType
from exchange_router.service.stream_manager import StreamManager
from exchange_router.version import SCHEMA_VERSION

from fake_exchange import FakeExchange


TOPIC = "publicTrade.BTCUSDT"
KEY   = "fake:spot:trades:BTCUSDT"


class Venue:

    def __init__(self):
        self.inbox = asyncio.Queue()


    async def send(self, text):
        payload = json.loads(text)
        if payload.get("op") == "subscribe":
            await self.inbox.put(json.dumps({"success": True, "ret_msg": "", "req_id": payload["req_id"], "op": "subscribe"}))


    def __aiter__(self):
        return self


    async def __anext__(self):
        frame = await self.inbox.get()
        if frame is None:
            raise StopAsyncIteration
        return frame


    async def close(self):
        await self.inbox.put(None)


class Telling(FakeExchange):

    async def stream_trades(self, market_type, symbol):
        event  = stream_events.get()
        trades = await self.get_trades(market_type, symbol, 2)
        event("subscribed", 1_000)
        yield trades[0]
        event("lost", 2_000)
        event("subscribed", 3_000)
        yield trades[1]


class Fed(FakeExchange):

    def __init__(self):
        super().__init__()
        self.feed = asyncio.Queue()
        self.open = 0


    async def stream_trades(self, market_type, symbol):
        self.open += 1
        try:
            stream_events.get()("subscribed", 1_000)
            while True:
                yield await self.feed.get()
        finally:
            self.open -= 1


class Scripted(FakeExchange):

    def __init__(self):
        super().__init__()
        self.scripts = []


    async def stream_trades(self, market_type, symbol):
        event, script = stream_events.get(), asyncio.Queue()
        self.scripts.append(script)
        while True:
            step = await script.get()
            if isinstance(step, Exception):
                raise step
            if isinstance(step, tuple):
                event(*step)
            else:
                yield step


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


class Gone(Client):

    async def send_text(self, text):
        raise ConnectionResetError("the client went away")


class Held(Client):

    def __init__(self):
        super().__init__()
        self.gate = asyncio.Event()


    async def send_text(self, text):
        await self.gate.wait()
        await super().send_text(text)


    async def send_json(self, data):
        await self.gate.wait()
        await super().send_json(data)


def heard(client):
    return [next(iter(frame)) if len(frame) == 1 else "trade" for frame in client.sent]


def hub(venues):
    async def connect():
        return venues.pop(0)

    return StreamHub(
        name                = "bybit_test",
        connect             = connect,
        subscribe_payload   = lambda ts: [{"op": "subscribe", "args": ts, "req_id": f"sub-{ts[0]}"}],
        unsubscribe_payload = lambda ts: [{"op": "unsubscribe", "args": ts}],
        route               = lambda msg: msg.get("topic"),
        answer              = BybitAdapter._answer,
    )


async def test_the_hub_tells_each_subscriber_when_the_venue_took_lost_and_retook_the_topic():
    first, second = Venue(), Venue()
    streams       = hub([first, second])
    heard, joined = [], []
    retaken       = asyncio.Event()

    def first_subscriber(kind, ts, reason=None):
        heard.append(kind)
        if len(heard) == 3:
            retaken.set()

    async def join():
        stream_events.set(lambda kind, ts, reason=None: joined.append(kind))
        return await streams.subscribe(TOPIC)

    async def drain(q):
        while True:
            await streams.next(q)

    stream_events.set(first_subscriber)
    readers = []
    try:
        readers.append(asyncio.create_task(drain(await streams.subscribe(TOPIC))))
        readers.append(asyncio.create_task(drain(await asyncio.create_task(join()))))
        await asyncio.sleep(0.05)
        assert (heard, joined) == (["subscribed"], ["subscribed"])

        await first.close()
        await asyncio.wait_for(retaken.wait(), timeout=5)
        await asyncio.sleep(0.05)
    finally:
        for reader in readers:
            reader.cancel()
        await streams.close()

    assert heard  == ["subscribed", "lost", "subscribed"]
    assert joined == ["subscribed", "lost", "subscribed"]


async def test_data_the_venue_sent_before_a_drop_reaches_the_consumer_before_lost():
    first, second = Venue(), Venue()
    streams       = hub([first, second])
    heard         = []

    stream_events.set(lambda kind, ts, reason=None: heard.append(kind))
    try:
        q = await streams.subscribe(TOPIC)
        for n in (1, 2):
            await first.inbox.put(json.dumps({"topic": TOPIC, "n": n}))
        await first.close()
        await asyncio.sleep(0.05)
        seen = [((await streams.next(q))["n"], list(heard)) for _ in range(2)]
    finally:
        await streams.close()

    assert seen == [(1, ["subscribed"]), (2, ["subscribed"])]


async def test_the_service_frames_the_venues_answer_and_the_gap_around_the_data():
    manager = StreamManager()
    client  = Client()

    await manager.subscribe("fake:spot:trades:BTCUSDT", client, Telling(), MarketType.SPOT, "trades", "BTCUSDT")
    await asyncio.sleep(0.2)

    kinds = [next(iter(frame)) if len(frame) == 1 else "trade" for frame in client.sent]
    assert kinds[:5] == ["subscribed", "trade", "lost", "subscribed", "trade"]
    assert client.sent[0] == {"subscribed": {"channel": "trades", "symbol": "BTCUSDT", "schema_version": SCHEMA_VERSION, "ts": 1_000}}
    assert client.sent[2] == {"lost": {"channel": "trades", "symbol": "BTCUSDT", "ts": 2_000}}


async def test_a_client_that_joins_a_live_stream_hears_subscribed_before_the_data():
    venue         = Fed()
    manager       = StreamManager()
    first, second = Client(), Client()
    trade         = (await venue.get_trades(MarketType.SPOT, "BTCUSDT", 1))[0]

    await manager.subscribe(KEY, first, venue, MarketType.SPOT, "trades", "BTCUSDT")
    await asyncio.sleep(0.05)
    venue.feed.put_nowait(trade)
    await manager.subscribe(KEY, second, venue, MarketType.SPOT, "trades", "BTCUSDT")
    await asyncio.sleep(0.05)
    await manager.shutdown()

    assert heard(first)  == ["subscribed", "trade"]
    assert heard(second) == ["subscribed", "trade"]


async def test_a_client_that_joins_before_the_first_subscribed_goes_out_hears_it_once():
    venue         = Fed()
    manager       = StreamManager()
    first, second = Client(), Client()

    await manager.subscribe(KEY, first, venue, MarketType.SPOT, "trades", "BTCUSDT")
    await asyncio.sleep(0)
    await manager.subscribe(KEY, second, venue, MarketType.SPOT, "trades", "BTCUSDT")
    await asyncio.sleep(0.05)
    await manager.shutdown()

    assert heard(first)  == ["subscribed"]
    assert heard(second) == ["subscribed"]


async def test_a_stream_whose_last_client_fails_a_control_frame_lets_the_venue_go():
    venue   = Fed()
    manager = StreamManager()

    await manager.subscribe(KEY, Gone(), venue, MarketType.SPOT, "trades", "BTCUSDT")
    await asyncio.sleep(0.05)
    await manager.shutdown()

    assert venue.open == 0


async def test_a_stream_that_starts_while_the_one_before_closes_its_clients_keeps_its_frames():
    venue         = Scripted()
    manager       = StreamManager()
    first, second = Held(), Held()

    await manager.subscribe(KEY, first, venue, MarketType.SPOT, "trades", "BTCUSDT")
    await asyncio.sleep(0.01)
    venue.scripts[0].put_nowait(RuntimeError("the venue ended the stream"))
    await asyncio.sleep(0.01)

    await manager.subscribe(KEY, second, venue, MarketType.SPOT, "trades", "BTCUSDT")
    await asyncio.sleep(0.01)
    venue.scripts[1].put_nowait(("subscribed", 1_000))
    await asyncio.sleep(0.01)
    venue.scripts[1].put_nowait(("lost", 2_000))
    venue.scripts[1].put_nowait(("subscribed", 3_000))
    await asyncio.sleep(0.01)

    first.gate.set()
    await asyncio.sleep(0.01)
    second.gate.set()
    await asyncio.sleep(0.05)
    await manager.shutdown()

    assert heard(second) == ["subscribed", "lost", "subscribed"]


async def test_local_mode_yields_only_data_and_warns_once_with_the_gaps_bounds(monkeypatch):
    monkeypatch.setitem(registry.EXCHANGE_REGISTRY, "fake", Telling())
    router = AsyncRouter.local(["fake"], verbose=False, backend=LocalBackend())

    try:
        with pytest.warns(RouterDataWarning, match="the venue was lost from 2000 to 3000") as caught:
            messages = [message async for message in router.stream("fake", "spot", "trades", "BTCUSDT", reconnect=False)]
    finally:
        await router.close()

    assert [message["id"] for message in messages] == ["9000", "9001"]
    assert len([w for w in caught if "was lost" in str(w.message)]) == 1
