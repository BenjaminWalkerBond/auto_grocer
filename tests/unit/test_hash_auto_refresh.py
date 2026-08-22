"""Tests for automatic stale-hash recovery in the GraphQL client.

When HEB rotates its persisted-query hashes, any persisted operation starts
failing with ``PersistedQueryNotFound``. The client should invoke a registered
refresh callback, reload the hashes, and retry the operation once.
"""

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


@pytest.fixture(autouse=True)
def _reset_hash_hook():
    """Reset the module-level hash-refresh hook state around each test."""
    graphql.register_hash_refresh_callback(None)
    graphql._last_hash_refresh_monotonic = 0.0
    graphql._hash_refresh_lock = None
    yield
    graphql.register_hash_refresh_callback(None)
    graphql._last_hash_refresh_monotonic = 0.0
    graphql._hash_refresh_lock = None


@pytest.fixture
def client():
    return graphql.HEBGraphQLClient()


@pytest.mark.asyncio
@respx.mock
async def test_stale_hash_triggers_refresh_and_retries(client):
    """A stale hash should invoke the callback once and retry successfully."""
    calls: list[int] = []

    def _refresh() -> bool:
        calls.append(1)
        return True

    graphql.register_hash_refresh_callback(_refresh)

    respx.post(_URL).mock(side_effect=[Response(200, json=_STALE), Response(200, json=_OK)])

    result = await client._execute_persisted_query(_OP, {"userIsLoggedIn": True})

    assert result == {"cart": {"id": "abc"}}
    assert len(calls) == 1  # refreshed exactly once


@pytest.mark.asyncio
@respx.mock
async def test_no_callback_raises_persisted_query_error(client):
    """Without a registered callback the stale-hash error propagates."""
    respx.post(_URL).mock(return_value=Response(200, json=_STALE))

    with pytest.raises(graphql.PersistedQueryNotFoundError):
        await client._execute_persisted_query(_OP, {})


@pytest.mark.asyncio
@respx.mock
async def test_failed_refresh_raises_after_single_attempt(client):
    """If the refresh callback fails, the error propagates without a retry."""
    calls: list[int] = []

    def _refresh() -> bool:
        calls.append(1)
        return False

    graphql.register_hash_refresh_callback(_refresh)

    respx.post(_URL).mock(return_value=Response(200, json=_STALE))

    with pytest.raises(graphql.PersistedQueryNotFoundError):
        await client._execute_persisted_query(_OP, {})

    assert len(calls) == 1  # attempted once, did not loop


@pytest.mark.asyncio
@respx.mock
async def test_persistent_stale_hash_retries_only_once(client):
    """Even if the hash is still stale after refresh, retry happens only once."""
    calls: list[int] = []

    def _refresh() -> bool:
        calls.append(1)
        return True

    graphql.register_hash_refresh_callback(_refresh)

    # Always stale: first attempt, then the single post-refresh retry.
    route = respx.post(_URL).mock(return_value=Response(200, json=_STALE))

    with pytest.raises(graphql.PersistedQueryNotFoundError):
        await client._execute_persisted_query(_OP, {})

    assert len(calls) == 1
    assert route.call_count == 2  # original + one retry, no infinite loop


@pytest.mark.asyncio
@respx.mock
async def test_with_client_path_also_recovers(client):
    """The authenticated (with-client) executor recovers the same way."""
    calls: list[int] = []

    def _refresh() -> bool:
        calls.append(1)
        return True

    graphql.register_hash_refresh_callback(_refresh)

    respx.post(_URL).mock(side_effect=[Response(200, json=_STALE), Response(200, json=_OK)])

    http_client = await client._get_client()
    result = await client._execute_persisted_query_with_client(
        http_client, _OP, {"userIsLoggedIn": True}
    )

    assert result == {"cart": {"id": "abc"}}
    assert len(calls) == 1
