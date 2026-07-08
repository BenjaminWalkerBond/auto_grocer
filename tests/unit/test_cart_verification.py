"""Tests for cart verification logic."""

from unittest.mock import AsyncMock, patch

import pytest

from texas_grocery_mcp.tools.cart import (
    _extract_price_from_cart_item,
    _extract_sku_from_cart_item,
)


class TestExtractSkuFromCartItem:
    """Tests for SKU extraction helper."""

    def test_extracts_from_sku_object(self):
        """Should extract SKU from nested sku.id object."""
        item = {"sku": {"id": "4122071073"}}
        assert _extract_sku_from_cart_item(item) == "4122071073"

    def test_extracts_from_sku_object_with_int(self):
        """Should handle integer SKU IDs."""
        item = {"sku": {"id": 4122071073}}
        assert _extract_sku_from_cart_item(item) == "4122071073"

    def test_extracts_from_direct_sku_id(self):
        """Should extract SKU from direct skuId field."""
        item = {"skuId": "4122071073"}
        assert _extract_sku_from_cart_item(item) == "4122071073"

    def test_extracts_from_direct_sku_id_underscore(self):
        """Should extract SKU from sku_id field (snake_case)."""
        item = {"sku_id": "4122071073"}
        assert _extract_sku_from_cart_item(item) == "4122071073"

    def test_extracts_from_product_skus(self):
        """Should extract SKU from product.SKUs array."""
        item = {"product": {"SKUs": [{"id": "4122071073"}]}}
        assert _extract_sku_from_cart_item(item) == "4122071073"

    def test_extracts_from_product_skus_lowercase(self):
        """Should extract SKU from product.skus array (lowercase)."""
        item = {"product": {"skus": [{"id": "4122071073"}]}}
        assert _extract_sku_from_cart_item(item) == "4122071073"

    def test_extracts_from_product_skus_sku_id(self):
        """Should extract SKU from product.SKUs[].skuId field."""
        item = {"product": {"SKUs": [{"skuId": "4122071073"}]}}
        assert _extract_sku_from_cart_item(item) == "4122071073"

    def test_returns_none_when_missing(self):
        """Should return None when SKU is not present."""
        item = {"product": {}}
        assert _extract_sku_from_cart_item(item) is None

    def test_returns_none_for_empty_item(self):
        """Should return None for empty item."""
        item = {}
        assert _extract_sku_from_cart_item(item) is None

    def test_prefers_sku_object_over_product_skus(self):
        """Should prefer direct sku.id over product.SKUs."""
        item = {
            "sku": {"id": "direct-sku"},
            "product": {"SKUs": [{"id": "product-sku"}]},
        }
        assert _extract_sku_from_cart_item(item) == "direct-sku"


class TestExtractPriceFromCartItem:
    """Tests for price extraction helper."""

    def test_extracts_from_price_amount(self):
        """Should extract price from price.amount."""
        item = {"price": {"amount": 5.99}}
        assert _extract_price_from_cart_item(item) == 5.99

    def test_extracts_from_price_amount_int(self):
        """Should handle integer prices."""
        item = {"price": {"amount": 5}}
        assert _extract_price_from_cart_item(item) == 5.0

    def test_extracts_from_unit_price(self):
        """Should extract price from unitPrice field."""
        item = {"unitPrice": 5.99}
        assert _extract_price_from_cart_item(item) == 5.99

    def test_extracts_from_list_price_amount(self):
        """Should extract price from listPrice.amount."""
        item = {"listPrice": {"amount": 5.99}}
        assert _extract_price_from_cart_item(item) == 5.99

    def test_extracts_from_product_price_dict(self):
        """Should extract price from product.price dict."""
        item = {"product": {"price": {"amount": 5.99}}}
        assert _extract_price_from_cart_item(item) == 5.99

    def test_extracts_from_product_price_float(self):
        """Should extract price from product.price float."""
        item = {"product": {"price": 5.99}}
        assert _extract_price_from_cart_item(item) == 5.99

    def test_extracts_from_context_prices_curbside(self):
        """Should extract price from SKU contextPrices for CURBSIDE."""
        item = {
            "product": {
                "SKUs": [{
                    "contextPrices": [{
                        "context": "CURBSIDE",
                        "salePrice": {"amount": 4.99},
                        "listPrice": {"amount": 5.99},
                    }]
                }]
            }
        }
        assert _extract_price_from_cart_item(item) == 4.99

    def test_extracts_from_context_prices_list_price_fallback(self):
        """Should fall back to listPrice if salePrice missing."""
        item = {
            "product": {
                "SKUs": [{
                    "contextPrices": [{
                        "context": "CURBSIDE",
                        "listPrice": {"amount": 5.99},
                    }]
                }]
            }
        }
        assert _extract_price_from_cart_item(item) == 5.99

    def test_returns_zero_when_missing(self):
        """Should return 0 when price is not present."""
        item = {}
        assert _extract_price_from_cart_item(item) == 0.0

    def test_returns_zero_for_empty_price_object(self):
        """Should return 0 for empty price object."""
        item = {"price": {}}
        assert _extract_price_from_cart_item(item) == 0.0

    def test_prefers_direct_price_over_product(self):
        """Should prefer direct price.amount over product.price."""
        item = {
            "price": {"amount": 5.99},
            "product": {"price": 10.99},
        }
        assert _extract_price_from_cart_item(item) == 5.99


