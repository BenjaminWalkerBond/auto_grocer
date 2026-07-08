"""Tests for store tools."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from texas_grocery_mcp.clients.graphql import KNOWN_STORES
from texas_grocery_mcp.models import GeocodedLocation, SearchAttempt, Store, StoreSearchResult
from texas_grocery_mcp.state import StateManager


def _make_mock_store_search_result(
    stores: list[Store] | None = None,
    geocoded: GeocodedLocation | None = None,
    error: str | None = None,
) -> StoreSearchResult:
    """Create a mock StoreSearchResult for testing."""
    if stores is None:
        stores = [
            Store(
                store_id="737",
                name="The Heights H-E-B",
                address="2300 N. SHEPHERD DR., HOUSTON, TX 77008",
                phone="(713) 802-9090",
                distance_miles=2.5,
                latitude=29.8028,
                longitude=-95.4103,
            ),
            Store(
                store_id="150",
                name="Montrose H-E-B",
                address="1701 W ALABAMA ST, HOUSTON, TX 77098",
                phone="(713) 523-4481",
                distance_miles=5.1,
                latitude=29.7419,
                longitude=-95.3979,
            ),
        ]

    return StoreSearchResult(
        stores=stores,
        count=len(stores),
        search_address="Houston, TX",
        geocoded=geocoded or GeocodedLocation(
            latitude=29.7604,
            longitude=-95.3698,
            display_name="Houston, TX, USA",
        ),
        attempts=[SearchAttempt(query="77007", result="success")],
        error=error,
        suggestions=[],
    )


@pytest.mark.asyncio
async def test_store_search_returns_stores():
    """store_search should return stores from the API."""
    from texas_grocery_mcp.tools.store import store_search

    mock_result = _make_mock_store_search_result()

    with patch("texas_grocery_mcp.tools.store._get_client") as mock_get_client:
        mock_client = MagicMock()
        mock_client.search_stores = AsyncMock(return_value=mock_result)
        mock_get_client.return_value = mock_client

        result = await store_search(address="Houston, TX")

        assert result["count"] == 2
        assert len(result["stores"]) == 2
        assert result["stores"][0]["store_id"] == "737"
        assert result["stores"][0]["name"] == "The Heights H-E-B"


@pytest.mark.asyncio
async def test_store_search_includes_geocoded_info():
    """store_search should include geocoded location info."""
    from texas_grocery_mcp.tools.store import store_search

    mock_result = _make_mock_store_search_result()

    with patch("texas_grocery_mcp.tools.store._get_client") as mock_get_client:
        mock_client = MagicMock()
        mock_client.search_stores = AsyncMock(return_value=mock_result)
        mock_get_client.return_value = mock_client

        result = await store_search(address="Rice Military, Houston")

        assert "geocoded" in result
        assert result["geocoded"]["latitude"] == 29.7604
        assert result["geocoded"]["longitude"] == -95.3698


@pytest.mark.asyncio
async def test_store_search_includes_note_on_success():
    """store_search should include note about store_change on success."""
    from texas_grocery_mcp.tools.store import store_search

    mock_result = _make_mock_store_search_result()

    with patch("texas_grocery_mcp.tools.store._get_client") as mock_get_client:
        mock_client = MagicMock()
        mock_client.search_stores = AsyncMock(return_value=mock_result)
        mock_get_client.return_value = mock_client

        result = await store_search(address="Houston, TX")

        assert "note" in result
        assert "store_change" in result["note"]


@pytest.mark.asyncio
async def test_store_search_includes_error_on_failure():
    """store_search should include error message when no stores found."""
    from texas_grocery_mcp.tools.store import store_search

    mock_result = StoreSearchResult(
        stores=[],
        count=0,
        search_address="New York, NY",
        geocoded=GeocodedLocation(
            latitude=40.7128,
            longitude=-74.0060,
            display_name="New York, NY, USA",
        ),
        attempts=[
            SearchAttempt(query="10001", result="no_stores"),
            SearchAttempt(query="New York, NY", result="no_stores"),
        ],
        error="No HEB stores found within 25 miles of New York, NY, USA.",
        suggestions=["HEB operates primarily in Texas"],
    )

    with patch("texas_grocery_mcp.tools.store._get_client") as mock_get_client:
        mock_client = MagicMock()
        mock_client.search_stores = AsyncMock(return_value=mock_result)
        mock_get_client.return_value = mock_client

        result = await store_search(address="New York, NY")

        assert result["count"] == 0
        assert "error" in result
        assert "No HEB stores" in result["error"]
        assert "suggestions" in result
        assert "note" not in result  # No note when no stores found


@pytest.mark.asyncio
async def test_store_search_includes_attempts():
    """store_search should include search attempts made."""
    from texas_grocery_mcp.tools.store import store_search

    mock_result = _make_mock_store_search_result()
    mock_result.attempts = [
        SearchAttempt(query="77007", result="success"),
    ]

    with patch("texas_grocery_mcp.tools.store._get_client") as mock_get_client:
        mock_client = MagicMock()
        mock_client.search_stores = AsyncMock(return_value=mock_result)
        mock_get_client.return_value = mock_client

        result = await store_search(address="Rice Military")

        assert "attempts" in result
        assert result["attempts"][0]["query"] == "77007"
        assert result["attempts"][0]["result"] == "success"


@pytest.mark.asyncio
async def test_store_search_rounds_distance():
    """store_search should round distance to 2 decimal places."""
    from texas_grocery_mcp.tools.store import store_search

    stores = [
        Store(
            store_id="737",
            name="Test Store",
            address="123 Test St",
            distance_miles=2.56789,
            latitude=29.8,
            longitude=-95.4,
        ),
    ]
    mock_result = _make_mock_store_search_result(stores=stores)

    with patch("texas_grocery_mcp.tools.store._get_client") as mock_get_client:
        mock_client = MagicMock()
        mock_client.search_stores = AsyncMock(return_value=mock_result)
        mock_get_client.return_value = mock_client

        result = await store_search(address="Houston, TX")

        assert result["stores"][0]["distance_miles"] == 2.57


@pytest.mark.asyncio
async def test_store_search_caches_found_stores():
    """store_search should cache found stores for store_change."""
    from texas_grocery_mcp.tools.store import store_search

    mock_result = _make_mock_store_search_result()

    with patch("texas_grocery_mcp.tools.store._get_client") as mock_get_client:
        mock_client = MagicMock()
        mock_client.search_stores = AsyncMock(return_value=mock_result)
        mock_get_client.return_value = mock_client

        await store_search(address="Houston, TX")

        # Should have cached the stores via StateManager
        assert StateManager.get_cached_store("737") is not None
        assert StateManager.get_cached_store("150") is not None
        # Cached store should have correct info
        assert StateManager.get_cached_store("737").name == "The Heights H-E-B"


@pytest.mark.asyncio
async def test_store_change_sets_local_when_not_authenticated():
    """store_change should set local default when not authenticated."""
    from texas_grocery_mcp.tools.store import store_change, store_get_default

    with patch("texas_grocery_mcp.auth.session.is_authenticated", return_value=False):
        # Use The Heights H-E-B (a known store)
        result = await store_change(store_id="737")

        assert result["success"] is True
        assert result["store_id"] == "737"
        assert result["store_name"] == "The Heights H-E-B"
        assert result["method"] == "local_only"
        assert "warning" in result  # Should warn about not being logged in

        default = store_get_default()
        assert default["store_id"] == "737"
        assert default["store_name"] == "The Heights H-E-B"


def test_store_get_default_none():
    """store_get_default should return None when not set."""
    from texas_grocery_mcp.tools.store import store_get_default

    # StateManager is reset by conftest fixture

    result = store_get_default()

    assert result["store_id"] is None
    assert "not set" in result["message"].lower()
    assert "suggestion" in result
    assert "available_stores" in result


def test_store_get_default_suggests_store():
    """store_get_default should suggest a store when not set."""
    from texas_grocery_mcp.tools.store import store_get_default

    # StateManager is reset by conftest fixture

    result = store_get_default()

    # Should suggest a known store
    assert "suggestion" in result
    assert result["suggestion"]["store_id"] in KNOWN_STORES
    assert result["suggestion"]["name"] is not None


def test_store_get_default_uses_found_stores():
    """store_get_default should use found stores cache."""
    from texas_grocery_mcp.tools.store import store_get_default

    # Simulate a store found via search (not in KNOWN_STORES)
    StateManager.cache_stores_sync({
        "12345": Store(
            store_id="12345",
            name="New Store",
            address="456 New St",
            distance_miles=1.0,
        ),
    })
    StateManager.set_default_store_id_sync("12345")

    result = store_get_default()

    assert result["store_id"] == "12345"
    assert result["store_name"] == "New Store"
    assert result["store_address"] == "456 New St"


@pytest.mark.asyncio
async def test_store_change_strips_whitespace():
    """store_change should strip whitespace from store ID."""
    from texas_grocery_mcp.tools.store import store_change

    with patch("texas_grocery_mcp.auth.session.is_authenticated", return_value=False):
        result = await store_change(store_id="  737  ")

        assert result["success"] is True
        assert result["store_id"] == "737"


def test_get_default_store_id_internal():
    """get_default_store_id should return the internal store ID."""
    from texas_grocery_mcp.tools.store import get_default_store_id, set_default_store_id

    # Initially None
    assert get_default_store_id() is None

    # After setting
    set_default_store_id("579")
    assert get_default_store_id() == "579"


@pytest.mark.asyncio
async def test_store_search_includes_curbside_support():
    """store_search should include supports_curbside in response."""
    from texas_grocery_mcp.tools.store import store_search

    stores = [
        Store(
            store_id="699",
            name="Nogalitos H-E-B",
            address="1601 NOGALITOS, SAN ANTONIO, TX 78204",
            distance_miles=0.83,
            latitude=29.3978,
            longitude=-98.5150,
            supports_curbside=True,
            supports_delivery=True,
        ),
        Store(
            store_id="718",
            name="South Flores Market H-E-B",
            address="516 S FLORES STREET, SAN ANTONIO, TX 78204",
            distance_miles=1.10,
            latitude=29.4195,
            longitude=-98.4939,
            supports_curbside=False,
            supports_delivery=False,
        ),
    ]
    mock_result = _make_mock_store_search_result(stores=stores)

    with patch("texas_grocery_mcp.tools.store._get_client") as mock_get_client:
        mock_client = MagicMock()
        mock_client.search_stores = AsyncMock(return_value=mock_result)
        mock_get_client.return_value = mock_client

        result = await store_search(address="San Antonio, TX 78204")

        assert result["count"] == 2
        # First store supports curbside
        assert result["stores"][0]["supports_curbside"] is True
        assert result["stores"][0]["supports_delivery"] is True
        # Second store does not
        assert result["stores"][1]["supports_curbside"] is False
        assert result["stores"][1]["supports_delivery"] is False


@pytest.mark.asyncio
async def test_store_change_rejects_ineligible_store():
    """store_change should reject stores that don't support curbside."""
    from texas_grocery_mcp.tools.store import store_change, store_search

    # Set up a store search result with an ineligible store
    stores = [
        Store(
            store_id="699",
            name="Nogalitos H-E-B",
            address="1601 NOGALITOS, SAN ANTONIO, TX 78204",
            distance_miles=0.83,
            supports_curbside=True,
        ),
        Store(
            store_id="718",
            name="South Flores Market H-E-B",
            address="516 S FLORES STREET, SAN ANTONIO, TX 78204",
            distance_miles=1.10,
            supports_curbside=False,  # Doesn't support curbside
        ),
    ]
    mock_result = _make_mock_store_search_result(stores=stores)

    with patch("texas_grocery_mcp.tools.store._get_client") as mock_get_client:
        mock_client = MagicMock()
        mock_client.search_stores = AsyncMock(return_value=mock_result)
        mock_get_client.return_value = mock_client

        # First search for stores to populate the cache
        await store_search(address="San Antonio, TX 78204")

    # Mock authentication (patch where it's used)
    with patch("texas_grocery_mcp.auth.session.is_authenticated", return_value=True):
        # Try to change to ineligible store
        result = await store_change(store_id="718")

        # Should return error about store not supporting curbside
        assert result.get("error") is True
        assert result.get("code") == "STORE_NOT_ELIGIBLE"
        message = result.get("message", "").lower()
        assert "curbside" in message or "online" in message
        # Should suggest an alternative
        assert "suggestion" in result or "nearest" in result.get("message", "").lower()


