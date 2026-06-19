"""Store-related MCP tools."""

from typing import TYPE_CHECKING, Annotated, Any

from pydantic import Field

from texas_grocery_mcp.auth.session import ensure_session
from texas_grocery_mcp.clients.graphql import KNOWN_STORES
from texas_grocery_mcp.state import StateManager

if TYPE_CHECKING:
    from texas_grocery_mcp.clients.graphql import HEBGraphQLClient


def _get_client() -> "HEBGraphQLClient":
    """Get or create GraphQL client."""
    return StateManager.get_graphql_client_sync()


async def store_search(
    address: Annotated[str, Field(description="Address or zip code to search near")],
    radius_miles: Annotated[
        int, Field(description="Search radius in miles", ge=1, le=100)
    ] = 25,
) -> dict[str, Any]:
    """Search for HEB stores near an address.

    Returns stores sorted by distance, including store ID, name,
    address, and distance from the search location.
    """
    client = _get_client()
    result = await client.search_stores(address=address, radius_miles=radius_miles)

    # Cache found stores for later use in store_change
    stores_dict = {s.store_id: s for s in result.stores}
    StateManager.cache_stores_sync(stores_dict)

    # Build response with geocoding metadata
    response: dict[str, Any] = {
        "stores": [
            {
                "store_id": s.store_id,
                "name": s.name,
                "address": s.address,
                "distance_miles": round(s.distance_miles, 2) if s.distance_miles else None,
                "phone": s.phone,
                "supports_curbside": s.supports_curbside,
                "supports_delivery": s.supports_delivery,
            }
            for s in result.stores
        ],
        "count": result.count,
        "search_address": result.search_address,
    }

    # Add geocoded location if available
    if result.geocoded:
        response["geocoded"] = {
            "latitude": result.geocoded.latitude,
            "longitude": result.geocoded.longitude,
            "display_name": result.geocoded.display_name,
        }

    # Add feedback for failed/partial searches
    if result.error:
        response["error"] = result.error

    if result.suggestions:
        response["suggestions"] = result.suggestions

    if result.attempts:
        response["attempts"] = [
            {"query": a.query, "result": a.result}
            for a in result.attempts
        ]

    # Add helpful note for successful searches
    if result.stores:
        response["note"] = "Use store_change with a store_id to select one."

    return response


def store_get_default() -> dict[str, Any]:
    """Get the currently set default store.

    Returns the default store ID if set, otherwise indicates no default.
    """
    default_store_id = StateManager.get_default_store_id()

    if default_store_id is None:
        # Suggest a known store
        suggested = list(KNOWN_STORES.values())[0]
        return {
            "store_id": None,
            "message": "Default store not set. Use store_change to set one.",
            "suggestion": {
                "store_id": suggested.store_id,
                "name": suggested.name,
                "address": suggested.address,
            },
            "available_stores": [
                {"store_id": s.store_id, "name": s.name}
                for s in KNOWN_STORES.values()
            ],
        }

    # Return info about the default store - check found stores first
    cached_store = StateManager.get_cached_store(default_store_id)
    if cached_store:
        return {
            "store_id": default_store_id,
            "store_name": cached_store.name,
            "store_address": cached_store.address,
            "message": f"Default store is {cached_store.name}",
        }

    # Fall back to known stores
    if default_store_id in KNOWN_STORES:
        store = KNOWN_STORES[default_store_id]
        return {
            "store_id": default_store_id,
            "store_name": store.name,
            "store_address": store.address,
            "message": f"Default store is {store.name}",
        }

    return {
        "store_id": default_store_id,
        "message": f"Default store is {default_store_id}",
    }


def get_default_store_id() -> str | None:
    """Get default store ID for internal use."""
    return StateManager.get_default_store_id()


def set_default_store_id(store_id: str | None) -> None:
    """Set default store ID for internal/test use.

    This is an internal function - use store_change for the public API.
    """
    StateManager.set_default_store_id_sync(store_id)


