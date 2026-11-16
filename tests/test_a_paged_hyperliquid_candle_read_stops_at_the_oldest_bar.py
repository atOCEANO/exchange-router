from exchange_router.exchanges.hyperliquid.adapter import HyperliquidAdapter
from exchange_router.models import MarketType


HOUR   = 3_600_000
NOW    = 1_794_096_000_000
LISTED = NOW - 2_999 * HOUR


class Venue:

    def __init__(self):
        self.asked = []


    async def answer(self, info_type, body):
        start, end = body["req"]["startTime"], body["req"]["endTime"]
        self.asked.append((start, end))
        first = -(-max(start, LISTED) // HOUR) * HOUR
        return [bar(t) for t in range(first, min(end, NOW) + 1, HOUR)][:5000]


def bar(opened):
    return {"t": opened, "o": "1.0", "h": "1.0", "l": "1.0", "c": "1.0", "v": "1.0"}


async def lookup(market_type, symbol):
    return "BTCUSDC", "BTC", "USDC"


async def test_a_young_market_is_read_without_asking_past_its_first_bar():
    venue   = Venue()
    adapter = HyperliquidAdapter()
    adapter._make_request = venue.answer
    adapter._lookup       = lookup
    try:
        rows = await adapter.get_candles(MarketType.LINEAR, "BTCUSDC", "1h", NOW + HOUR // 2, 10_000)
    finally:
        await adapter.shutdown()

    assert [row.timestamp for row in rows] == list(range(LISTED, NOW + 1, HOUR))
    assert venue.asked                     == [(NOW + HOUR // 2 - 5_000 * HOUR, NOW + HOUR // 2), (0, NOW + HOUR // 2)]
