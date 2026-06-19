"""Cart-related MCP tools with human-in-the-loop confirmation."""

from typing import TYPE_CHECKING, Annotated, Any

from pydantic import Field

from texas_grocery_mcp.auth.session import (
    check_auth,
    ensure_session,
    get_auth_instructions,
    is_authenticated,
)
from texas_grocery_mcp.state import StateManager

if TYPE_CHECKING:
    from texas_grocery_mcp.clients.graphql import HEBGraphQLClient


def _get_client() -> "HEBGraphQLClient":
    """Get or create GraphQL client."""
    return StateManager.get_graphql_client_sync()


def _extract_sku_from_cart_item(item: dict[str, Any]) -> str | None:
    """Extract SKU ID from a cart item.

    Cart items have SKU in multiple possible locations.
    """
    # Primary: item.sku.id (nested object)
    sku_obj = item.get("sku", {})
    if isinstance(sku_obj, dict):
        sku_id = sku_obj.get("id")
        if sku_id:
            return str(sku_id)

    # Fallback: direct skuId field
    sku_id = item.get("skuId") or item.get("sku_id")
    if sku_id:
        return str(sku_id)

    # Fallback: product's SKUs array
    product = item.get("product", {})
    skus = product.get("SKUs", []) or product.get("skus", [])
    if skus and isinstance(skus[0], dict):
        sku_id = skus[0].get("id") or skus[0].get("skuId")
        if sku_id:
            return str(sku_id)

    return None


def _extract_price_from_cart_item(item: dict[str, Any]) -> float:
    """Extract price from a cart item.

    Prices can be in multiple locations depending on API response.
    """
    # Primary: item.price.amount
    price_obj = item.get("price", {})
    if isinstance(price_obj, dict):
        amount = price_obj.get("amount")
        if amount is not None:
            return float(amount)

    # Fallback: item.unitPrice
    unit_price = item.get("unitPrice")
    if unit_price is not None:
        return float(unit_price)

    # Fallback: item.listPrice.amount
    list_price = item.get("listPrice", {})
    if isinstance(list_price, dict):
        amount = list_price.get("amount")
        if amount is not None:
            return float(amount)

    # Fallback: product's price
    product = item.get("product", {})

    # product.price
    prod_price = product.get("price")
    if prod_price is not None:
        if isinstance(prod_price, dict):
            amount = prod_price.get("amount")
            if amount is not None:
                return float(amount)
        else:
            try:
                return float(prod_price)
            except (TypeError, ValueError):
                pass

    # product.SKUs[0].contextPrices
    skus = product.get("SKUs", []) or product.get("skus", [])
    if skus and isinstance(skus[0], dict):
        context_prices = skus[0].get("contextPrices", [])
        for ctx in context_prices:
            if ctx.get("context") in ("CURBSIDE", "CURBSIDE_PICKUP", "ONLINE"):
                sale_price = ctx.get("salePrice", {})
                list_price_ctx = ctx.get("listPrice", {})
                amount = None
                if isinstance(sale_price, dict):
                    amount = sale_price.get("amount")
                if amount is None and isinstance(list_price_ctx, dict):
                    amount = list_price_ctx.get("amount")
                if amount is not None:
                    return float(amount)

    return 0.0


def cart_check_auth() -> dict[str, Any]:
    """Check if authenticated for cart operations.

    Returns authentication status and instructions if not authenticated.
    Use this before attempting cart operations.
    """
    return check_auth()


