"""Tests for automatic stale-hash recovery in the GraphQL client.

When HEB rotates its persisted-query hashes, any persisted operation starts
failing with ``PersistedQueryNotFound``. The client triggers a registered
refresh callback on a background thread (never blocking the caller) and fails
fast with a "retry shortly" error. A subsequent operation within the cooldown
window after a successful refresh retries immediately using the reloaded
hashes.
"""

import threading
import time

import pytest
import respx
from httpx import Response

import auto_grocer_mcp.clients.graphql as graphql

# NOTE: reference exception/registration symbols through the ``graphql`` module
# alias (not ``from`` imports). ``test_graphql_client`` calls
# ``importlib.reload`` on this module, which rebinds its classes to new objects;
# a ``from`` import would capture stale classes and break ``pytest.raises``.

_URL = "https://www.heb.com/graphql"
_OP = "cartEstimated"  # any operation present in PERSISTED_QUERIES

_STALE = {"errors": [{"message": "PersistedQueryNotFound"}]}
_OK = {"data": {"cart": {"id": "abc"}}}


def _wait_until_refresh_idle(timeout: float = 2.0) -> None:
    """Block (test thread only) until the background refresh thread finishes."""
    deadline = time.monotonic() + timeout
    while graphql._hash_refresh_in_progress and time.monotonic() < deadline:
        time.sleep(0.02)


@pytest.fixture(autouse=True)
def _reset_hash_hook():
    """Reset the module-level hash-refresh hook state around each test."""
    graphql.register_hash_refresh_callback(None)
    graphql._last_hash_refresh_monotonic = 0.0
    graphql._hash_refresh_in_progress = False
    yield
    graphql.register_hash_refresh_callback(None)
    graphql._last_hash_refresh_monotonic = 0.0
    graphql._hash_refresh_in_progress = False


@pytest.fixture
def client():
    return graphql.HEBGraphQLClient()


@pytest.mark.asyncio
@respx.mock
async def test_stale_hash_triggers_background_refresh_and_fails_fast(client):
    """A stale hash launches a background refresh and fails fast (never blocks)."""
    started = threading.Event()
    release = threading.Event()
    calls: list[str] = []

    def _refresh(operation_name: str) -> bool:
        calls.append(operation_name)
        started.set()
        release.wait(timeout=2)
        return True

    graphql.register_hash_refresh_callback(_refresh)
    respx.post(_URL).mock(return_value=Response(200, json=_STALE))

    with pytest.raises(graphql.PersistedQueryNotFoundError, match="background"):
        await client._execute_persisted_query(_OP, {})

    assert started.wait(timeout=1), "refresh callback should have been invoked"
    assert calls == [_OP]
    assert graphql._hash_refresh_in_progress is True

    release.set()
    _wait_until_refresh_idle()
    assert graphql._hash_refresh_in_progress is False
    assert graphql._last_hash_refresh_monotonic > 0


@pytest.mark.asyncio
@respx.mock
async def test_no_callback_raises_persisted_query_error(client):
    """Without a registered callback the stale-hash error propagates unchanged."""
    respx.post(_URL).mock(return_value=Response(200, json=_STALE))

    with pytest.raises(graphql.PersistedQueryNotFoundError):
        await client._execute_persisted_query(_OP, {})


@pytest.mark.asyncio
@respx.mock
async def test_failed_refresh_does_not_start_a_cooldown(client):
    """If the background refresh callback fails, no cooldown/retry is granted."""
    release = threading.Event()
    calls: list[str] = []

    def _refresh(operation_name: str) -> bool:
        calls.append(operation_name)
        release.wait(timeout=2)
        return False

    graphql.register_hash_refresh_callback(_refresh)
    respx.post(_URL).mock(return_value=Response(200, json=_STALE))

    with pytest.raises(graphql.PersistedQueryNotFoundError):
        await client._execute_persisted_query(_OP, {})

    release.set()
    _wait_until_refresh_idle()

    assert calls == [_OP]
    assert graphql._last_hash_refresh_monotonic == 0.0  # failure grants no cooldown


@pytest.mark.asyncio
@respx.mock
async def test_concurrent_stale_operation_fails_fast_without_duplicate_refresh(client):
    """A second stale operation while a refresh is running does not launch another."""
    started = threading.Event()
    release = threading.Event()
    calls: list[str] = []

    def _refresh(operation_name: str) -> bool:
        calls.append(operation_name)
        started.set()
        release.wait(timeout=2)
        return True

    graphql.register_hash_refresh_callback(_refresh)
    respx.post(_URL).mock(return_value=Response(200, json=_STALE))

    with pytest.raises(graphql.PersistedQueryNotFoundError, match="just started"):
        await client._execute_persisted_query(_OP, {})
    assert started.wait(timeout=1)

    with pytest.raises(graphql.PersistedQueryNotFoundError, match="already been triggered"):
        await client._execute_persisted_query(_OP, {})

    release.set()
    _wait_until_refresh_idle()
    assert calls == [_OP]  # only one background refresh was launched


@pytest.mark.asyncio
@respx.mock
async def test_refresh_within_cooldown_retries_immediately(client):
    """An operation that fails shortly after a completed refresh retries at once."""
    graphql._last_hash_refresh_monotonic = time.monotonic()  # simulate a recent success
    calls: list[str] = []

    def _refresh(operation_name: str) -> bool:
        calls.append(operation_name)
        return True

    graphql.register_hash_refresh_callback(_refresh)
    respx.post(_URL).mock(side_effect=[Response(200, json=_STALE), Response(200, json=_OK)])

    result = await client._execute_persisted_query(_OP, {"userIsLoggedIn": True})

    assert result == {"cart": {"id": "abc"}}
    assert calls == []  # cooldown reused; no new background capture launched


@pytest.mark.asyncio
@respx.mock
async def test_with_client_path_recovers_within_cooldown(client):
    """The authenticated (with-client) executor recovers the same way."""
    graphql._last_hash_refresh_monotonic = time.monotonic()
    respx.post(_URL).mock(side_effect=[Response(200, json=_STALE), Response(200, json=_OK)])

    http_client = await client._get_client()
    result = await client._execute_persisted_query_with_client(
        http_client, _OP, {"userIsLoggedIn": True}
    )

    assert result == {"cart": {"id": "abc"}}
