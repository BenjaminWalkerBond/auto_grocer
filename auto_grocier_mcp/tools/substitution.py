"""Substitution-related MCP tools for out-of-stock products."""

from typing import TYPE_CHECKING, Annotated, Any

import structlog
from pydantic import Field

from auto_grocier_mcp.auth.session import ensure_session
from auto_grocier_mcp.state import StateManager

logger = structlog.get_logger()

if TYPE_CHECKING:
    from auto_grocier_mcp.clients.graphql import HEBGraphQLClient


def _get_client() -> "HEBGraphQLClient":
    """Get or create GraphQL client."""
    return StateManager.get_graphql_client_sync()


def get_default_store_id() -> str | None:
    """Get default store ID."""
    return StateManager.get_default_store_id()


async def _search_products(query: str, store_id: str, limit: int = 10) -> list[dict]:
    """Search for products and return as list of dicts.

    Returns list of product dicts with keys: product_id, sku, name, brand, size,
    price, available, category_path.
    """
    client = _get_client()
    try:
        search_result = await client.search_products(
            query=query,
            store_id=store_id,
            limit=limit,
        )
        products = []
        for p in search_result.products:
            products.append({
                "product_id": p.product_id,
                "sku": p.sku,
                "name": p.name,
                "brand": p.brand,
                "size": p.size,
                "price": p.price,
                "available": p.available,
                "category_path": getattr(p, "category_path", None),
            })
        return products
    except Exception as e:
        logger.warning("Product search failed", query=query, error=str(e))
        return []


def _extract_category_terms(ingredient_name: str) -> list[str]:
    """Extract broader category search terms from an ingredient name.

    For example:
    - "unsalted butter" -> ["butter", "cooking fat"]
    - "fresh spinach" -> ["spinach", "leafy greens"]
    - "chicken breast" -> ["chicken", "poultry"]
    """
    name_lower = ingredient_name.lower()
    terms = [ingredient_name]  # Always include original

    # Butter variations
    if "butter" in name_lower:
        terms.extend(["butter", "cooking butter"])

    # Milk variations
    if "milk" in name_lower:
        terms.extend(["milk", "dairy milk"])

    # Egg variations
    if "egg" in name_lower:
        terms.extend(["eggs", "fresh eggs"])

    # Chicken variations
    if "chicken" in name_lower:
        if "breast" in name_lower:
            terms.extend(["chicken breast", "chicken"])
        elif "thigh" in name_lower:
            terms.extend(["chicken thigh", "chicken"])
        else:
            terms.append("chicken")

    # Beef variations
    if "beef" in name_lower or "steak" in name_lower:
        terms.extend(["beef", "steak"])

    # Leafy greens
    greens = ["spinach", "kale", "lettuce", "arugula", "chard"]
    if any(g in name_lower for g in greens):
        terms.append("leafy greens")

    # Remove duplicates while preserving order
    seen = set()
    unique_terms = []
    for t in terms:
        if t.lower() not in seen:
            seen.add(t.lower())
            unique_terms.append(t)

    return unique_terms[:3]  # Limit to 3 search terms


