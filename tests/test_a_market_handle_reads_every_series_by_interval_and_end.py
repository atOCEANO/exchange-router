from exchange_router import Router
from exchange_router.backend import LocalBackend


async def test_an_async_handle_reads_every_series_by_interval_and_end(router):
    m = router.market("fake", "linear", "BTCUSDT")

    candles = await m.candles(interval="1h", limit=3)
    newest  = int(candles.index[-1].timestamp() * 1000)
    older   = await m.candles(interval="1h", limit=2, end=newest - 1)
    series  = [
        await m.trades(limit=3),
        await m.agg_trades(limit=3),
        await m.funding_rate(limit=3),
        await m.open_interest(interval="1h", limit=3),
        await m.liquidations(limit=3),
        await m.long_short_ratio(interval="5m", limit=3),
    ]

    assert [len(frame) for frame in series] == [3] * 6
    assert (len(older), int(older.index[0].timestamp() * 1000)) == (2, newest - 1)


def test_a_sync_handle_reads_a_series_by_interval_and_end():
    with Router.local(["fake"], verbose=False, backend=LocalBackend()) as client:
        m      = client.market("fake", "linear", "BTCUSDT")
        bars   = m.candles(interval="1h", limit=3)
        oi     = m.open_interest(interval="1h", limit=2, end=int(bars.index[-1].timestamp() * 1000))

    assert (len(bars), len(oi)) == (3, 2)
