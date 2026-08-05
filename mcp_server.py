"""
auto_grocier MCP server (standalone, GraphQL-only).

Exposes the project's grocery automation to an MCP client (e.g. VS Code Copilot
Chat) so you can drive the whole flow conversationally:

    "what's my login status" -> auth_status
    "add penne, spinach"     -> add_groceries           (GraphQL search + add)
    "I want palak paneer"    -> add_recipe_ingredients   (DB matcher + GraphQL)
    "show my saved recipes"  -> query_recipes            (DB browse/search)
    "list all my recipes"    -> list_all_recipes         (DB paginated, 10/page)
    "add these recipes ..."  -> seed_recipes             (DB insert one recipe)
    "nutrition for X"        -> get_product_details      (GraphQL, ingredients/nutrition)
    "find HEB near Austin"   -> search_stores            (GraphQL, geocoded)
    "coupons for cereal"     -> list_coupons             (GraphQL)
    "clip that coupon"       -> clip_coupon              (GraphQL)
    "what's in my cart"      -> get_cart                 (GraphQL)
    "empty my cart"          -> clear_cart               (GraphQL)
    "remove the cat food"    -> remove_from_cart         (GraphQL)
    "set store 737"          -> set_store                (GraphQL)
    "show pickup slots"      -> list_timeslots           (GraphQL)
    "reserve slot X"         -> reserve_timeslot         (GraphQL)
    "check out"              -> checkout                 (GraphQL, review only)
    "place my order"         -> place_order              (GraphQL, charges - guarded)

ARCHITECTURE
------------
This server is PURE GraphQL and contains NO browser automation. It talks to
HEB's internal GraphQL API through the vendored ``auto_grocier_mcp`` client,
reusing an authenticated session previously exported to
``~/.texas-grocery-mcp/auth.json``.

Producing/refreshing that session, and refreshing HEB's rotating persisted-query
hashes (including the timeslot/checkout operations), is the job of a SEPARATE
maintenance workflow driven by nodriver (async CDP browser, runs under Xvfb in
Docker):

    MODE=update_graphql_hashes python -m session_maintenance.run

That workflow logs in, exercises the site, and writes:
  * ~/.texas-grocery-mcp/auth.json                (session for this server)
  * ~/.texas-grocery-mcp/persisted_queries.json   (current operation hashes)
  * ~/.texas-grocery-mcp/captured_operations.json (timeslot/checkout payloads)

If a tool reports NOT_AUTHENTICATED or OPERATION_NOT_CAPTURED, re-run that
maintenance workflow, then call refresh_session here. When AUTO_GROCIER_AUTO_LOGIN
is enabled (default), authenticated tools refresh an expired session
automatically by running the login_export flow.

Run standalone:
    python mcp_server.py
"""
import asyncio
import os
import subprocess
import sys
import threading
from collections.abc import Callable

from fastmcp import FastMCP

from classes.Ingredient import Ingredient
from classes.IngredientList import IngredientList
from claude import get_setting
from recipe_grabber import clean_ingredient
from utility.graphql_cart import graphql_cart_sync
from utility.graphql_checkout import (
    checkout_sync,
    list_timeslots_sync,
    reserve_timeslot_sync,
)
from utility.graphql_store import select_store

_PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))

# Set to True to permit the place_order tool to actually submit a paid order.
# Left False by default so checkout can never charge accidentally.
_ALLOW_PLACE_ORDER = os.environ.get("AUTO_GROCIER_ALLOW_PLACE_ORDER", "").lower() in (
    "1", "true", "yes",
)

# When True (default), authenticated tools will automatically run the browser
# login-and-export workflow if no valid session is available, instead of just
# returning NOT_AUTHENTICATED. Set AUTO_GROCIER_AUTO_LOGIN=0 to disable and use
# the manual workflow (run the script yourself, then call refresh_session).
_AUTO_LOGIN = os.environ.get("AUTO_GROCIER_AUTO_LOGIN", "1").lower() in (
    "1", "true", "yes",
)

# How long (seconds) to allow the browser login-and-export to run before giving
# up. The flow logs in, may handle email verification, and exports auth.json.
_AUTO_LOGIN_TIMEOUT = int(os.environ.get("AUTO_GROCIER_AUTO_LOGIN_TIMEOUT", "300"))

# Serialize auto-login so concurrent tool calls don't launch multiple browsers.
_AUTO_LOGIN_LOCK = threading.Lock()

_NOT_AUTHED = {
    "error": True,
    "code": "NOT_AUTHENTICATED",
    "message": (
        "No valid HEB session and automatic login is disabled or failed. "
        "Enable auto-login (AUTO_GROCIER_AUTO_LOGIN=1) or refresh the session "
        "manually (MODE=login_export python -m session_maintenance.run), then call "
        "refresh_session."
    ),
}


def _store_id(override: str = "") -> str:
    """Resolve the store id: explicit override > STORE_ID env (.env) > default."""
    if override:
        return str(override).strip()
    return (get_setting("STORE_ID", "737") or "737").strip() or "737"


def _is_authed() -> bool:
    """Return True if a valid exported HEB session is available for GraphQL."""
    try:
        from auto_grocier_mcp.auth.session import is_authenticated
        return bool(is_authenticated())
    except Exception:
        return False