@ensure_session
async def find_substitute(
    ingredient_name: Annotated[
        str,
        Field(
            description="Name of the ingredient to find a substitute for (e.g., 'butter', 'spinach')",
            min_length=1,
        ),
    ],
    store_id: Annotated[
        str | None,
        Field(
            description="Store ID for availability check. Uses default if not provided."
        ),
    ] = None,
    recipe_context: Annotated[
        dict[str, str] | None,
        Field(
            description=(
                "Optional recipe context with keys: title, description, cook_time. "
                "Helps Claude make better substitution decisions."
            )
        ),
    ] = None,
    ingredient_tags: Annotated[
        list[str] | None,
        Field(
            description="Tags for the ingredient (e.g., ['vegetable'], ['dairy'])"
        ),
    ] = None,
    ingredient_amount: Annotated[
        str | None,
        Field(description="Amount needed (e.g., '2 cups', '1 lb')")
    ] = None,
) -> dict[str, Any]:
    """Find a substitute for an out-of-stock product.

    Uses Claude AI to evaluate candidate products and recommend the best
    contextually-appropriate substitute. If Claude is unavailable, falls back
    to returning the top available category match with a warning.

    Returns a recommendation with explanation, alternatives, and warnings.
    """
    # Validate ingredient name
    ingredient_name = ingredient_name.strip()
    if not ingredient_name:
        return {
            "error": True,
            "code": "INVALID_INGREDIENT",
            "message": "Ingredient name cannot be empty.",
        }

    # Resolve store ID
    effective_store_id = store_id or get_default_store_id()
    if not effective_store_id:
        return {
            "error": True,
            "code": "NO_STORE_SET",
            "message": (
                "No store specified. Set a default store with store_change or provide "
                "store_id."
            ),
        }

    logger.info(
        "Finding substitute",
        ingredient=ingredient_name,
        store_id=effective_store_id,
        has_recipe_context=recipe_context is not None,
    )

    # Search for the original ingredient first
    products = await _search_products(ingredient_name, effective_store_id, limit=10)

    if not products:
        # No products found at all - search broader terms
        search_terms = _extract_category_terms(ingredient_name)
        for term in search_terms[1:]:  # Skip first (original name already tried)
            products = await _search_products(term, effective_store_id, limit=10)
            if products:
                break

    if not products:
        return {
            "error": True,
            "code": "NO_PRODUCTS_FOUND",
            "message": f"No products found matching '{ingredient_name}' at store {effective_store_id}.",
            "store_id": effective_store_id,
        }

    # Check if best match is available
    best_match = products[0]
    if best_match.get("available", False):
        # Best match is available - no substitution needed
        return {
            "substitution_needed": False,
            "product": {
                "product_id": best_match.get("product_id"),
                "sku": best_match.get("sku"),
                "name": best_match.get("name"),
                "brand": best_match.get("brand"),
                "price": best_match.get("price"),
                "available": True,
            },
            "message": "Best matching product is available. No substitution needed.",
            "store_id": effective_store_id,
        }

    # Best match is unavailable - find substitutes
    unavailable_product = {
        "name": best_match.get("name"),
        "brand": best_match.get("brand"),
        "size": best_match.get("size"),
        "category_path": best_match.get("category_path"),
        "product_id": best_match.get("product_id"),
        "sku": best_match.get("sku"),
    }

    # Gather candidates - other products that ARE available
    candidates = [p for p in products if p.get("available", False)]

    # If no available candidates in initial search, try broader category search
    if not candidates:
        search_terms = _extract_category_terms(ingredient_name)
        for term in search_terms:
            additional_products = await _search_products(term, effective_store_id, limit=10)
            for p in additional_products:
                if p.get("available", False) and p.get("product_id") not in [
                    c.get("product_id") for c in candidates
                ]:
                    candidates.append(p)
            if len(candidates) >= 5:
                break

    if not candidates:
        return {
            "substitution_needed": True,
            "unavailable_product": unavailable_product,
            "recommended": None,
            "alternatives": [],
            "no_good_substitute": True,
            "warning": "No available substitute products found in this category.",
            "store_id": effective_store_id,
        }

    # Build ingredient info for Claude
    original_ingredient = {
        "name": ingredient_name,
        "amount": ingredient_amount or "",
        "unit": "",
        "tags": ingredient_tags or [],
    }

    # Parse amount/unit if provided together
    if ingredient_amount:
        parts = ingredient_amount.split(maxsplit=1)
        if len(parts) == 2:
            original_ingredient["amount"] = parts[0]
            original_ingredient["unit"] = parts[1]
        else:
            original_ingredient["amount"] = ingredient_amount

    # Import and call Claude evaluation
    try:
        from claude import evaluate_substitutes

        result = evaluate_substitutes(
            original_ingredient=original_ingredient,
            recipe_context=recipe_context,
            unavailable_product=unavailable_product,
            candidates=candidates,
        )
    except ImportError as e:
        logger.error("Failed to import claude module", error=str(e))
        # Fallback if import fails
        fallback = candidates[0]
        result = {
            "recommended": {
                "product_id": fallback.get("product_id"),
                "sku": fallback.get("sku"),
                "name": fallback.get("name"),
                "reason": "Claude unavailable — category match only",
            },
            "alternatives": [],
            "no_good_substitute": False,
            "warning": "Review suggested substitute — AI evaluation unavailable",
            "fallback_used": True,
        }
    except Exception as e:
        logger.error("Claude evaluation failed", error=str(e))
        fallback = candidates[0]
        result = {
            "recommended": {
                "product_id": fallback.get("product_id"),
                "sku": fallback.get("sku"),
                "name": fallback.get("name"),
                "reason": "Claude unavailable — category match only",
            },
            "alternatives": [],
            "no_good_substitute": False,
            "warning": "Review suggested substitute — AI evaluation unavailable",
            "fallback_used": True,
        }

    # Build response
    response: dict[str, Any] = {
        "substitution_needed": True,
        "unavailable_product": unavailable_product,
        "recommended": result.get("recommended"),
        "alternatives": result.get("alternatives", []),
        "no_good_substitute": result.get("no_good_substitute", False),
        "warning": result.get("warning"),
        "store_id": effective_store_id,
        "candidates_evaluated": len(candidates),
    }

    if result.get("fallback_used"):
        response["fallback_used"] = True
        response["note"] = (
            "Claude AI was unavailable. Recommendation is based on category match only. "
            "Please verify the substitute is appropriate for your recipe."
        )

    # Add cart usage instructions if we have a recommendation
    if result.get("recommended"):
        rec = result["recommended"]
        response["cart_usage"] = {
            "instructions": "To add the recommended substitute to cart:",
            "example": f"cart_add(product_id='{rec.get('product_id')}', sku_id='{rec.get('sku')}', quantity=1, confirm=True)",
        }

    logger.info(
        "Substitution result",
        ingredient=ingredient_name,
        has_recommendation=result.get("recommended") is not None,
        no_good_substitute=result.get("no_good_substitute", False),
        fallback_used=result.get("fallback_used", False),
    )

    return response
