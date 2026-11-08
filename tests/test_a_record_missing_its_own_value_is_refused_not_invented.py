import copy

import httpx
import pytest

from exchange_router import exchanges as registry
from exchange_router.async_router import AsyncRouter
from exchange_router.backend import LocalBackend, RemoteBackend
from exchange_router.errors import RouterError
from exchange_router.exchanges.base import UpstreamDataError
from exchange_router.exchanges.bybit.adapter import BybitAdapter
from exchange_router.exchanges.kraken.adapter import KrakenAdapter
from exchange_router.exchanges.kucoin.adapter import KucoinAdapter
from exchange_router.models import MarketType
from exchange_router.service import app


SPOT_SYMBOL = {
    "symbol":         "BTC-USDT",
    "baseCurrency":   "BTC",
    "quoteCurrency":  "USDT",
    "baseMinSize":    "0.00001",
    "baseMaxSize":    "10000000000",
    "baseIncrement":  "0.00000001",
    "priceIncrement": "0.1",
    "minFunds":       "0.1",
    "enableTrading":  True,
}

LINEAR_CONTRACT = {
    "symbol":                 "XBTUSDTM",
    "baseCurrency":           "XBT",
    "quoteCurrency":          "USDT",
    "settleCurrency":         "USDT",
    "isInverse":              False,
    "status":                 "Open",
    "multiplier":             0.001,
    "lotSize":                1,
    "tickSize":               0.1,
    "maxOrderQty":            1000000,
    "fundingRateGranularity": 28800000,
    "fundingFeeRate":         0.0001,
    "nextFundingRateTime":    26506915,
}

INVERSE_CONTRACT = {
    "symbol":                 "XBTUSDM",
    "baseCurrency":           "XBT",
    "quoteCurrency":          "USD",
    "settleCurrency":         "XBT",
    "isInverse":              True,
    "status":                 "Open",
    "multiplier":             -1.0,
    "lotSize":                1,
    "tickSize":               0.1,
    "maxOrderQty":            1000000,
    "fundingRateGranularity": 28800000,
}

SPOT_TRADE = {
    "sequence": "25153616864362496",
    "tradeId":  "25153616864362496",
    "price":    "75735.5",
    "size":     "0.00017255",
    "side":     "sell",
    "time":     1794098291043000000,
}

MARK = {"symbol": "XBTUSDTM", "granularity": 1000, "timePoint": 1794098294000, "value": 75716.03, "indexPrice": 75735.83}

KUCOIN_OI = [{"openInterest": "10375383", "ts": 1794110400000}, {"openInterest": "10479860", "ts": 1794106800000}]

FUNDING = [
    {"symbol": "XBTUSDTM", "fundingRate": 0.0001, "timepoint": 1794096000000},
    {"symbol": "XBTUSDTM", "fundingRate": 5.9e-05, "timepoint": 1794067200000},
]

SPOT_MATCH = {
    "topic":   "/market/match:BTC-USDT",
    "type":    "message",
    "subject": "trade.l3match",
    "data": {
        "makerOrderId": "508706311412670464",
        "price":        "75735.5",
        "sequence":     "25153619363774464",
        "side":         "sell",
        "size":         "0.00091596",
        "symbol":       "BTC-USDT",
        "takerOrderId": "6aefc48e342f760007239e2b",
        "time":         "1794098318141000000",
        "tradeId":      "25153619363774464",
        "type":         "match",
    },
}

KRAKEN_XBTUSD_PAIR = {
    "altname":       "XBTUSD",
    "wsname":        "XBT/USD",
    "base":          "XXBT",
    "quote":         "ZUSD",
    "pair_decimals": 1,
    "lot_decimals":  8,
    "ordermin":      "0.00006",
    "costmin":       "0.5",
    "tick_size":     "0.1",
    "status":        "online",
}

KRAKEN_SPOT_TRADES = {
    "channel": "trade",
    "type":    "snapshot",
    "data": [
        {"symbol": "BTC/USD", "side": "buy", "price": 75632.3, "qty": 6.12e-05, "ord_type": "limit", "trade_id": 114745541, "timestamp": "2026-11-08T02:36:17.875188Z"},
        {"symbol": "BTC/USD", "side": "buy", "price": 75633.8, "qty": 0.00014706, "ord_type": "limit", "trade_id": 114745542, "timestamp": "2026-11-08T02:36:17.875188Z"},
    ],
}

KRAKEN_FUTURES_TRADES = {
    "feed":       "trade_snapshot",
    "product_id": "PF_XBTUSD",
    "trades": [
        {"product_id": "PF_XBTUSD", "feed": "trade", "uid": "73f1fdff-3165-4eb2-9eda-1ead2d6ded4c", "side": "buy", "type": "fill", "time": 1794105496587, "qty": 0.0013, "price": 75654.0, "seq": 943136},
        {"product_id": "PF_XBTUSD", "feed": "trade", "uid": "a8b0d013-0650-4fed-a8a4-849b7c173186", "side": "sell", "type": "fill", "time": 1794105491823, "qty": 0.0002, "price": 75653.0, "seq": 943135},
    ],
}