def _session_expiry() -> dict:
    """Inspect auth.json cookies to report the real session lifespan.

    The limiter is the session cookies (sat/sst) — not the short-lived reese84
    renewTime. Returns the soonest relevant expiry and days remaining.
    """
    import json
    import time
    from datetime import datetime, timezone
    try:
        from auto_grocier_mcp.utils.config import get_settings
        path = get_settings().auth_state_path
        with open(path) as f:
            state = json.load(f)
    except Exception:
        return {"session_expires": None, "days_left": None}

    now = time.time()
    soonest = None
    for c in state.get("cookies", []):
        if "heb.com" not in c.get("domain", ""):
            continue
        if c.get("name") not in ("sat", "sst"):
            continue
        exp = c.get("expires", -1)
        if exp and exp != -1 and (soonest is None or exp < soonest):
            soonest = exp
    if not soonest:
        return {"session_expires": None, "days_left": None}
    return {
        "session_expires": datetime.fromtimestamp(soonest, timezone.utc).isoformat(),
        "days_left": round((soonest - now) / 86400, 1),
    }


def _hashes_ok() -> bool:
    """Live probe: confirm the GraphQL persisted-query hashes still work.

    Hashes have no timestamp; they only break when HEB rotates them. A cheap
    authenticated call surfaces a stale hash, so checking that is the reliable
    signal for whether re-auth/hash-refresh is needed.
    """
    try:
        cart = _graphql_get_cart_sync()
    except Exception:
        return False
    return isinstance(cart, dict) and not cart.get("error")



def _reload_session_caches() -> None:
    """Drop cached settings/hashes so the next check re-reads auth.json."""
    try:
        from auto_grocier_mcp.utils.config import get_settings
        get_settings.cache_clear()
    except Exception:
        pass
    try:
        from auto_grocier_mcp.clients.graphql import reload_persisted_query_overrides
        reload_persisted_query_overrides()
    except Exception:
        pass


def _auto_authenticate() -> dict:
    """Run the browser login-and-export workflow to refresh the HEB session.

    Logs in with the configured credentials (handling email verification) via the
    async nodriver flow (``session_maintenance.run`` with MODE=login_export) and
    re-exports ~/.texas-grocery-mcp/auth.json. The browser is driven over CDP and
    runs under Xvfb inside the Docker image. Blocks until it finishes (up to
    _AUTO_LOGIN_TIMEOUT seconds). Serialized so only one login runs at a time.
    Returns a dict describing the outcome.
    """
    with _AUTO_LOGIN_LOCK:
        # Another thread may have authenticated while we waited for the lock.
        if _is_authed():
            return {"ok": True, "skipped": "already authenticated"}

        # Prefer the project venv interpreter so dependencies resolve.
        venv_python = os.path.join(_PROJECT_ROOT, "venv", "bin", "python")
        python_exe = venv_python if os.path.exists(venv_python) else sys.executable

        env = dict(os.environ)
        env.setdefault("DISPLAY", ":0")  # X server (WSLg on host, Xvfb in Docker)
        env["MODE"] = "login_export"
        cmd = [python_exe, "-u", "-m", "session_maintenance.run"]

        print(
            "[auto-grocier] No valid session - running nodriver login "
            "(login_export) to refresh auth.json (this can take a minute)...",
            file=sys.stderr,
        )
        try:
            proc = subprocess.run(
                cmd,
                cwd=_PROJECT_ROOT,
                env=env,
                capture_output=True,
                text=True,
                timeout=_AUTO_LOGIN_TIMEOUT,
            )
        except subprocess.TimeoutExpired:
            return {"ok": False, "detail": f"login timed out after {_AUTO_LOGIN_TIMEOUT}s"}
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "detail": f"failed to run login: {e}"}

        # Re-read the freshly exported session.
        _reload_session_caches()
        ok = _is_authed()
        if not ok:
            print(
                "[auto-grocier] Auto-login finished but session still invalid. "
                f"(returncode={proc.returncode})",
                file=sys.stderr,
            )
        return {
            "ok": ok,
            "returncode": proc.returncode,
            "stdout_tail": (proc.stdout or "")[-600:],
            "stderr_tail": (proc.stderr or "")[-600:],
        }


def _ensure_authed() -> bool:
    """Ensure a valid HEB session exists, auto-running login if needed.

    Returns True if authenticated (possibly after a successful auto-login).
    Honors AUTO_GROCIER_AUTO_LOGIN; when disabled, behaves like _is_authed().
    """
    if _is_authed():
        return True
    if not _AUTO_LOGIN:
        return False
    _auto_authenticate()
    return _is_authed()


def _ingredient_list_from_items(items):
    """Build an IngredientList from a list of free-form item strings."""
    IL = IngredientList()
    for raw in items:
        name, amount, unit = clean_ingredient(raw)
        IL.add_ingredient(Ingredient(name, amount, unit))
    return IL


