from exchange_router.exchanges.okx.adapter import OkxAdapter
from exchange_router.models import MarketType


INSTRUMENT = {
    "instId":   "BTC-USDT-SWAP",
    "state":    "live",
    "ctType":   "linear",
    "uly":      "BTC-USDT",
    "ctVal":    "0.01",
    "tickSz":   "0.1",
    "lotSz":    "0.01",
    "minSz":    "0.01",
    "maxLmtSz": "100000000",
}

CANDLES_1DUTC = [
    ["1794009600000", "75816.3", "76216.8", "75531", "75749.3", "1787097.84", "17870.9784", "1356135940.80723", "0"],
    ["1793923200000", "76049.4", "76399.9", "74800.1", "75816.3", "8401624.23", "84016.2423", "6363940586.97096", "1"],
]

OPEN_INTEREST_1DUTC = [
    ["1794009600000", "3456922.3800000167", "34569.223800000167", "2619185638.1203326529888"],
    ["1793923200000", "3460234.01000001684", "34602.3401000001684", "2623421397.72364276746492"],
]

LONG_SHORT_1D = [
    ["1794067200000", "2.99"],
    ["1793980800000", "2.93"],
]


def okx(sent):
    async def answer(method, endpoint, params=None):
        if endpoint == "/api/v5/public/instruments":
            return [INSTRUMENT] if params["instType"] == "SWAP" else []
        sent.append((endpoint, dict(params or {})))
        if endpoint in ("/api/v5/market/candles", "/api/v5/market/history-candles"):
            return CANDLES_1DUTC
        if endpoint == "/api/v5/rubik/stat/contracts/open-interest-history":
            return OPEN_INTEREST_1DUTC
        if endpoint == "/api/v5/rubik/stat/contracts/long-short-account-ratio":
            return LONG_SHORT_1D
        raise AssertionError(endpoint)
    return answer


async def test_okx_names_its_utc_bars_for_six_hours_and_longer():
    adapter = OkxAdapter()
    try:
        bars = [adapter._map_candle_interval(interval) for interval in ("1h", "4h", "6h", "12h", "1d", "1w", "1M")]
    finally:
        await adapter.shutdown()

    assert bars == ["1H", "4H", "6Hutc", "12Hutc", "1Dutc", "1Wutc", "1Mutc"]


async def test_daily_candles_and_open_interest_open_at_midnight_utc():
    sent    = []
    adapter = OkxAdapter()
    adapter._make_request = okx(sent)
    try:
        candles  = await adapter.get_candles(MarketType.LINEAR, "BTCUSDT", "1d", None, 2)
        interest = await adapter.get_open_interest(MarketType.LINEAR, "BTCUSDT", "1d", None, 2)
    finally:
        await adapter.shutdown()

    assert {params["bar"] for endpoint, params in sent if "candles" in endpoint} == {"1Dutc"}
    assert {params["period"] for endpoint, params in sent if "open-interest" in endpoint} == {"1Dutc"}
    assert [c.timestamp for c in candles] == [1_793_923_200_000, 1_794_009_600_000]
    assert [r.timestamp % 86_400_000 for r in interest] == [0, 0]


async def test_daily_long_short_keeps_the_one_day_okx_serves():
    sent    = []
    adapter = OkxAdapter()
    adapter._make_request = okx(sent)
    try:
        ratios = await adapter.get_long_short_ratio(MarketType.LINEAR, "BTCUSDT", "1d", None, 2)
    finally:
        await adapter.shutdown()

    assert [params["period"] for _, params in sent] == ["1D"]
    assert [r.timestamp % 86_400_000 for r in ratios] == [16 * 3_600_000, 16 * 3_600_000]
