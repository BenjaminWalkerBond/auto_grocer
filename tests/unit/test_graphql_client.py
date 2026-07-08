"""Tests for HEB GraphQL client."""

import pytest
import respx
from httpx import Response

from texas_grocery_mcp.clients.graphql import (
    KNOWN_STORES,
    PERSISTED_QUERIES,
    GraphQLError,
    HEBGraphQLClient,
)


@pytest.fixture
def client():
    """Create test client."""
    return HEBGraphQLClient()


@pytest.mark.asyncio
@respx.mock
async def test_search_stores_returns_result_with_geocoding(client):
    """Should return StoreSearchResult with geocoding info."""
    # Mock the geocoding service
    from unittest.mock import AsyncMock, patch

    from texas_grocery_mcp.services.geocoding import GeocodingResult

    mock_geocoding_result = GeocodingResult(
        latitude=30.2672,
        longitude=-97.7431,
        city="Austin",
        state="TX",
        postcode="78701",
        display_name="Austin, TX, USA",
    )

    # Mock HEB store search API response
    mock_store_response = {
        "data": {
            "storeSearch": {
                "stores": [
                    {
                        "id": "100",
                        "name": "Austin H-E-B",
                        "address1": "123 Congress Ave",
                        "city": "Austin",
                        "state": "TX",
                        "postalCode": "78701",
                        "phone": "(512) 555-0100",
                        "latitude": 30.27,
                        "longitude": -97.74,
                    }
                ]
            }
        }
    }

    respx.post("https://www.heb.com/graphql").mock(
        return_value=Response(200, json=mock_store_response)
    )

    with patch("texas_grocery_mcp.clients.graphql.GeocodingService") as mock_geo_class:
        mock_geo_service = AsyncMock()
        mock_geo_service.geocode = AsyncMock(return_value=mock_geocoding_result)
        mock_geo_service.close = AsyncMock()
        mock_geo_class.return_value = mock_geo_service

        result = await client.search_stores(address="Austin, TX", radius_miles=10)

        # Should return StoreSearchResult
        assert result.count == 1
        assert len(result.stores) == 1
        assert result.stores[0].store_id == "100"
        assert result.stores[0].name == "Austin H-E-B"

        # Should include geocoded info
        assert result.geocoded is not None
        assert result.geocoded.latitude == 30.2672
        assert result.geocoded.display_name == "Austin, TX, USA"

        # Should include attempts
        assert len(result.attempts) >= 1


@pytest.mark.asyncio
@respx.mock
async def test_typeahead_success(client):
    """Should parse typeahead response."""
    mock_response = {
        "data": {
            "typeaheadContent": {
                "verticalStack": [
                    {
                        "terms": ["Milk", "Milk 2%", "Whole milk"],
                        "__typename": "TypeaheadTypingSuggestedSearches",
                    }
                ],
                "__typename": "TypeaheadContentResponse",
            }
        }
    }

    respx.post("https://www.heb.com/graphql").mock(
        return_value=Response(200, json=mock_response)
    )

    suggestions = await client.get_typeahead("milk")

    assert len(suggestions) == 3
    assert "Milk" in suggestions
    assert "Milk 2%" in suggestions


@pytest.mark.asyncio
@respx.mock
async def test_search_products_uses_typeahead(client, monkeypatch):
    """Should use typeahead for product search."""
    # Mock as not authenticated to force typeahead fallback
    monkeypatch.setattr(
        "texas_grocery_mcp.clients.graphql.is_authenticated",
        lambda: False,
    )

    mock_response = {
        "data": {
            "typeaheadContent": {
                "verticalStack": [
                    {
                        "terms": ["Milk", "Milk 2%"],
                        "__typename": "TypeaheadTypingSuggestedSearches",
                    }
                ],
                "__typename": "TypeaheadContentResponse",
            }
        }
    }

    respx.post("https://www.heb.com/graphql").mock(
        return_value=Response(200, json=mock_response)
    )

    result = await client.search_products(query="milk", store_id="590")

    # Products are created from typeahead suggestions
    assert result.count == 2
    assert result.products[0].name == "Milk"
    assert result.products[0].price == 0.0  # Price not available from typeahead
    assert result.data_source == "typeahead_suggestions"
    assert result.authenticated is False


