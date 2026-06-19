"""Coupon-related MCP tools."""

from typing import TYPE_CHECKING, Annotated, Any

from pydantic import Field

from texas_grocery_mcp.auth.session import ensure_session, is_authenticated
from texas_grocery_mcp.state import StateManager

if TYPE_CHECKING:
    from texas_grocery_mcp.clients.graphql import HEBGraphQLClient

# Category name to ID mapping for convenience
CATEGORY_IDS = {
    "baby": 489924,
    "baby & kids": 489924,
    "bakery": 490014,
    "bakery & bread": 490014,
    "beverages": 490015,
    "dairy": 490016,
    "dairy & eggs": 490016,
    "deli": 490017,
    "deli & prepared food": 490017,
    "everyday": 490018,
    "everyday essentials": 490018,
    "frozen": 490019,
    "frozen food": 490019,
    "produce": 490020,
    "fruit & vegetables": 490020,
    "health": 490021,
    "health & beauty": 490021,
    "beauty": 490021,
    "home": 490022,
    "home & outdoor": 490022,
    "meat": 490023,
    "meat & seafood": 490023,
    "seafood": 490023,
    "pantry": 490024,
    "pets": 490025,
}


def _get_client() -> "HEBGraphQLClient":
    """Get or create GraphQL client."""
    return StateManager.get_graphql_client_sync()


def _resolve_category(category: str | None) -> int | None:
    """Resolve category name to ID.

    Args:
        category: Category name or ID

    Returns:
        Category ID or None
    """
    if not category:
        return None

    # If it's already a number, use it
    if category.isdigit():
        return int(category)

    # Look up by name (case-insensitive)
    return CATEGORY_IDS.get(category.lower())


@ensure_session
async def coupon_list(
    category: Annotated[
        str | None,
        Field(
            description="Filter by category name (e.g., 'pantry', 'health & beauty') or ID"
        ),
    ] = None,
    limit: Annotated[
        int,
        Field(description="Maximum coupons to return", ge=1, le=60),
    ] = 20,
) -> dict[str, Any]:
    """List available HEB digital coupons.

    Returns coupons with discount details, descriptions, and expiration dates.
    Filter by category to find coupons in specific departments.
    """
    # Check authentication
    if not is_authenticated():
        return {
            "error": True,
            "code": "AUTH_REQUIRED",
            "message": (
                "Authentication required to view coupons. Use session_save_instructions "
                "to log in."
            ),
            "coupons": [],
            "count": 0,
        }

    # Resolve category
    category_id = _resolve_category(category)

    client = _get_client()
    result = await client.get_coupons(
        category_id=category_id,
        limit=limit,
    )

    # Format response
    coupons_data = []
    for c in result.coupons:
        coupon_dict = {
            "coupon_id": c.coupon_id,
            "headline": c.headline,
            "description": c.description,
            "expires": c.expires_display or c.expires,
            "type": c.coupon_type,
            "clipped": c.clipped,
            "usage_limit": c.usage_limit,
        }

        # Add optional fields if present
        if c.image_url:
            coupon_dict["image_url"] = c.image_url
        if c.digital_only:
            coupon_dict["digital_only"] = True

        coupons_data.append(coupon_dict)

    response = {
        "coupons": coupons_data,
        "count": result.count,
        "total": result.total,
    }

    # Include categories in first request
    if result.categories:
        response["categories"] = [
            {"name": cat.name, "id": cat.id, "count": cat.count}
            for cat in result.categories
        ]

    if category:
        response["filtered_by"] = category

    return response


@ensure_session
async def coupon_search(
    query: Annotated[
        str,
        Field(description="Search term (e.g., 'chips', 'dove', '25% off')", min_length=1),
    ],
    limit: Annotated[
        int,
        Field(description="Maximum coupons to return", ge=1, le=60),
    ] = 20,
) -> dict[str, Any]:
    """Search for HEB coupons by keyword.

    Search for coupons by product name, brand, or discount type.
    """
    # Check authentication
    if not is_authenticated():
        return {
            "error": True,
            "code": "AUTH_REQUIRED",
            "message": (
                "Authentication required to search coupons. Use session_save_instructions "
                "to log in."
            ),
            "coupons": [],
            "count": 0,
        }

    query = query.strip()
    if not query:
        return {
            "error": True,
            "code": "INVALID_QUERY",
            "message": "Search query cannot be empty.",
            "coupons": [],
            "count": 0,
        }

    client = _get_client()
    result = await client.get_coupons(
        search_query=query,
        limit=limit,
    )

    # Format response
    coupons_data = []
    for c in result.coupons:
        coupon_dict = {
            "coupon_id": c.coupon_id,
            "headline": c.headline,
            "description": c.description,
            "expires": c.expires_display or c.expires,
            "type": c.coupon_type,
            "clipped": c.clipped,
            "usage_limit": c.usage_limit,
        }

        if c.image_url:
            coupon_dict["image_url"] = c.image_url
        if c.digital_only:
            coupon_dict["digital_only"] = True

        coupons_data.append(coupon_dict)

    return {
        "coupons": coupons_data,
        "count": result.count,
        "total": result.total,
        "query": query,
    }


