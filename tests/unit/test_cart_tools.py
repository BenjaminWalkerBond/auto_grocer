"""Tests for cart tools."""

from unittest.mock import patch

import pytest


@pytest.fixture(autouse=True)
def reset_auth_state():
    """Reset auth state before each test."""
    from texas_grocery_mcp.auth.session import _reset_auth_state
    _reset_auth_state()
    yield
    _reset_auth_state()


@pytest.mark.asyncio
async def test_cart_add_without_confirm_returns_preview():
    """cart_add without confirm should return preview."""
    from texas_grocery_mcp.tools.cart import cart_add

    with patch("texas_grocery_mcp.tools.cart.is_authenticated", return_value=True):
        result = await cart_add(product_id="123456", quantity=2)

    assert result["preview"] is True
    assert result["action"] == "add_to_cart"
    assert "confirm" in result["message"].lower()


@pytest.mark.asyncio
async def test_cart_add_requires_auth():
    """cart_add should require authentication."""
    from texas_grocery_mcp.tools.cart import cart_add

    with patch("texas_grocery_mcp.tools.cart.is_authenticated", return_value=False):
        result = await cart_add(product_id="123456", quantity=1)

    assert result["auth_required"] is True
    assert "instructions" in result


def test_cart_check_auth_returns_status():
    """cart_check_auth should return auth status."""
    from texas_grocery_mcp.tools.cart import cart_check_auth

    # check_auth internally calls is_authenticated via auth.session
    with patch("texas_grocery_mcp.auth.session.is_authenticated", return_value=False):
        result = cart_check_auth()

    assert "authenticated" in result
    assert isinstance(result["authenticated"], bool)


@pytest.mark.asyncio
async def test_cart_get_requires_auth():
    """cart_get should require authentication."""
    from texas_grocery_mcp.tools.cart import cart_get

    with patch("texas_grocery_mcp.tools.cart.is_authenticated", return_value=False):
        result = await cart_get()

    assert result["auth_required"] is True
    assert "instructions" in result


@pytest.mark.asyncio
async def test_cart_remove_requires_auth():
    """cart_remove should require authentication."""
    from texas_grocery_mcp.tools.cart import cart_remove

    with patch("texas_grocery_mcp.tools.cart.is_authenticated", return_value=False):
        result = await cart_remove(product_id="123456")

    assert result["auth_required"] is True
    assert "instructions" in result


@pytest.mark.asyncio
async def test_cart_remove_without_confirm_returns_preview():
    """cart_remove without confirm should return preview."""
    import texas_grocery_mcp.auth.session as session_module
    from texas_grocery_mcp.tools.cart import cart_remove
    session_module._is_authenticated = True

    result = await cart_remove(product_id="123456")

    assert result["preview"] is True
    assert result["action"] == "remove_from_cart"
    assert "confirm" in result["message"].lower()


