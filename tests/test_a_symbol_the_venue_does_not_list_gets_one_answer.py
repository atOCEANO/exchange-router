import pytest

from exchange_router import exchanges as registry
from exchange_router.backend import LocalBackend
from exchange_router.errors import BadRequest
from exchange_router.exchanges.base import UpstreamUnavailableError
from exchange_router.models import MarketType
from exchange_router.service.main import websocket_endpoint

from fake_exchange import FakeExchange


UNLISTED = "symbol 'NOSUCHUSDT' is not listed on fake spot; see /fake/spot/markets"


class Socket:

    def __init__(self, subscription):
        self.subscription = subscription
        self.closed       = None


    async def accept(self):
        return None


    async def receive_json(self):
        return self.subscription


    async def close(self, code=1000, reason=""):
        self.closed = (code, reason)


class ListingExchange(FakeExchange):

    def __init__(self):
        super().__init__()
        self.fetches = 0


    async def _fetch_exchange_info(self, market_type):
        self.fetches += 1
        infos = await super()._fetch_exchange_info(market_type)
        if self.fetches == 1:
            return infos
        return infos + [infos[0].model_copy(update={"symbol": "SOLUSDT", "native_symbol": "solusdt", "base_asset": "SOL"})]


async def test_an_unlisted_symbol_is_one_bad_request_in_both_modes(router):
    with pytest.raises(BadRequest) as refused:
        await router.get_ticker("fake", "spot", "NOSUCHUSDT")

    assert refused.value.detail == UNLISTED


async def test_a_local_stream_for_an_unlisted_symbol_is_the_same_bad_request():
    with pytest.raises(BadRequest) as refused:
        async for _ in LocalBackend().stream("fake", "spot", "trades", "NOSUCHUSDT"):
            pass

    assert refused.value.detail == UNLISTED


async def test_a_service_stream_for_an_unlisted_symbol_closes_with_the_same_answer():
    socket = Socket({"channel": "ticker", "symbol": "NOSUCHUSDT"})

    await websocket_endpoint(socket, "fake", MarketType.SPOT)

    assert socket.closed == (1008, UNLISTED)


async def test_a_symbol_listed_after_the_list_was_read_is_found_by_one_refresh():
    adapter = ListingExchange()

    assert await adapter.listed_symbol(MarketType.SPOT, "BTCUSDT") == "BTCUSDT"
    assert await adapter.listed_symbol(MarketType.SPOT, "sol-usdt") == "SOLUSDT"
    assert adapter.fetches == 2

    with pytest.raises(ValueError, match="'NOSUCHUSDT' is not listed"):
        await adapter.listed_symbol(MarketType.SPOT, "NOSUCHUSDT")
    assert adapter.fetches == 2


async def test_a_service_stream_closes_1011_when_the_venue_fails_the_symbol_check(monkeypatch):
    async def down(market_type, symbol):
        raise UpstreamUnavailableError("fake is unavailable (50013): Systems are busy")

    monkeypatch.setattr(registry.EXCHANGE_REGISTRY["fake"], "listed_symbol", down)
    socket = Socket({"channel": "ticker", "symbol": "BTCUSDT"})

    await websocket_endpoint(socket, "fake", MarketType.SPOT)

    assert socket.closed == (1011, "fake is unavailable (50013): Systems are busy")


async def test_a_close_reason_fits_a_close_frame_whatever_its_alphabet():
    cyrillic  = Socket({"channel": "ticker", "symbol": "Б" * 40})
    malformed = Socket({"channel": "ticker", "symbol": 7})

    await websocket_endpoint(cyrillic, "fake", MarketType.SPOT)
    await websocket_endpoint(malformed, "fake", MarketType.SPOT)

    assert cyrillic.closed[0] == 1008
    assert len(cyrillic.closed[1].encode("utf-8")) <= 123
    assert malformed.closed == (1003, "")
