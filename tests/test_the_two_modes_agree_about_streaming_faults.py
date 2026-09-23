import time
import types

import pytest

from exchange_router import AsyncRouter, Router
from exchange_router import exchanges as registry
from exchange_router._warnings import RouterDataWarning
from exchange_router.backend import LocalBackend, error_for_close, is_retryable_stream_error
from exchange_router.errors import BadRequest, NotSupported, RouterError

from fake_exchange import FakeExchange


class Closed(Exception):

    def __init__(self, code, reason=""):
        super().__init__(f"closed {code}")
        self.rcvd = types.SimpleNamespace(code=code, reason=reason)


class DroppingExchange(FakeExchange):

    async def stream_trades(self, market_type, symbol):
        raise OSError("the socket went away")
        yield


class FaultyExchange(FakeExchange):

    async def stream_trades(self, market_type, symbol):
        raise ValueError("BTCUSDT is not listed")
        yield


class LoudExchange(FakeExchange):

    async def stream_trades(self, market_type, symbol):
        for index in range(4000):
            yield {"id": index}


async def drain(adapter, monkeypatch):
    monkeypatch.setitem(registry.EXCHANGE_REGISTRY, "fake", adapter)

    async for _ in LocalBackend().stream("fake", "spot", "trades", "BTCUSDT"):
        pass


async def test_a_local_stream_drop_reaches_the_retry_path_as_the_transport_raised_it(monkeypatch):
    with pytest.raises(OSError) as caught:
        await drain(DroppingExchange(), monkeypatch)

    assert is_retryable_stream_error(caught.value)
    assert not isinstance(caught.value, RouterError)


async def test_a_local_stream_fault_that_is_not_a_drop_still_becomes_a_router_error(monkeypatch):
    with pytest.raises(BadRequest):
        await drain(FaultyExchange(), monkeypatch)


def test_an_unsupported_channel_close_becomes_not_supported():
    error = error_for_close(Closed(1003), "fake", "spot", "liquidations")

    assert isinstance(error, NotSupported)
    assert "liquidations" in str(error)


def test_a_refused_subscription_close_becomes_a_bad_request():
    assert isinstance(error_for_close(Closed(1008), "fake", "spot", "trades"), BadRequest)


def test_an_ordinary_close_is_left_alone_for_the_retry_path():
    assert error_for_close(Closed(1011), "fake", "spot", "trades") is None


def test_the_close_reason_is_carried_into_the_error():
    error = error_for_close(Closed(1003, "mark_price is not streamed here"), "fake", "spot", "mark_price")

    assert error.detail == "mark_price is not streamed here"


def test_a_slow_consumer_is_told_that_it_lost_messages(monkeypatch):
    monkeypatch.setitem(registry.EXCHANGE_REGISTRY, "fake", LoudExchange())
    router = Router.local(["fake"], verbose=False, backend=LocalBackend())

    with pytest.warns(RouterDataWarning, match="dropped"):
        messages = router.subscribe("fake", "spot", "trades", "BTCUSDT")
        next(messages)

        # the pump has the whole 4000 to push while this thread is asleep, so the buffer overflows
        time.sleep(0.3)

        for _ in messages:
            pass

    router.close()


class FiniteExchange(FakeExchange):

    async def stream_trades(self, market_type, symbol):
        for index in range(2):
            yield {"id": index}


async def test_a_stream_told_not_to_reconnect_ends_when_the_upstream_does(monkeypatch):
    monkeypatch.setitem(registry.EXCHANGE_REGISTRY, "fake", FiniteExchange())
    router = AsyncRouter.local(["fake"], verbose=False, backend=LocalBackend())

    messages = [message async for message in
                router.stream("fake", "spot", "trades", "BTCUSDT", reconnect=False)]

    assert messages == [{"id": 0}, {"id": 1}]

    await router.close()