@pytest.mark.asyncio
@respx.mock
async def test_get_categories_success(client):
    """Should parse shop navigation response."""
    mock_response = {
        "data": {
            "shopNavigation": [
                {
                    "id": "490020",
                    "displayName": "Fruit & vegetables",
                    "href": "/category/shop/fruit-vegetables/2863/490020",
                    "subCategories": [
                        {"id": "sub1", "displayName": "Fresh Fruit"},
                    ],
                }
            ]
        }
    }

    respx.post("https://www.heb.com/graphql").mock(
        return_value=Response(200, json=mock_response)
    )

    categories = await client.get_categories()

    assert len(categories) == 1
    assert categories[0]["name"] == "Fruit & vegetables"
    assert len(categories[0]["subcategories"]) == 1


@pytest.mark.asyncio
@respx.mock
async def test_handles_graphql_error(client):
    """Should raise on GraphQL errors in persisted queries."""
    mock_response = {
        "errors": [{"message": "Invalid query"}],
        "data": None,
    }

    respx.post("https://www.heb.com/graphql").mock(
        return_value=Response(200, json=mock_response)
    )

    # Test the underlying method directly (get_typeahead catches errors)
    with pytest.raises(GraphQLError, match="Invalid query"):
        await client._execute_persisted_query(
            "typeaheadContent",
            {"term": "test", "searchMode": "MAIN_SEARCH"},
        )


@pytest.mark.asyncio
@respx.mock
async def test_persisted_query_not_found_error(client):
    """Should raise PersistedQueryNotFoundError when hash is invalid."""
    mock_response = {
        "errors": [
            {
                "message": "PersistedQueryNotFound",
                "extensions": {"code": "PERSISTED_QUERY_NOT_FOUND"},
            }
        ],
        "data": None,
    }

    respx.post("https://www.heb.com/graphql").mock(
        return_value=Response(200, json=mock_response)
    )

    from texas_grocery_mcp.clients.graphql import PersistedQueryNotFoundError

    # Test the underlying method directly
    with pytest.raises(PersistedQueryNotFoundError):
        await client._execute_persisted_query(
            "typeaheadContent",
            {"term": "test", "searchMode": "MAIN_SEARCH"},
        )


def test_known_stores_exist():
    """Should have known stores configured."""
    assert len(KNOWN_STORES) >= 1
    for store_id, store in KNOWN_STORES.items():
        assert store.store_id == store_id
        assert store.name is not None
        assert store.address is not None


def test_persisted_queries_exist():
    """Should have persisted query hashes configured."""
    expected_queries = ["ShopNavigation", "typeaheadContent", "cartEstimated"]
    for query in expected_queries:
        assert query in PERSISTED_QUERIES
        assert len(PERSISTED_QUERIES[query]) == 64  # SHA-256 is 64 hex chars


def test_client_has_throttlers():
    """Should initialize with SSR and GraphQL throttlers."""
    client = HEBGraphQLClient()

    # Should have SSR throttler
    assert hasattr(client, "_ssr_throttler")
    assert client._ssr_throttler is not None
    assert client._ssr_throttler.config.max_concurrent == 3  # default

    # Should have GraphQL throttler
    assert hasattr(client, "_graphql_throttler")
    assert client._graphql_throttler is not None
    assert client._graphql_throttler.config.max_concurrent == 5  # default