class TestCartAddMany:
    """Tests for cart_add_many bulk add functionality."""

    @pytest.mark.asyncio
    async def test_requires_auth(self):
        """cart_add_many should require authentication."""
        from texas_grocery_mcp.tools.cart import cart_add_many

        with patch("texas_grocery_mcp.tools.cart.is_authenticated", return_value=False):
            result = await cart_add_many(
                items=[{"product_id": "123", "sku_id": "123-HEB", "quantity": 1}]
            )

        assert result["auth_required"] is True

    @pytest.mark.asyncio
    async def test_preview_mode_returns_items(self):
        """cart_add_many without confirm should return preview."""
        from texas_grocery_mcp.tools.cart import cart_add_many

        with patch("texas_grocery_mcp.tools.cart.is_authenticated", return_value=True):
            result = await cart_add_many(
                items=[
                    {"product_id": "123", "sku_id": "123-HEB", "quantity": 2},
                    {"product_id": "456", "sku_id": "456-HEB", "quantity": 1},
                ],
                confirm=False,
            )

        assert result["preview"] is True
        assert result["count"] == 2
        assert len(result["items_to_add"]) == 2

    @pytest.mark.asyncio
    async def test_rejects_empty_items(self):
        """cart_add_many should reject empty items list."""
        from texas_grocery_mcp.tools.cart import cart_add_many

        with patch("texas_grocery_mcp.tools.cart.is_authenticated", return_value=True):
            result = await cart_add_many(items=[], confirm=True)

        assert result["error"] is True
        assert result["code"] == "NO_ITEMS"

    @pytest.mark.asyncio
    async def test_rejects_over_100_items(self):
        """cart_add_many should reject more than 100 items."""
        from texas_grocery_mcp.tools.cart import cart_add_many

        items = [
            {"product_id": str(i), "sku_id": f"{i}-HEB", "quantity": 1}
            for i in range(101)
        ]

        with patch("texas_grocery_mcp.tools.cart.is_authenticated", return_value=True):
            result = await cart_add_many(items=items, confirm=True)

        assert result["error"] is True
        assert result["code"] == "TOO_MANY_ITEMS"

    @pytest.mark.asyncio
    async def test_validates_required_fields(self):
        """cart_add_many should reject items missing required fields."""
        from texas_grocery_mcp.tools.cart import cart_add_many

        with patch("texas_grocery_mcp.tools.cart.is_authenticated", return_value=True):
            result = await cart_add_many(
                items=[
                    {"product_id": "123"},  # Missing sku_id and quantity
                    {"sku_id": "456-HEB", "quantity": 1},  # Missing product_id
                ],
                confirm=True,
            )

        assert result["error"] is True
        assert result["code"] == "VALIDATION_ERROR"
        assert len(result["validation_errors"]) == 2

    @pytest.mark.asyncio
    async def test_validates_quantity_positive(self):
        """cart_add_many should reject quantity < 1."""
        from texas_grocery_mcp.tools.cart import cart_add_many

        with patch("texas_grocery_mcp.tools.cart.is_authenticated", return_value=True):
            result = await cart_add_many(
                items=[
                    {"product_id": "123", "sku_id": "123-HEB", "quantity": 0},
                    {"product_id": "456", "sku_id": "456-HEB", "quantity": -1},
                ],
                confirm=True,
            )

        assert result["error"] is True
        assert result["code"] == "VALIDATION_ERROR"

    @pytest.mark.asyncio
    async def test_success_all_items_added(self):
        """cart_add_many should return success when all items add successfully."""
        from unittest.mock import AsyncMock, MagicMock

        from texas_grocery_mcp.tools.cart import cart_add_many

        mock_client = MagicMock()
        mock_client.add_to_cart = AsyncMock(return_value={"success": True})
        mock_client.get_cart = AsyncMock(return_value={
            "cartV2": {
                "items": [
                    {
                        "product": {"id": "123", "displayName": "Product 1"},
                        "sku": {"id": "123-HEB"},
                        "quantity": 2,
                        "price": {"amount": 5.99},
                    },
                    {
                        "product": {"id": "456", "displayName": "Product 2"},
                        "sku": {"id": "456-HEB"},
                        "quantity": 1,
                        "price": {"amount": 3.99},
                    },
                ]
            }
        })

        with (
            patch("texas_grocery_mcp.tools.cart.is_authenticated", return_value=True),
            patch("texas_grocery_mcp.tools.cart._get_client", return_value=mock_client),
        ):
            result = await cart_add_many(
                items=[
                    {"product_id": "123", "sku_id": "123-HEB", "quantity": 2},
                    {"product_id": "456", "sku_id": "456-HEB", "quantity": 1},
                ],
                confirm=True,
            )

        assert result["success"] is True
        assert len(result["added"]) == 2
        assert result["summary"]["requested"] == 2
        assert result["summary"]["added"] == 2
        assert result["summary"]["failed"] == 0

    @pytest.mark.asyncio
    async def test_partial_failure_returns_error(self):
        """cart_add_many should return failure if any item fails (strict mode)."""
        from unittest.mock import AsyncMock, MagicMock

        from texas_grocery_mcp.tools.cart import cart_add_many

        mock_client = MagicMock()

        # First item succeeds, second fails
        mock_client.add_to_cart = AsyncMock(side_effect=[
            {"success": True},
            {"error": True, "code": "OUT_OF_STOCK", "message": "Out of stock"},
        ])
        mock_client.get_cart = AsyncMock(return_value={
            "cartV2": {
                "items": [
                    {
                        "product": {"id": "123", "displayName": "Product 1"},
                        "sku": {"id": "123-HEB"},
                        "quantity": 2,
                        "price": {"amount": 5.99},
                    },
                    # Note: 456 is NOT in cart (it failed)
                ]
            }
        })

        with (
            patch("texas_grocery_mcp.tools.cart.is_authenticated", return_value=True),
            patch("texas_grocery_mcp.tools.cart._get_client", return_value=mock_client),
        ):
            result = await cart_add_many(
                items=[
                    {"product_id": "123", "sku_id": "123-HEB", "quantity": 2},
                    {"product_id": "456", "sku_id": "456-HEB", "quantity": 1},
                ],
                confirm=True,
            )

        assert result["success"] is False
        assert result["error"] is True
        assert result["code"] == "PARTIAL_FAILURE"
        assert len(result["added"]) == 1
        assert len(result["failed"]) == 1
        assert result["failed"][0]["product_id"] == "456"
        assert result["summary"]["added"] == 1
        assert result["summary"]["failed"] == 1

    @pytest.mark.asyncio
    async def test_verification_failure_reports_error(self):
        """cart_add_many should report error if item not found in cart after add."""
        from unittest.mock import AsyncMock, MagicMock

        from texas_grocery_mcp.tools.cart import cart_add_many

        mock_client = MagicMock()
        mock_client.add_to_cart = AsyncMock(return_value={"success": True})
        # Cart doesn't contain the item after add (verification failure)
        mock_client.get_cart = AsyncMock(return_value={
            "cartV2": {"items": []}
        })

        with (
            patch("texas_grocery_mcp.tools.cart.is_authenticated", return_value=True),
            patch("texas_grocery_mcp.tools.cart._get_client", return_value=mock_client),
        ):
            result = await cart_add_many(
                items=[
                    {"product_id": "123", "sku_id": "123-HEB", "quantity": 1},
                ],
                confirm=True,
            )

        assert result["success"] is False
        assert result["code"] == "PARTIAL_FAILURE"
        assert len(result["failed"]) == 1
        assert result["failed"][0]["code"] == "VERIFICATION_FAILED"
