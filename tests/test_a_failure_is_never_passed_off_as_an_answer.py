import asyncio
import time

import httpx
import pytest

from exchange_router.exchanges.base import RequestError, UpstreamDataError, UpstreamUnavailableError, join_open_interest_basis
from exchange_router.exchanges.bybit.adapter import BybitAdapter
from exchange_router.exchanges.hyperliquid.adapter import HyperliquidAdapter
from exchange_router.exchanges.kraken.adapter import KrakenAdapter
from exchange_router.exchanges.kucoin.adapter import KucoinAdapter
from exchange_router.exchanges.okx.adapter import OkxAdapter
from exchange_router.models import MarketType

from fake_exchange import FakeExchange


class Answering:

    def __init__(self, body):
        self.body  = body
        self.calls = 0


    async def request(self, method, url, params=None):
        self.calls += 1
        return httpx.Response(200, json=self.body, request=httpx.Request(method, url))


    async def post(self, url, json=None):
        return await self.request("POST", url)


    async def aclose(self):
        return None


class Rows(FakeExchange):

    async def get_candles(self, market_type, symbol, interval, start_time=None, limit=100):
        raise UpstreamUnavailableError("fake candles are down")


@pytest.fixture(autouse=True)
def no_waiting(monkeypatch):
    async def instantly(seconds):
        return None

    monkeypatch.setattr(asyncio, "sleep", instantly)


async def nothing(*args, **kwargs):
    return 0.0


def unthrottled():
    adapter = KrakenAdapter()
    adapter._await_throttle = nothing
    adapter._set_backoff    = nothing
    return adapter


async def answered(adapter, body, call):
    adapter.http_client = Answering(body)
    try:
        return await call(adapter)
    finally:
        await adapter.shutdown()


async def test_a_page_that_fails_fails_the_request():
    async def pages(end_ts, limit):
        if end_ts is None:
            return (await FakeExchange().get_open_interest(MarketType.LINEAR, "BTCUSDT", "1h", 1_700_000_000_000, 3))
        raise ValueError("Bybit API Error (10001): params error")

    with pytest.raises(ValueError, match="10001"):
        await FakeExchange()._paginate_backwards(pages, 10, 3)


async def test_a_limit_beyond_the_page_cap_is_refused_before_any_request():
    asked = []

    async def pages(end_ts, limit):
        asked.append(end_ts)
        return []

    with pytest.raises(ValueError, match="limit: 1001 is more than fake serves in one request; the most is 1000"):
        await FakeExchange()._paginate_backwards(pages, 1001, 10)
    assert asked == []


async def test_kraken_refuses_a_futures_candle_walk_that_reaches_its_page_cap_short():
    async def chart(method, url, params=None):
        if url.endswith("/instruments"):
            return {"instruments": []}
        first = params["from"] * 1000
        return {"candles": [{"time": first + i * 60_000, "open": "75788", "high": "75798", "low": "75776", "close": "75776", "volume": "3.21790000"} for i in range(2000)], "more_candles": True}

    anchor = 1_794_105_600_000
    reads  = []
    for limit in (3000, 50_000):
        adapter = KrakenAdapter()
        adapter._make_request = chart
        try:
            reads.append(await adapter.get_candles(MarketType.LINEAR, "XBTUSD", "1m", anchor, limit))
        except ValueError as e:
            reads.append(str(e))
        finally:
            await adapter.shutdown()

    assert [len(reads[0]), reads[0][-1].timestamp] == [3000, anchor]
    assert reads[1] == "limit: 50000 took more than 20 pages on kraken; the most one request reached is 40000"


async def test_each_venue_answers_busy_codes_with_a_503_argument_codes_with_a_400_and_the_rest_with_a_502():
    busy = [
        (BybitAdapter(), {"retCode": 10016, "retMsg": "Server error.", "result": {}}, lambda a: a._make_request("GET", "/v5/market/time")),
        (OkxAdapter(), {"code": "50013", "msg": "Systems are busy. Please try again later.", "data": []}, lambda a: a._make_request("GET", "/api/v5/public/time")),
        (KucoinAdapter(), {"code": "500000", "msg": "Internal Server Error"}, lambda a: a._make_request("GET", "https://api.kucoin.com", "/api/v1/timestamp")),
        (unthrottled(), {"error": ["EService:Unavailable"]}, lambda a: a._make_request("GET", "https://api.kraken.com/0/public/Time")),
    ]
    for adapter, body, call in busy:
        with pytest.raises(UpstreamUnavailableError):
            await answered(adapter, body, call)

    caller = [
        (BybitAdapter(), {"retCode": 10001, "retMsg": "params error: symbol invalid", "result": {}}, lambda a: a._make_request("GET", "/v5/market/time")),
        (OkxAdapter(), {"code": "51001", "msg": "Instrument ID doesn't exist.", "data": []}, lambda a: a._make_request("GET", "/api/v5/public/time")),
        (KucoinAdapter(), {"code": "400100", "msg": "Parameter Error"}, lambda a: a._make_request("GET", "https://api.kucoin.com", "/api/v1/timestamp")),
        (unthrottled(), {"error": ["EQuery:Unknown asset pair"]}, lambda a: a._make_request("GET", "https://api.kraken.com/0/public/Time")),
    ]
    for adapter, body, call in caller:
        with pytest.raises(RequestError):
            await answered(adapter, body, call)

    unplaced = [
        (BybitAdapter(), {"retCode": 10002, "retMsg": "Request expired.", "result": {}}, lambda a: a._make_request("GET", "/v5/market/time")),
        (OkxAdapter(), {"code": "50030", "msg": "No permission to use this API.", "data": []}, lambda a: a._make_request("GET", "/api/v5/public/time")),
        (KucoinAdapter(), {"code": "900001", "msg": "Symbol not exists"}, lambda a: a._make_request("GET", "https://api.kucoin.com", "/api/v1/timestamp")),
        (unthrottled(), {"error": ["EGeneral:Unknown method"]}, lambda a: a._make_request("GET", "https://api.kraken.com/0/public/Time")),
        (unthrottled(), {"result": "error", "errors": ["unknownError"]}, lambda a: a._make_request("GET", "https://futures.kraken.com/derivatives/api/v3/tickers")),
    ]
    for adapter, body, call in unplaced:
        with pytest.raises(UpstreamDataError):
            await answered(adapter, body, call)