@pytest.mark.asyncio
async def test_store_change_accepts_eligible_store():
    """store_change should accept stores that support curbside."""
    from texas_grocery_mcp.tools.store import store_change, store_search

    # Set up a store search result with an eligible store
    stores = [
        Store(
            store_id="699",
            name="Nogalitos H-E-B",
            address="1601 NOGALITOS, SAN ANTONIO, TX 78204",
            distance_miles=0.83,
            supports_curbside=True,
        ),
    ]
    mock_result = _make_mock_store_search_result(stores=stores)

    with patch("texas_grocery_mcp.tools.store._get_client") as mock_get_client:
        mock_client = MagicMock()
        mock_client.search_stores = AsyncMock(return_value=mock_result)
        mock_client.select_store = AsyncMock(return_value={"success": True, "store_id": "699"})
        mock_get_client.return_value = mock_client

        # First search for stores to populate the cache
        await store_search(address="San Antonio, TX 78204")

        # Mock authentication (patch where it's used)
        with patch("texas_grocery_mcp.auth.session.is_authenticated", return_value=True):
            # Try to change to eligible store
            result = await store_change(store_id="699")

            # Should succeed
            assert result.get("success") is True or result.get("error") is not True
            assert result.get("store_id") == "699"


# ============================================================================
# Store Change Verification Tests
# ============================================================================


