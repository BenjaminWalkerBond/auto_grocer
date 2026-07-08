"""Unit tests for coupon tools."""

from unittest.mock import AsyncMock, patch

import pytest

from texas_grocery_mcp.models.coupon import Coupon, CouponCategory, CouponSearchResult
from texas_grocery_mcp.tools.coupon import (
    CATEGORY_IDS,
    _resolve_category,
    coupon_categories,
    coupon_clip,
    coupon_clipped,
    coupon_list,
    coupon_search,
)


class TestResolveCatetgory:
    """Tests for category resolution."""

    def test_resolve_category_by_name(self):
        """Test resolving category by name."""
        assert _resolve_category("pantry") == 490024
        assert _resolve_category("Pantry") == 490024
        assert _resolve_category("PANTRY") == 490024

    def test_resolve_category_by_id(self):
        """Test resolving category by numeric ID."""
        assert _resolve_category("490024") == 490024

    def test_resolve_category_with_spaces(self):
        """Test resolving category with spaces."""
        assert _resolve_category("health & beauty") == 490021
        assert _resolve_category("meat & seafood") == 490023

    def test_resolve_category_aliases(self):
        """Test category aliases work."""
        # All should map to the same ID
        assert _resolve_category("health") == _resolve_category("health & beauty")
        assert _resolve_category("beauty") == _resolve_category("health & beauty")

    def test_resolve_category_none(self):
        """Test None returns None."""
        assert _resolve_category(None) is None

    def test_resolve_category_unknown(self):
        """Test unknown category returns None."""
        assert _resolve_category("nonexistent") is None

    def test_category_ids_mapping_complete(self):
        """Test all expected categories are mapped."""
        expected_categories = [
            "baby & kids",
            "bakery & bread",
            "beverages",
            "dairy & eggs",
            "deli & prepared food",
            "everyday essentials",
            "frozen food",
            "fruit & vegetables",
            "health & beauty",
            "home & outdoor",
            "meat & seafood",
            "pantry",
            "pets",
        ]
        for cat in expected_categories:
            assert cat in CATEGORY_IDS, f"Missing category: {cat}"


class TestCouponList:
    """Tests for coupon_list tool."""

    @pytest.fixture
    def mock_coupons(self):
        """Sample coupon data."""
        return [
            Coupon(
                coupon_id=84035988,
                headline="25% off",
                description="25% off any H-E-B Analgesics",
                expires="2026-02-03",
                expires_display="02/03/2026",
                coupon_type="NORMAL",
                clipped=False,
                usage_limit="Unlimited use",
            ),
            Coupon(
                coupon_id=84041100,
                headline="$2 off",
                description="$2 off Party Trays",
                expires="2026-02-17",
                expires_display="02/17/2026",
                coupon_type="NORMAL",
                clipped=False,
                usage_limit="Unlimited use",
            ),
        ]

    @pytest.fixture
    def mock_categories(self):
        """Sample category data."""
        return [
            CouponCategory(id=490024, name="Pantry", count=205),
            CouponCategory(id=490021, name="Health & beauty", count=177),
        ]

    @pytest.mark.asyncio
    async def test_coupon_list_requires_auth(self):
        """Test coupon_list requires authentication."""
        with patch("texas_grocery_mcp.tools.coupon.is_authenticated", return_value=False):
            result = await coupon_list()

        assert result["error"] is True
        assert result["code"] == "AUTH_REQUIRED"
        assert result["coupons"] == []

    @pytest.mark.asyncio
    async def test_coupon_list_returns_coupons(self, mock_coupons, mock_categories):
        """Test coupon_list returns formatted coupons."""
        mock_result = CouponSearchResult(
            coupons=mock_coupons,
            count=2,
            total=716,
            categories=mock_categories,
        )

        with (
            patch("texas_grocery_mcp.tools.coupon.is_authenticated", return_value=True),
            patch("texas_grocery_mcp.tools.coupon._get_client") as mock_get_client,
        ):
            mock_client = AsyncMock()
            mock_client.get_coupons.return_value = mock_result
            mock_get_client.return_value = mock_client

            result = await coupon_list(limit=20)

        assert result["count"] == 2
        assert result["total"] == 716
        assert len(result["coupons"]) == 2
        assert result["coupons"][0]["coupon_id"] == 84035988
        assert result["coupons"][0]["headline"] == "25% off"
        assert "categories" in result

    @pytest.mark.asyncio
    async def test_coupon_list_with_category_filter(self, mock_coupons, mock_categories):
        """Test coupon_list with category filter."""
        mock_result = CouponSearchResult(
            coupons=mock_coupons[:1],
            count=1,
            total=205,
            categories=mock_categories,
        )

        with (
            patch("texas_grocery_mcp.tools.coupon.is_authenticated", return_value=True),
            patch("texas_grocery_mcp.tools.coupon._get_client") as mock_get_client,
        ):
            mock_client = AsyncMock()
            mock_client.get_coupons.return_value = mock_result
            mock_get_client.return_value = mock_client

            result = await coupon_list(category="pantry")

        assert result["filtered_by"] == "pantry"
        mock_client.get_coupons.assert_called_once_with(
            category_id=490024,
            limit=20,
        )


