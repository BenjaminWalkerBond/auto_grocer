"""Tests for Apollo APQ (Automatic Persisted Queries) recovery in the client.

HEB evicts low-traffic operations (notably ``SelectPickupFulfillment``, the
store-change mutation) from its shared APQ cache, after which it returns
``PersistedQueryNotFound`` for EVERY hash value — so capturing a "fresh" hash
never helps (verified live against HEB). The fix is standard APQ recovery:
resend the request WITH the full ``query`` text to re-register + execute it.

For APQ-only operations with no captured query document, an automatic browser
hash refresh is futile, so the client fails fast with clear guidance instead of
launching a multi-minute browser capture.
"""

import json

import pytest
import respx
from httpx import Response

import auto_grocer_mcp.clients.graphql as graphql

_URL = "https://www.heb.com/graphql"
_STALE = {"errors": [{"message": "PersistedQueryNotFound"}]}


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    """Isolate module-level APQ/refresh state around each test."""
    graphql.register_hash_refresh_callback(None)
    graphql._last_hash_refresh_monotonic = 0.0
    graphql._hash_refresh_in_progress = False
    monkeypatch.setattr(graphql, "PERSISTED_QUERY_DOCUMENTS", {})
    yield
    graphql.register_hash_refresh_callback(None)


# ---------------------------------------------------------------------------
# Parser + loader
# ---------------------------------------------------------------------------
def test_parse_operation_samples_captures_query():
    from auto_grocer.utility.graphql_hash_capture import _parse_operation_samples

    query = "mutation SelectPickupFulfillment { selectPickupFulfillment { id } }"
    body = json.dumps(
        {
            "operationName": "SelectPickupFulfillment",
            "variables": {"storeId": 14},
            "query": query,
            "extensions": {"persistedQuery": {"version": 1, "sha256Hash": "abc"}},
        }
    )

    out = _parse_operation_samples(body)

    assert out == [("SelectPickupFulfillment", "abc", {"storeId": 14}, query)]


def test_parse_operation_samples_query_none_when_absent():
    from auto_grocer.utility.graphql_hash_capture import _parse_operation_samples

    body = json.dumps(
        {
            "operationName": "cartEstimated",
            "variables": {},
            "extensions": {"persistedQuery": {"version": 1, "sha256Hash": "h"}},
        }
    )

    out = _parse_operation_samples(body)

    assert out[0][3] is None


def test_load_query_documents(tmp_path, monkeypatch):
    ops = {
        "SelectPickupFulfillment": {"hash": "h", "variables": {}, "query": "mutation X { y }"},
        "NoQuery": {"hash": "h2", "variables": {}, "query": None},
    }
    p = tmp_path / "captured_operations.json"
    p.write_text(json.dumps(ops))
    monkeypatch.setenv("GRAPHQL_OPERATIONS_PATH", str(p))

    graphql._load_persisted_query_documents()

    assert graphql.PERSISTED_QUERY_DOCUMENTS.get("SelectPickupFulfillment") == "mutation X { y }"
    assert "NoQuery" not in graphql.PERSISTED_QUERY_DOCUMENTS


# ---------------------------------------------------------------------------
# APQ full-query fallback
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
@respx.mock
async def test_apq_fallback_registers_full_query(monkeypatch):
    """On PersistedQueryNotFound with a captured doc, resend WITH the full query."""
    op = "SelectPickupFulfillment"
    query = "mutation SelectPickupFulfillment { selectPickupFulfillment { id } }"
    monkeypatch.setitem(graphql.PERSISTED_QUERY_DOCUMENTS, op, query)

    route = respx.post(_URL).mock(
        side_effect=[
            Response(200, json=_STALE),  # hash-only -> miss
            Response(200, json={"data": {"selectPickupFulfillment": {"ok": True}}}),  # +query
        ]
    )

    client = graphql.HEBGraphQLClient()
    try:
        c = await client._get_client()
        data = await client._execute_persisted_query_with_client(c, op, {"storeId": 14})
    finally:
        await client.close()

    assert data == {"selectPickupFulfillment": {"ok": True}}
    assert route.call_count == 2
    # First request is hash-only; second carries the full query for registration.
    first = json.loads(route.calls[0].request.content)
    second = json.loads(route.calls[1].request.content)
    assert "query" not in first
    assert second.get("query") == query


@pytest.mark.asyncio
@respx.mock
async def test_apq_only_op_fails_fast_without_doc(monkeypatch):
    """SelectPickupFulfillment with no query doc must fail fast, NOT trigger a
    browser hash refresh (which cannot fix an APQ-eviction)."""
    op = "SelectPickupFulfillment"
    # No document registered (autouse fixture cleared the dict).
    triggered: list = []

    async def _never(operation_name):  # pragma: no cover - must not be called
        triggered.append(operation_name)
        return "disabled"

    monkeypatch.setattr(graphql, "_attempt_hash_refresh", _never)
    respx.post(_URL).mock(return_value=Response(200, json=_STALE))

    client = graphql.HEBGraphQLClient()
    try:
        c = await client._get_client()
        with pytest.raises(graphql.PersistedQueryNotFoundError) as ei:
            await client._execute_persisted_query_with_client(c, op, {"storeId": 14})
    finally:
        await client.close()

    assert "capture_hashes" in str(ei.value)
    assert triggered == []  # browser refresh NOT triggered for an APQ-only op


@pytest.mark.asyncio
@respx.mock
async def test_non_apq_op_still_uses_background_refresh(monkeypatch):
    """A normal rotated-hash op (not APQ-only, no doc) still uses the refresh path."""
    op = "cartEstimated"
    seen: list = []

    async def _refresh(operation_name):
        seen.append(operation_name)
        return "started"

    monkeypatch.setattr(graphql, "_attempt_hash_refresh", _refresh)
    respx.post(_URL).mock(return_value=Response(200, json=_STALE))

    client = graphql.HEBGraphQLClient()
    try:
        c = await client._get_client()
        with pytest.raises(graphql.PersistedQueryNotFoundError) as ei:
            await client._execute_persisted_query_with_client(c, op, {})
    finally:
        await client.close()

    assert seen == [op]  # refresh path was used
    assert "60-90 seconds" in str(ei.value)
