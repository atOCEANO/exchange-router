import pytest

from exchange_router import exchanges as registry
from exchange_router.backend import LocalBackend
from exchange_router.errors import BadRequest, UpstreamUnavailable
from exchange_router.exchanges.base import UpstreamUnavailableError
from exchange_router.service.main import websocket_endpoint

from fake_exchange import FakeExchange


class Unanswered(FakeExchange):

    async def stream_trades(self, market_type, symbol):
        raise UpstreamUnavailableError("fake gave no answer in 30 s to the subscription of trades")
        yield


class BinarySocket:

    def __init__(self):
        self.sent   = []
        self.closed = None


    async def accept(self):
        return None


    async def receive_json(self):
        raise KeyError("text")


    async def send_json(self, data):
        self.sent.append(data)


    async def close(self, code=1000, reason=""):
        self.closed = code


async def first(stream):
    async for frame in stream:
        return frame


async def test_local_mode_refuses_a_channel_it_does_not_know_as_the_service_does():
    with pytest.raises(BadRequest, match="channel: 'tickers' is not a stream on fake linear; /fake/capabilities lists the channels"):
        await first(LocalBackend().stream("fake", "linear", "tickers", "BTCUSDT"))


async def test_local_mode_raises_the_sdks_own_error_for_a_venue_that_never_answers(monkeypatch):
    monkeypatch.setitem(registry.EXCHANGE_REGISTRY, "fake", Unanswered())

    with pytest.raises(UpstreamUnavailable, match="gave no answer in 30 s"):
        await first(LocalBackend().stream("fake", "linear", "trades", "BTCUSDT"))


async def test_a_binary_subscription_is_refused_with_the_body_then_closed():
    socket = BinarySocket()
    await websocket_endpoint(socket, "fake", "linear")

    assert (socket.sent, socket.closed) == ([{"error": "Invalid Request", "detail": "the subscription must be a JSON object naming channel and symbol"}], 1003)
