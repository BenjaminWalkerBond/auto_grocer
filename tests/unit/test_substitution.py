"""Tests for substitution tools."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def reset_tool_state():
    """Reset global state before each test."""
    from auto_grocier_mcp.tools import store as store_module

    store_module._default_store_id = None
    store_module._graphql_client = None
    yield
    store_module._default_store_id = None
    store_module._graphql_client = None


@pytest.fixture
def mock_available_products():
    """Mock product search results with available products."""
    return [
        {
            "product_id": "123",
            "sku": "123456789",
            "name": "Unsalted Butter",
            "brand": "HEB",
            "size": "16 oz",
            "price": 4.99,
            "available": False,  # Best match is unavailable
            "category_path": "Dairy/Butter",
        },
        {
            "product_id": "124",
            "sku": "124456789",
            "name": "Salted Butter",
            "brand": "HEB",
            "size": "16 oz",
            "price": 4.99,
            "available": True,
            "category_path": "Dairy/Butter",
        },
        {
            "product_id": "125",
            "sku": "125456789",
            "name": "European Style Butter",
            "brand": "Kerrygold",
            "size": "8 oz",
            "price": 5.99,
            "available": True,
            "category_path": "Dairy/Butter",
        },
    ]


@pytest.fixture
def mock_all_available_products():
    """Mock product search results where best match IS available."""
    return [
        {
            "product_id": "123",
            "sku": "123456789",
            "name": "Unsalted Butter",
            "brand": "HEB",
            "size": "16 oz",
            "price": 4.99,
            "available": True,  # Best match IS available
            "category_path": "Dairy/Butter",
        },
    ]


@pytest.fixture
def mock_claude_response():
    """Mock Claude's evaluate_substitutes response."""
    return {
        "recommended": {
            "product_id": "125",
            "sku": "125456789",
            "name": "European Style Butter",
            "reason": "European butter has higher fat content, excellent for baking.",
        },
        "alternatives": [
            {
                "product_id": "124",
                "sku": "124456789",
                "name": "Salted Butter",
                "reason": "Works but may need to reduce salt in recipe.",
            }
        ],
        "no_good_substitute": False,
        "warning": None,
        "fallback_used": False,
    }


@pytest.fixture
def mock_croissant_context():
    """Recipe context for croissants (butter-critical)."""
    return {
        "title": "French Croissants",
        "description": "Classic laminated pastry with butter layers",
        "cook_time": "3 hours",
    }