def test_client_throttlers_use_settings(monkeypatch):
    """Should configure throttlers from settings."""
    # Set environment variables FIRST
    monkeypatch.setenv("MAX_CONCURRENT_SSR_SEARCHES", "7")
    monkeypatch.setenv("MAX_CONCURRENT_GRAPHQL", "10")
    monkeypatch.setenv("THROTTLING_ENABLED", "false")

    # Then reload config module to pick up new env vars
    import importlib

    import texas_grocery_mcp.utils.config as config_module
    importlib.reload(config_module)

    # Also reload the graphql module so it uses fresh settings
    import texas_grocery_mcp.clients.graphql as graphql_module
    importlib.reload(graphql_module)

    try:
        client = graphql_module.HEBGraphQLClient()

        assert client._ssr_throttler.config.max_concurrent == 7
        assert client._graphql_throttler.config.max_concurrent == 10
        assert client._ssr_throttler.config.enabled is False
        assert client._graphql_throttler.config.enabled is False
    finally:
        # Restore modules to original state
        importlib.reload(config_module)
        importlib.reload(graphql_module)


def test_parse_store_result_with_curbside_support():
    """Should parse storeFulfillments and set supports_curbside=True."""
    client = HEBGraphQLClient()

    # Store with curbside/pickup fulfillment (actual API format)
    store_result = {
        "distanceMiles": 0.83,
        "store": {
            "storeNumber": 699,
            "name": "Nogalitos H-E-B",
            "address": {
                "streetAddress": "1601 NOGALITOS",
                "locality": "SAN ANTONIO",
                "region": "TX",
                "postalCode": "78204-2427",
            },
            "latitude": 29.3978,
            "longitude": -98.5150,
            "storeFulfillments": [
                {"name": "ALCOHOL_DELIVERY", "__typename": "FulfillmentChannel"},
                {"name": "CURBSIDE_DELIVERY", "__typename": "FulfillmentChannel"},
                {"name": "CURBSIDE_PICKUP", "__typename": "FulfillmentChannel"},
                {"name": "PICK_UP_IN_STORE", "__typename": "FulfillmentChannel"},
            ],
        },
    }

    store = client._parse_store_result(store_result)

    assert store is not None
    assert store.store_id == "699"
    assert store.supports_curbside is True
    assert store.supports_delivery is True  # ALCOHOL_DELIVERY counts


def test_parse_store_result_without_curbside_support():
    """Should set supports_curbside=False when store is in-store only."""
    client = HEBGraphQLClient()

    # Store without curbside (in-store only) - actual API format
    store_result = {
        "distanceMiles": 1.1,
        "store": {
            "storeNumber": 718,
            "name": "South Flores Market H-E-B",
            "address": {
                "streetAddress": "516 S FLORES STREET",
                "locality": "SAN ANTONIO",
                "region": "TX",
                "postalCode": "78204-1217",
            },
            "latitude": 29.4195,
            "longitude": -98.4939,
            "storeFulfillments": [
                {"name": "PICK_UP_IN_STORE", "__typename": "FulfillmentChannel"},
            ],
        },
    }

    store = client._parse_store_result(store_result)

    assert store is not None
    assert store.store_id == "718"
    assert store.supports_curbside is False
    assert store.supports_delivery is False


def test_parse_store_result_missing_fulfillment_defaults_true():
    """Should default supports_curbside=True when fulfillmentChannels missing."""
    client = HEBGraphQLClient()

    # Store without fulfillmentChannels field (legacy API response)
    store_result = {
        "distanceMiles": 2.5,
        "store": {
            "storeNumber": "737",
            "name": "The Heights H-E-B",
            "address": {
                "streetAddress": "2300 N. SHEPHERD DR.",
                "locality": "HOUSTON",
                "region": "TX",
                "postalCode": "77008",
            },
            "latitude": 29.8028,
            "longitude": -95.4103,
            # No fulfillmentChannels field
        },
    }

    store = client._parse_store_result(store_result)

    assert store is not None
    # Default to True when field is missing (most stores support curbside)
    assert store.supports_curbside is True
    assert store.supports_delivery is False  # Delivery still defaults False