def _summarize(report: dict) -> dict:
    """Trim a graphql_cart_sync report to a chat-friendly summary."""
    added = [
        {
            "ingredient": a.get("ingredient"),
            "product": a.get("product"),
            "price": a.get("price"),
            "size": a.get("size"),
            "quantity": a.get("quantity", 1),
        }
        for a in report.get("added", [])
    ]
    failed = [
        {"ingredient": f.get("ingredient"), "status": f.get("status"), "detail": f.get("detail")}
        for f in report.get("failed", [])
    ]
    return {
        "added": added,
        "failed": failed,
        "added_count": len(added),
        "failed_count": len(failed),
    }


def _graphql_get_cart_sync() -> dict:
    async def _run():
        from auto_grocier_mcp.clients.graphql import HEBGraphQLClient
        client = HEBGraphQLClient()
        try:
            return await client.get_cart()
        finally:
            await client.close()
    return asyncio.run(_run())


def _remove_from_cart_sync(matchers: list[str]) -> dict:
    """Remove cart items matching any of the given identifiers.

    Each matcher is compared (case-insensitive) against the item's product id,
    sku id, or a substring of the product name. Matching items are removed by
    setting their quantity to 0.
    """
    from utility.graphql_cart import _extract_sku

    needles = [m.strip().lower() for m in matchers if m and m.strip()]

    async def _run():
        from auto_grocier_mcp.clients.graphql import HEBGraphQLClient
        client = HEBGraphQLClient()
        removed = []
        not_found = []
        try:
            cart = await client.get_cart()
            cart_data = (cart or {}).get("cartV2", {}) or {}
            items = cart_data.get("items", []) or []
            matched_indexes = set()
            for needle in needles:
                hit = False
                for idx, item in enumerate(items):
                    product = item.get("product", {}) or {}
                    product_id = str(product.get("id") or "")
                    sku_id = _extract_sku(item) or product_id
                    name = str(
                        product.get("displayName")
                        or product.get("decodedDisplayName")
                        or product.get("fullDisplayName")
                        or product.get("name")
                        or ""
                    ).lower()
                    if needle in (product_id.lower(), str(sku_id).lower()) or needle in name:
                        if idx in matched_indexes:
                            continue
                        result = await client.add_to_cart(
                            product_id=product_id, sku_id=str(sku_id), quantity=0
                        )
                        if isinstance(result, dict) and result.get("error"):
                            continue
                        matched_indexes.add(idx)
                        removed.append({"name": product.get("displayName") or product.get("name"), "product_id": product_id})
                        hit = True
                if not hit:
                    not_found.append(needle)
            return {"removed": removed, "removed_count": len(removed), "not_found": not_found}
        finally:
            await client.close()

    return asyncio.run(_run())


def _add_by_id_sync(entries: list[dict]) -> dict:
    """Add specific products to the cart by product id + sku (no search step).

    Each entry is a dict with: product_id (str), sku (str), quantity (int,
    default 1), and an optional name (str) used only for the response. Entries
    missing a product_id or sku are reported as failures.
    """
    async def _run():
        from auto_grocier_mcp.clients.graphql import HEBGraphQLClient
        client = HEBGraphQLClient()
        added = []
        failed = []
        try:
            for entry in entries:
                product_id = str(entry.get("product_id") or "").strip()
                sku = str(entry.get("sku") or "").strip()
                name = entry.get("name") or product_id
                try:
                    qty = int(entry.get("quantity", 1))
                except (TypeError, ValueError):
                    qty = 1
                if qty < 1:
                    qty = 1
                if not product_id or not sku:
                    failed.append(
                        {
                            "product_id": product_id,
                            "name": name,
                            "status": "missing_product_id_or_sku",
                        }
                    )
                    continue
                result = await client.add_to_cart(
                    product_id=product_id, sku_id=sku, quantity=qty
                )
                if isinstance(result, dict) and result.get("error"):
                    failed.append(
                        {
                            "product_id": product_id,
                            "name": name,
                            "status": result.get("code") or "error",
                            "detail": result.get("message"),
                        }
                    )
                    continue
                added.append(
                    {
                        "product_id": product_id,
                        "sku": sku,
                        "name": name,
                        "quantity": qty,
                    }
                )
            return {
                "added": added,
                "failed": failed,
                "added_count": len(added),
                "failed_count": len(failed),
            }
        finally:
            await client.close()

    return asyncio.run(_run())


def _search_products_sync(query: str, store_id: str, limit: int) -> list:
    async def _run():
        from auto_grocier_mcp.clients.graphql import HEBGraphQLClient
        client = HEBGraphQLClient()
        try:
            result = await client.search_products(
                query=query, store_id=str(store_id), limit=limit
            )
            products = getattr(result, "products", []) or []
            return [
                {
                    "name": getattr(p, "name", None),
                    "price": getattr(p, "price", None),
                    "available": getattr(p, "available", None),
                    "product_id": getattr(p, "product_id", None),
                    "sku": getattr(p, "sku", None),
                }
                for p in products
            ]
        finally:
            await client.close()
    return asyncio.run(_run())


def _product_details_sync(product_id: str, store_id: str) -> dict | None:
    async def _run():
        from auto_grocier_mcp.clients.graphql import HEBGraphQLClient
        client = HEBGraphQLClient()
        try:
            details = await client.get_product_details(
                str(product_id), str(store_id) or None
            )
            return details.model_dump() if details is not None else None
        finally:
            await client.close()
    return asyncio.run(_run())