class TestCouponSearch:
    """Tests for coupon_search tool."""

    @pytest.mark.asyncio
    async def test_coupon_search_requires_auth(self):
        """Test coupon_search requires authentication."""
        with patch("texas_grocery_mcp.tools.coupon.is_authenticated", return_value=False):
            result = await coupon_search(query="chips")

        assert result["error"] is True
        assert result["code"] == "AUTH_REQUIRED"

    @pytest.mark.asyncio
    async def test_coupon_search_empty_query(self):
        """Test coupon_search rejects empty query."""
        with patch("texas_grocery_mcp.tools.coupon.is_authenticated", return_value=True):
            result = await coupon_search(query="   ")

        assert result["error"] is True
        assert result["code"] == "INVALID_QUERY"

    @pytest.mark.asyncio
    async def test_coupon_search_returns_results(self):
        """Test coupon_search returns matching coupons."""
        mock_coupon = Coupon(
            coupon_id=84037355,
            headline="$1 off 2",
            description="$1 off 2 H-E-B Tortilla, Potato, or Corn Chips",
            expires="2026-02-10",
            coupon_type="NORMAL",
            clipped=False,
            usage_limit="Unlimited use",
        )
        mock_result = CouponSearchResult(
            coupons=[mock_coupon],
            count=1,
            total=1,
            categories=[],
        )

        with (
            patch("texas_grocery_mcp.tools.coupon.is_authenticated", return_value=True),
            patch("texas_grocery_mcp.tools.coupon._get_client") as mock_get_client,
        ):
            mock_client = AsyncMock()
            mock_client.get_coupons.return_value = mock_result
            mock_get_client.return_value = mock_client

            result = await coupon_search(query="chips")

        assert result["count"] == 1
        assert result["query"] == "chips"
        assert result["coupons"][0]["description"].lower().__contains__("chips")


class TestCouponCategories:
    """Tests for coupon_categories tool."""

    @pytest.mark.asyncio
    async def test_coupon_categories_requires_auth(self):
        """Test coupon_categories requires authentication."""
        with patch("texas_grocery_mcp.tools.coupon.is_authenticated", return_value=False):
            result = await coupon_categories()

        assert result["error"] is True
        assert result["code"] == "AUTH_REQUIRED"

    @pytest.mark.asyncio
    async def test_coupon_categories_returns_sorted_list(self):
        """Test coupon_categories returns sorted categories."""
        mock_categories = [
            CouponCategory(id=490024, name="Pantry", count=205),
            CouponCategory(id=490021, name="Health & beauty", count=177),
            CouponCategory(id=490015, name="Beverages", count=96),
        ]
        mock_result = CouponSearchResult(
            coupons=[],
            count=0,
            total=716,
            categories=mock_categories,
        )

        with (
            patch("texas_grocery_mcp.tools.coupon.is_authenticated", return_value=True),
            patch("texas_grocery_mcp.tools.coupon._get_client") as mock_get_client,
        ):
            mock_client = AsyncMock()
            mock_client.get_coupons.return_value = mock_result
            mock_get_client.return_value = mock_client

            result = await coupon_categories()

        assert len(result["categories"]) == 3
        # Should be sorted alphabetically
        assert result["categories"][0]["name"] == "Beverages"
        assert result["categories"][1]["name"] == "Health & beauty"
        assert result["categories"][2]["name"] == "Pantry"
        assert result["total_coupons"] == 716


