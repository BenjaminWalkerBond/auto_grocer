"""Thread-safe state management for MCP tools.

Uses contextvars for request-scoped state and locks for shared resources.
"""

import asyncio
from contextvars import ContextVar
from typing import TYPE_CHECKING, Any, cast

import structlog

logger = structlog.get_logger()

if TYPE_CHECKING:
    from texas_grocery_mcp.clients.graphql import HEBGraphQLClient

# Request-scoped state using contextvars
_request_store_id: ContextVar[str | None] = ContextVar("request_store_id", default=None)

# Shared state with proper locking
_state_lock = asyncio.Lock()
_shared_state: dict[str, Any] = {
    "default_store_id": None,
    "found_stores": {},
    "graphql_client": None,
    "pending_login": None,
}


class StateManager:
    """Thread-safe state manager for MCP tools.

    Provides:
    - Request-scoped store ID via contextvars
    - Shared GraphQL client with lazy initialization
    - Thread-safe store cache
    - Login state management with locking
    """

    # --- GraphQL Client (singleton, thread-safe) ---

    @staticmethod
    async def get_graphql_client() -> "HEBGraphQLClient":
        """Get or create the shared GraphQL client.

        Thread-safe lazy initialization.
        """
        from texas_grocery_mcp.clients.graphql import HEBGraphQLClient

        async with _state_lock:
            if _shared_state["graphql_client"] is None:
                _shared_state["graphql_client"] = HEBGraphQLClient()
            return cast(HEBGraphQLClient, _shared_state["graphql_client"])

    @staticmethod
    def get_graphql_client_sync() -> "HEBGraphQLClient":
        """Get or create GraphQL client (sync version for non-async contexts).

        Note: Initialization is not fully thread-safe, but acceptable for
        MCP's primarily single-threaded execution model.
        """
        from texas_grocery_mcp.clients.graphql import HEBGraphQLClient

        if _shared_state["graphql_client"] is None:
            _shared_state["graphql_client"] = HEBGraphQLClient()
        return cast(HEBGraphQLClient, _shared_state["graphql_client"])

    # --- Default Store ID ---

    @staticmethod
    def get_default_store_id() -> str | None:
        """Get the current default store ID."""
        # Check request-scoped override first
        request_store = _request_store_id.get()
        if request_store is not None:
            return request_store
        return cast(str | None, _shared_state["default_store_id"])

    @staticmethod
    async def set_default_store_id(store_id: str | None) -> None:
        """Set the default store ID (thread-safe)."""
        async with _state_lock:
            _shared_state["default_store_id"] = store_id

    @staticmethod
    def set_default_store_id_sync(store_id: str | None) -> None:
        """Set default store ID (sync version)."""
        _shared_state["default_store_id"] = store_id

    @staticmethod
    def set_request_store_id(store_id: str | None) -> None:
        """Set store ID for the current request only."""
        _request_store_id.set(store_id)

    # --- Found Stores Cache ---

    @staticmethod
    async def cache_stores(stores: dict[str, Any]) -> None:
        """Cache stores found via search (thread-safe)."""
        async with _state_lock:
            _shared_state["found_stores"].update(stores)

    @staticmethod
    def cache_stores_sync(stores: dict[str, Any]) -> None:
        """Cache stores found via search (sync version)."""
        _shared_state["found_stores"].update(stores)

    @staticmethod
    def get_cached_store(store_id: str) -> Any | None:
        """Get a cached store by ID."""
        return _shared_state["found_stores"].get(store_id)

    @staticmethod
    def get_all_cached_stores() -> dict[str, Any]:
        """Get all cached stores (returns a copy for safety)."""
        return dict(cast(dict[str, Any], _shared_state["found_stores"]))

    @staticmethod
    def get_cached_stores_values() -> Any:
        """Get cached stores values (for iteration)."""
        return _shared_state["found_stores"].values()

    # --- Pending Login State ---

    @staticmethod
    async def get_pending_login() -> dict[str, Any] | None:
        """Get pending login state (thread-safe)."""
        async with _state_lock:
            return cast(dict[str, Any] | None, _shared_state["pending_login"])

    @staticmethod
    def get_pending_login_sync() -> dict[str, Any] | None:
        """Get pending login state (sync version)."""
        return cast(dict[str, Any] | None, _shared_state["pending_login"])

    @staticmethod
    async def set_pending_login(state: dict[str, Any] | None) -> None:
        """Set pending login state (thread-safe)."""
        async with _state_lock:
            _shared_state["pending_login"] = state

    @staticmethod
    def set_pending_login_sync(state: dict[str, Any] | None) -> None:
        """Set pending login state (sync version)."""
        _shared_state["pending_login"] = state

    # --- Reset (for testing) ---

    @staticmethod
    async def reset() -> None:
        """Reset all state. For testing only."""
        async with _state_lock:
            _shared_state["default_store_id"] = None
            _shared_state["found_stores"] = {}
            _shared_state["graphql_client"] = None
            _shared_state["pending_login"] = None
        _request_store_id.set(None)

    @staticmethod
    def reset_sync() -> None:
        """Reset all state synchronously. For testing only."""
        _shared_state["default_store_id"] = None
        _shared_state["found_stores"] = {}
        _shared_state["graphql_client"] = None
        _shared_state["pending_login"] = None
        _request_store_id.set(None)