def _get_coupons_sync(search: str, category_id: int, limit: int) -> dict:
    async def _run():
        from auto_grocier_mcp.clients.graphql import HEBGraphQLClient
        client = HEBGraphQLClient()
        try:
            result = await client.get_coupons(
                category_id=int(category_id) or None,
                search_query=search.strip() or None,
                limit=int(limit),
            )
            return result.model_dump()
        finally:
            await client.close()
    return asyncio.run(_run())


def _clipped_coupons_sync(limit: int) -> dict:
    async def _run():
        from auto_grocier_mcp.clients.graphql import HEBGraphQLClient
        client = HEBGraphQLClient()
        try:
            result = await client.get_clipped_coupons(limit=int(limit))
            return result.model_dump()
        finally:
            await client.close()
    return asyncio.run(_run())


def _clip_coupon_sync(coupon_id: int) -> dict:
    async def _run():
        from auto_grocier_mcp.clients.graphql import HEBGraphQLClient
        client = HEBGraphQLClient()
        try:
            return await client.clip_coupon(int(coupon_id))
        finally:
            await client.close()
    return asyncio.run(_run())


def _search_stores_sync(address: str, radius_miles: int) -> dict:
    async def _run():
        from auto_grocier_mcp.clients.graphql import HEBGraphQLClient
        client = HEBGraphQLClient()
        try:
            result = await client.search_stores(
                address=address, radius_miles=int(radius_miles)
            )
            return result.model_dump()
        finally:
            await client.close()
    return asyncio.run(_run())


# ---------------------------------------------------------------------------
# MCP server + tools
# ---------------------------------------------------------------------------
mcp = FastMCP(
    name="auto-grocier",
    instructions=(
        "Drive HEB grocery automation over GraphQL. This server reuses an "
        "exported HEB session. If no valid session exists, authenticated tools "
        "automatically run a browser login to refresh it (set "
        "AUTO_GROCIER_AUTO_LOGIN=0 to disable and use refresh_session manually). "
        "Typical order: add_groceries / add_recipe_ingredients -> get_cart -> "
        "list_timeslots -> reserve_timeslot -> checkout (review only). "
        "place_order is guarded and will charge."
    ),
)


@mcp.tool()
def auth_status() -> dict:
    """Report whether a valid HEB session is available and the active store. Reads the exported session file; does not open a browser.

    Session validity is driven by the sat/sst cookies (the real limiter), not the
    short-lived reese84 token. hashes_ok is a live probe confirming the GraphQL
    persisted-query hashes still work; if False, refresh the hashes/re-auth.
    """
    authed = _is_authed()
    status = {
        "authenticated": authed,
        "store_id": _store_id(),
        "place_order_enabled": _ALLOW_PLACE_ORDER,
        "hashes_ok": _hashes_ok() if authed else False,
    }
    status.update(_session_expiry())
    return status



@mcp.tool()
def refresh_session() -> dict:
    """Reload the exported session and the latest persisted-query hashes after running the maintenance workflow. Call this if tools start reporting NOT_AUTHENTICATED or OPERATION_NOT_CAPTURED."""
    _reload_session_caches()
    return {"authenticated": _is_authed(), "store_id": _store_id()}


@mcp.tool()
def search_products(query: str, limit: int = 10, store_id: str = "") -> dict:
    """
    Search HEB products via GraphQL without adding anything to the cart.

    Args:
        query: Search term, e.g. "organic spinach" or "chicken breast".
        limit: Maximum number of results to return.
        store_id: Optional HEB store id. Defaults to STORE_ID in .env.
    """
    if not _ensure_authed():
        return _NOT_AUTHED
    products = _search_products_sync(query, _store_id(store_id), limit)
    return {"query": query, "count": len(products), "products": products}


@mcp.tool()
def get_product_details(product_id: str, store_id: str = "") -> dict:
    """
    Get comprehensive details for a single HEB product via GraphQL: ingredients,
    nutrition facts, allergen/safety warnings, dietary attributes (gluten-free,
    organic, vegan, kosher, ...), package size, and store location.

    Use search_products first to get a product_id. Results are cached ~24h.

    Args:
        product_id: The product id (e.g. "127074"), from a search result.
        store_id: Optional HEB store id. Defaults to STORE_ID in .env.
    """
    if not _ensure_authed():
        return _NOT_AUTHED
    details = _product_details_sync(product_id, _store_id(store_id))
    if details is None:
        return {
            "error": True,
            "code": "PRODUCT_NOT_FOUND",
            "message": f"No product details found for id {product_id}.",
        }
    return details