@ensure_session
async def store_change(
    store_id: Annotated[str, Field(description="Store ID to change to", min_length=1)],
    ignore_conflicts: Annotated[
        bool,
        Field(
            description=(
                "Force store change even if cart has conflicts (items unavailable, "
                "price changes). Default False - will fail safely and report conflicts."
            ),
        ),
    ] = False,
) -> dict[str, Any]:
    """Change the active store for HEB operations.

    When authenticated: Changes the store on HEB.com via their API with verification.
    When not authenticated: Sets a local default for product searches.

    The store change is VERIFIED by checking the cart's actual store after the
    mutation. This ensures we never return success when the store didn't actually
    change (e.g., due to cart conflicts).

    Args:
        store_id: The store ID to change to
        ignore_conflicts: If True, force store change even if cart has items
            unavailable at the new store or with price changes. Default False.
    """
    from texas_grocery_mcp.auth.session import is_authenticated

    store_id = store_id.strip()

    # Look up store info if available
    store_name = None
    store_address = None
    supports_curbside = True  # Default to True if unknown
    store = None

    cached_store = StateManager.get_cached_store(store_id)
    if cached_store:
        store = cached_store
        store_name = store.name
        store_address = store.address
        supports_curbside = store.supports_curbside
    elif store_id in KNOWN_STORES:
        store = KNOWN_STORES[store_id]
        store_name = store.name
        store_address = store.address
        supports_curbside = store.supports_curbside

    # Check if store supports curbside/online shopping
    if not supports_curbside:
        # Find nearest eligible store to suggest
        suggestion = None
        for s in StateManager.get_cached_stores_values():
            if s.supports_curbside and s.store_id != store_id:
                suggestion = {
                    "store_id": s.store_id,
                    "name": s.name,
                    "address": s.address,
                    "distance_miles": s.distance_miles,
                }
                break

        store_label = store_name or f"Store {store_id}"
        message = (
            f"{store_label} doesn't support online shopping (curbside pickup). "
            "This store is in-store only."
        )

        if suggestion:
            message = f"{message} Try {suggestion['name']} instead."

        result: dict[str, Any] = {
            "error": True,
            "code": "STORE_NOT_ELIGIBLE",
            "message": message,
            "store_id": store_id,
            "store_name": store_name,
        }
        if suggestion:
            result["suggestion"] = suggestion
        return result

    # If not authenticated, set local default only
    if not is_authenticated():
        StateManager.set_default_store_id_sync(store_id)
        return {
            "success": True,
            "store_id": store_id,
            "store_name": store_name,
            "store_address": store_address,
            "message": f"Local default set to {store_name or store_id}",
            "method": "local_only",
            "warning": "Not logged in - store set locally for product searches only.",
            "how_to_sync": (
                "Run session_refresh to log in, then call store_change again to sync with "
                "HEB.com."
            ),
        }

    # Call the GraphQL API to change the store (with verification)
    client = _get_client()
    result = await client.select_store(store_id, ignore_conflicts=ignore_conflicts)

    if result.get("error"):
        # API failed or verification failed - return the error details
        error_response = {
            "error": True,
            "code": result.get("code", "STORE_CHANGE_FAILED"),
            "message": result.get("message", "Failed to change store via API"),
            "store_id": store_id,
            "store_name": store_name,
        }

        # Include additional context from the API response
        if result.get("expected_store"):
            error_response["expected_store"] = result["expected_store"]
        if result.get("actual_store"):
            error_response["actual_store"] = result["actual_store"]
        if result.get("suggestion"):
            error_response["suggestion"] = result["suggestion"]

        # For cart conflicts, add specific guidance
        if result.get("code") == "CART_CONFLICT":
            error_response["help"] = (
                "Your cart has items that may be unavailable or priced differently at the "
                "new store. "
                "Options: (1) Call store_change with ignore_conflicts=True to force the change, "
                "(2) Clear your cart first, or (3) Keep your current store."
            )

        return error_response

    # SUCCESS - Store change verified!
    # Now safe to update local state since we know server state matches
    StateManager.set_default_store_id_sync(store_id)

    # Update the cookie in auth.json so session_status reflects the change
    _update_store_cookie(store_id)

    return {
        "success": True,
        "store_id": store_id,
        "store_name": store_name,
        "store_address": store_address,
        "message": f"Store successfully changed to {store_name or store_id}",
        "method": "api",
        "verified": result.get("verified", False),
    }


def _update_store_cookie(store_id: str) -> bool:
    """Update the CURR_SESSION_STORE cookie in auth.json.

    This ensures session_status reflects the new store immediately.

    Args:
        store_id: The new store ID

    Returns:
        True if updated successfully, False otherwise
    """
    import json

    from texas_grocery_mcp.utils.config import get_settings

    settings = get_settings()
    auth_path = settings.auth_state_path

    if not auth_path.exists():
        return False

    try:
        with open(auth_path) as f:
            state = json.load(f)

        cookies = state.get("cookies", [])
        found = False

        for cookie in cookies:
            if cookie.get("name") == "CURR_SESSION_STORE" and "heb.com" in cookie.get("domain", ""):
                cookie["value"] = store_id
                found = True
                break

        if not found:
            # Add the cookie if it doesn't exist
            cookies.append({
                "name": "CURR_SESSION_STORE",
                "value": store_id,
                "domain": "www.heb.com",
                "path": "/",
                "expires": -1,
                "httpOnly": True,
                "secure": True,
                "sameSite": "Lax",
            })
            state["cookies"] = cookies

        from texas_grocery_mcp.utils.secure_file import write_secure_json

        write_secure_json(auth_path, state)

        return True

    except (json.JSONDecodeError, OSError):
        return False