@ensure_session
async def coupon_categories() -> dict[str, Any]:
    """Get available coupon categories/departments.

    Returns a list of categories with the number of coupons in each.
    Use category names with coupon_list to filter coupons.
    """
    # Check authentication
    if not is_authenticated():
        return {
            "error": True,
            "code": "AUTH_REQUIRED",
            "message": (
                "Authentication required to view coupon categories. Use "
                "session_save_instructions to log in."
            ),
            "categories": [],
        }

    client = _get_client()
    result = await client.get_coupons(limit=1)  # Just need categories

    if not result.categories:
        return {
            "categories": [],
            "note": "No categories available. Try again later.",
        }

    categories_data = [
        {
            "name": cat.name,
            "id": cat.id,
            "count": cat.count,
        }
        for cat in sorted(result.categories, key=lambda x: x.name)
    ]

    return {
        "categories": categories_data,
        "total_coupons": result.total,
        "note": "Use category name with coupon_list to filter coupons.",
    }


@ensure_session
async def coupon_clip(
    coupon_id: Annotated[
        int,
        Field(description="Coupon ID to clip (from coupon_list or coupon_search)"),
    ],
    confirm: Annotated[
        bool,
        Field(description="Set to true to confirm the action"),
    ] = False,
) -> dict[str, Any]:
    """Clip a coupon to your HEB account.

    Without confirm=true, returns a preview of the action.
    With confirm=true, clips the coupon (requires authentication).

    Clipped coupons automatically apply at checkout when you buy eligible items.
    """
    # Check authentication
    if not is_authenticated():
        return {
            "error": True,
            "code": "AUTH_REQUIRED",
            "message": (
                "Authentication required to clip coupons. Use session_save_instructions "
                "to log in."
            ),
        }

    client = _get_client()

    # Without confirm, show preview
    if not confirm:
        # Try to get coupon details for preview
        coupons_result = await client.get_coupons(limit=60)
        coupon_info = None
        for c in coupons_result.coupons:
            if c.coupon_id == coupon_id:
                coupon_info = {
                    "coupon_id": c.coupon_id,
                    "headline": c.headline,
                    "description": c.description,
                    "expires": c.expires_display or c.expires,
                    "clipped": c.clipped,
                }
                break

        if coupon_info and coupon_info.get("clipped"):
            return {
                "preview": True,
                "coupon": coupon_info,
                "message": "This coupon is already clipped to your account.",
            }

        return {
            "preview": True,
            "coupon_id": coupon_id,
            "coupon": coupon_info,
            "message": "Ready to clip this coupon. Set confirm=true to proceed.",
        }

    # Execute clip
    clip_result = await client.clip_coupon(coupon_id)
    return clip_result


@ensure_session
async def coupon_clipped(
    limit: Annotated[
        int,
        Field(description="Maximum coupons to return", ge=1, le=60),
    ] = 20,
) -> dict[str, Any]:
    """List your clipped coupons.

    Returns all coupons you've clipped to your HEB account.
    Clipped coupons automatically apply at checkout when you buy eligible items.
    """
    # Check authentication
    if not is_authenticated():
        return {
            "error": True,
            "code": "AUTH_REQUIRED",
            "message": (
                "Authentication required to view clipped coupons. Use "
                "session_save_instructions to log in."
            ),
            "coupons": [],
            "count": 0,
        }

    client = _get_client()
    result = await client.get_clipped_coupons(limit=limit)

    # Format response
    coupons_data = []
    for c in result.coupons:
        coupon_dict = {
            "coupon_id": c.coupon_id,
            "headline": c.headline,
            "description": c.description,
            "expires": c.expires_display or c.expires,
            "type": c.coupon_type,
            "usage_limit": c.usage_limit,
        }

        if c.image_url:
            coupon_dict["image_url"] = c.image_url
        if c.digital_only:
            coupon_dict["digital_only"] = True

        coupons_data.append(coupon_dict)

    return {
        "clipped_coupons": coupons_data,
        "count": result.count,
        "total": result.total,
    }