@mcp.tool()
def add_groceries(items: list[str], clear_first: bool = False, quantity: int = 1) -> dict:
    """
    Search HEB for each item and add the best match to the cart via GraphQL (fast).

    Each item is a free-form string: a bare name ("spinach") or a name with a
    measured amount ("16 oz spinach", "2 lb chicken breast", "1 cup heavy cream").
    Produce (fruit/vegetables) is automatically searched as organic.

    HOW QUANTITY IS DECIDED
    -----------------------
    1. MEASURED amounts (weight/volume: oz, lb, g, cup, tbsp, ml, qt, gal, ...)
       scale by package size automatically. The server reads each result's
       package size and adds enough packages to cover the amount with the least
       waste. Example: "16 oz spinach" with only 5 oz bags on the shelf adds 4
       bags; if a 1 lb bag exists it adds that single bag instead. You do NOT
       pass `quantity` for these — keep the amount in the item string.

    2. WHOLE-ITEM COUNTS (e.g. 2 onions, 3 limes, 4 avocados) are NOT inferred
       from the text — a leading number with no unit is ignored. To buy several
       of a whole item, pass `quantity` with the count.

    USING `quantity`
    ----------------
    `quantity` multiplies EVERY item in the same call. So group items that share
    the same count, and make a SEPARATE call for each distinct count:
      * 2 onions and 3 limes ->
          add_groceries(["onion"], quantity=2)
          add_groceries(["lime"], quantity=3)
      * 1 each of many things -> a single call with the default quantity=1.
    Do not put differently-counted items in one call expecting per-item counts.

    Args:
        items: Grocery item descriptions to add. Bare names or name+amount.
        clear_first: If True, empty the cart before adding.
        quantity: How many of EACH item in `items` to add (applies to all of
            them; default 1). Use this for whole-item counts, not for measured
            amounts (put those in the item string instead).

    Returns:
        A summary dict with `added` (ingredient, product, size, price, quantity),
        `failed`, and their counts.
    """
    if not _ensure_authed():
        return _NOT_AUTHED
    IL = _ingredient_list_from_items(items)
    report = graphql_cart_sync(IL, _store_id(), do_clear=clear_first, quantity=quantity)
    return _summarize(report)


@mcp.tool()
def add_products_by_id(products: list[dict], clear_first: bool = False) -> dict:
    """
    Add EXACT products to the cart by product id + sku, with NO search step.

    Use this after search_products (or get_product_details) has already found the
    right product, so the precise item you chose is added instead of a
    re-searched guess. This is the reliable way to add a specific
    replacement/substitute you have already picked — prefer it over add_groceries
    once you know the product_id.

    Args:
        products: List of product entries. Each entry is a dict with:
            - product_id (str, required): from a search_products result.
            - sku (str, required): the matching sku from that same result.
            - quantity (int, optional): how many to add (default 1).
            - name (str, optional): display name, used only in the response.
            Example: [{"product_id": "8075021", "sku": "4122031137",
                       "quantity": 1, "name": "Mi Tienda Fresh Garlic, 3 ct"}]
        clear_first: If True, empty the cart before adding.

    Returns:
        A summary dict with `added` (product_id, sku, name, quantity), `failed`
        (with a status/detail), and their counts.
    """
    if not _ensure_authed():
        return _NOT_AUTHED
    if clear_first:
        graphql_cart_sync(IngredientList(), _store_id(), do_clear=True)
    return _add_by_id_sync(products or [])


@mcp.tool()
def add_recipe_ingredients(request: str, clear_first: bool = False) -> dict:
    """
    Match a natural-language meal request against recipes in the database and add
    all matched recipes' ingredients to the cart via GraphQL.

    Example request: "I want palak paneer, chicken buffalo wraps, and penne alla vodka".
    Requires recipes seeded via database/seed_recipes.py.

    Args:
        request: Natural-language description of the meals/recipes you want.
        clear_first: If True, empty the cart before adding.
    """
    if not _ensure_authed():
        return _NOT_AUTHED

    from database.db_connection import get_db_session
    from database.ingredient_repository import IngredientRepository
    from database.recipe_repository import RecipeRepository
    from utility.recipe_matcher import build_ingredient_list, parse_and_match

    db = get_db_session()
    try:
        matched, unmatched = parse_and_match(request, RecipeRepository(db))
        IL = build_ingredient_list(matched, IngredientRepository(db))
        matched_titles = [r.title or r.url for r in matched]
    finally:
        db.close()

    if not IL.get_ingredients():
        return {
            "matched_recipes": matched_titles,
            "unmatched": unmatched,
            "added": [],
            "failed": [],
            "message": "No ingredients found for the matched recipes.",
        }

    summary = _summarize(graphql_cart_sync(IL, _store_id(), do_clear=clear_first))
    summary["matched_recipes"] = matched_titles
    summary["unmatched"] = unmatched
    return summary


@mcp.tool()
def find_recipes(request: str) -> dict:
    """
    Preview which database recipes match a natural-language request WITHOUT adding
    anything to the cart.

    Args:
        request: Natural-language description of the meals/recipes you want.
    """
    from database.db_connection import get_db_session
    from database.recipe_repository import RecipeRepository
    from utility.recipe_matcher import parse_and_match

    db = get_db_session()
    try:
        matched, unmatched = parse_and_match(request, RecipeRepository(db))
        return {
            "matched_recipes": [
                {"id": r.id, "title": r.title, "description": r.description} for r in matched
            ],
            "unmatched": unmatched,
        }
    finally:
        db.close()


