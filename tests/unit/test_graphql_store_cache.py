"""Unit tests for the in-memory store cache in auto_grocer.utility.graphql_store.

Mirrors texas-grocery-mcp's StateManager.cache_stores_sync/get_cached_store:
cache_stores lets set_store enrich its response with a store's name/address
without a second network round-trip after search_stores.
"""

from __future__ import annotations

from types import SimpleNamespace

from auto_grocer.utility.graphql_store import cache_stores, get_cached_store


def test_cache_and_get_store_object():
    store = SimpleNamespace(store_id="14", name="Kyle H-E-B", address="100 Main St")

    cache_stores([store])

    cached = get_cached_store("14")
    assert cached is store
    assert cached.name == "Kyle H-E-B"


def test_cache_and_get_store_dict():
    cache_stores([{"store_id": "243", "name": "East Hopkins H-E-B"}])

    cached = get_cached_store("243")
    assert cached["name"] == "East Hopkins H-E-B"


def test_get_cached_store_missing_returns_none():
    assert get_cached_store("does-not-exist-999") is None


def test_cache_stores_ignores_entries_without_store_id():
    # Must not raise for malformed entries (missing/empty store_id).
    cache_stores([{"name": "no id"}, SimpleNamespace(name="also no id")])
    assert get_cached_store("") is None
