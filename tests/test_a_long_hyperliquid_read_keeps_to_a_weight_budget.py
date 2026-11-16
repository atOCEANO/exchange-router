import asyncio

import httpx
import pytest

from exchange_router.exchanges.base import UpstreamUnavailableError
from exchange_router.exchanges.hyperliquid import adapter as hyperliquid
from exchange_router.exchanges.hyperliquid.adapter import HyperliquidAdapter
from exchange_router.models import MarketType


HOUR  = 3_600_000
NOW   = 1_794_096_000_000
FIRST = NOW - 100_000 * HOUR
LIMIT = 1_200


class Clock:

    def __init__(self):
        self.now = 0.0


    def monotonic(self):
        return self.now


    def time(self):
        return (NOW + HOUR // 2) / 1000 + self.now


    async def sleep(self, seconds):
        self.now += max(seconds, 0.001)


class Polled(Clock):

    def __init__(self, every, until):
        super().__init__()
        self.every  = every
        self.until  = until
        self.polled = 0.0
        self.ledger = None


    async def sleep(self, seconds):
        end = self.now + max(seconds, 0.001)
        while self.polled + self.every <= min(end, self.until):
            self.polled += self.every
            self.now     = self.polled
            self.ledger.spend(20)
        self.now = end


class Burst(Clock):

    def __init__(self, bursts):
        super().__init__()
        self.bursts = list(bursts)
        self.ledger = None


    async def sleep(self, seconds):
        end = self.now + max(seconds, 0.001)
        while self.bursts and self.bursts[0][0] <= end:
            self.now, weight = self.bursts.pop(0)
            self.ledger.spend(weight)
        self.now = end


class Refusals(Clock):

    def __init__(self, refusals):
        super().__init__()
        self.refusals = list(refusals)
        self.adapter  = None


    async def sleep(self, seconds):
        end = self.now + max(seconds, 0.001)
        while self.refusals and self.refusals[0][0] <= end:
            self.now, paced = self.refusals.pop(0)
            self.adapter._backoff_until = max(self.adapter._backoff_until, self.time() + 5.0)
            if paced:
                self.adapter._weights.hold()
        self.now = end


class Held(Polled):

    def __init__(self, every, until, at):
        super().__init__(every, until)
        self.at = at


    async def sleep(self, seconds):
        end = self.now + max(seconds, 0.001)
        if self.now < self.at < end:
            await super().sleep(self.at - self.now)
            self.ledger.hold()
        await super().sleep(end - self.now)


class Venue:

    def __init__(self, clock, refused=(), oldest=FIRST):
        self.clock    = clock
        self.refused  = set(refused)
        self.oldest   = oldest
        self.spent    = []
        self.asked    = []
        self.refusals = 0
        self.most     = 0


    async def post(self, url, json=None):
        now = self.clock.now
        self.asked.append(now)
        if json["type"] == "fundingHistory":
            rows   = [funding(t) for t in hours(json["startTime"], json["endTime"], self.oldest, 500)]
            weight = 20 + len(rows) // 20
        else:
            rows   = [bar(t) for t in hours(json["req"]["startTime"], json["req"]["endTime"], self.oldest, 5000)]
            weight = 20 + len(rows) // 60

        held = sum(w for t, w in self.spent if t > now - 60.0) + weight
        self.spent.append((now, weight))
        if len(self.asked) in self.refused or held > LIMIT:
            self.refusals += 1
            return httpx.Response(429, request=httpx.Request("POST", url))

        self.most = max(self.most, held)
        return httpx.Response(200, json=rows, request=httpx.Request("POST", url))


    async def aclose(self):
        return None


def hours(start, end, oldest, most):
    first = -(-max(start, oldest) // HOUR) * HOUR
    return range(first, min(end, NOW) + 1, HOUR)[:most]


def funding(opened):
    return {"coin": "BTC", "fundingRate": "0.0000125", "premium": "0.0", "time": opened}


def bar(opened):
    return {"t": opened, "o": "1.0", "h": "1.0", "l": "1.0", "c": "1.0", "v": "1.0"}


async def lookup(market_type, symbol):
    return "BTCUSDC", "BTC", "USDC"


async def cycle(market_type, symbol):
    return HOUR


def hyperliquid_on(venue):
    adapter = HyperliquidAdapter()
    adapter.http_client              = venue
    adapter._lookup                  = lookup
    adapter._funding_interval_ms_for = cycle
    return adapter


def install(monkeypatch, clock):
    monkeypatch.setattr(hyperliquid, "time", clock)
    monkeypatch.setattr(asyncio, "sleep", clock.sleep)
    return clock


@pytest.fixture
def clock(monkeypatch):
    return install(monkeypatch, Clock())


async def test_a_funding_history_longer_than_a_minute_allows_arrives_whole_and_unrefused(clock):
    venue   = Venue(clock)
    adapter = hyperliquid_on(venue)
    try:
        rows = await adapter.get_funding_rate(MarketType.LINEAR, "BTCUSDC", limit=27_000)
    finally:
        await adapter.shutdown()

    assert [row.timestamp for row in rows] == list(range(NOW - 26_999 * HOUR, NOW + 1, HOUR))
    assert venue.asked                     == pytest.approx([0.0] * 20 + [60.0] * 20 + [120.0] * 14)
    assert venue.refusals                  == 0
    assert venue.most                      <= 900


async def test_a_read_that_fits_one_page_goes_out_at_once_after_a_walk(clock):
    venue   = Venue(clock)
    adapter = hyperliquid_on(venue)
    try:
        await adapter.get_funding_rate(MarketType.LINEAR, "BTCUSDC", limit=10_000)
        rows = await adapter.get_funding_rate(MarketType.LINEAR, "BTCUSDC", limit=24)
    finally:
        await adapter.shutdown()

    assert [row.timestamp for row in rows] == list(range(NOW - 23 * HOUR, NOW + 1, HOUR))
    assert venue.asked                     == [0.0] * 21


async def test_a_walk_counts_what_the_reads_before_it_spent(clock):
    venue   = Venue(clock)
    adapter = hyperliquid_on(venue)
    try:
        for _ in range(20):
            await adapter.get_funding_rate(MarketType.LINEAR, "BTCUSDC", limit=24)
        rows = await adapter.get_funding_rate(MarketType.LINEAR, "BTCUSDC", limit=1_500)
    finally:
        await adapter.shutdown()

    assert [row.timestamp for row in rows] == list(range(NOW - 1_499 * HOUR, NOW + 1, HOUR))
    assert venue.asked                     == pytest.approx([0.0] * 21 + [60.0] * 2)
    assert venue.refusals                  == 0


async def test_a_candle_read_is_counted_but_never_held(clock):
    venue   = Venue(clock, oldest=NOW - 4_999 * HOUR)
    adapter = hyperliquid_on(venue)
    try:
        for _ in range(8):
            bars = await adapter.get_candles(MarketType.LINEAR, "BTCUSDC", "1h", NOW + HOUR // 2, 10_000)
        rows = await adapter.get_funding_rate(MarketType.LINEAR, "BTCUSDC", limit=1_000)
    finally:
        await adapter.shutdown()

    assert [row.timestamp for row in bars] == list(range(NOW - 4_999 * HOUR, NOW + 1, HOUR))
    assert [row.timestamp for row in rows] == list(range(NOW - 999 * HOUR, NOW + 1, HOUR))
    assert venue.asked                     == pytest.approx([0.0] * 25 + [60.0])
    assert venue.refusals                  == 0


async def test_a_page_is_counted_at_the_weight_of_its_answer(clock):
    venue   = Venue(clock, oldest=NOW - 509 * HOUR)
    adapter = hyperliquid_on(venue)
    try:
        for _ in range(10):
            rows = await adapter.get_funding_rate(MarketType.LINEAR, "BTCUSDC", limit=1_000)
    finally:
        await adapter.shutdown()

    assert [row.timestamp for row in rows] == list(range(NOW - 509 * HOUR, NOW + 1, HOUR))
    assert venue.asked                     == [0.0] * 30


async def test_a_young_markets_funding_read_checks_for_older_events_at_once(clock):
    venue   = Venue(clock, oldest=NOW - 47 * HOUR)
    adapter = hyperliquid_on(venue)
    try:
        adapter._weights.spend(880)
        rows = await adapter.get_funding_rate(MarketType.LINEAR, "BTCUSDC", limit=100)
    finally:
        await adapter.shutdown()

    assert [row.timestamp for row in rows] == list(range(NOW - 47 * HOUR, NOW + 1, HOUR))
    assert venue.asked                     == [0.0] * 2


async def test_a_refused_page_waits_out_the_minute_and_the_walk_completes(clock):
    venue   = Venue(clock, refused={3})
    adapter = hyperliquid_on(venue)
    try:
        rows = await adapter.get_funding_rate(MarketType.LINEAR, "BTCUSDC", limit=2_000)
    finally:
        await adapter.shutdown()

    assert [row.timestamp for row in rows] == list(range(NOW - 1_999 * HOUR, NOW + 1, HOUR))
    assert venue.asked                     == pytest.approx([0.0, 0.0, 0.0, 60.0, 60.0])


async def test_a_page_refused_three_times_fails_the_read_and_holds_the_next(clock, monkeypatch):
    monkeypatch.setattr(hyperliquid.random, "uniform", lambda low, high: low)
    venue   = Venue(clock, refused={3, 4, 5})
    adapter = hyperliquid_on(venue)
    try:
        with pytest.raises(UpstreamUnavailableError, match="Max retries exceeded") as failed:
            await adapter.get_funding_rate(MarketType.LINEAR, "BTCUSDC", limit=2_000)
        rows = await adapter.get_funding_rate(MarketType.LINEAR, "BTCUSDC", limit=1_000)
    finally:
        await adapter.shutdown()

    assert failed.value.retry_after        == pytest.approx(15.0)
    assert [row.timestamp for row in rows] == list(range(NOW - 999 * HOUR, NOW + 1, HOUR))
    assert venue.asked                     == pytest.approx([0.0, 0.0, 0.0, 60.0, 120.0, 135.05, 180.0])


async def test_a_refused_single_read_backs_off_seconds_and_holds_no_page(clock, monkeypatch):
    monkeypatch.setattr(hyperliquid.random, "uniform", lambda low, high: low)
    venue   = Venue(clock, refused={1, 2})
    adapter = hyperliquid_on(venue)
    try:
        await adapter.get_funding_rate(MarketType.LINEAR, "BTCUSDC", limit=24)
        rows = await adapter.get_funding_rate(MarketType.LINEAR, "BTCUSDC", limit=1_000)
    finally:
        await adapter.shutdown()

    assert [row.timestamp for row in rows] == list(range(NOW - 999 * HOUR, NOW + 1, HOUR))
    assert venue.asked                     == pytest.approx([0.0, 5.05, 15.1, 15.1, 15.1])


async def test_a_page_that_finds_room_during_a_backoff_waits_it_out(monkeypatch):
    clock   = install(monkeypatch, Refusals([(58.0, False)]))
    venue   = Venue(clock)
    adapter = hyperliquid_on(venue)
    clock.adapter = adapter
    try:
        adapter._weights.spend(860)
        rows = await adapter.get_funding_rate(MarketType.LINEAR, "BTCUSDC", limit=1_000)
    finally:
        await adapter.shutdown()

    assert [row.timestamp for row in rows] == list(range(NOW - 999 * HOUR, NOW + 1, HOUR))
    assert venue.asked                     == pytest.approx([0.0, 63.0])


async def test_a_page_waits_out_a_hold_that_starts_during_its_backoff_wait(monkeypatch):
    clock   = install(monkeypatch, Refusals([(58.0, False), (62.0, True)]))
    venue   = Venue(clock)
    adapter = hyperliquid_on(venue)
    clock.adapter = adapter
    try:
        adapter._weights.spend(860)
        rows = await adapter.get_funding_rate(MarketType.LINEAR, "BTCUSDC", limit=1_000)
    finally:
        await adapter.shutdown()

    assert [row.timestamp for row in rows] == list(range(NOW - 999 * HOUR, NOW + 1, HOUR))
    assert venue.asked                     == pytest.approx([0.0, 122.0])


async def test_a_page_that_has_waited_a_minute_goes_once_it_fits_the_venues_own_limit(monkeypatch):
    clock   = install(monkeypatch, Polled(every=1.25, until=600.0))
    venue   = Venue(clock)
    adapter = hyperliquid_on(venue)
    clock.ledger = adapter._weights
    try:
        await asyncio.sleep(60.0)
        rows = await adapter.get_funding_rate(MarketType.LINEAR, "BTCUSDC", limit=1_000)
    finally:
        await adapter.shutdown()

    assert [row.timestamp for row in rows] == list(range(NOW - 999 * HOUR, NOW + 1, HOUR))
    assert venue.asked                     == pytest.approx([60.0, 120.0])


async def test_a_page_goes_on_the_one_minute_mark_even_after_a_burst(monkeypatch):
    monkeypatch.setattr(hyperliquid.random, "uniform", lambda low, high: low)
    clock   = install(monkeypatch, Burst([(30.0, 900)]))
    venue   = Venue(clock, refused={2})
    adapter = hyperliquid_on(venue)
    clock.ledger = adapter._weights
    try:
        rows = await adapter.get_funding_rate(MarketType.LINEAR, "BTCUSDC", limit=1_000)
    finally:
        await adapter.shutdown()

    assert [row.timestamp for row in rows] == list(range(NOW - 999 * HOUR, NOW + 1, HOUR))
    assert venue.asked                     == pytest.approx([0.0, 0.0, 65.05])


async def test_a_page_that_has_waited_two_minutes_goes_whatever_the_ledger_holds(monkeypatch):
    clock   = install(monkeypatch, Polled(every=1.0, until=600.0))
    venue   = Venue(clock)
    adapter = hyperliquid_on(venue)
    clock.ledger = adapter._weights
    try:
        await asyncio.sleep(60.0)
        rows = await adapter.get_funding_rate(MarketType.LINEAR, "BTCUSDC", limit=1_000)
    finally:
        await adapter.shutdown()

    assert [row.timestamp for row in rows] == list(range(NOW - 999 * HOUR, NOW + 1, HOUR))
    assert venue.asked                     == pytest.approx([60.0, 180.0])


async def test_a_page_goes_on_the_two_minute_mark_even_between_bursts(monkeypatch):
    clock   = install(monkeypatch, Burst([(59.0, 1_160), (118.0, 1_160)]))
    venue   = Venue(clock)
    adapter = hyperliquid_on(venue)
    clock.ledger = adapter._weights
    try:
        adapter._weights.spend(860)
        rows = await adapter.get_funding_rate(MarketType.LINEAR, "BTCUSDC", limit=1_000)
    finally:
        await adapter.shutdown()

    assert [row.timestamp for row in rows] == list(range(NOW - 999 * HOUR, NOW + 1, HOUR))
    assert venue.asked                     == pytest.approx([0.0, 120.0])


async def test_a_hold_keeps_back_a_page_past_its_two_minute_mark(monkeypatch):
    clock   = install(monkeypatch, Held(every=1.0, until=600.0, at=179.5))
    venue   = Venue(clock)
    adapter = hyperliquid_on(venue)
    clock.ledger = adapter._weights
    try:
        await asyncio.sleep(60.0)
        rows = await adapter.get_funding_rate(MarketType.LINEAR, "BTCUSDC", limit=1_000)
    finally:
        await adapter.shutdown()

    assert [row.timestamp for row in rows] == list(range(NOW - 999 * HOUR, NOW + 1, HOUR))
    assert venue.asked                     == pytest.approx([60.0, 239.5])