@mcp.tool()
def query_recipes(
    search: str = "",
    recipe_id: int = 0,
    domain: str = "",
    include_ingredients: bool = False,
    limit: int = 50,
) -> dict:
    """
    Browse and query the recipe database directly (no AI matching, no HEB login
    required). Use this to list, search, or inspect saved recipes.

    Resolution order (first non-empty wins):
      * recipe_id > 0  -> return that single recipe (ingredients always included)
      * search         -> case-insensitive match on title OR description
      * domain         -> recipes from a source domain (e.g. "cookingclassy.com")
      * otherwise      -> the most recent recipes (up to `limit`)

    Args:
        search: Text to match against recipe title/description.
        recipe_id: Fetch one recipe by its database id.
        domain: Filter recipes by source domain.
        include_ingredients: Include each recipe's ingredient list in the result.
        limit: Max recipes to return when listing (default 50).
    """
    from database.db_connection import get_db_session
    from database.ingredient_repository import IngredientRepository
    from database.recipe_repository import RecipeRepository

    try:
        db = get_db_session()
    except Exception as e:
        return {
            "error": True,
            "code": "DATABASE_UNAVAILABLE",
            "message": f"Could not open the recipe database: {e}",
        }

    try:
        recipes_repo = RecipeRepository(db)
        ingredients_repo = IngredientRepository(db)

        if recipe_id and int(recipe_id) > 0:
            recipe = recipes_repo.get_by_id(int(recipe_id))
            if recipe is None:
                return {"recipes": [], "count": 0, "message": f"No recipe with id {recipe_id}."}
            recipes = [recipe]
            include_ingredients = True
            mode = "by_id"
        elif search.strip():
            recipes = recipes_repo.search_recipes(search.strip())
            mode = "search"
        elif domain.strip():
            recipes = recipes_repo.get_by_domain(domain.strip())
            mode = "domain"
        else:
            recipes = recipes_repo.get_all(limit=int(limit) if limit else None)
            mode = "list"

        results = []
        for r in recipes:
            entry = r.to_dict()
            if include_ingredients:
                entry["ingredients"] = [
                    ing.to_dict() for ing in ingredients_repo.get_by_recipe(r.id)
                ]
            results.append(entry)

        return {
            "mode": mode,
            "count": len(results),
            "total_recipes": recipes_repo.count(),
            "recipes": results,
        }
    except Exception as e:
        return {"error": True, "code": "QUERY_FAILED", "message": str(e)}
    finally:
        db.close()


@mcp.tool()
def list_all_recipes(page: int = 1) -> dict:
    """
    List every recipe in the database, paginated 10 per page (no AI matching, no
    HEB login required).

    Call with page=1 to get the first ten recipes, page=2 for the next ten, and
    so on. Use the returned `has_next`/`next_page` fields to keep requesting more
    until `has_next` is false.

    Each recipe entry contains:
      * name             -> the recipe title
      * url              -> the source URL
      * ingredient_count -> number of ingredients on the recipe
      * cook_time        -> cook time in minutes (null if not recorded)

    Args:
        page: 1-indexed page number (10 recipes per page). Defaults to 1.
    """
    from database.db_connection import get_db_session
    from database.recipe_repository import RecipeRepository

    PAGE_SIZE = 10

    try:
        page_num = int(page)
    except (TypeError, ValueError):
        page_num = 1
    if page_num < 1:
        page_num = 1

    try:
        db = get_db_session()
    except Exception as e:
        return {
            "error": True,
            "code": "DATABASE_UNAVAILABLE",
            "message": f"Could not open the recipe database: {e}",
        }

    try:
        recipes_repo = RecipeRepository(db)
        total = recipes_repo.count()
        total_pages = (total + PAGE_SIZE - 1) // PAGE_SIZE if total else 0
        offset = (page_num - 1) * PAGE_SIZE

        recipes = recipes_repo.get_all(limit=PAGE_SIZE, offset=offset)
        results = [
            {
                "name": r.title,
                "url": r.url,
                "ingredient_count": len(r.ingredients) if r.ingredients else 0,
                "cook_time": r.cook_time,
            }
            for r in recipes
        ]

        has_next = (offset + len(results)) < total
        return {
            "page": page_num,
            "page_size": PAGE_SIZE,
            "count": len(results),
            "total_recipes": total,
            "total_pages": total_pages,
            "has_next": has_next,
            "next_page": page_num + 1 if has_next else None,
            "recipes": results,
        }
    except Exception as e:
        return {"error": True, "code": "QUERY_FAILED", "message": str(e)}
    finally:
        db.close()