class TestFindSubstitute:
    """Tests for the find_substitute tool."""

    @pytest.mark.asyncio
    async def test_requires_store_id(self):
        """find_substitute should error when no store available."""
        from auto_grocier_mcp.tools.substitution import find_substitute

        result = await find_substitute(ingredient_name="butter")

        assert result.get("error") is True
        assert result.get("code") == "NO_STORE_SET"

    @pytest.mark.asyncio
    async def test_rejects_empty_ingredient_name(self):
        """find_substitute should reject empty ingredient names."""
        from auto_grocier_mcp.tools.store import set_default_store_id
        from auto_grocier_mcp.tools.substitution import find_substitute

        set_default_store_id("590")

        result = await find_substitute(ingredient_name="   ")

        assert result.get("error") is True
        assert result.get("code") == "INVALID_INGREDIENT"

    @pytest.mark.asyncio
    async def test_no_substitution_needed_when_available(
        self, mock_all_available_products
    ):
        """find_substitute should indicate no substitution when best match is available."""
        from auto_grocier_mcp.tools.store import set_default_store_id
        from auto_grocier_mcp.tools.substitution import find_substitute

        set_default_store_id("590")

        with patch(
            "auto_grocier_mcp.tools.substitution._search_products",
            new_callable=AsyncMock,
            return_value=mock_all_available_products,
        ):
            result = await find_substitute(ingredient_name="butter")

        assert result.get("substitution_needed") is False
        assert result.get("product", {}).get("available") is True

    @pytest.mark.asyncio
    async def test_calls_claude_for_substitution(
        self, mock_available_products, mock_claude_response
    ):
        """find_substitute should call Claude to evaluate candidates."""
        from auto_grocier_mcp.tools.store import set_default_store_id
        from auto_grocier_mcp.tools.substitution import find_substitute

        set_default_store_id("590")

        with patch(
            "auto_grocier_mcp.tools.substitution._search_products",
            new_callable=AsyncMock,
            return_value=mock_available_products,
        ), patch(
            "auto_grocier.claude.evaluate_substitutes",
            return_value=mock_claude_response,
        ) as mock_eval:
            result = await find_substitute(ingredient_name="unsalted butter")

        # Should have called Claude
        mock_eval.assert_called_once()

        # Check the result
        assert result.get("substitution_needed") is True
        assert result.get("recommended") is not None
        assert result["recommended"]["product_id"] == "125"

    @pytest.mark.asyncio
    async def test_only_passes_available_products_to_claude(
        self, mock_available_products
    ):
        """find_substitute should filter to available=true before calling Claude."""
        from auto_grocier_mcp.tools.store import set_default_store_id
        from auto_grocier_mcp.tools.substitution import find_substitute

        set_default_store_id("590")

        with patch(
            "auto_grocier_mcp.tools.substitution._search_products",
            new_callable=AsyncMock,
            return_value=mock_available_products,
        ), patch(
            "auto_grocier.claude.evaluate_substitutes",
            return_value={
                "recommended": None,
                "alternatives": [],
                "no_good_substitute": True,
                "warning": "No suitable substitute",
                "fallback_used": False,
            },
        ) as mock_eval:
            await find_substitute(ingredient_name="butter")

        # Check that only available products were passed
        call_args = mock_eval.call_args
        candidates = call_args[1]["candidates"] if call_args[1] else call_args[0][3]

        # All candidates should be available
        for candidate in candidates:
            assert candidate.get("available") is True

    @pytest.mark.asyncio
    async def test_includes_recipe_context(
        self, mock_available_products, mock_claude_response, mock_croissant_context
    ):
        """find_substitute should pass recipe context to Claude."""
        from auto_grocier_mcp.tools.store import set_default_store_id
        from auto_grocier_mcp.tools.substitution import find_substitute

        set_default_store_id("590")

        with patch(
            "auto_grocier_mcp.tools.substitution._search_products",
            new_callable=AsyncMock,
            return_value=mock_available_products,
        ), patch(
            "auto_grocier.claude.evaluate_substitutes",
            return_value=mock_claude_response,
        ) as mock_eval:
            await find_substitute(
                ingredient_name="butter",
                recipe_context=mock_croissant_context,
            )

        call_args = mock_eval.call_args
        recipe_ctx = call_args[1]["recipe_context"] if call_args[1] else call_args[0][1]
        assert recipe_ctx["title"] == "French Croissants"

    @pytest.mark.asyncio
    async def test_fallback_when_claude_unavailable(self, mock_available_products):
        """find_substitute should fall back to category match when Claude fails."""
        from auto_grocier_mcp.tools.store import set_default_store_id
        from auto_grocier_mcp.tools.substitution import find_substitute

        set_default_store_id("590")

        with patch(
            "auto_grocier_mcp.tools.substitution._search_products",
            new_callable=AsyncMock,
            return_value=mock_available_products,
        ), patch(
            "auto_grocier.claude.evaluate_substitutes",
            side_effect=Exception("API unavailable"),
        ):
            result = await find_substitute(ingredient_name="butter")

        # Should have a recommendation (fallback)
        assert result.get("substitution_needed") is True
        assert result.get("recommended") is not None
        assert result.get("fallback_used") is True
        assert "Claude unavailable" in result["recommended"]["reason"]

    @pytest.mark.asyncio
    async def test_no_products_found(self):
        """find_substitute should handle no products found."""
        from auto_grocier_mcp.tools.store import set_default_store_id
        from auto_grocier_mcp.tools.substitution import find_substitute

        set_default_store_id("590")

        with patch(
            "auto_grocier_mcp.tools.substitution._search_products",
            new_callable=AsyncMock,
            return_value=[],
        ):
            result = await find_substitute(ingredient_name="nonexistent-ingredient-xyz")

        assert result.get("error") is True
        assert result.get("code") == "NO_PRODUCTS_FOUND"


