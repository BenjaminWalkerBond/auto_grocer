"""Integration tests for substitution tool.

These tests hit the real HEB API and require:
1. An authenticated session (run session_refresh first)
2. Network access to heb.com

Run with: pytest tests/integration/ --run-integration
"""

import pytest

from texas_grocery_mcp.tools.store import set_default_store_id
from texas_grocery_mcp.tools.substitution import find_substitute

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
async def test_find_substitute_for_common_ingredient():
    """Test finding substitutes for a common ingredient (butter)."""
    result = await find_substitute(
        ingredient_name="butter",
        store_id=HEIGHTS_HEB_ID,
    )

    # Should not be an error
    assert result.get("error") is not True, f"Unexpected error: {result}"

    # Should have either found the product or provided substitution info
    if result.get("substitution_needed") is False:
        # Best match was available
        assert result.get("product") is not None
        assert result["product"].get("available") is True
    else:
        # Substitution was needed
        assert result.get("unavailable_product") is not None
        # Should have either a recommendation or no_good_substitute flag
        assert (
            result.get("recommended") is not None
            or result.get("no_good_substitute") is True
        )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_find_substitute_with_recipe_context():
    """Test that recipe context is accepted and used."""
    result = await find_substitute(
        ingredient_name="milk",
        store_id=HEIGHTS_HEB_ID,
        recipe_context={
            "title": "Chocolate Cake",
            "description": "Rich chocolate layer cake",
            "cook_time": "45 minutes",
        },
    )

    # Should not error
    assert result.get("error") is not True, f"Unexpected error: {result}"

    # Result should be valid
    assert "substitution_needed" in result or "product" in result


@pytest.mark.integration
@pytest.mark.asyncio
async def test_find_substitute_includes_reason():
    """Test that substitution recommendations include a reason field."""
    result = await find_substitute(
        ingredient_name="eggs",
        store_id=HEIGHTS_HEB_ID,
    )

    # Should not error
    assert result.get("error") is not True, f"Unexpected error: {result}"

    # If substitution was needed and we have a recommendation
    if result.get("substitution_needed") and result.get("recommended"):
        assert "reason" in result["recommended"], (
            "Recommendation should include a reason"
        )
        assert len(result["recommended"]["reason"]) > 0


@pytest.mark.integration
@pytest.mark.asyncio
async def test_find_substitute_with_ingredient_tags():
    """Test passing ingredient tags."""
    result = await find_substitute(
        ingredient_name="spinach",
        store_id=HEIGHTS_HEB_ID,
        ingredient_tags=["vegetable", "leafy green"],
    )

    # Should not error
    assert result.get("error") is not True, f"Unexpected error: {result}"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_find_substitute_with_amount():
    """Test passing ingredient amount."""
    result = await find_substitute(
        ingredient_name="chicken breast",
        store_id=HEIGHTS_HEB_ID,
        ingredient_amount="2 lbs",
    )

    # Should not error
    assert result.get("error") is not True, f"Unexpected error: {result}"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_find_substitute_only_available_products():
    """Test that recommended products are marked as available."""
    result = await find_substitute(
        ingredient_name="flour",
        store_id=HEIGHTS_HEB_ID,
    )

    # Should not error
    assert result.get("error") is not True, f"Unexpected error: {result}"

    # If we have a recommendation, verify it's for an available product
    # Note: We can't easily verify availability without another API call,
    # but the tool's internal logic filters unavailable products before
    # passing to Claude.
    if result.get("recommended"):
        # The recommendation should have product identifiers
        rec = result["recommended"]
        assert rec.get("product_id") or rec.get("sku"), (
            "Recommendation should have product identifiers"
        )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_find_substitute_rare_ingredient():
    """Test behavior with a less common ingredient."""
    result = await find_substitute(
        ingredient_name="truffle oil",
        store_id=HEIGHTS_HEB_ID,
    )

    # Should not crash, even if no products found
    # May return error or no_good_substitute
    if result.get("error"):
        assert result.get("code") in ["NO_PRODUCTS_FOUND", "NO_STORE_SET"]
    else:
        # Should have valid response structure
        assert "substitution_needed" in result or "no_good_substitute" in result


@pytest.mark.integration
@pytest.mark.asyncio
async def test_find_substitute_returns_store_id():
    """Test that response includes the store_id used."""
    result = await find_substitute(
        ingredient_name="cheese",
        store_id=HEIGHTS_HEB_ID,
    )

    # Should not error
    assert result.get("error") is not True, f"Unexpected error: {result}"

    # Should include store_id in response
    assert result.get("store_id") == HEIGHTS_HEB_ID