class TestCouponClip:
    """Tests for coupon_clip tool."""

    @pytest.mark.asyncio
    async def test_coupon_clip_requires_auth(self):
        """Test coupon_clip requires authentication."""
        with patch("texas_grocery_mcp.tools.coupon.is_authenticated", return_value=False):
            result = await coupon_clip(coupon_id=84035988)

        assert result["error"] is True
        assert result["code"] == "AUTH_REQUIRED"

    @pytest.mark.asyncio
    async def test_coupon_clip_preview_mode(self):
        """Test coupon_clip returns preview without confirm."""
        mock_coupon = Coupon(
            coupon_id=84035988,
            headline="25% off",
            description="25% off any H-E-B Analgesics",
            expires="2026-02-03",
            expires_display="02/03/2026",
            coupon_type="NORMAL",
            clipped=False,
            usage_limit="Unlimited use",
        )
        mock_result = CouponSearchResult(
            coupons=[mock_coupon],
            count=1,
            total=1,
            categories=[],
        )

        with (
            patch("texas_grocery_mcp.tools.coupon.is_authenticated", return_value=True),
            patch("texas_grocery_mcp.tools.coupon._get_client") as mock_get_client,
        ):
            mock_client = AsyncMock()
            mock_client.get_coupons.return_value = mock_result
            mock_get_client.return_value = mock_client

            result = await coupon_clip(coupon_id=84035988, confirm=False)

        assert result["preview"] is True
        assert "Ready to clip" in result["message"]
        assert result["coupon"]["coupon_id"] == 84035988

    @pytest.mark.asyncio
    async def test_coupon_clip_already_clipped_preview(self):
        """Test coupon_clip preview shows already clipped status."""
        mock_coupon = Coupon(
            coupon_id=84035988,
            headline="25% off",
            description="25% off any H-E-B Analgesics",
            expires="2026-02-03",
            coupon_type="NORMAL",
            clipped=True,
            usage_limit="Unlimited use",
        )
        mock_result = CouponSearchResult(
            coupons=[mock_coupon],
            count=1,
            total=1,
            categories=[],
        )

        with (
            patch("texas_grocery_mcp.tools.coupon.is_authenticated", return_value=True),
            patch("texas_grocery_mcp.tools.coupon._get_client") as mock_get_client,
        ):
            mock_client = AsyncMock()
            mock_client.get_coupons.return_value = mock_result
            mock_get_client.return_value = mock_client

            result = await coupon_clip(coupon_id=84035988, confirm=False)

        assert result["preview"] is True
        assert "already clipped" in result["message"]

    @pytest.mark.asyncio
    async def test_coupon_clip_executes_with_confirm(self):
        """Test coupon_clip executes clip with confirm=True."""
        with (
            patch("texas_grocery_mcp.tools.coupon.is_authenticated", return_value=True),
            patch("texas_grocery_mcp.tools.coupon._get_client") as mock_get_client,
        ):
            mock_client = AsyncMock()
            mock_client.clip_coupon.return_value = {
                "success": True,
                "coupon_id": 84035988,
                "message": "Coupon clipped successfully!",
            }
            mock_get_client.return_value = mock_client

            result = await coupon_clip(coupon_id=84035988, confirm=True)

        assert result["success"] is True
        assert result["coupon_id"] == 84035988
        mock_client.clip_coupon.assert_called_once_with(84035988)


class TestCouponClipped:
    """Tests for coupon_clipped tool."""

    @pytest.mark.asyncio
    async def test_coupon_clipped_requires_auth(self):
        """Test coupon_clipped requires authentication."""
        with patch("texas_grocery_mcp.tools.coupon.is_authenticated", return_value=False):
            result = await coupon_clipped()

        assert result["error"] is True
        assert result["code"] == "AUTH_REQUIRED"
        assert result["coupons"] == []

    @pytest.mark.asyncio
    async def test_coupon_clipped_returns_coupons(self):
        """Test coupon_clipped returns user's clipped coupons."""
        mock_coupons = [
            Coupon(
                coupon_id=84035988,
                headline="25% off",
                description="25% off any H-E-B Analgesics",
                expires="2026-02-03",
                expires_display="02/03/2026",
                coupon_type="NORMAL",
                clipped=True,
                usage_limit="Unlimited use",
            ),
            Coupon(
                coupon_id=84041100,
                headline="$2 off",
                description="$2 off Party Trays",
                expires="2026-02-17",
                expires_display="02/17/2026",
                coupon_type="NORMAL",
                clipped=True,
                usage_limit="Unlimited use",
            ),
        ]
        mock_result = CouponSearchResult(
            coupons=mock_coupons,
            count=2,
            total=2,
            categories=[],
        )

        with (
            patch("texas_grocery_mcp.tools.coupon.is_authenticated", return_value=True),
            patch("texas_grocery_mcp.tools.coupon._get_client") as mock_get_client,
        ):
            mock_client = AsyncMock()
            mock_client.get_clipped_coupons.return_value = mock_result
            mock_get_client.return_value = mock_client

            result = await coupon_clipped(limit=20)

        assert result["count"] == 2
        assert result["total"] == 2
        assert len(result["clipped_coupons"]) == 2
        assert result["clipped_coupons"][0]["coupon_id"] == 84035988
        mock_client.get_clipped_coupons.assert_called_once_with(limit=20)

    @pytest.mark.asyncio
    async def test_coupon_clipped_empty_list(self):
        """Test coupon_clipped returns empty list when no coupons clipped."""
        mock_result = CouponSearchResult(
            coupons=[],
            count=0,
            total=0,
            categories=[],
        )

        with (
            patch("texas_grocery_mcp.tools.coupon.is_authenticated", return_value=True),
            patch("texas_grocery_mcp.tools.coupon._get_client") as mock_get_client,
        ):
            mock_client = AsyncMock()
            mock_client.get_clipped_coupons.return_value = mock_result
            mock_get_client.return_value = mock_client

            result = await coupon_clipped()

        assert result["count"] == 0
        assert result["clipped_coupons"] == []