@ensure_session
async def cart_add(
    product_id: Annotated[
        str,
        Field(
            description="HEB product ID (short numeric ID from search results)",
            min_length=1,
        ),
    ],
    sku_id: Annotated[
        str | None,
        Field(
            description=(
                "SKU ID (longer numeric ID). If not provided, uses product_id for both."
            )
        ),
    ] = None,
    quantity: Annotated[
        int,
        Field(description="Quantity to add", ge=1, le=99),
    ] = 1,
    confirm: Annotated[
        bool, Field(description="Set to true to confirm the action")
    ] = False,
) -> dict[str, Any]:
    """Add an item to the shopping cart with verification.

    Without confirm=true, returns a preview of the action.
    With confirm=true, executes the action and VERIFIES it worked.

    IMPORTANT: Use both product_id and sku_id from product_search results:
    - product_id: shorter ID (e.g., '127074')
    - sku_id: longer ID (e.g., '4122071073')

    Returns error if item wasn't actually added to cart.
    """
    # Validate product_id
    product_id = product_id.strip()
    if not product_id:
        return {
            "error": True,
            "code": "INVALID_PRODUCT_ID",
            "message": "Product ID cannot be empty or whitespace.",
        }

    # Use sku_id if provided, otherwise fall back to product_id
    effective_sku_id = (sku_id.strip() if sku_id else None) or product_id

    # Check authentication first
    if not is_authenticated():
        return {
            "auth_required": True,
            "message": "Login required for cart operations",
            "instructions": get_auth_instructions(),
        }

    # If not confirmed, return preview
    if not confirm:
        return {
            "preview": True,
            "action": "add_to_cart",
            "product_id": product_id,
            "sku_id": effective_sku_id,
            "quantity": quantity,
            "message": "Set confirm=true to add this item to cart",
            "note": (
                "Ensure product_id is the SHORT ID and sku_id is the LONG ID from "
                "product_search"
            ),
        }

    client = _get_client()

    try:
        # Get cart state BEFORE adding (to compare later)
        cart_before = await client.get_cart()
        items_before: set[str] = set()
        if not cart_before.get("error"):
            cart_data = cart_before.get("cartV2", {})
            for item in cart_data.get("items", []):
                item_sku = _extract_sku_from_cart_item(item)
                if item_sku:
                    items_before.add(item_sku)

        # Execute cart addition via GraphQL API
        result = await client.add_to_cart(
            product_id=product_id,
            sku_id=effective_sku_id,
            quantity=quantity,
        )

        if result.get("error"):
            return result

        # VERIFY: Get cart state AFTER adding
        cart_after = await client.get_cart()
        if cart_after.get("error"):
            return {
                "warning": True,
                "code": "VERIFICATION_UNAVAILABLE",
                "message": (
                    "Item may have been added, but verification failed (could not fetch cart)."
                ),
                "product_id": product_id,
                "sku_id": effective_sku_id,
                "quantity": quantity,
            }

        # Check if item is now in cart
        cart_data_after = cart_after.get("cartV2", {})
        item_found = False
        item_quantity = 0

        for item in cart_data_after.get("items", []):
            item_sku = _extract_sku_from_cart_item(item)
            item_product_id = item.get("product", {}).get("id")

            # Match by either SKU or product_id
            if item_sku == effective_sku_id or item_product_id == product_id:
                item_found = True
                item_quantity = item.get("quantity", 0)
                break

        if not item_found:
            # Item not in cart - the add failed silently
            return {
                "error": True,
                "code": "CART_ADD_NOT_VERIFIED",
                "message": (
                    "Item was NOT added to cart. The API returned success but the item "
                    "is not in your cart. This usually means the product_id/sku_id format is wrong."
                ),
                "product_id": product_id,
                "sku_id": effective_sku_id,
                "quantity": quantity,
                "troubleshooting": [
                    "1. Ensure product_id is the SHORT numeric ID (e.g., '127074')",
                    "2. Ensure sku_id is the LONGER numeric ID (e.g., '4122071073')",
                    "3. Both IDs come from product_search results",
                    "4. The product may be out of stock at your selected store",
                ],
                "suggestion": (
                    "Run product_search again and use the exact product_id and sku values "
                    "returned."
                ),
            }

        # SUCCESS - Item verified in cart
        return {
            "success": True,
            "verified": True,
            "action": "add_to_cart",
            "product_id": product_id,
            "sku_id": effective_sku_id,
            "quantity": quantity,
            "cart_quantity": item_quantity,
            "message": f"Added {quantity}x product to cart (verified)",
        }

    except Exception as e:
        return {
            "error": True,
            "code": "CART_ADD_FAILED",
            "message": f"Failed to add item to cart: {e!s}",
        }


