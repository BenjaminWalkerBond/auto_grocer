"""Integration tests for product_get tool.

These tests hit the real HEB API and require:
1. An authenticated session (run session_refresh first)
2. Network access to heb.com

Run with: pytest tests/integration/ --run-integration
"""

import pytest

from texas_grocery_mcp.tools.product import product_get, product_search
from texas_grocery_mcp.tools.store import set_default_store_id

# Known stable product IDs for testing
OLIVE_OIL_ID = "127074"  # H-E-B Extra Virgin Olive Oil
BANANA_ID = "320228"  # Fresh Bunch of Organic Bananas
CLOROX_ID = "1904127"  # Clorox Disinfecting Wipes

# Known store ID
HEIGHTS_HEB_ID = "737"


@pytest.fixture(autouse=True)
def reset_tool_state():
    """Reset global state before each test to avoid client reuse issues."""
    from texas_grocery_mcp.tools import product as product_module
    from texas_grocery_mcp.tools import store as store_module

    # Reset graphql clients to avoid event loop issues
    store_module._default_store_id = None
    store_module._graphql_client = None
    product_module._graphql_client = None

    # Set default store
    set_default_store_id(HEIGHTS_HEB_ID)

    yield

    # Cleanup
    store_module._default_store_id = None
    store_module._graphql_client = None
    product_module._graphql_client = None


@pytest.mark.integration
@pytest.mark.asyncio
async def test_get_real_product_details_food():
    """Test fetching real product details for a food item (olive oil)."""
    result = await product_get(product_id=OLIVE_OIL_ID)

    # Should not be an error
    assert result.get("error") is not True, f"Unexpected error: {result}"

    # Basic fields should be present
    assert result["product_id"] == OLIVE_OIL_ID
    assert result["name"] is not None
    assert "olive oil" in result["name"].lower()
    assert result["sku"] is not None
    assert result["price"] > 0

    # Food item should have ingredients
    assert result.get("ingredients") is not None
    assert "olive oil" in result["ingredients"].lower()

    # Food item should have nutrition
    assert result.get("nutrition") is not None
    assert result["nutrition"].get("calories") is not None

    # Should have dietary attributes
    assert result.get("dietary_attributes") is not None


@pytest.mark.integration
@pytest.mark.asyncio
async def test_get_real_product_details_produce():
    """Test fetching real product details for produce (bananas)."""
    result = await product_get(product_id=BANANA_ID)

    # Should not be an error
    assert result.get("error") is not True, f"Unexpected error: {result}"

    # Basic fields should be present
    assert result["product_id"] == BANANA_ID
    assert result["name"] is not None
    assert "banana" in result["name"].lower()

    # Produce typically has no nutrition panel
    # (may be null or empty)

    # Should have dietary attributes (organic, vegan, etc.)
    assert result.get("dietary_attributes") is not None


@pytest.mark.integration
@pytest.mark.asyncio
async def test_get_real_product_details_non_food():
    """Test fetching real product details for non-food (cleaning product)."""
    result = await product_get(product_id=CLOROX_ID)

    # Should not be an error
    assert result.get("error") is not True, f"Unexpected error: {result}"

    # Basic fields should be present
    assert result["product_id"] == CLOROX_ID
    assert result["name"] is not None
    assert "clorox" in result["name"].lower() or "wipes" in result["name"].lower()

    # Non-food should have safety warnings
    assert result.get("safety_warning") is not None

    # Non-food should have instructions
    assert result.get("instructions") is not None


@pytest.mark.integration
@pytest.mark.asyncio
async def test_product_search_then_details():
    """Test full workflow: search for product then get details."""
    # Search for a product
    search_result = await product_search(query="heb whole milk gallon", limit=5)

    assert search_result.get("error") is not True, f"Search error: {search_result}"
    assert search_result["count"] > 0, "No products found in search"

    # Find a product with a valid product_id (not a suggestion)
    valid_product = None
    for p in search_result["products"]:
        pid = p.get("product_id")
        if pid and not str(pid).startswith("suggestion-"):
            valid_product = p
            break

    if not valid_product:
        pytest.skip("No products with valid product_id found (may be using typeahead fallback)")

    # Get details for the product
    product_id = valid_product["product_id"]
    details = await product_get(product_id=str(product_id))

    assert details.get("error") is not True, f"Details error: {details}"
    assert details["product_id"] == str(product_id)

    # Milk should have nutrition info
    assert details.get("nutrition") is not None, "Milk should have nutrition facts"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_product_get_invalid_id():
    """Test that invalid product ID returns proper error."""
    result = await product_get(product_id="99999999999")

    assert result.get("error") is True
    assert result["code"] == "PRODUCT_NOT_FOUND"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_product_details_include_cart_usage():
    """Test that product details include cart usage instructions."""
    result = await product_get(product_id=OLIVE_OIL_ID)

    assert result.get("error") is not True

    # Should have cart usage instructions
    assert "cart_usage" in result
    assert "instructions" in result["cart_usage"]
    assert "example" in result["cart_usage"]


@pytest.mark.integration
@pytest.mark.asyncio
async def test_product_details_include_metadata():
    """Test that product details include metadata."""
    result = await product_get(product_id=OLIVE_OIL_ID, store_id=HEIGHTS_HEB_ID)

    assert result.get("error") is not True

    # Should have metadata
    assert "_meta" in result
    assert result["_meta"]["store_id"] == HEIGHTS_HEB_ID


@pytest.mark.integration
@pytest.mark.asyncio
async def test_product_details_nutrition_structure():
    """Test that nutrition facts have correct nested structure."""
    result = await product_get(product_id=OLIVE_OIL_ID)

    assert result.get("error") is not True
    assert result.get("nutrition") is not None

    nutrition = result["nutrition"]

    # Check structure
    assert "serving_size" in nutrition
    assert "calories" in nutrition
    assert "nutrients" in nutrition

    # Check that nutrients is a list
    assert isinstance(nutrition["nutrients"], list)

    # Check for nested sub_items if present (like Saturated Fat under Total Fat)
    for nutrient in nutrition["nutrients"]:
        assert "title" in nutrient
        assert "unit" in nutrient
        # sub_items may or may not be present