@pytest.mark.asyncio
async def test_store_change_verifies_success():
    """store_change should verify store actually changed via get_cart."""
    from texas_grocery_mcp.tools.store import store_change

    with patch("texas_grocery_mcp.tools.store._get_client") as mock_get_client:
        mock_client = MagicMock()
        # Mock select_store to return verified success
        mock_client.select_store = AsyncMock(return_value={
            "success": True,
            "store_id": "465",
            "verified": True,
        })
        mock_get_client.return_value = mock_client

        with patch("texas_grocery_mcp.auth.session.is_authenticated", return_value=True):
            result = await store_change(store_id="465")

            # Should call select_store with default ignore_conflicts=False
            mock_client.select_store.assert_called_once_with("465", ignore_conflicts=False)

            # Should succeed with verified flag
            assert result["success"] is True
            assert result["store_id"] == "465"
            assert result.get("verified") is True


@pytest.mark.asyncio
async def test_store_change_detects_cart_conflict():
    """store_change should detect and report cart conflicts."""
    from texas_grocery_mcp.tools.store import store_change

    with patch("texas_grocery_mcp.tools.store._get_client") as mock_get_client:
        mock_client = MagicMock()
        # Mock select_store to return cart conflict error
        mock_client.select_store = AsyncMock(return_value={
            "error": True,
            "code": "CART_CONFLICT",
            "message": "Store change not applied - cart has conflicts",
            "expected_store": "465",
            "actual_store": "737",
            "suggestion": "Try with ignore_conflicts=True",
        })
        mock_get_client.return_value = mock_client

        with patch("texas_grocery_mcp.auth.session.is_authenticated", return_value=True):
            result = await store_change(store_id="465")

            # Should return error with cart conflict code
            assert result["error"] is True
            assert result["code"] == "CART_CONFLICT"
            assert result["expected_store"] == "465"
            assert result["actual_store"] == "737"
            # Should include help text for cart conflicts
            assert "help" in result