@mcp.tool()
def seed_recipes(
    title: str = "",
    url: str = "",
    ingredients: list | None = None,
    description: str = "",
    cook_time: int = 0,
) -> dict:
    """
    Insert ONE recipe (with its ingredients) into the recipe database. No HEB
    login required - this is a pure database write.

    Intended workflow: when the user pastes a list of recipes
    ("add these recipes to my database: ..."), the assistant visits each recipe
    link, extracts EVERY ingredient (name, quantity, unit), shows the full list
    in chat, then calls this tool ONCE PER RECIPE to persist it.

    YOUTUBE SUPPORT: if `url` is a YouTube video or Short and no `ingredients`
    are supplied, this tool automatically fetches the video's description
    (assumed to contain the full recipe + ingredient list), parses the
    ingredients with Claude, and derives the title/description when they aren't
    given. Just pass the YouTube URL with an empty `ingredients` list.

    Ingredients are auto-tagged (vegetable, fruit, meat, fish, cheese, pasta,
    oil, spice, wine, tree_nut, eggs, milk) using the project's word
    dictionaries so downstream cart/organic logic works. Re-seeding the same URL
    updates the existing recipe and replaces its ingredients instead of creating
    a duplicate.

    Args:
        title: Recipe name/title (e.g. "Palak Paneer"). Optional for YouTube
            URLs (derived from the description when blank).
        url: Source URL. Used as the unique key; required. May be a recipe page
            or a YouTube video/Short URL.
        ingredients: List of ingredient dicts. Each item supports:
            - name (str, required) e.g. "spinach"
            - amount (number, default 1) e.g. 2
            - unit (str, default "none") e.g. "cup", "tablespoon", "lb"
            - tags (list[str], optional; auto-derived from name if omitted)
            Optional/empty for YouTube URLs (parsed from the description).
        description: Optional short description for natural-language matching.
            Derived from the video for YouTube URLs when blank.
        cook_time: Optional cook time in minutes (0 or omit if unknown).
    """
    from database.db_connection import get_db_session
    from database.ingredient_repository import IngredientRepository
    from database.recipe_repository import RecipeRepository

    if not url or not str(url).strip():
        return {"error": True, "code": "INVALID_INPUT", "message": "A recipe 'url' is required."}

    if ingredients is None:
        ingredients = []

    # YouTube auto-detection: when a video/Short URL is given without explicit
    # ingredients, fetch + parse the description into ingredients.
    youtube_source = False
    is_youtube_url: Callable[[str], bool] | None
    try:
        from utility.youtube import is_youtube_url, youtube_recipe_from_url
    except Exception:  # noqa: BLE001 - module optional at import time
        is_youtube_url = None

    if is_youtube_url and is_youtube_url(url) and not ingredients:
        try:
            parsed = youtube_recipe_from_url(url)
        except ValueError as e:
            return {
                "error": True,
                "code": "YOUTUBE_FETCH_FAILED",
                "message": str(e),
            }
        except Exception as e:  # noqa: BLE001
            return {
                "error": True,
                "code": "YOUTUBE_FETCH_FAILED",
                "message": f"Could not process YouTube URL: {e}",
            }

        ingredients = parsed.get("ingredients") or []
        if not str(title).strip():
            title = parsed.get("title", "")
        if not str(description).strip():
            description = parsed.get("description", "")
        youtube_source = True

    if not isinstance(ingredients, list) or not ingredients:
        return {"error": True, "code": "INVALID_INPUT", "message": "'ingredients' must be a non-empty list."}

    try:
        db = get_db_session()
    except Exception as e:
        return {
            "error": True,
            "code": "DATABASE_UNAVAILABLE",
            "message": f"Could not open the recipe database: {e}",
        }

    try:
        recipe_repo = RecipeRepository(db)
        ingredient_repo = IngredientRepository(db)

        # Tagger reused for every ingredient (loads the word dictionaries once).
        tagger = IngredientList()

        recipe = recipe_repo.get_or_create(
            url=str(url).strip(),
            title=(title or "").strip() or None,
            description=(description or "").strip() or None,
        )

        # Update cook_time if provided (works for both new and re-seeded recipes).
        try:
            cook_time_minutes = int(cook_time)
        except (TypeError, ValueError):
            cook_time_minutes = 0
        if cook_time_minutes > 0 and recipe.cook_time != cook_time_minutes:
            recipe_repo.update(recipe.id, cook_time=cook_time_minutes)

        # Replace any existing ingredients so re-seeding is idempotent.
        existing = ingredient_repo.get_by_recipe(recipe.id)
        for ing in existing:
            ingredient_repo.delete(ing.id)

        added = []
        skipped = []
        for raw in ingredients:
            if not isinstance(raw, dict):
                skipped.append({"ingredient": raw, "reason": "not an object"})
                continue
            name = str(raw.get("name", "")).strip()
            if not name:
                skipped.append({"ingredient": raw, "reason": "missing name"})
                continue

            try:
                amount = float(raw.get("amount", 1) or 1)
            except (TypeError, ValueError):
                amount = 1.0
            unit = str(raw.get("unit", "none") or "none").strip() or "none"

            tags = raw.get("tags")
            if not tags:
                derived = tagger.get_tag(name)
                tags = [derived] if derived else []

            created = ingredient_repo.create(
                name=name,
                amount=amount,
                unit=unit,
                tag_names=tags,
                recipe_id=recipe.id,
            )
            added.append(created.to_dict())

        return {
            "success": True,
            "source": "youtube" if youtube_source else "manual",
            "recipe": recipe.to_dict(),
            "ingredients_added": len(added),
            "ingredients_skipped": len(skipped),
            "ingredients": added,
            "skipped": skipped,
        }
    except Exception as e:
        return {"error": True, "code": "SEED_FAILED", "message": str(e)}
    finally:
        db.close()


@mcp.tool()
def get_cart() -> dict:
    """Return the current cart contents (items, quantities, totals) via GraphQL."""
    if not _ensure_authed():
        return _NOT_AUTHED
    return _graphql_get_cart_sync()