@pytest.mark.asyncio
@respx.mock
async def test_select_store_verifies_actual_change():
    """select_store should verify the store actually changed via get_cart."""
    client = HEBGraphQLClient()

    from unittest.mock import AsyncMock, MagicMock, patch

    # Mock the mutation response (empty but not error)
    mock_mutation_response = {
        "data": {
            "selectPickupFulfillment": {}
        }
    }

    # Mock the cart response that shows the store actually changed
    mock_cart_response = {
        "data": {
            "cartV2": {
                "fulfillment": {
                    "store": {
                        "id": "699"
                    }
                }
            }
        }
    }

    with patch.object(client, "_get_authenticated_client") as mock_get_auth:
        mock_auth_client = MagicMock()

        # Track which call we're on (mutation vs cart)
        call_count = [0]

        def mock_post(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                # First call is the mutation
                return MagicMock(
                    json=MagicMock(return_value=mock_mutation_response),
                    raise_for_status=MagicMock(),
                )
            else:
                # Second call is get_cart for verification
                return MagicMock(
                    json=MagicMock(return_value=mock_cart_response),
                    raise_for_status=MagicMock(),
                )

        mock_auth_client.post = AsyncMock(side_effect=mock_post)
        mock_get_auth.return_value = mock_auth_client

        result = await client.select_store("699")

        # Should report success=True when verified
        assert result.get("success") is True
        assert result.get("store_id") == "699"
        assert result.get("verified") is True


@pytest.mark.asyncio
@respx.mock
async def test_select_store_detects_verification_failure():
    """select_store should detect when store didn't actually change."""
    client = HEBGraphQLClient()

    from unittest.mock import AsyncMock, MagicMock, patch

    # Mock the mutation response (appears successful)
    mock_mutation_response = {
        "data": {
            "selectPickupFulfillment": {}
        }
    }

    # Mock the cart response showing store DIDN'T change (cart conflict scenario)
    mock_cart_response = {
        "data": {
            "cartV2": {
                "fulfillment": {
                    "store": {
                        "id": "737"  # Different store - change didn't happen
                    }
                }
            }
        }
    }

    with patch.object(client, "_get_authenticated_client") as mock_get_auth:
        mock_auth_client = MagicMock()

        call_count = [0]

        def mock_post(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                return MagicMock(
                    json=MagicMock(return_value=mock_mutation_response),
                    raise_for_status=MagicMock(),
                )
            else:
                return MagicMock(
                    json=MagicMock(return_value=mock_cart_response),
                    raise_for_status=MagicMock(),
                )

        mock_auth_client.post = AsyncMock(side_effect=mock_post)
        mock_get_auth.return_value = mock_auth_client

        result = await client.select_store("699")

        # Should report error because verification failed
        assert result.get("error") is True
        assert result.get("code") == "CART_CONFLICT"
        assert result.get("expected_store") == "699"
        assert result.get("actual_store") == "737"


@pytest.mark.asyncio
@respx.mock
async def test_select_store_reports_error_on_graphql_error():
    """select_store should report error when GraphQL returns errors."""
    client = HEBGraphQLClient()

    from unittest.mock import AsyncMock, MagicMock, patch

    from texas_grocery_mcp.clients.graphql import GraphQLError

    with patch.object(client, "_get_authenticated_client") as mock_get_auth:
        mock_auth_client = MagicMock()

        # Simulate GraphQL error being raised
        async def raise_graphql_error(*args, **kwargs):
            raise GraphQLError([{"message": "Store not found"}])

        mock_auth_client.post = AsyncMock(side_effect=raise_graphql_error)
        mock_get_auth.return_value = mock_auth_client

        # Use a valid numeric store_id to avoid INVALID_STORE_ID error
        result = await client.select_store("999")

        # Should report error
        assert result.get("error") is True
        assert result.get("code") == "STORE_CHANGE_FAILED"


@pytest.mark.asyncio
async def test_select_store_handles_invalid_store_id():
    """select_store should handle non-numeric store IDs gracefully."""
    client = HEBGraphQLClient()

    from unittest.mock import MagicMock, patch

    with patch.object(client, "_get_authenticated_client") as mock_get_auth:
        mock_auth_client = MagicMock()
        mock_get_auth.return_value = mock_auth_client

        result = await client.select_store("invalid_id")

        # Should report INVALID_STORE_ID error
        assert result.get("error") is True
        assert result.get("code") == "INVALID_STORE_ID"