@ensure_session
async def cart_remove(
    product_id: Annotated[
        str,
        Field(description="Product SKU/ID to remove", min_length=1),
    ],
    sku_id: Annotated[
        str | None,
        Field(
            description=(
                "SKU ID if known (will be looked up from cart if not provided)"
            )
        ),
    ] = None,
    confirm: Annotated[
        bool, Field(description="Set to true to confirm the action")
    ] = False,
) -> dict[str, Any]:
    """Remove an item from the shopping cart.

    Without confirm=true, returns a preview of the action.
    With confirm=true, executes the action.
    """
    # Validate product_id
    product_id = product_id.strip()
    if not product_id:
        return {
            "error": True,
            "code": "INVALID_PRODUCT_ID",
            "message": "Product ID cannot be empty or whitespace.",
        }

    if not is_authenticated():
        return {
            "auth_required": True,
            "message": "Login required for cart operations",
            "instructions": get_auth_instructions(),
        }

    # If sku_id not provided, look it up from the cart
    effective_sku_id = sku_id.strip() if sku_id else None
    if not effective_sku_id:
        # Fetch cart to find the SKU ID for this product
        client = _get_client()
        try:
            cart_result = await client.get_cart()
            if not cart_result.get("error"):
                cart_data = cart_result.get("cartV2", {})
                items = cart_data.get("items", [])
                for item in items:
                    product = item.get("product", {})
                    if product.get("id") == product_id:
                        # Found the product - use helper to extract SKU
                        effective_sku_id = _extract_sku_from_cart_item(item)
                        break
        except Exception:
            pass  # Will fall back to using product_id

    # If still no SKU ID, use product_id as fallback
    if not effective_sku_id:
        effective_sku_id = product_id

    if not confirm:
        return {
            "preview": True,
            "action": "remove_from_cart",
            "product_id": product_id,
            "sku_id": effective_sku_id,
            "message": "Set confirm=true to remove this item from cart",
        }

    # Execute removal via setting quantity to 0
    client = _get_client()
    try:
        result = await client.add_to_cart(
            product_id=product_id,
            sku_id=effective_sku_id,
            quantity=0,  # Setting quantity to 0 removes the item
        )

        if result.get("error"):
            return result

        return {
            "success": True,
            "action": "remove_from_cart",
            "product_id": product_id,
            "sku_id": effective_sku_id,
            "message": f"Removed product {product_id} from cart",
        }
    except Exception as e:
        return {
            "error": True,
            "code": "CART_REMOVE_FAILED",
            "message": f"Failed to remove item from cart: {e!s}",
        }


@ensure_session
async def cart_get() -> dict[str, Any]:
    """Get current cart contents.

    Returns all items in the cart with quantities and prices.
    """
    if not is_authenticated():
        return {
            "auth_required": True,
            "message": "Login required to view cart",
            "instructions": get_auth_instructions(),
        }

    client = _get_client()
    try:
        result = await client.get_cart()

        if result.get("error"):
            return result

        # Parse cart data from GraphQL response
        cart_data = result.get("cartV2", {})
        items = cart_data.get("items", [])

        # Format items for response
        formatted_items = []
        subtotal = 0.0

        for item in items:
            product = item.get("product", {})
            quantity = item.get("quantity", 0)

            # Use helper for robust price extraction
            price = _extract_price_from_cart_item(item)
            item_total = price * quantity

            # Use helper for robust SKU extraction
            sku_id = _extract_sku_from_cart_item(item)

            formatted_items.append({
                "product_id": product.get("id"),
                "sku_id": sku_id,
                "name": product.get("displayName") or product.get("name"),
                "quantity": quantity,
                "price": price,
                "total": round(item_total, 2),
            })
            subtotal += item_total

        message = (
            f"Cart has {len(formatted_items)} item(s)"
            if formatted_items
            else "Cart is empty"
        )
        return {
            "items": formatted_items,
            "item_count": len(formatted_items),
            "subtotal": round(subtotal, 2),
            "message": message,
        }
    except Exception as e:
        return {
            "error": True,
            "code": "CART_GET_FAILED",
            "message": f"Failed to get cart: {e!s}",
        }