class TestEvaluateSubstitutes:
    """Tests for the evaluate_substitutes function in claude.py."""

    def test_returns_fallback_when_no_client(self):
        """evaluate_substitutes should return fallback when Claude client is None."""
        with patch("auto_grocier.claude.client", None):
            from auto_grocier.claude import evaluate_substitutes

            candidates = [
                {
                    "product_id": "124",
                    "sku": "124456789",
                    "name": "Salted Butter",
                    "brand": "HEB",
                    "available": True,
                }
            ]

            result = evaluate_substitutes(
                original_ingredient={"name": "butter", "amount": "1", "unit": "cup", "tags": []},
                recipe_context=None,
                unavailable_product={"name": "Unsalted Butter", "brand": "HEB"},
                candidates=candidates,
            )

        assert result.get("fallback_used") is True
        assert result.get("recommended") is not None
        assert "Claude unavailable" in result["recommended"]["reason"]

    def test_returns_no_substitute_when_no_available_candidates(self):
        """evaluate_substitutes should return no_good_substitute when no candidates."""
        from auto_grocier.claude import evaluate_substitutes

        result = evaluate_substitutes(
            original_ingredient={"name": "butter", "amount": "1", "unit": "cup", "tags": []},
            recipe_context=None,
            unavailable_product={"name": "Unsalted Butter", "brand": "HEB"},
            candidates=[],  # No candidates
        )

        assert result.get("no_good_substitute") is True
        assert result.get("recommended") is None

    def test_filters_unavailable_from_candidates(self):
        """evaluate_substitutes should filter out unavailable candidates."""
        from auto_grocier.claude import evaluate_substitutes

        candidates = [
            {"product_id": "1", "name": "Product A", "available": False},
            {"product_id": "2", "name": "Product B", "available": True},
        ]

        with patch("auto_grocier.claude.client") as mock_client:
            mock_client.messages.create.return_value = MagicMock(
                content=[MagicMock(text='{"recommended": {"product_id": "2", "sku": "", "name": "Product B", "reason": "Good"}, "alternatives": [], "no_good_substitute": false, "warning": null}')]
            )

            result = evaluate_substitutes(
                original_ingredient={"name": "test", "amount": "", "unit": "", "tags": []},
                recipe_context=None,
                unavailable_product={"name": "Test Product"},
                candidates=candidates,
            )

        # Product B should be recommended (only available one)
        assert result.get("recommended", {}).get("product_id") == "2"

    def test_parses_claude_json_response(self):
        """evaluate_substitutes should correctly parse Claude's JSON response."""
        from auto_grocier.claude import evaluate_substitutes

        candidates = [
            {"product_id": "125", "sku": "125456", "name": "European Butter", "available": True}
        ]

        with patch("auto_grocier.claude.client") as mock_client:
            mock_client.messages.create.return_value = MagicMock(
                content=[
                    MagicMock(
                        text=json.dumps(
                            {
                                "recommended": {
                                    "product_id": "125",
                                    "sku": "125456",
                                    "name": "European Butter",
                                    "reason": "Higher fat content for better pastry.",
                                },
                                "alternatives": [],
                                "no_good_substitute": False,
                                "warning": "May need to adjust quantity.",
                            }
                        )
                    )
                ]
            )

            result = evaluate_substitutes(
                original_ingredient={"name": "butter", "amount": "1", "unit": "cup", "tags": []},
                recipe_context={"title": "Cookies", "description": "Baked goods"},
                unavailable_product={"name": "Unsalted Butter", "brand": "HEB"},
                candidates=candidates,
            )

        assert result["recommended"]["product_id"] == "125"
        assert "fat content" in result["recommended"]["reason"].lower()
        assert result["warning"] == "May need to adjust quantity."
        assert result["no_good_substitute"] is False

    def test_handles_json_in_code_fences(self):
        """evaluate_substitutes should handle JSON wrapped in code fences."""
        from auto_grocier.claude import evaluate_substitutes

        candidates = [
            {"product_id": "125", "sku": "125456", "name": "Butter", "available": True}
        ]

        with patch("auto_grocier.claude.client") as mock_client:
            # Claude sometimes wraps JSON in code fences
            mock_client.messages.create.return_value = MagicMock(
                content=[
                    MagicMock(
                        text='```json\n{"recommended": {"product_id": "125", "sku": "125456", "name": "Butter", "reason": "Good"}, "alternatives": [], "no_good_substitute": false, "warning": null}\n```'
                    )
                ]
            )

            result = evaluate_substitutes(
                original_ingredient={"name": "butter", "amount": "", "unit": "", "tags": []},
                recipe_context=None,
                unavailable_product={"name": "Test"},
                candidates=candidates,
            )

        assert result["recommended"]["product_id"] == "125"
        assert result["fallback_used"] is False


