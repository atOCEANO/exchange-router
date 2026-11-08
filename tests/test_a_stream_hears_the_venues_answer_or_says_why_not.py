import asyncio
import json

import pytest
import websockets

from exchange_router import AsyncRouter
from exchange_router.backend import Backend, error_for_fault, is_retryable_stream_error
from exchange_router.errors import BadRequest, NotSupported, SchemaMismatch
from exchange_router.exchanges.base import StreamHub, SubscriptionRefused, UpstreamUnavailableError
from exchange_router.exchanges.binance.adapter import BinanceAdapter
from exchange_router.exchanges.bybit.adapter import BybitAdapter
from exchange_router.exchanges.hyperliquid.adapter import HyperliquidAdapter
from exchange_router.exchanges.kraken.adapter import KrakenAdapter
from exchange_router.exchanges.kucoin.adapter import KucoinAdapter
from exchange_router.exchanges.okx.adapter import OkxAdapter
from exchange_router.service.stream_manager import StreamManager
from exchange_router.version import SCHEMA_VERSION


BYBIT_REFUSAL = {"success": False, "ret_msg": "error:handler not found,topic:publicTrade.NOSUCHUSDT", "conn_id": "db294pd7qk6al3src5t0-aho64", "req_id": "r2", "op": "subscribe"}

KRAKEN_ACCEPTED = {"method": "subscribe", "result": {"channel": "trade", "snapshot": False, "symbol": "BTC/USD"}, "success": True, "time_in": "2026-11-08T04:30:56.526100Z", "time_out": "2026-11-08T04:30:56.526123Z"}
KRAKEN_REFUSED  = {"error": "Currency pair not supported NOPE/USD", "method": "subscribe", "success": False, "symbol": "NOPE/USD", "time_in": "2026-11-08T04:30:56.526143Z", "time_out": "2026-11-08T04:30:56.526154Z"}
KRAKEN_TRADE    = {"channel": "trade", "type": "update", "data": [{"symbol": "BTC/USD", "side": "buy", "price": 75632.3, "qty": 6.12e-05, "ord_type": "limit", "trade_id": 114745541, "timestamp": "2026-11-08T02:36:17.875188Z"}]}

OKX_ACCEPTED = {"event": "subscribe", "arg": {"channel": "tickers", "instId": "BTC-USDT"}, "connId": "a8af5577"}
OKX_REFUSED  = {"event": "error", "msg": "Subscribe failed, wrong URL or channel:tickers,instId:NOPE-USDT doesn't exist. Please use the correct URL, channel and parameters referring to API document.", "code": "60018", "connId": "a8af5577"}
OKX_TICKER   = {"arg": {"channel": "tickers", "instId": "BTC-USDT"}, "data": [{"instType": "SPOT", "instId": "BTC-USDT", "last": "75950.8", "lastSz": "0.00010138", "askPx": "75950.8", "askSz": "0.60581581", "bidPx": "75950.7", "bidSz": "0.31161319", "open24h": "75859.8", "high24h": "76251.1", "low24h": "75569.1", "sodUtc0": "75868", "sodUtc8": "75764.7", "volCcy24h": "153615929.406395576", "vol24h": "2023.11081306", "ts": "1794112372065"}]}


class Venue:

    def __init__(self, reply=lambda payload: [], pong=None):
        self.reply = reply
        self.pong  = pong
        self.inbox = asyncio.Queue()
        self.sent  = []


    async def send(self, text):
        payload = json.loads(text)
        self.sent.append(payload)
        frames = [self.pong] if self.pong is not None and payload == {"op": "ping"} else self.reply(payload)
        for frame in frames:
            await self.inbox.put(json.dumps(frame))


    def __aiter__(self):
        return self


    async def __anext__(self):
        frame = await self.inbox.get()
        if frame is None:
            raise StopAsyncIteration
        return frame


    async def close(self):
        await self.inbox.put(None)


def bybit_hub(venues, **kwargs):
    async def connect():
        venue = venues[0] if len(venues) == 1 else venues.pop(0)
        connect.count += 1
        return venue
    connect.count = 0

    hub = StreamHub(
        name                = "bybit_test",
        connect             = connect,
        subscribe_payload   = lambda ts: [{"op": "subscribe", "args": ts, "req_id": f"sub-{len(ts)}-{ts[0]}"}],
        unsubscribe_payload = lambda ts: [{"op": "unsubscribe", "args": ts}],
        route               = lambda msg: msg.get("topic"),
        answer              = BybitAdapter._answer,
        **kwargs,
    )
    return hub, connect