@ensure_session
async def cart_add_with_retry(
    product_id: Annotated[str, Field(description="HEB product ID", min_length=1)],
    sku_id: Annotated[str | None, Field(description="SKU ID")] = None,
    quantity: Annotated[int, Field(description="Quantity to add", ge=1, le=99)] = 1,
    confirm: Annotated[bool, Field(description="Set to true to confirm")] = False,
    auto_correct_ids: Annotated[
        bool, Field(description="Attempt to auto-correct IDs if add fails")
    ] = True,
) -> dict[str, Any]:
    """Add item to cart with automatic ID correction.

    If the initial add fails due to ID format issues and auto_correct_ids=True,
    this will search for the product and retry with the correct IDs.

    This is a more resilient version of cart_add that can recover from
    incorrect ID formats by looking up the product.
    """
    # First attempt with provided IDs
    result = await cart_add(
        product_id=product_id,
        sku_id=sku_id,
        quantity=quantity,
        confirm=confirm,
    )

    # If not confirming or if it succeeded, return result
    if not confirm or result.get("success") or result.get("preview"):
        return result

    # If failed with CART_ADD_NOT_VERIFIED and auto-correct is enabled
    if result.get("code") == "CART_ADD_NOT_VERIFIED" and auto_correct_ids:
        from texas_grocery_mcp.tools.product import product_search
        from texas_grocery_mcp.tools.store import get_default_store_id

        # Try to find product by searching with the SKU/product_id as query
        search_query = sku_id or product_id
        store_id = get_default_store_id()

        if not store_id:
            result["auto_correct_attempted"] = False
            result["auto_correct_reason"] = "No default store set"
            return result

        try:
            search_result = await product_search(
                query=search_query,
                store_id=store_id,
                limit=5,
            )

            products = search_result.get("products", [])
            if not products:
                result["auto_correct_attempted"] = True
                result["auto_correct_reason"] = f"No products found for '{search_query}'"
                return result

            # Find a product with valid IDs
            for product in products:
                correct_product_id = product.get("product_id")
                correct_sku = product.get("sku")

                # Skip if IDs are missing or are suggestion placeholders
                if not correct_product_id or str(correct_product_id).startswith("suggestion-"):
                    continue
                if not correct_sku or str(correct_sku).startswith("suggestion-"):
                    continue

                # Retry with corrected IDs
                retry_result = await cart_add(
                    product_id=correct_product_id,
                    sku_id=correct_sku,
                    quantity=quantity,
                    confirm=True,
                )

                if retry_result.get("success"):
                    retry_result["auto_corrected"] = True
                    retry_result["original_ids"] = {
                        "product_id": product_id,
                        "sku_id": sku_id,
                    }
                    retry_result["corrected_ids"] = {
                        "product_id": correct_product_id,
                        "sku_id": correct_sku,
                    }
                    return retry_result

            result["auto_correct_attempted"] = True
            result["auto_correct_reason"] = "Found products but retry still failed"

        except Exception as e:
            result["auto_correct_attempted"] = True
            result["auto_correct_reason"] = f"Search failed: {e!s}"

    return result