class TestCategoryTermExtraction:
    """Tests for _extract_category_terms helper."""

    def test_extracts_butter_terms(self):
        """Should extract butter-related terms."""
        from auto_grocier_mcp.tools.substitution import _extract_category_terms

        terms = _extract_category_terms("unsalted butter")
        assert "butter" in terms or "unsalted butter" in terms

    def test_extracts_chicken_terms(self):
        """Should extract chicken-related terms."""
        from auto_grocier_mcp.tools.substitution import _extract_category_terms

        terms = _extract_category_terms("chicken breast")
        assert any("chicken" in t.lower() for t in terms)

    def test_extracts_leafy_greens_terms(self):
        """Should recognize leafy greens."""
        from auto_grocier_mcp.tools.substitution import _extract_category_terms

        terms = _extract_category_terms("fresh spinach")
        assert "fresh spinach" in terms or "leafy greens" in [t.lower() for t in terms]

    def test_limits_to_three_terms(self):
        """Should limit to 3 search terms max."""
        from auto_grocier_mcp.tools.substitution import _extract_category_terms

        terms = _extract_category_terms("some ingredient")
        assert len(terms) <= 3


class TestCroissantButterSubstitution:
    """Test the specific croissant/butter scenario from AC4."""

    @pytest.mark.asyncio
    async def test_croissant_margarine_rejection(self):
        """For croissants, Claude should reject margarine as a substitute for butter."""
        from auto_grocier_mcp.tools.store import set_default_store_id
        from auto_grocier_mcp.tools.substitution import find_substitute

        set_default_store_id("590")

        # Products where only margarine is available
        mock_products = [
            {
                "product_id": "100",
                "sku": "100000",
                "name": "Unsalted Butter",
                "brand": "HEB",
                "size": "16 oz",
                "price": 4.99,
                "available": False,  # Unavailable
                "category_path": "Dairy/Butter",
            },
            {
                "product_id": "200",
                "sku": "200000",
                "name": "Margarine Spread",
                "brand": "Imperial",
                "size": "16 oz",
                "price": 2.99,
                "available": True,
                "category_path": "Dairy/Butter Substitutes",
            },
        ]

        # Claude should recognize this is problematic
        mock_no_good_response = {
            "recommended": None,
            "alternatives": [],
            "no_good_substitute": True,
            "warning": "Margarine cannot be used for laminated dough. The water content and behavior under heat will ruin the layers.",
            "fallback_used": False,
        }

        with patch(
            "auto_grocier_mcp.tools.substitution._search_products",
            new_callable=AsyncMock,
            return_value=mock_products,
        ), patch(
            "auto_grocier.claude.evaluate_substitutes",
            return_value=mock_no_good_response,
        ):
            result = await find_substitute(
                ingredient_name="butter",
                recipe_context={
                    "title": "French Croissants",
                    "description": "Classic laminated pastry requiring careful butter folding",
                    "cook_time": "3 hours",
                },
            )

        assert result.get("no_good_substitute") is True
        assert result.get("warning") is not None
        assert "laminated" in result["warning"].lower() or "margarine" in result["warning"].lower()
