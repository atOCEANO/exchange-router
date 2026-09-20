import time

import pytest

from exchange_router import AsyncRouter, Router
from exchange_router.backend import LocalBackend
from exchange_router.errors import BadRequest, NotFound


@pytest.mark.parametrize("cls", [Router, AsyncRouter], ids=["sync", "async"])
def test_bare_construction_raises_and_the_message_names_both_modes(cls):
    with pytest.raises(TypeError) as caught:
        cls()

    message = str(caught.value)
    assert "local" in message
    assert "service" in message


@pytest.mark.parametrize("cls", [Router, AsyncRouter], ids=["sync", "async"])
def test_construction_with_a_url_alone_still_raises(cls):
    with pytest.raises(TypeError):
        cls("http://localhost:8040")


@pytest.mark.parametrize("cls", [Router, AsyncRouter], ids=["sync", "async"])
def test_local_without_a_scope_raises(cls):
    with pytest.raises(TypeError):
        cls.local()


@pytest.mark.parametrize("cls", [Router, AsyncRouter], ids=["sync", "async"])
def test_an_empty_scope_is_refused_rather_than_treated_as_everything(cls):
    with pytest.raises(BadRequest):
        cls.local([])


@pytest.mark.parametrize("cls", [Router, AsyncRouter], ids=["sync", "async"])
def test_a_bare_string_that_is_not_all_is_refused(cls):
    with pytest.raises(BadRequest) as caught:
        cls.local("fake")

    assert "['fake']" in str(caught.value)


@pytest.mark.parametrize("cls", [Router, AsyncRouter], ids=["sync", "async"])
def test_an_unknown_exchange_is_caught_at_construction_in_local_mode(cls):
    with pytest.raises(NotFound) as caught:
        cls.local(["nosuch"])

    assert "nosuch" in str(caught.value)


@pytest.mark.parametrize("cls", [Router, AsyncRouter], ids=["sync", "async"])
def test_service_without_a_url_raises(cls):
    with pytest.raises(TypeError):
        cls.service(exchanges=["fake"])


@pytest.mark.parametrize("cls", [Router, AsyncRouter], ids=["sync", "async"])
def test_service_without_a_scope_raises(cls):
    with pytest.raises(TypeError):
        cls.service("http://localhost:8040")


@pytest.mark.parametrize("cls", [Router, AsyncRouter], ids=["sync", "async"])
def test_a_fallback_that_is_not_local_is_refused(cls):
    with pytest.raises(BadRequest):
        cls.service("http://localhost:8040", ["fake"], fallback="remote")


def test_all_resolves_to_every_registered_exchange_in_local_mode():
    router = AsyncRouter.local("all", verbose=False, backend=LocalBackend())
    assert router.scope == ["fake"]


def test_mode_is_readable_and_never_inferred():
    local   = AsyncRouter.local(["fake"], verbose=False, backend=LocalBackend())
    service = AsyncRouter.service("http://router.test", ["fake"], verbose=False)

    assert local.mode   == "local"
    assert service.mode == "service"


def test_the_schema_version_is_the_one_the_sdk_speaks():
    router = AsyncRouter.local(["fake"], verbose=False, backend=LocalBackend())
    assert router.schema_version == 3


@pytest.mark.parametrize("cls", [Router, AsyncRouter], ids=["sync", "async"])
def test_construction_returns_immediately_in_both_modes(cls):
    started = time.monotonic()
    local   = cls.local(["fake"], verbose=False)
    service = cls.service("http://router.test", ["fake"], verbose=False)
    elapsed = time.monotonic() - started

    assert elapsed < 1.0

    if cls is Router:
        local.close()
        service.close()