@pytest.mark.asyncio
async def test_store_change_passes_ignore_conflicts():
    """store_change should pass ignore_conflicts parameter to API."""
    from texas_grocery_mcp.tools.store import store_change

    with patch("texas_grocery_mcp.tools.store._get_client") as mock_get_client:
        mock_client = MagicMock()
        mock_client.select_store = AsyncMock(return_value={
            "success": True,
            "store_id": "465",
            "verified": True,
        })
        mock_get_client.return_value = mock_client

        with patch("texas_grocery_mcp.auth.session.is_authenticated", return_value=True):
            await store_change(store_id="465", ignore_conflicts=True)

            # Should pass ignore_conflicts=True to select_store
            mock_client.select_store.assert_called_once_with("465", ignore_conflicts=True)


@pytest.mark.asyncio
async def test_store_change_unauthenticated_includes_how_to_sync():
    """store_change should guide unauthenticated users to log in."""
    from texas_grocery_mcp.tools.store import store_change

    with patch("texas_grocery_mcp.auth.session.is_authenticated", return_value=False):
        result = await store_change(store_id="737")

        assert result["success"] is True
        assert result["method"] == "local_only"
        # Should include guidance on how to sync
        assert "how_to_sync" in result
        assert "session_refresh" in result["how_to_sync"]