async def test_a_failed_candle_read_fails_open_interest_and_a_market_without_candles_stays_unpriced():
    adapter = Rows()
    rows    = await adapter.get_open_interest(MarketType.LINEAR, "BTCUSDT", "1h", None, 3)

    with pytest.raises(UpstreamUnavailableError, match="fake candles are down"):
        await join_open_interest_basis(adapter, MarketType.LINEAR, "BTCUSDT", "1h", None, 3, rows)

    unpriced = await join_open_interest_basis(adapter, MarketType.LINEAR, "BTCUSDT", "8h", None, 3, rows)
    assert unpriced == rows


async def test_hyperliquid_keeps_its_last_market_list_when_a_builder_dex_read_fails():
    calls = []

    async def answer(info_type, body):
        calls.append(info_type)
        if info_type == "metaAndAssetCtxs":
            return [{"universe": [{"szDecimals": 5, "name": "BTC", "maxLeverage": 40}], "marginTables": []}, [{}]]
        if len(calls) > 2:
            raise UpstreamUnavailableError("Max retries exceeded for perpDexs")
        return [None]

    adapter = HyperliquidAdapter()
    adapter._make_request = answer
    try:
        first = await adapter._ensure_info_cache(MarketType.LINEAR)
        with pytest.raises(UpstreamUnavailableError):
            await adapter._fetch_exchange_info(MarketType.LINEAR)
        kept = await adapter._ensure_info_cache(MarketType.LINEAR, max_age_s=0)
    finally:
        await adapter.shutdown()

    assert list(first) == list(kept) == ["BTCUSDC"]


async def test_kucoin_stamps_an_order_book_it_got_without_a_time_when_it_read_it():
    async def answer(method, base, endpoint, params=None):
        if endpoint == "/api/v1/symbols":
            return [{"symbol": "BTC-USDT", "baseCurrency": "BTC", "quoteCurrency": "USDT", "priceIncrement": "0.1", "baseIncrement": "0.00000001", "enableTrading": True}]
        return {"sequence": "1", "bids": [["75735.5", "0.5"]], "asks": [["75735.6", "0.2"]]}

    adapter = KucoinAdapter()
    adapter._make_request = answer
    before  = int(time.time() * 1000)
    try:
        book = await adapter.get_orderbook(MarketType.SPOT, "BTCUSDT", 20)
    finally:
        await adapter.shutdown()

    assert book.timestamp >= before


class Sequenced(Answering):

    def __init__(self, *bodies):
        super().__init__(None)
        self.bodies = list(bodies)


    async def request(self, method, url, params=None):
        self.calls += 1
        return httpx.Response(200, json=self.bodies.pop(0), request=httpx.Request(method, url))


async def test_a_busy_answer_is_retried_and_the_next_good_answer_served():
    venues = [
        (BybitAdapter(), {"retCode": 10016, "retMsg": "Server error.", "result": {}}, {"retCode": 0, "retMsg": "OK", "result": {"timeSecond": "1794112372"}}, lambda a: a._make_request("GET", "/v5/market/time")),
        (OkxAdapter(), {"code": "50013", "msg": "Systems are busy. Please try again later.", "data": []}, {"code": "0", "msg": "", "data": [{"ts": "1794112372065"}]}, lambda a: a._make_request("GET", "/api/v5/public/time")),
        (KucoinAdapter(), {"code": "500000", "msg": "Internal Server Error"}, {"code": "200000", "data": 1794112372065}, lambda a: a._make_request("GET", "https://api.kucoin.com", "/api/v1/timestamp")),
        (unthrottled(), {"error": ["EService:Unavailable"]}, {"error": [], "result": {"unixtime": 1794112372}}, lambda a: a._make_request("GET", "https://api.kraken.com/0/public/Time")),
    ]
    served = []
    for adapter, busy, good, call in venues:
        adapter.http_client = Sequenced(busy, good)
        try:
            served.append((await call(adapter), adapter.http_client.calls))
        finally:
            await adapter.shutdown()

    assert served == [({"timeSecond": "1794112372"}, 2), ([{"ts": "1794112372065"}], 2), (1794112372065, 2), ({"unixtime": 1794112372}, 2)]


async def test_a_route_that_reads_one_row_more_names_the_callers_limit_and_its_own_most():
    asked = []

    async def pages(end_ts, limit):
        asked.append(end_ts)
        return []

    with pytest.raises(ValueError, match="limit: 1000 is more than fake serves in one request; the most is 999$"):
        await FakeExchange()._paginate_backwards(pages, 1000, 10, extra_rows=1)
    assert asked == []
