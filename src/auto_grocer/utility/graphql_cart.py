"""GraphQL-based cart orchestration for auto_grocer.

Performs product search, cart clearing, and add-to-cart operations directly
against HEB's internal GraphQL API via the vendored ``auto_grocer_mcp``
client, instead of driving the website with Selenium.

The public entry point is :func:`graphql_cart_sync`, a synchronous wrapper
that the main program can call after the Selenium login + auth export.
"""

import asyncio
import math
import re


def _build_search_term(ingredient):
    """Mirror the Selenium flow: prefix produce with 'organic'."""
    name = ingredient.get_name()
    tag = ingredient.get_tag()
    if tag in ("vegetable", "fruit"):
        return f"organic {name}"
    return name


# --- Package-size aware quantity scaling -----------------------------------
#
# The recipe knows how much it needs (e.g. "16 oz spinach"), and each search
# result advertises a package size (e.g. "5 oz"). We convert both to a common
# base unit, pick the product whose package size covers the need with the least
# waste, and add enough packages to reach the target amount.

_WEIGHT_TO_G = {
    "oz": 28.349523125, "ounce": 28.349523125, "ounces": 28.349523125,
    "lb": 453.59237, "lbs": 453.59237, "pound": 453.59237, "pounds": 453.59237,
    "g": 1.0, "gram": 1.0, "grams": 1.0,
    "kg": 1000.0, "kilogram": 1000.0, "kilograms": 1000.0,
    "mg": 0.001,
}
_VOLUME_TO_ML = {
    "tsp": 4.92892159, "teaspoon": 4.92892159, "teaspoons": 4.92892159,
    "tbsp": 14.7867648, "tablespoon": 14.7867648, "tablespoons": 14.7867648,
    "floz": 29.5735296, "fluid ounce": 29.5735296, "fluid ounces": 29.5735296,
    "cup": 236.588237, "cups": 236.588237,
    "pt": 473.176473, "pint": 473.176473, "pints": 473.176473,
    "qt": 946.352946, "quart": 946.352946, "quarts": 946.352946,
    "gal": 3785.411784, "gallon": 3785.411784, "gallons": 3785.411784,
    "ml": 1.0, "milliliter": 1.0, "milliliters": 1.0,
    "l": 1000.0, "liter": 1000.0, "liters": 1000.0, "litre": 1000.0, "litres": 1000.0,
}
_COUNT_TO_EACH = {
    "ct": 1.0, "count": 1.0, "each": 1.0, "ea": 1.0,
    "pk": 1.0, "pack": 1.0, "packs": 1.0, "dozen": 12.0,
}

_SIZE_RE = re.compile(
    r"(\d+(?:\.\d+)?)\s*"
    r"(fl\.?\s?oz|floz|fluid\s+ounces?|ounces?|oz|lbs?|pounds?|kilograms?|kg|grams?|g|"
    r"gallons?|gal|quarts?|qt|pints?|pt|cups?|tablespoons?|tbsp|teaspoons?|tsp|"
    r"milliliters?|ml|liters?|litres?|l|dozen|count|ct|each|ea|packs?|pk)\b",
    re.IGNORECASE,
)


def _safe_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _coerce_scalar(value, default):
    """clean_ingredient returns amount/unit as lists; recipes store scalars."""
    if isinstance(value, (list, tuple)):
        value = value[0] if value else default
    return value if value is not None else default


def _normalize_unit(unit):
    if not unit:
        return ""
    u = str(unit).strip().lower()
    u = u.replace("fl. oz", "floz").replace("fl oz", "floz").replace("fl.oz", "floz")
    return u


def _to_base(value, unit):
    """Convert (value, unit) to (base_value, family) or None if not convertible.

    Families: 'weight' (grams), 'volume' (ml), 'count' (each).
    """
    u = _normalize_unit(unit)
    if u in _WEIGHT_TO_G:
        return value * _WEIGHT_TO_G[u], "weight"
    if u in _VOLUME_TO_ML:
        return value * _VOLUME_TO_ML[u], "volume"
    if u in _COUNT_TO_EACH:
        return value * _COUNT_TO_EACH[u], "count"
    return None