@pytest.mark.asyncio
async def test_store_change_does_not_update_cookie_on_failure():
    """store_change should NOT update cookie when verification fails."""
    from texas_grocery_mcp.tools.store import store_change

    # Set initial state
    StateManager.set_default_store_id_sync("737")  # Existing store

    with patch("texas_grocery_mcp.tools.store._get_client") as mock_get_client:
        mock_client = MagicMock()
        # Mock select_store to return verification failure
        mock_client.select_store = AsyncMock(return_value={
            "error": True,
            "code": "VERIFICATION_FAILED",
            "message": "Store change not applied",
            "expected_store": "465",
            "actual_store": "737",
        })
        mock_get_client.return_value = mock_client

        with (
            patch("texas_grocery_mcp.auth.session.is_authenticated", return_value=True),
            patch("texas_grocery_mcp.tools.store._update_store_cookie") as mock_update,
        ):
            result = await store_change(store_id="465")

            # Should NOT call _update_store_cookie on failure
            mock_update.assert_not_called()

            # Should return error
            assert result["error"] is True

            # Local default should NOT have changed
            assert StateManager.get_default_store_id() == "737"


@pytest.mark.asyncio
async def test_store_change_updates_cookie_on_verified_success():
    """store_change should update cookie only after verified success."""
    from texas_grocery_mcp.tools.store import store_change

    with patch("texas_grocery_mcp.tools.store._get_client") as mock_get_client:
        mock_client = MagicMock()
        mock_client.select_store = AsyncMock(return_value={
            "success": True,
            "store_id": "465",
            "verified": True,
        })
        mock_get_client.return_value = mock_client

        with (
            patch("texas_grocery_mcp.auth.session.is_authenticated", return_value=True),
            patch("texas_grocery_mcp.tools.store._update_store_cookie") as mock_update,
        ):
            result = await store_change(store_id="465")

            # Should call _update_store_cookie on success
            mock_update.assert_called_once_with("465")

            # Should return success
            assert result["success"] is True

            # Local default should have changed
            assert StateManager.get_default_store_id() == "465"