KRAKEN_FUNDING = [
    {"timestamp": "2026-11-08T01:00:00Z", "fundingRate": 1.2428464228968499, "relativeFundingRate": 1.6419145833333e-05},
    {"timestamp": "2026-11-08T02:00:00Z", "fundingRate": 1.2345605814295, "relativeFundingRate": 1.632215e-05},
]

BYBIT_LIQUIDATIONS = {
    "topic": "allLiquidation.AKEUSDT",
    "type":  "snapshot",
    "ts":    1794091801243,
    "data": [
        {"T": 1794091800954, "s": "AKEUSDT", "S": "Sell", "v": "123000", "p": "0.0056960"},
        {"T": 1794091801189, "s": "AKEUSDT", "S": "Sell", "v": "17900", "p": "0.0056880"},
    ],
}


def without(record, key):
    trimmed = copy.deepcopy(record)
    (trimmed["data"] if "data" in trimmed else trimmed).pop(key)
    return trimmed


def kucoin(trades=None, mark=None, funding=None, contracts=(LINEAR_CONTRACT, INVERSE_CONTRACT), oi=None):
    async def answer(method, base, endpoint, params=None):
        if endpoint == "/api/v1/symbols":
            return [SPOT_SYMBOL]
        if endpoint == "/api/v1/contracts/active":
            return list(contracts)
        if endpoint == "/api/v1/market/histories":
            return trades
        if endpoint.startswith("/api/v1/mark-price/"):
            return mark
        if endpoint.startswith("/api/v1/contracts/"):
            return LINEAR_CONTRACT
        if endpoint == "/api/ua/v1/market/open-interest":
            return oi
        if endpoint == "/api/v1/contract/funding-rates":
            return funding
        raise AssertionError(endpoint)
    return answer


async def on_kucoin(answer, call, *frames):
    async def connect(*args):
        for frame in frames:
            yield frame

    adapter = KucoinAdapter()
    adapter._make_request = answer
    adapter._ws_connect   = connect
    try:
        return await call(adapter)
    finally:
        await adapter.shutdown()


async def kraken(method, url, params=None):
    if url.endswith("/AssetPairs"):
        return {"XXBTZUSD": KRAKEN_XBTUSD_PAIR}
    if url.endswith("/instruments"):
        return {"instruments": []}
    raise AssertionError(url)


async def bybit(method, endpoint, params=None):
    return {"list": [], "nextPageCursor": ""}


async def streamed(adapter, answer, stream, *frames):
    async def connect(*args):
        for frame in frames:
            yield frame

    adapter._make_request = answer
    adapter._ws_connect   = connect
    try:
        return [row async for row in stream(adapter)]
    finally:
        await adapter.shutdown()


async def test_a_trade_without_its_price_or_time_is_refused_and_never_filled_in():
    whole = await on_kucoin(kucoin(trades=[SPOT_TRADE]), lambda a: a.get_trades(MarketType.SPOT, "BTCUSDT"))

    assert [(t.price, t.qty.native, t.timestamp) for t in whole] == [(75735.5, 0.00017255, 1794098291043)]

    with pytest.raises(UpstreamDataError, match="arrived without price"):
        await on_kucoin(kucoin(trades=[without(SPOT_TRADE, "price")]), lambda a: a.get_trades(MarketType.SPOT, "BTCUSDT"))

    with pytest.raises(UpstreamDataError, match="arrived without time"):
        await on_kucoin(kucoin(trades=[without(SPOT_TRADE, "time")]), lambda a: a.get_trades(MarketType.SPOT, "BTCUSDT"))


async def test_a_mark_price_without_its_value_is_refused():
    with pytest.raises(UpstreamDataError, match="arrived without value"):
        await on_kucoin(kucoin(mark=without(MARK, "value")), lambda a: a.get_mark_price(MarketType.LINEAR, "XBTUSDTM"))


async def test_a_funding_row_without_its_rate_is_refused():
    rows = [FUNDING[0], without(FUNDING[1], "fundingRate")]

    with pytest.raises(UpstreamDataError, match="arrived without fundingRate"):
        await on_kucoin(kucoin(funding=rows), lambda a: a.get_funding_rate(MarketType.LINEAR, "XBTUSDTM", None, 2))


async def test_an_open_interest_row_without_its_value_is_refused():
    whole = await on_kucoin(kucoin(oi=KUCOIN_OI), lambda a: a.get_open_interest(MarketType.LINEAR, "XBTUSDTM", "1h", None, 2))

    assert [row.open_interest.native for row in whole] == [10479860 * 0.001, 10375383 * 0.001]

    with pytest.raises(UpstreamDataError, match="arrived without openInterest"):
        await on_kucoin(kucoin(oi=[KUCOIN_OI[0], without(KUCOIN_OI[1], "openInterest")]), lambda a: a.get_open_interest(MarketType.LINEAR, "XBTUSDTM", "1h", None, 2))