def _parse_size(size_text):
    """Parse a product size string (e.g. 'Avg. 0.63 lb', '5 oz', '2 ct').

    Returns (base_value, family) or None when no usable size is found.
    """
    if not size_text:
        return None
    match = _SIZE_RE.search(str(size_text))
    if not match:
        return None
    return _to_base(_safe_float(match.group(1)), match.group(2))


def _choose_best_product(products, target_base, family):
    """Pick (product, packages) whose package size best covers the target.

    Only products with a parseable size in the same measurement family are
    considered. Available products are preferred, then least overshoot (waste),
    then fewest packages, then original search relevance. Returns None when no
    compatible size can be parsed.
    """
    best_key = None
    best = None
    for idx, product in enumerate(products):
        parsed = _parse_size(getattr(product, "size", None))
        if not parsed:
            continue
        size_base, fam = parsed
        if fam != family or size_base <= 0:
            continue
        packages = max(1, math.ceil(target_base / size_base)) if target_base > 0 else 1
        overshoot = packages * size_base - target_base
        avail_rank = 0 if getattr(product, "available", False) else 1
        key = (avail_rank, overshoot, packages, idx)
        if best_key is None or key < best_key:
            best_key = key
            best = (product, packages)
    return best


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


async def _add_ingredient(client, ingredient, store_id, quantity=1):
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

    # Decide how much to add. When the caller hasn't forced a quantity, scale by
    # the recipe amount vs. each product's package size to reach the target.
    # Whole-item counts (e.g. "2 onions") are intentionally NOT inferred here;
    # the caller requests the desired count explicitly via the quantity argument.
    add_qty = int(quantity)
    chosen = None
    if int(quantity) == 1:
        amount_val = _safe_float(_coerce_scalar(ingredient.get_amount(), 0))
        unit_norm = _normalize_unit(_coerce_scalar(ingredient.get_unit(), ""))
        target = _to_base(amount_val, unit_norm)
        if target is not None:
            target_base, family = target
            match = _choose_best_product(products, target_base, family)
            if match is not None:
                chosen, add_qty = match

    # Fall back to first available (then first result) when no size-based match.
    if chosen is None:
        chosen = next((p for p in products if getattr(p, "available", False)), products[0])

    product_id = getattr(chosen, "product_id", None)
    sku_id = getattr(chosen, "sku", None)
    if not product_id or not sku_id:
        return {"ingredient": name, "term": term, "status": "missing_ids"}

    try:
        result = await client.add_to_cart(
            product_id=str(product_id), sku_id=str(sku_id), quantity=int(add_qty)
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
        "size": getattr(chosen, "size", None),
        "quantity": int(add_qty),
    }


async def run_graphql_cart_ops(ingredient_list, store_id, do_clear=True, quantity=1):
    """Run all GraphQL cart operations for the given ingredient list.

    Args:
        ingredient_list: IngredientList with the ingredients to add.
        store_id: HEB store id to operate against.
        do_clear: Whether to empty the cart before adding.
        quantity: Quantity to add for each ingredient (default 1).

    Returns:
        A report dict: {"added": [...], "failed": [...], "cart": <get_cart result>}
    """
    # Imported lazily so the dependency is only required for GraphQL modes.
    from auto_grocer_mcp.clients.graphql import HEBGraphQLClient

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
            outcome = await _add_ingredient(client, ingredient, store_id, quantity)
            if outcome["status"] == "added":
                added.append(outcome)
                price = outcome.get("price")
                price_str = f" (${price})" if price is not None else ""
                qty = outcome.get("quantity", 1)
                qty_str = f" x{qty}" if qty and qty != 1 else ""
                size = outcome.get("size")
                size_str = f" [{size}]" if size else ""
                print(
                    f"    ✓ {outcome['ingredient']} -> "
                    f"{outcome.get('product')}{size_str}{qty_str}{price_str}"
                )
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


def graphql_cart_sync(ingredient_list, store_id, do_clear=True, quantity=1):
    """Synchronous wrapper around :func:`run_graphql_cart_ops`."""
    return asyncio.run(
        run_graphql_cart_ops(ingredient_list, store_id, do_clear=do_clear, quantity=quantity)
    )
