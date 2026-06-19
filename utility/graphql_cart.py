"""GraphQL-based cart orchestration for auto_grocier.

Performs product search, cart clearing, and add-to-cart operations directly
against HEB's internal GraphQL API via the vendored ``texas_grocery_mcp``
client, instead of driving the website with Selenium.

The public entry point is :func:`graphql_cart_sync`, a synchronous wrapper
that the main program can call after the Selenium login + auth export.
"""

import asyncio


def _build_search_term(ingredient):
    """Mirror the Selenium flow: prefix produce with 'organic'."""
    name = ingredient.get_name()
    tag = ingredient.get_tag()
    if tag in ("vegetable", "fruit"):
        return f"organic {name}"
    return name


def _extract_sku(item):
    """Extract a SKU id from a cart item (nested sku object or flat field)."""
    sku_obj = item.get("sku", {})
    if isinstance(sku_obj, dict) and sku_obj.get("id"):
        return str(sku_obj["id"])
    sku_id = item.get("skuId") or item.get("sku_id")
    return str(sku_id) if sku_id else None


async def _clear_cart(client):
    """Remove every item from the cart by setting its quantity to 0."""
    removed = 0
    try:
        cart = await client.get_cart()
    except Exception as e:  # noqa: BLE001
        print(f"    ⚠️  Could not fetch cart to clear: {e}")
        return removed

    if not isinstance(cart, dict) or cart.get("error"):
        print("    ⚠️  Cart not available for clearing (not authenticated?).")
        return removed

    cart_data = cart.get("cartV2", {}) or {}
    items = cart_data.get("items", []) or []
    for item in items:
        product = item.get("product", {}) or {}
        product_id = product.get("id")
        sku_id = _extract_sku(item) or product_id
        if not product_id:
            continue
        try:
            result = await client.add_to_cart(
                product_id=str(product_id), sku_id=str(sku_id), quantity=0
            )
            if not (isinstance(result, dict) and result.get("error")):
                removed += 1
        except Exception as e:  # noqa: BLE001
            print(f"    ⚠️  Failed to remove product {product_id}: {e}")

    print(f"    🧹 Cleared {removed} item(s) from cart.")
    return removed


async def _add_ingredient(client, ingredient, store_id):
    """Search for an ingredient and add the first available match to the cart.

    Returns a dict describing the outcome.
    """
    term = _build_search_term(ingredient)
    name = ingredient.get_name()

    try:
        search = await client.search_products(query=term, store_id=str(store_id), limit=20)
    except Exception as e:  # noqa: BLE001
        return {"ingredient": name, "term": term, "status": "search_error", "detail": str(e)}

    products = getattr(search, "products", []) or []
    if not products:
        return {"ingredient": name, "term": term, "status": "no_results"}

    # Prefer the first available product; fall back to the first result.
    chosen = next((p for p in products if getattr(p, "available", False)), products[0])

    product_id = getattr(chosen, "product_id", None)
    sku_id = getattr(chosen, "sku", None)
    if not product_id or not sku_id:
        return {"ingredient": name, "term": term, "status": "missing_ids"}

    try:
        result = await client.add_to_cart(
            product_id=str(product_id), sku_id=str(sku_id), quantity=1
        )
    except Exception as e:  # noqa: BLE001
        return {"ingredient": name, "term": term, "status": "add_error", "detail": str(e)}

    if isinstance(result, dict) and result.get("error"):
        return {
            "ingredient": name,
            "term": term,
            "status": "add_failed",
            "detail": result.get("message") or result.get("code"),
        }

    return {
        "ingredient": name,
        "term": term,
        "status": "added",
        "product": getattr(chosen, "name", None),
        "price": getattr(chosen, "price", None),
    }


async def run_graphql_cart_ops(ingredient_list, store_id, do_clear=True):
    """Run all GraphQL cart operations for the given ingredient list.

    Args:
        ingredient_list: IngredientList with the ingredients to add.
        store_id: HEB store id to operate against.
        do_clear: Whether to empty the cart before adding.

    Returns:
        A report dict: {"added": [...], "failed": [...], "cart": <get_cart result>}
    """
    # Imported lazily so the dependency is only required for GraphQL modes.
    from texas_grocery_mcp.clients.graphql import HEBGraphQLClient

    client = HEBGraphQLClient()
    added = []
    failed = []

    try:
        # Make sure the active store matches the one we search/price against.
        try:
            store_result = await client.select_store(str(store_id))
            if isinstance(store_result, dict) and store_result.get("error"):
                print(
                    f"    ⚠️  Could not select store {store_id}: "
                    f"{store_result.get('message') or store_result.get('code')}"
                )
        except Exception as e:  # noqa: BLE001
            print(f"    ⚠️  Store selection error: {e}")

        if do_clear:
            await _clear_cart(client)

        for ingredient in ingredient_list.get_ingredients():
            outcome = await _add_ingredient(client, ingredient, store_id)
            if outcome["status"] == "added":
                added.append(outcome)
                price = outcome.get("price")
                price_str = f" (${price})" if price is not None else ""
                print(f"    ✓ {outcome['ingredient']} -> {outcome.get('product')}{price_str}")
            else:
                failed.append(outcome)
                detail = outcome.get("detail")
                detail_str = f": {detail}" if detail else ""
                print(f"    ✗ {outcome['ingredient']} [{outcome['status']}]{detail_str}")

        try:
            cart = await client.get_cart()
        except Exception as e:  # noqa: BLE001
            cart = {"error": True, "message": str(e)}

        return {"added": added, "failed": failed, "cart": cart}
    finally:
        await client.close()


def graphql_cart_sync(ingredient_list, store_id, do_clear=True):
    """Synchronous wrapper around :func:`run_graphql_cart_ops`."""
    return asyncio.run(
        run_graphql_cart_ops(ingredient_list, store_id, do_clear=do_clear)
    )