def acknowledged(payload):
    return [{"success": True, "ret_msg": "", "req_id": payload["req_id"], "op": "subscribe"}] if payload.get("op") == "subscribe" else []


def refused(payload):
    return [dict(BYBIT_REFUSAL, req_id=payload["req_id"])] if payload.get("op") == "subscribe" else []


async def test_a_subscription_the_venue_acknowledges_returns_its_queue():
    hub, _ = bybit_hub([Venue(acknowledged)])
    try:
        q = await hub.subscribe("publicTrade.BTCUSDT")
        assert q.empty()
    finally:
        await hub.close()


async def test_a_refusal_raises_with_the_venues_reason_for_the_first_subscriber_and_a_joiner():
    hub, _ = bybit_hub([Venue(refused)])
    try:
        first, joiner = await asyncio.gather(
            hub.subscribe("publicTrade.NOSUCHUSDT"),
            hub.subscribe("publicTrade.NOSUCHUSDT"),
            return_exceptions=True,
        )
    finally:
        await hub.close()

    assert [type(e) for e in (first, joiner)] == [SubscriptionRefused, SubscriptionRefused]
    assert str(first) == "bybit_test refused publicTrade.NOSUCHUSDT: error:handler not found,topic:publicTrade.NOSUCHUSDT"
    assert hub._queues == {} and hub._answers == {}


async def test_no_answer_is_an_outage_the_stream_retries(monkeypatch):
    monkeypatch.setattr(StreamHub, "ANSWER_S", 0.2)
    hub, _ = bybit_hub([Venue()])
    try:
        with pytest.raises(UpstreamUnavailableError, match="gave no answer"):
            await hub.subscribe("publicTrade.BTCUSDT")
    finally:
        await hub.close()

    assert is_retryable_stream_error(UpstreamUnavailableError("no answer"))


async def test_a_connection_silent_for_two_keepalive_intervals_is_replaced_and_a_live_one_kept():
    pong = {"success": True, "ret_msg": "pong", "op": "ping"}

    silent, reconnects = bybit_hub([Venue(acknowledged), Venue(acknowledged), Venue(acknowledged)], keepalive_payload={"op": "ping"}, keepalive_interval=0.05)
    live, connects     = bybit_hub([Venue(acknowledged, pong=pong)], keepalive_payload={"op": "ping"}, keepalive_interval=0.05)
    try:
        await silent.subscribe("publicTrade.BTCUSDT")
        await live.subscribe("publicTrade.BTCUSDT")
        await asyncio.sleep(2.5)
    finally:
        await silent.close()
        await live.close()

    assert reconnects.count >= 2
    assert connects.count == 1


def test_each_venue_reads_its_own_answer_to_a_subscription():
    hyperliquid = HyperliquidAdapter()
    hyperliquid._topic_args["l2Book:BTC"] = {"type": "l2Book", "coin": "BTC"}

    assert BinanceAdapter._answer({"result": None, "id": 2}) == ("2", None)
    assert BinanceAdapter._answer({"stream": "btcusdt@trade", "data": {}}) is None
    assert BybitAdapter._answer(BYBIT_REFUSAL) == ("r2", "error:handler not found,topic:publicTrade.NOSUCHUSDT")
    assert BybitAdapter._answer({"success": True, "ret_msg": "pong", "op": "ping"}) is None
    assert OkxAdapter._answer({"id": "r1", "event": "subscribe", "arg": {"channel": "trades", "instId": "BTC-USDT"}, "connId": "076cbca0"}) == ("trades:BTC-USDT", None)
    assert OkxAdapter._answer({"event": "error", "msg": "Subscribe failed, wrong URL or channel:trades,instId:NOSUCH-USDT doesn't exist.", "code": "60018", "connId": "076cbca0", "id": "r2"})[1].startswith("Subscribe failed")
    assert OkxAdapter._answer({"event": "notice", "msg": "WebSocket port 8443 will be retired soon.", "code": "64010", "connId": "076cbca0"}) is None
    assert KucoinAdapter._answer({"id": "r2", "type": "ack"}) == ("r2", None)
    assert KucoinAdapter._answer({"id": "keepalive", "type": "pong"}) is None
    assert hyperliquid._answer({"channel": "subscriptionResponse", "data": {"method": "subscribe", "subscription": {"type": "l2Book", "coin": "BTC", "nSigFigs": None, "mantissa": None, "fast": False}}}) == ("l2Book:BTC", None)


def kraken_answers(payload):
    if payload.get("method") != "subscribe":
        return []
    if payload["params"]["symbol"] == ["BTC/USD"]:
        return [dict(KRAKEN_ACCEPTED, req_id=payload["req_id"]), KRAKEN_TRADE]
    return [dict(KRAKEN_REFUSED, req_id=payload["req_id"])]