async def test_a_trade_frame_without_its_price_is_skipped_and_the_next_one_kept():
    async def streamed(adapter):
        return [row async for row in adapter.stream_trades(MarketType.SPOT, "BTCUSDT")]

    rows = await on_kucoin(kucoin(), streamed, without(SPOT_MATCH, "price"), SPOT_MATCH)

    assert [(row.price, row.timestamp) for row in rows] == [(75735.5, 1794098318141)]


async def test_kraken_skips_a_trade_frame_without_its_price_or_size():
    unpriced = {**KRAKEN_SPOT_TRADES, "data": [without(KRAKEN_SPOT_TRADES["data"][0], "price")]}
    unsized  = {**KRAKEN_FUTURES_TRADES, "trades": [without(KRAKEN_FUTURES_TRADES["trades"][0], "qty")]}

    spot    = await streamed(KrakenAdapter(), kraken, lambda a: a.stream_trades(MarketType.SPOT, "XBTUSD"), unpriced, KRAKEN_SPOT_TRADES)
    futures = await streamed(KrakenAdapter(), kraken, lambda a: a.stream_trades(MarketType.LINEAR, "XBTUSD"), unsized, KRAKEN_FUTURES_TRADES["trades"][1])

    assert [(t.price, t.qty.native) for t in spot]    == [(75632.3, 6.12e-05), (75633.8, 0.00014706)]
    assert [(t.price, t.qty.native) for t in futures] == [(75653.0, 0.0002)]


async def test_kraken_refuses_a_funding_row_without_its_rate():
    async def read(rows):
        async def answer(method, url, params=None):
            if url.endswith("/historical-funding-rates"):
                return {"rates": rows}
            return await kraken(method, url, params)

        adapter = KrakenAdapter()
        adapter._make_request = answer
        try:
            return await adapter.get_funding_rate(MarketType.LINEAR, "XBTUSD", None, 2)
        finally:
            await adapter.shutdown()

    whole = await read(KRAKEN_FUNDING)

    assert [row.rate.per_cycle for row in whole] == [1.6419145833333e-05, 1.632215e-05]

    with pytest.raises(UpstreamDataError, match="arrived without relativeFundingRate"):
        await read([KRAKEN_FUNDING[0], without(KRAKEN_FUNDING[1], "relativeFundingRate")])


async def test_bybit_skips_a_liquidation_frame_without_its_price_or_size():
    unpriced = {**BYBIT_LIQUIDATIONS, "data": [without(BYBIT_LIQUIDATIONS["data"][0], "p")]}
    unsized  = {**BYBIT_LIQUIDATIONS, "data": [without(BYBIT_LIQUIDATIONS["data"][0], "v")]}

    rows = await streamed(BybitAdapter(), bybit, lambda a: a.stream_liquidations(MarketType.LINEAR, "AKEUSDT"), unpriced, unsized, BYBIT_LIQUIDATIONS)

    assert [(row.price, row.qty.native) for row in rows] == [(0.005696, 123000.0), (0.005688, 17900.0)]


async def test_an_inverse_contract_without_its_size_stays_out_of_the_list():
    sized   = await on_kucoin(kucoin(), lambda a: a._fetch_exchange_info(MarketType.INVERSE))
    unsized = await on_kucoin(kucoin(contracts=[without(INVERSE_CONTRACT, "multiplier")]), lambda a: a._fetch_exchange_info(MarketType.INVERSE))

    assert [(info.symbol, info.qty.contract_size) for info in sized] == [("XBTUSD", 1.0)]
    assert unsized == []


async def test_a_record_without_its_value_is_a_bad_upstream_response_in_both_modes(monkeypatch):
    async def unpriced(market_type, symbol, limit=100):
        raise UpstreamDataError("KuCoin trade 1 on BTC-USDT arrived without price")

    monkeypatch.setattr(registry.EXCHANGE_REGISTRY["fake"], "get_trades", unpriced)

    remote  = RemoteBackend("http://router.test", max_retries=0, http=httpx.AsyncClient(transport=httpx.ASGITransport(app=app), timeout=30))
    routers = [
        AsyncRouter.local(["fake"], verbose=False, backend=LocalBackend()),
        AsyncRouter.service("http://router.test", ["fake"], verbose=False, backend=remote),
    ]
    caught = []
    try:
        for router in routers:
            with pytest.raises(RouterError) as raised:
                await router.get_trades("fake", "spot", "BTCUSDT", limit=5)
            caught.append((raised.value.status, raised.value.detail))
    finally:
        for router in routers:
            await router.close()

    assert caught == [(502, "KuCoin trade 1 on BTC-USDT arrived without price")] * 2
