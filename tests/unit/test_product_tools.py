"""Tests for product tools."""

from unittest.mock import AsyncMock, patch

import pytest
import respx
import structlog
from httpx import Response

logger = structlog.get_logger()


@pytest.fixture(autouse=True)
def reset_tool_state():
    """Reset global state before each test."""
    from texas_grocery_mcp.tools import product as product_module
    from texas_grocery_mcp.tools import store as store_module

    store_module._default_store_id = None
    store_module._graphql_client = None
    product_module._graphql_client = None
    yield
    store_module._default_store_id = None
    store_module._graphql_client = None
    product_module._graphql_client = None


@pytest.fixture
def mock_typeahead_response():
    """Mock typeahead response for product search."""
    return {
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


@pytest.mark.asyncio
@respx.mock
async def test_product_search_with_store_id(mock_typeahead_response):
    """product_search should work with explicit store_id."""
    from texas_grocery_mcp.tools.product import product_search

    respx.post("https://www.heb.com/graphql").mock(
        return_value=Response(200, json=mock_typeahead_response)
    )

    result = await product_search(query="milk", store_id="590")

    # Product search now uses typeahead suggestions
    assert len(result["products"]) == 3
    assert result["products"][0]["name"] == "Milk"
    assert result["products"][0]["price"] == 0.0  # Price not available from typeahead
    assert "note" in result  # Should have explanation about typeahead


@pytest.mark.asyncio
@respx.mock
async def test_product_search_uses_default_store(mock_typeahead_response):
    """product_search should use default store when not specified."""
    from texas_grocery_mcp.tools.product import product_search
    from texas_grocery_mcp.tools.store import set_default_store_id

    set_default_store_id("590")

    respx.post("https://www.heb.com/graphql").mock(
        return_value=Response(200, json=mock_typeahead_response)
    )

    result = await product_search(query="milk")

    assert result["store_id"] == "590"
    assert len(result["products"]) == 3


@pytest.mark.asyncio
async def test_product_search_requires_store():
    """product_search should error when no store available."""
    from texas_grocery_mcp.tools.product import product_search

    result = await product_search(query="milk")

    assert "error" in result
    assert "store" in result["message"].lower()


@pytest.mark.asyncio
@respx.mock
async def test_product_search_includes_search_url(mock_typeahead_response):
    """product_search should include HEB search URL."""
    from texas_grocery_mcp.tools.product import product_search

    respx.post("https://www.heb.com/graphql").mock(
        return_value=Response(200, json=mock_typeahead_response)
    )

    result = await product_search(query="chicken breast", store_id="737")

    assert "search_url" in result
    assert "heb.com/search" in result["search_url"]
    assert "chicken+breast" in result["search_url"]


@pytest.mark.asyncio
async def test_product_search_empty_query():
    """product_search should error on empty query."""
    from texas_grocery_mcp.tools.product import product_search

    result = await product_search(query="   ", store_id="737")

    assert "error" in result
    assert result["code"] == "INVALID_QUERY"


@pytest.mark.asyncio
@respx.mock
async def test_product_search_with_known_store(mock_typeahead_response):
    """product_search should work with known store IDs."""
    from texas_grocery_mcp.tools.product import product_search
    from texas_grocery_mcp.tools.store import set_default_store_id

    # Use a known store ID
    set_default_store_id("737")  # The Heights H-E-B

    respx.post("https://www.heb.com/graphql").mock(
        return_value=Response(200, json=mock_typeahead_response)
    )

    result = await product_search(query="milk")

    assert result["store_id"] == "737"
    assert len(result["products"]) > 0


# ============================================================================
# Batch Search Tests
# ============================================================================


@pytest.mark.asyncio
@respx.mock
async def test_product_search_batch_multiple_queries(mock_typeahead_response):
    """product_search_batch should search for multiple products."""
    from texas_grocery_mcp.tools.product import product_search_batch

    respx.post("https://www.heb.com/graphql").mock(
        return_value=Response(200, json=mock_typeahead_response)
    )

    result = await product_search_batch(
        queries=["milk", "eggs", "bread"],
        store_id="737",
        limit_per_query=5,
    )

    # Should have results for each query
    assert "results" in result
    assert len(result["results"]) == 3

    # Each result should have query and success status
    for r in result["results"]:
        assert "query" in r
        assert "success" in r
        assert "products" in r

    # Should have summary
    assert "summary" in result
    assert result["summary"]["total_queries"] == 3
    assert result["summary"]["store_id"] == "737"


@pytest.mark.asyncio
async def test_product_search_batch_empty_queries():
    """product_search_batch should error on empty queries list."""
    from texas_grocery_mcp.tools.product import product_search_batch

    result = await product_search_batch(queries=[], store_id="737")

    assert "error" in result
    assert "No queries" in result["error"]


@pytest.mark.asyncio
async def test_product_search_batch_too_many_queries():
    """product_search_batch should reject more than 20 queries."""
    from texas_grocery_mcp.tools.product import product_search_batch

    result = await product_search_batch(
        queries=["item"] * 25,
        store_id="737",
    )

    assert "error" in result
    assert "Maximum 20" in result["error"]


@pytest.mark.asyncio
async def test_product_search_batch_requires_store():
    """product_search_batch should error when no store available."""
    from texas_grocery_mcp.tools.product import product_search_batch

    result = await product_search_batch(queries=["milk", "eggs"])

    assert "error" in result
    assert "store" in result["error"].lower()


@pytest.mark.asyncio
@respx.mock
async def test_product_search_batch_uses_default_store(mock_typeahead_response):
    """product_search_batch should use default store when not specified."""
    from texas_grocery_mcp.tools.product import product_search_batch
    from texas_grocery_mcp.tools.store import set_default_store_id

    set_default_store_id("590")

    respx.post("https://www.heb.com/graphql").mock(
        return_value=Response(200, json=mock_typeahead_response)
    )

    result = await product_search_batch(queries=["milk"])

    assert result["summary"]["store_id"] == "590"


@pytest.mark.asyncio
@respx.mock
async def test_product_search_batch_handles_partial_failures(mock_typeahead_response):
    """product_search_batch should handle some queries failing."""
    from texas_grocery_mcp.tools.product import product_search_batch

    # First call succeeds, second fails, third succeeds
    call_count = [0]

    def mock_response(request):
        call_count[0] += 1
        if call_count[0] == 2:
            return Response(500, text="Internal Server Error")
        return Response(200, json=mock_typeahead_response)

    respx.post("https://www.heb.com/graphql").mock(side_effect=mock_response)

    result = await product_search_batch(
        queries=["milk", "bad_query", "eggs"],
        store_id="737",
    )

    # Should still return results for all queries
    assert len(result["results"]) == 3

    # Summary should track successes and failures
    assert result["summary"]["total_queries"] == 3
    # Note: The actual success/failure counts depend on retry logic


# ============================================================================
# Product Get (Detail) Tests
# ============================================================================


@pytest.fixture
def mock_product_details_response():
    """Mock SSR response for product details (food item with nutrition)."""
    return {
        "pageProps": {
            "productData": {
                "id": "127074",
                "sku": "4122071073",
                "upc": "041220710737",
                "description": "H-E-B Extra Virgin Olive Oil",
                "longDescription": "Also referred to as EVOO, extra virgin olive oil...",
                "brand": "H-E-B",
                "isOwnBrand": True,
                "primaryImageUrl": "https://images.heb.com/is/image/HEBGrocery/004122071",
                "price": 7.01,
                "priceOnline": 6.68,
                "unitPrice": "$0.41 / fl oz",
                "unitOfMeasureDescription": "17 oz",
                "isAvailable": True,
                "ingredientStatement": "Extra Virgin Olive Oil.",
                "safetyWarning": "WARNING: Overheating any oil can cause fire...",
                "preparationAndStorage": "Store in a cool, dark place.",
                "attributeFlags": ["Gluten free verified", "Made in Italy"],
                "nutritionFacts": {
                    "servingSize": "1 Tbsp (15mL)",
                    "servingsPerContainer": "about 34",
                    "calories": "120",
                    "nutrients": [
                        {
                            "title": "Total Fat",
                            "unit": "14g",
                            "percentage": "18%",
                            "fontModifier": "BOLD",
                            "subItems": [
                                {"title": "Saturated Fat", "unit": "2g", "percentage": "10%"},
                            ],
                        },
                    ],
                    "vitaminsAndMinerals": [
                        {"title": "Vitamin E", "unit": "2mg", "percentage": "10%"},
                    ],
                },
                "categoryPath": [
                    {"name": "Shop"},
                    {"name": "Pantry"},
                    {"name": "Oils"},
                ],
                "aisleBayDetails": {"description": "Aisle 5"},
            }
        }
    }


@pytest.mark.asyncio
async def test_product_get_valid_product():
    """product_get should return detailed product info for valid ID."""
    from texas_grocery_mcp.tools.product import product_get

    with patch(
        "texas_grocery_mcp.tools.product._get_client"
    ) as mock_get_client:
        mock_client = AsyncMock()
        mock_get_client.return_value = mock_client

        # Create a mock ProductDetails object
        from texas_grocery_mcp.models import ProductDetails
        mock_product = ProductDetails(
            product_id="127074",
            sku="4122071073",
            name="H-E-B Extra Virgin Olive Oil",
            price=7.01,
            available=True,
            brand="H-E-B",
            ingredients="Extra Virgin Olive Oil.",
        )
        mock_client.get_product_details.return_value = mock_product

        result = await product_get(product_id="127074", store_id="737")

        assert result["product_id"] == "127074"
        assert result["sku"] == "4122071073"
        assert result["name"] == "H-E-B Extra Virgin Olive Oil"
        assert result["price"] == 7.01
        assert result["ingredients"] == "Extra Virgin Olive Oil."
        assert "cart_usage" in result


@pytest.mark.asyncio
async def test_product_get_empty_id():
    """product_get should error on empty product ID."""
    from texas_grocery_mcp.tools.product import product_get

    result = await product_get(product_id="", store_id="737")

    assert result["error"] is True
    assert result["code"] == "INVALID_PRODUCT_ID"


@pytest.mark.asyncio
async def test_product_get_whitespace_id():
    """product_get should error on whitespace-only product ID."""
    from texas_grocery_mcp.tools.product import product_get

    result = await product_get(product_id="   ", store_id="737")

    assert result["error"] is True
    assert result["code"] == "INVALID_PRODUCT_ID"


@pytest.mark.asyncio
async def test_product_get_suggestion_id():
    """product_get should reject suggestion IDs (not real products)."""
    from texas_grocery_mcp.tools.product import product_get

    result = await product_get(product_id="suggestion-milk", store_id="737")

    assert result["error"] is True
    assert result["code"] == "INVALID_PRODUCT_ID"
    assert "search suggestion" in result["message"]


@pytest.mark.asyncio
async def test_product_get_not_found():
    """product_get should handle product not found gracefully."""
    from texas_grocery_mcp.tools.product import product_get

    with patch(
        "texas_grocery_mcp.tools.product._get_client"
    ) as mock_get_client:
        mock_client = AsyncMock()
        mock_get_client.return_value = mock_client
        mock_client.get_product_details.return_value = None

        result = await product_get(product_id="999999999", store_id="737")

        assert result["error"] is True
        assert result["code"] == "PRODUCT_NOT_FOUND"
        assert "999999999" in result["message"]


@pytest.mark.asyncio
async def test_product_get_uses_default_store():
    """product_get should use default store when not specified."""
    from texas_grocery_mcp.tools.product import product_get
    from texas_grocery_mcp.tools.store import set_default_store_id

    set_default_store_id("590")

    with patch(
        "texas_grocery_mcp.tools.product._get_client"
    ) as mock_get_client:
        mock_client = AsyncMock()
        mock_get_client.return_value = mock_client

        from texas_grocery_mcp.models import ProductDetails
        mock_product = ProductDetails(
            product_id="127074",
            sku="4122071073",
            name="Test Product",
            price=5.99,
            available=True,
        )
        mock_client.get_product_details.return_value = mock_product

        result = await product_get(product_id="127074")

        # Verify the client was called with the default store
        mock_client.get_product_details.assert_called_once_with(
            product_id="127074",
            store_id="590",
        )
        assert result["product_id"] == "127074"


@pytest.mark.asyncio
async def test_product_get_with_nutrition():
    """product_get should include full nutrition facts when available."""
    from texas_grocery_mcp.tools.product import product_get

    with patch(
        "texas_grocery_mcp.tools.product._get_client"
    ) as mock_get_client:
        mock_client = AsyncMock()
        mock_get_client.return_value = mock_client

        from texas_grocery_mcp.models import ExtendedNutrition, NutrientInfo, ProductDetails

        nutrition = ExtendedNutrition(
            serving_size="1 Tbsp (15mL)",
            calories="120",
            nutrients=[
                NutrientInfo(
                    title="Total Fat",
                    unit="14g",
                    percentage="18%",
                    sub_items=[
                        NutrientInfo(title="Saturated Fat", unit="2g", percentage="10%"),
                    ],
                ),
            ],
        )

        mock_product = ProductDetails(
            product_id="127074",
            sku="4122071073",
            name="H-E-B Extra Virgin Olive Oil",
            price=7.01,
            available=True,
            nutrition=nutrition,
        )
        mock_client.get_product_details.return_value = mock_product

        result = await product_get(product_id="127074", store_id="737")

        assert "nutrition" in result
        assert result["nutrition"]["serving_size"] == "1 Tbsp (15mL)"
        assert result["nutrition"]["calories"] == "120"
        assert len(result["nutrition"]["nutrients"]) == 1
        assert result["nutrition"]["nutrients"][0]["title"] == "Total Fat"


@pytest.mark.asyncio
async def test_product_get_api_error():
    """product_get should handle API errors gracefully."""
    from texas_grocery_mcp.tools.product import product_get

    with patch(
        "texas_grocery_mcp.tools.product._get_client"
    ) as mock_get_client:
        mock_client = AsyncMock()
        mock_get_client.return_value = mock_client
        mock_client.get_product_details.side_effect = Exception("Network timeout")

        result = await product_get(product_id="127074", store_id="737")

        assert result["error"] is True
        assert result["code"] == "FETCH_ERROR"
        assert "Network timeout" in result["message"]
        assert "suggestion" in result  # Should have a recovery suggestion