@mcp.tool()
def clear_cart() -> dict:
    """Empty all items from the cart via GraphQL."""
    if not _ensure_authed():
        return _NOT_AUTHED
    report = graphql_cart_sync(IngredientList(), _store_id(), do_clear=True)
    return {"status": "cleared", "cart": report.get("cart")}


@mcp.tool()
def remove_from_cart(items: list[str]) -> dict:
    """
    Remove specific items from the cart via GraphQL (without emptying it).

    Each item is an identifier matched against the cart's products: a product id,
    a sku id, or a case-insensitive substring of the product name (e.g.
    "Friskies" or "cat food"). Matching items have their quantity set to 0.

    Args:
        items: List of product identifiers / name fragments to remove.
    """
    if not _ensure_authed():
        return _NOT_AUTHED
    return _remove_from_cart_sync(items)


@mcp.tool()
def set_store(store_id: str) -> dict:
    """
    Set the active pickup store for GraphQL operations.

    Args:
        store_id: HEB store id to make active.
    """
    if not _ensure_authed():
        return _NOT_AUTHED
    result = asyncio.run(select_store(str(store_id)))
    return {"store_id": str(store_id), "result": result}


@mcp.tool()
def search_stores(address: str, radius_miles: int = 25) -> dict:
    """
    Find HEB stores near an address, zip code, neighborhood, or landmark via
    GraphQL (geocoding-backed). Use this to discover a store id you can pass to
    set_store.

    Args:
        address: Address, zip code, neighborhood, or landmark to search near.
        radius_miles: Search radius in miles (default 25).
    """
    return _search_stores_sync(address, radius_miles)


@mcp.tool()
def list_coupons(search: str = "", category_id: int = 0, limit: int = 60) -> dict:
    """
    List or search available HEB digital coupons via GraphQL. Requires a valid
    session. Use clip_coupon to clip one to your account before checkout.

    Args:
        search: Optional keyword to filter coupons (e.g. "cereal").
        category_id: Optional category id to filter by (see result `categories`).
        limit: Maximum coupons to return (max 60).
    """
    if not _ensure_authed():
        return _NOT_AUTHED
    return _get_coupons_sync(search, category_id, limit)


@mcp.tool()
def list_clipped_coupons(limit: int = 60) -> dict:
    """
    List the coupons already clipped to your HEB account via GraphQL.

    Args:
        limit: Maximum coupons to return (max 60).
    """
    if not _ensure_authed():
        return _NOT_AUTHED
    return _clipped_coupons_sync(limit)


@mcp.tool()
def clip_coupon(coupon_id: int) -> dict:
    """
    Clip a digital coupon to your HEB account via GraphQL so its discount applies
    at checkout. Use list_coupons to find a coupon_id.

    Args:
        coupon_id: The coupon id to clip (from list_coupons).
    """
    if not _ensure_authed():
        return _NOT_AUTHED
    return _clip_coupon_sync(coupon_id)


@mcp.tool()
def list_timeslots(store_id: str = "") -> dict:
    """
    List available curbside pickup time slots via GraphQL.

    Returns OPERATION_NOT_CAPTURED if the timeslot operation hasn't been
    captured yet - run the maintenance workflow and refresh_session.

    Args:
        store_id: Optional HEB store id. Defaults to STORE_ID in .env.
    """
    if not _ensure_authed():
        return _NOT_AUTHED
    return list_timeslots_sync(_store_id(store_id))


@mcp.tool()
def reserve_timeslot(slot_id: str, store_id: str = "") -> dict:
    """
    Reserve a curbside pickup time slot via GraphQL.

    Use list_timeslots first to get a slot id. Returns OPERATION_NOT_CAPTURED
    if the reserve operation hasn't been captured yet.

    Args:
        slot_id: The time slot id to reserve (from list_timeslots).
        store_id: Optional HEB store id. Defaults to STORE_ID in .env.
    """
    if not _ensure_authed():
        return _NOT_AUTHED
    return reserve_timeslot_sync(slot_id, _store_id(store_id))


@mcp.tool()
def checkout() -> dict:
    """
    Advance to the order-review stage via GraphQL. This DOES NOT place the order
    and never charges. Reserve a timeslot first. Use place_order to actually
    submit the paid order.
    """
    if not _ensure_authed():
        return _NOT_AUTHED
    return checkout_sync(place_order=False)


@mcp.tool()
def place_order() -> dict:
    """
    Submit the final paid order via GraphQL. THIS CHARGES YOUR PAYMENT METHOD.

    Disabled by default for safety; enable by setting the environment variable
    AUTO_GROCIER_ALLOW_PLACE_ORDER=1 before starting the server. Run checkout
    (review) first.
    """
    if not _ensure_authed():
        return _NOT_AUTHED
    if not _ALLOW_PLACE_ORDER:
        return {
            "error": True,
            "code": "PLACE_ORDER_DISABLED",
            "message": (
                "place_order is disabled. Set AUTO_GROCIER_ALLOW_PLACE_ORDER=1 "
                "in the server environment to enable submitting a paid order."
            ),
        }
    return checkout_sync(place_order=True)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
