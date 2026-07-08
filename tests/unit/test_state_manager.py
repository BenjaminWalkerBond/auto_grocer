"""Tests for StateManager thread-safe state management."""

import asyncio

import pytest

from texas_grocery_mcp.state import StateManager


class TestStateManagerStoreId:
    """Tests for store ID management."""

    def test_get_default_store_id_initially_none(self):
        """Default store ID should be None initially."""
        assert StateManager.get_default_store_id() is None

    def test_set_and_get_default_store_id_sync(self):
        """Should set and retrieve default store ID synchronously."""
        StateManager.set_default_store_id_sync("123")
        assert StateManager.get_default_store_id() == "123"

    @pytest.mark.asyncio
    async def test_set_and_get_default_store_id_async(self):
        """Should set and retrieve default store ID asynchronously."""
        await StateManager.set_default_store_id("456")
        assert StateManager.get_default_store_id() == "456"

    def test_set_request_store_id_overrides_default(self):
        """Request-scoped store ID should override default."""
        StateManager.set_default_store_id_sync("default")
        StateManager.set_request_store_id("request")

        assert StateManager.get_default_store_id() == "request"

        # Clear request scope
        StateManager.set_request_store_id(None)
        assert StateManager.get_default_store_id() == "default"


class TestStateManagerStoreCache:
    """Tests for store caching."""

    def test_cache_and_get_store(self):
        """Should cache and retrieve stores."""
        from texas_grocery_mcp.models import Store

        store = Store(
            store_id="999",
            name="Test Store",
            address="123 Test St",
            distance_miles=1.0,
        )
        StateManager.cache_stores_sync({"999": store})

        cached = StateManager.get_cached_store("999")
        assert cached is not None
        assert cached.name == "Test Store"

    def test_get_cached_store_not_found(self):
        """Should return None for uncached store."""
        assert StateManager.get_cached_store("nonexistent") is None

    def test_get_all_cached_stores_returns_copy(self):
        """Should return a copy of cached stores."""
        from texas_grocery_mcp.models import Store

        store = Store(
            store_id="888",
            name="Another Store",
            address="456 Test St",
            distance_miles=2.0,
        )
        StateManager.cache_stores_sync({"888": store})

        all_stores = StateManager.get_all_cached_stores()
        assert "888" in all_stores

        # Modifying returned dict shouldn't affect cache
        all_stores["888"] = None
        assert StateManager.get_cached_store("888") is not None


class TestStateManagerGraphQLClient:
    """Tests for GraphQL client management."""

    def test_get_graphql_client_sync_creates_client(self):
        """Should create GraphQL client on first access."""
        client = StateManager.get_graphql_client_sync()
        assert client is not None

    def test_get_graphql_client_sync_returns_same_instance(self):
        """Should return same client instance on subsequent calls."""
        client1 = StateManager.get_graphql_client_sync()
        client2 = StateManager.get_graphql_client_sync()
        assert client1 is client2

    @pytest.mark.asyncio
    async def test_get_graphql_client_async(self):
        """Should get GraphQL client asynchronously."""
        client = await StateManager.get_graphql_client()
        assert client is not None


class TestStateManagerReset:
    """Tests for state reset functionality."""

    def test_reset_sync_clears_all_state(self):
        """Should clear all state synchronously."""
        from texas_grocery_mcp.models import Store

        # Set some state
        StateManager.set_default_store_id_sync("123")
        StateManager.cache_stores_sync({
            "999": Store(
                store_id="999",
                name="Test",
                address="Test",
                distance_miles=1.0,
            )
        })

        # Reset
        StateManager.reset_sync()

        # Verify cleared
        assert StateManager.get_default_store_id() is None
        assert StateManager.get_cached_store("999") is None

    @pytest.mark.asyncio
    async def test_reset_async_clears_all_state(self):
        """Should clear all state asynchronously."""
        from texas_grocery_mcp.models import Store

        # Set some state
        await StateManager.set_default_store_id("456")
        await StateManager.cache_stores({
            "888": Store(
                store_id="888",
                name="Test",
                address="Test",
                distance_miles=1.0,
            )
        })

        # Reset
        await StateManager.reset()

        # Verify cleared
        assert StateManager.get_default_store_id() is None
        assert StateManager.get_cached_store("888") is None


class TestStateManagerConcurrency:
    """Tests for concurrent access safety."""

    @pytest.mark.asyncio
    async def test_concurrent_store_id_updates(self):
        """Concurrent store ID updates should not corrupt state."""

        async def update_store(store_id: str):
            await StateManager.set_default_store_id(store_id)
            await asyncio.sleep(0.01)  # Simulate work
            return StateManager.get_default_store_id()

        # Run concurrent updates
        await asyncio.gather(
            update_store("100"),
            update_store("200"),
            update_store("300"),
        )

        # Final state should be one of the values (last writer wins)
        final = StateManager.get_default_store_id()
        assert final in ("100", "200", "300")

    @pytest.mark.asyncio
    async def test_concurrent_cache_updates(self):
        """Concurrent cache updates should not corrupt state."""
        from texas_grocery_mcp.models import Store

        async def cache_store(store_id: str):
            store = Store(
                store_id=store_id,
                name=f"Store {store_id}",
                address=f"{store_id} Main St",
                distance_miles=float(store_id),
            )
            await StateManager.cache_stores({store_id: store})
            await asyncio.sleep(0.01)

        # Run concurrent cache operations
        await asyncio.gather(
            cache_store("111"),
            cache_store("222"),
            cache_store("333"),
        )

        # All stores should be cached
        assert StateManager.get_cached_store("111") is not None
        assert StateManager.get_cached_store("222") is not None
        assert StateManager.get_cached_store("333") is not None