class TestCartAddVerification:
    """Tests for cart_add verification logic."""

    @pytest.mark.asyncio
    async def test_returns_error_when_item_not_in_cart_after_add(self):
        """cart_add should return error if item not found in cart after API success."""
        from texas_grocery_mcp.tools.cart import cart_add

        with (
            patch("texas_grocery_mcp.tools.cart.is_authenticated", return_value=True),
            patch("texas_grocery_mcp.tools.cart._get_client") as mock_get_client,
        ):
            client = AsyncMock()
            mock_get_client.return_value = client

            # API returns success but item not in cart
            client.get_cart.return_value = {"cartV2": {"items": []}}
            client.add_to_cart.return_value = {"success": True}

            result = await cart_add(
                product_id="127074",
                sku_id="4122071073",
                quantity=1,
                confirm=True,
            )

            assert result.get("error") is True
            assert result.get("code") == "CART_ADD_NOT_VERIFIED"
            assert "troubleshooting" in result

    @pytest.mark.asyncio
    async def test_returns_success_when_item_verified_in_cart(self):
        """cart_add should return success with verified=True when item found."""
        from texas_grocery_mcp.tools.cart import cart_add

        with (
            patch("texas_grocery_mcp.tools.cart.is_authenticated", return_value=True),
            patch("texas_grocery_mcp.tools.cart._get_client") as mock_get_client,
        ):
            client = AsyncMock()
            mock_get_client.return_value = client

            # Before: empty cart
            # After: item in cart
            client.get_cart.side_effect = [
                {"cartV2": {"items": []}},  # Before
                {
                    "cartV2": {  # After
                        "items": [
                            {
                                "sku": {"id": "4122071073"},
                                "product": {"id": "127074"},
                                "quantity": 1,
                            }
                        ]
                    }
                },
            ]
            client.add_to_cart.return_value = {"success": True}

            result = await cart_add(
                product_id="127074",
                sku_id="4122071073",
                quantity=1,
                confirm=True,
            )

            assert result.get("success") is True
            assert result.get("verified") is True

    @pytest.mark.asyncio
    async def test_returns_preview_when_not_confirmed(self):
        """cart_add should return preview when confirm=False."""
        from texas_grocery_mcp.tools.cart import cart_add

        with patch("texas_grocery_mcp.tools.cart.is_authenticated", return_value=True):
            result = await cart_add(
                product_id="127074",
                sku_id="4122071073",
                quantity=1,
                confirm=False,
            )

            assert result.get("preview") is True
            assert "note" in result  # Should have note about ID formats

    @pytest.mark.asyncio
    async def test_returns_auth_required_when_not_authenticated(self):
        """cart_add should return auth_required when not logged in."""
        from texas_grocery_mcp.tools.cart import cart_add

        with patch("texas_grocery_mcp.tools.cart.is_authenticated", return_value=False):
            result = await cart_add(
                product_id="127074",
                sku_id="4122071073",
                quantity=1,
                confirm=True,
            )

            assert result.get("auth_required") is True

    @pytest.mark.asyncio
    async def test_returns_warning_when_cart_fetch_fails_after_add(self):
        """cart_add should return warning if can't verify due to cart fetch failure."""
        from texas_grocery_mcp.tools.cart import cart_add

        with (
            patch("texas_grocery_mcp.tools.cart.is_authenticated", return_value=True),
            patch("texas_grocery_mcp.tools.cart._get_client") as mock_get_client,
        ):
            client = AsyncMock()
            mock_get_client.return_value = client

            # Before: returns cart
            # After: returns error
            client.get_cart.side_effect = [
                {"cartV2": {"items": []}},  # Before
                {"error": True, "code": "FETCH_FAILED"},  # After
            ]
            client.add_to_cart.return_value = {"success": True}

            result = await cart_add(
                product_id="127074",
                sku_id="4122071073",
                quantity=1,
                confirm=True,
            )

            assert result.get("warning") is True
            assert result.get("code") == "VERIFICATION_UNAVAILABLE"


class TestCartAddWithRetry:
    """Tests for cart_add_with_retry auto-correction logic."""

    @pytest.mark.asyncio
    async def test_returns_success_on_first_attempt(self):
        """Should return success without retry if first attempt works."""
        from texas_grocery_mcp.tools.cart import cart_add_with_retry

        with patch("texas_grocery_mcp.tools.cart.cart_add") as mock_cart_add:
            mock_cart_add.return_value = {"success": True, "verified": True}

            result = await cart_add_with_retry(
                product_id="127074",
                sku_id="4122071073",
                quantity=1,
                confirm=True,
            )

            assert result.get("success") is True
            assert "auto_corrected" not in result
            mock_cart_add.assert_called_once()

    @pytest.mark.asyncio
    async def test_returns_preview_without_retry(self):
        """Should return preview without attempting retry."""
        from texas_grocery_mcp.tools.cart import cart_add_with_retry

        with patch("texas_grocery_mcp.tools.cart.cart_add") as mock_cart_add:
            mock_cart_add.return_value = {"preview": True}

            result = await cart_add_with_retry(
                product_id="127074",
                sku_id="4122071073",
                quantity=1,
                confirm=False,
            )

            assert result.get("preview") is True
            mock_cart_add.assert_called_once()
