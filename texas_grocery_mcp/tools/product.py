"""Product-related MCP tools."""

from typing import TYPE_CHECKING, Annotated, Any, Literal

import structlog
from pydantic import Field

from texas_grocery_mcp.auth.session import ensure_session
from texas_grocery_mcp.state import StateManager

logger = structlog.get_logger()

if TYPE_CHECKING:
    from texas_grocery_mcp.clients.graphql import HEBGraphQLClient


def _get_client() -> "HEBGraphQLClient":
    """Get or create GraphQL client."""
    return StateManager.get_graphql_client_sync()


def get_default_store_id() -> str | None:
    """Get default store ID."""
    return StateManager.get_default_store_id()


@ensure_session
async def product_search(
    query: Annotated[
        str,
        Field(
            description="Search query (e.g., 'milk', 'chicken breast')",
            min_length=1,
        ),
    ],
    store_id: Annotated[
        str | None,
        Field(
            description="Store ID for pricing/availability. Uses default if not provided."
        ),
    ] = None,
    limit: Annotated[
        int, Field(description="Maximum results to return", ge=1, le=50)
    ] = 20,
    fields: Annotated[
        list[Literal["minimal", "standard", "all"]] | None,
        Field(
            description=(
                "Field set to return: minimal (sku, name, price), "
                "standard (+brand, size, image), all (+nutrition)"
            )
        ),
    ] = None,
) -> dict[str, Any]:
    """Search for products at an HEB store.

    Returns products matching the query with pricing and availability
    for the specified store.
    """
    # Validate query
    query = query.strip()
    if not query:
        return {
            "error": True,
            "code": "INVALID_QUERY",
            "message": "Search query cannot be empty or whitespace.",
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

    client = _get_client()
    search_result = await client.search_products(
        query=query,
        store_id=effective_store_id,
        limit=limit,
    )

    # Determine field set (default to standard)
    field_set = (fields or ["standard"])[0] if fields else "standard"

    result_products = []
    for p in search_result.products:
        # Always include both IDs at the top for cart operations
        product_data: dict[str, Any] = {
            "product_id": p.product_id,  # Short ID - REQUIRED for cart_add
            "sku": p.sku,                # Long ID - REQUIRED for cart_add as sku_id
            "name": p.name,
            "price": p.price,
            "available": p.available,
            "has_coupon": p.has_coupon,  # Coupon availability flag
        }

        # Warn if product_id is missing (typeahead fallback)
        if not p.product_id or p.product_id.startswith("suggestion-"):
            product_data["_warning"] = (
                "No product_id available - cannot add to cart. "
                "Try a more specific search or refresh session."
            )

        if field_set in ("standard", "all"):
            product_data.update({
                "brand": p.brand,
                "size": p.size,
                "price_per_unit": p.price_per_unit,
                "image_url": p.image_url,
                "aisle": p.aisle,
                "section": p.section,
            })

        if field_set == "all":
            product_data.update({
                "nutrition": p.nutrition.model_dump() if p.nutrition else None,
                "ingredients": p.ingredients,
                "on_sale": p.on_sale,
                "original_price": p.original_price,
                "rating": p.rating,
            })

        result_products.append(product_data)

    # Build response with diagnostic information
    result: dict[str, Any] = {
        "products": result_products,
        "count": len(result_products),
        "store_id": effective_store_id,
        "query": query,
        "data_source": search_result.data_source,
        "authenticated": search_result.authenticated,
    }

    # Add search URL for manual verification
    if search_result.search_url:
        result["search_url"] = search_result.search_url

    # Add diagnostic fields when fallback was used
    if search_result.data_source == "typeahead_suggestions":
        result["note"] = (
            "These are search suggestions only (no prices/inventory). "
            f"Reason: {search_result.fallback_reason or 'SSR search unsuccessful'}. "
        )
        result["auth_required_for_full_data"] = not search_result.authenticated

    # Add security challenge information
    if search_result.security_challenge_detected:
        result["security_challenge_detected"] = True
        result["note"] = (
            "Security challenge (WAF/captcha) blocked API requests. "
            "Use session_refresh tool or Playwright MCP to refresh your session."
        )

    # Add fallback reason if present
    if search_result.fallback_reason:
        result["fallback_reason"] = search_result.fallback_reason

    # Add Playwright fallback instructions when available
    if search_result.playwright_fallback_available and search_result.playwright_instructions:
        result["playwright_fallback"] = {
            "available": True,
            "instructions": search_result.playwright_instructions,
        }

    # Add search attempts for debugging (summarized)
    if search_result.attempts:
        result["attempts_summary"] = {
            "total": len(search_result.attempts),
            "successful": sum(
                1 for a in search_result.attempts if a.result == "success"
            ),
            "security_challenges": sum(
                1
                for a in search_result.attempts
                if a.result == "security_challenge"
            ),
            "empty": sum(1 for a in search_result.attempts if a.result == "empty"),
            "errors": sum(1 for a in search_result.attempts if a.result == "error"),
        }

    # Add cart usage instructions when products with valid IDs are found
    valid_products = [
        p for p in result_products
        if p.get("product_id") and not str(p.get("product_id", "")).startswith("suggestion-")
    ]
    if valid_products:
        result["cart_usage"] = {
            "instructions": "To add products to cart, use both IDs:",
            "example": "cart_add(product_id=<product_id>, sku_id=<sku>, quantity=1, confirm=True)",
            "note": "product_id is the shorter ID, sku is the longer ID",
        }

    return result


@ensure_session
async def product_search_batch(
    queries: Annotated[
        list[str],
        Field(description="List of search queries (e.g., ['milk', 'eggs', 'bread'])"),
    ],
    store_id: Annotated[
        str | None,
        Field(description="Store ID for pricing/availability. Uses default if not provided."),
    ] = None,
    limit_per_query: Annotated[
        int,
        Field(description="Maximum results per query", ge=1, le=20),
    ] = 5,
) -> dict[str, Any]:
    """Search for multiple products at once.

    More efficient than calling product_search multiple times.
    Handles throttling internally to prevent rate limiting.

    Returns results for each query, with availability at the specified store.
    """
    # Validate queries
    if not queries:
        return {
            "error": "No queries provided",
            "results": [],
        }

    if len(queries) > 20:
        return {
            "error": "Maximum 20 queries per batch",
            "results": [],
        }

    # Resolve store ID
    effective_store_id = store_id or get_default_store_id()

    if not effective_store_id:
        return {
            "error": (
                "No store_id provided and no default store set. Use store_search to find "
                "a store."
            ),
            "results": [],
        }

    client = _get_client()
    results = []
    successful = 0
    failed = 0

    # Process queries sequentially (throttling happens inside client)
    for query in queries:
        query = query.strip()
        if not query:
            results.append({
                "query": query,
                "success": False,
                "error": "Empty query",
                "products": [],
            })
            failed += 1
            continue

        try:
            search_result = await client.search_products(
                query=query,
                store_id=effective_store_id,
                limit=limit_per_query,
            )

            # Extract product data
            product_list = []
            for p in search_result.products[:limit_per_query]:
                product_dict = {
                    "product_id": p.product_id,  # Short ID for cart_add
                    "sku": p.sku,                # Long ID for cart_add as sku_id
                    "name": p.name,
                    "price": p.price,
                    "available": p.available,
                    "brand": p.brand,
                    "size": p.size,
                }
                # Warn if IDs are missing (typeahead fallback)
                if not p.product_id or p.product_id.startswith("suggestion-"):
                    product_dict["_warning"] = "Cannot add to cart - missing product_id"
                product_list.append(product_dict)

            results.append({
                "query": query,
                "success": True,
                "products": product_list,
                "count": len(product_list),
                "data_source": search_result.data_source,
            })
            successful += 1

        except Exception as e:
            logger.warning(
                "Batch search query failed",
                query=query,
                error=str(e),
            )
            results.append({
                "query": query,
                "success": False,
                "error": str(e),
                "products": [],
            })
            failed += 1

    return {
        "results": results,
        "summary": {
            "total_queries": len(queries),
            "successful": successful,
            "failed": failed,
            "store_id": effective_store_id,
        },
    }


@ensure_session
async def product_get(
    product_id: Annotated[
        str,
        Field(description="Product ID from product_search results (e.g., '127074')")
    ],
    store_id: Annotated[
        str | None,
        Field(description="Store ID for pricing/availability. Uses default if not provided.")
    ] = None,
) -> dict[str, Any]:
    """Get comprehensive details for a single product.

    Returns detailed product information including:
    - Full description
    - Complete ingredients text
    - Safety/allergen warnings
    - Nutritional information (full FDA panel for packaged food)
    - Storage and preparation instructions
    - Dietary attributes (Gluten-Free, Organic, Vegan, etc.)
    - Store location (aisle or section)

    Use this when you need more information than product_search provides,
    such as checking ingredients for dietary restrictions or allergens.

    Args:
        product_id: The product ID from product_search results
        store_id: Optional store ID for store-specific pricing

    Returns:
        Comprehensive product details or error response
    """
    # Validate product_id
    if not product_id or not product_id.strip():
        return {
            "error": True,
            "code": "INVALID_PRODUCT_ID",
            "message": "Product ID cannot be empty.",
        }

    product_id = product_id.strip()

    # Warn if it looks like a suggestion ID (not a real product)
    if product_id.startswith("suggestion-"):
        return {
            "error": True,
            "code": "INVALID_PRODUCT_ID",
            "message": (
                "This is a search suggestion, not a real product ID. Use product_search "
                "with a more specific query to get real product IDs."
            ),
        }

    # Resolve store ID
    effective_store_id = store_id or get_default_store_id()

    client = _get_client()

    try:
        details = await client.get_product_details(
            product_id=product_id,
            store_id=effective_store_id,
        )

        if not details:
            return {
                "error": True,
                "code": "PRODUCT_NOT_FOUND",
                "message": f"Product with ID '{product_id}' not found.",
                "suggestion": (
                    "Verify the product_id from product_search results. Product IDs are "
                    "numeric (e.g., '127074')."
                ),
            }

        # Convert to dict, excluding None values for cleaner output
        result = details.model_dump(exclude_none=True)

        # Convert nutrition to dict if present
        if details.nutrition:
            result["nutrition"] = details.nutrition.model_dump(exclude_none=True)

        # Add helpful metadata
        result["_meta"] = {
            "store_id": effective_store_id,
            "source": "ssr_product_detail",
        }

        # Add cart usage hint
        result["cart_usage"] = {
            "instructions": "To add this product to cart:",
            "example": (
                f"cart_add(product_id='{details.product_id}', sku_id='{details.sku}', "
                "quantity=1, confirm=True)"
            ),
        }

        return result

    except Exception as e:
        logger.error(
            "Error getting product details",
            product_id=product_id,
            error=str(e),
        )
        return {
            "error": True,
            "code": "FETCH_ERROR",
            "message": f"Error fetching product details: {str(e)}",
            "suggestion": "Try refreshing your session with session_refresh if this persists.",
        }