@ensure_session
async def cart_add_many(
    items: Annotated[
        list[dict[str, Any]],
        Field(
            description=(
                "List of items to add. Each item must have: "
                "product_id (short ID), sku_id (full SKU), quantity (>=1). "
                "Maximum 100 items per call."
            ),
        )
    ],
    confirm: Annotated[
        bool,
        Field(
            description=(
                "Set to True to execute the bulk add. "
                "Default False shows preview of items to be added."
            )
        )
    ] = False,
) -> dict[str, Any]:
    """Add multiple items to cart with a single confirmation.

    This is more efficient than calling cart_add multiple times and provides
    a single confirmation gate for the entire batch.

    IMPORTANT: This operation uses STRICT success semantics. If ANY item
    fails to add, the entire operation is reported as a FAILURE. Items that
    were successfully added will remain in the cart, but you'll receive
    a clear list of which items failed.

    Args:
        items: List of items, each with product_id, sku_id, and quantity
        confirm: Must be True to actually add items (human-in-the-loop safety)

    Returns:
        On success: All items added with details
        On failure: List of failed items with reasons (successful items stay in cart)
    """
    import structlog

    logger = structlog.get_logger()

    # Validate item count
    if not items:
        return {
            "error": True,
            "code": "NO_ITEMS",
            "message": "No items provided. Provide a list of items to add.",
        }

    if len(items) > 100:
        return {
            "error": True,
            "code": "TOO_MANY_ITEMS",
            "message": f"Maximum 100 items per call. You provided {len(items)}.",
        }

    # Check authentication
    if not is_authenticated():
        return {
            "auth_required": True,
            "message": "Login required for cart operations",
            "instructions": get_auth_instructions(),
        }

    # Validate each item and build normalized list
    validated_items = []
    validation_errors = []

    for idx, item in enumerate(items):
        item_errors = []

        # Check required fields
        product_id = item.get("product_id")
        sku_id = item.get("sku_id")
        quantity = item.get("quantity")

        if not product_id:
            item_errors.append("missing product_id")
        elif not str(product_id).strip():
            item_errors.append("product_id is empty")

        if not sku_id:
            item_errors.append("missing sku_id")
        elif not str(sku_id).strip():
            item_errors.append("sku_id is empty")

        if quantity is None:
            item_errors.append("missing quantity")
        elif not isinstance(quantity, int) or quantity < 1:
            item_errors.append("quantity must be integer >= 1")
        elif quantity > 99:
            item_errors.append("quantity must be <= 99")

        if item_errors:
            validation_errors.append({
                "index": idx,
                "item": item,
                "errors": item_errors,
            })
        else:
            validated_items.append({
                "product_id": str(product_id).strip(),
                "sku_id": str(sku_id).strip(),
                "quantity": quantity,
            })

    # Return validation errors if any
    if validation_errors:
        return {
            "error": True,
            "code": "VALIDATION_ERROR",
            "message": f"{len(validation_errors)} item(s) have validation errors.",
            "validation_errors": validation_errors,
            "valid_items": len(validated_items),
        }

    # Preview mode - return what would be added
    if not confirm:
        return {
            "preview": True,
            "items_to_add": validated_items,
            "count": len(validated_items),
            "message": (
                f"Review {len(validated_items)} item(s) above. Call with confirm=True "
                "to add all to cart."
            ),
        }

    # Execute mode - add all items
    client = _get_client()

    # Get cart state before (for verification)
    cart_before = await client.get_cart()
    items_before: dict[str, int] = {}  # sku -> quantity
    if not cart_before.get("error"):
        cart_data = cart_before.get("cartV2", {})
        for cart_item in cart_data.get("items", []):
            item_sku = _extract_sku_from_cart_item(cart_item)
            if item_sku:
                items_before[item_sku] = cart_item.get("quantity", 0)

    # Track results
    added_items = []
    failed_items = []

    # Add items one by one (respecting throttling)
    for item in validated_items:
        product_id = item["product_id"]
        sku_id = item["sku_id"]
        quantity = item["quantity"]

        try:
            result = await client.add_to_cart(
                product_id=product_id,
                sku_id=sku_id,
                quantity=quantity,
            )

            if result.get("error"):
                failed_items.append({
                    "product_id": product_id,
                    "sku_id": sku_id,
                    "quantity": quantity,
                    "error": result.get("message", "Add failed"),
                    "code": result.get("code", "ADD_FAILED"),
                })
            else:
                # Tentatively mark as added (will verify later)
                added_items.append({
                    "product_id": product_id,
                    "sku_id": sku_id,
                    "quantity": quantity,
                })

        except Exception as e:
            logger.warning(
                "cart_add_many item failed",
                product_id=product_id,
                error=str(e),
            )
            failed_items.append({
                "product_id": product_id,
                "sku_id": sku_id,
                "quantity": quantity,
                "error": str(e),
                "code": "EXCEPTION",
            })

    # Verify items in cart after all adds
    cart_after = await client.get_cart()
    if not cart_after.get("error"):
        cart_data = cart_after.get("cartV2", {})
        items_after: dict[str, dict[str, Any]] = {}  # sku -> {quantity, name, price}

        for cart_item in cart_data.get("items", []):
            item_sku = _extract_sku_from_cart_item(cart_item)
            if item_sku:
                product = cart_item.get("product", {})
                items_after[item_sku] = {
                    "quantity": cart_item.get("quantity", 0),
                    "name": product.get("displayName") or product.get("name"),
                    "price": _extract_price_from_cart_item(cart_item),
                }

        # Verify each "added" item is actually in the cart
        verified_added = []
        for item in added_items:
            sku_id = item["sku_id"]
            if sku_id in items_after:
                cart_info = items_after[sku_id]
                verified_added.append({
                    "product_id": item["product_id"],
                    "sku_id": sku_id,
                    "name": cart_info["name"],
                    "quantity": item["quantity"],
                    "cart_quantity": cart_info["quantity"],
                    "price": cart_info["price"],
                    "line_total": round(cart_info["price"] * cart_info["quantity"], 2),
                })
            else:
                # Item wasn't actually added
                failed_items.append({
                    "product_id": item["product_id"],
                    "sku_id": sku_id,
                    "quantity": item["quantity"],
                    "error": "Item not found in cart after add (verification failed)",
                    "code": "VERIFICATION_FAILED",
                })

        added_items = verified_added

    # Calculate totals
    total_cost = sum(item.get("line_total", 0) for item in added_items)

    # Build summary
    summary = {
        "requested": len(validated_items),
        "added": len(added_items),
        "failed": len(failed_items),
        "total_cost": round(total_cost, 2),
    }

    # Determine success/failure (strict: any failure = operation failure)
    if failed_items:
        return {
            "success": False,
            "error": True,
            "code": "PARTIAL_FAILURE",
            "message": (
                f"{len(failed_items)} of {len(validated_items)} item(s) could not be added "
                "to cart."
            ),
            "added": added_items,
            "failed": failed_items,
            "summary": summary,
            "note": (
                "Successfully added items remain in cart. Review failed items and retry if "
                "needed."
            ),
        }

    # All items added successfully
    return {
        "success": True,
        "added": added_items,
        "summary": summary,
        "message": f"All {len(added_items)} item(s) added to cart successfully.",
    }
