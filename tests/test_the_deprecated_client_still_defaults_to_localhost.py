import warnings

import httpx
import pytest

from exchange_router import AsyncExchangeRouterClient, AsyncRouter, ExchangeRouterClient, Router
from exchange_router.backend import RemoteBackend
from exchange_router.service import app


def asgi_backend(url="http://router.test"):
    return RemoteBackend(url, http=httpx.AsyncClient(transport=httpx.ASGITransport(app=app), timeout=30))


def test_the_old_name_still_takes_no_arguments_at_all():
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        client = AsyncExchangeRouterClient()

    assert client.base_url == "http://localhost:8040"
    assert client.mode     == "service"
    assert client.scope    == []


def test_the_old_name_warns_that_it_is_the_old_name():
    with pytest.warns(DeprecationWarning) as caught:
        AsyncExchangeRouterClient()

    message = str(caught[0].message)
    assert "AsyncRouter.service" in message
    assert "AsyncRouter.local" in message


def test_the_sync_old_name_warns_and_keeps_localhost():
    with pytest.warns(DeprecationWarning) as caught:
        client = ExchangeRouterClient()

    assert client._core.base_url == "http://localhost:8040"
    assert "Router.service" in str(caught[0].message)
    client.close()


def test_the_new_names_do_not_warn():
    with warnings.catch_warnings():
        warnings.simplefilter("error", DeprecationWarning)
        AsyncRouter.service("http://router.test", ["fake"], verbose=False)
        AsyncRouter.local(["fake"], verbose=False)


async def test_the_old_name_still_reads_data_through_the_same_surface():
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        client = AsyncExchangeRouterClient(verbose=False, backend=asgi_backend())

    row = await client.get_ticker("fake", "spot", "BTCUSDT")
    assert row.price == 100.0

    await client.close()


async def test_the_old_name_and_the_new_one_return_the_same_thing():
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        old = AsyncExchangeRouterClient(verbose=False, backend=asgi_backend())

    new = AsyncRouter.service("http://router.test", ["fake"], verbose=False, backend=asgi_backend())

    a = await old.get_candles("fake", "linear", "BTCUSDT", interval="1h", limit=3)
    b = await new.get_candles("fake", "linear", "BTCUSDT", interval="1h", limit=3)

    assert list(a.columns) == list(b.columns)
    assert list(a["close"]) == list(b["close"])
    assert a.attrs == b.attrs

    await old.close()
    await new.close()


def test_the_old_name_is_a_subclass_so_existing_except_clauses_keep_working():
    assert issubclass(AsyncExchangeRouterClient, AsyncRouter)
    assert issubclass(ExchangeRouterClient, Router)