def okx_answers(payload):
    if payload.get("op") != "subscribe":
        return []
    answers = [dict(OKX_ACCEPTED, id=payload["id"], arg=arg) if arg["instId"] == "BTC-USDT" else dict(OKX_REFUSED, id=payload["id"]) for arg in payload["args"]]
    data    = [OKX_TICKER] if any(arg["instId"] == "BTC-USDT" for arg in payload["args"]) else []
    return answers + data


async def test_each_topic_of_a_first_batch_is_settled_by_its_own_answer(monkeypatch):
    venues = {"kraken": Venue(kraken_answers), "okx": Venue(okx_answers)}

    async def connect(url, **kwargs):
        return venues["kraken" if "kraken" in url else "okx"]

    monkeypatch.setattr(websockets, "connect", connect)
    kraken, okx = KrakenAdapter(), OkxAdapter()
    streams = [
        kraken._ws_connect(kraken.spot_ws_url, {"method": "subscribe", "params": {"channel": "trade", "symbol": ["BTC/USD"], "snapshot": False}}),
        kraken._ws_connect(kraken.spot_ws_url, {"method": "subscribe", "params": {"channel": "trade", "symbol": ["NOPE/USD"], "snapshot": False}}),
        okx._ws_connect([{"channel": "tickers", "instId": "BTC-USDT"}]),
        okx._ws_connect([{"channel": "tickers", "instId": "NOPE-USDT"}]),
    ]
    try:
        kraken_first = await asyncio.wait_for(asyncio.gather(*[s.__anext__() for s in streams[:2]], return_exceptions=True), 2)
        okx_first    = await asyncio.wait_for(asyncio.gather(*[s.__anext__() for s in streams[2:]], return_exceptions=True), 2)
    finally:
        for stream in streams:
            await stream.aclose()
        await kraken.shutdown()
        await okx.shutdown()

    assert kraken_first[0] == KRAKEN_TRADE
    assert type(kraken_first[1]) is SubscriptionRefused and str(kraken_first[1]).endswith("Currency pair not supported NOPE/USD")
    assert okx_first[0] == OKX_TICKER
    assert type(okx_first[1]) is SubscriptionRefused and "NOPE-USDT doesn't exist" in str(okx_first[1])


class Client:

    def __init__(self):
        self.closed = None
        self.sent   = []


    async def send_json(self, data):
        self.sent.append(data)


    async def close(self, code=1000, reason=""):
        self.closed = (code, reason)


class Refusing:

    async def stream_trades(self, market_type, symbol):
        raise SubscriptionRefused("kraken_spot refused trade:NOSUCH/USD: Currency pair not supported NOSUCH/USD")
        yield


async def test_the_service_closes_a_refused_stream_with_1003_and_the_venues_reason():
    manager = StreamManager()
    client  = Client()

    await manager.subscribe("kraken:spot:trades:NOSUCHUSD", client, Refusing(), "spot", "trades", "NOSUCHUSD")
    await asyncio.sleep(0.1)

    assert client.sent   == [{"error": "Invalid Request", "detail": "kraken_spot refused trade:NOSUCH/USD: Currency pair not supported NOSUCH/USD"}]
    assert client.closed == (1003, "kraken_spot refused trade:NOSUCH/USD: Currency pair not supported NOSUCH/USD")


def test_local_mode_raises_the_same_refusal_the_service_closes_with():
    error = error_for_fault(SubscriptionRefused("bybit_linear refused publicTrade.X: error:handler not found"))

    assert isinstance(error, BadRequest) and error.error == "Invalid Request"
    assert error.detail == "bybit_linear refused publicTrade.X: error:handler not found"


class Unmatched(Backend):

    def __init__(self):
        self.calls = []


    async def fetch(self, route, exchange=None, market_type=None, symbol=None, **params):
        self.calls.append(route)
        if route == "version":
            return {"version": "9.9.9", "schema_version": SCHEMA_VERSION + 1}
        if route == "exchanges":
            return {"count": 1, "exchanges": ["fake"]}
        return {}


    async def stream(self, exchange, market_type, channel, symbol):
        self.calls.append("stream")
        yield {"price": 1.0}


async def test_a_stream_checks_the_schema_before_its_first_message():
    backend = Unmatched()
    router  = AsyncRouter.service("http://router.test", ["fake"], verbose=False, backend=backend)

    with pytest.raises(SchemaMismatch):
        async for _ in router.stream("fake", "spot", "ticker", "BTCUSDT", reconnect=False):
            pass

    assert "stream" not in backend.calls
