"""
auto_grocier MCP server (standalone, GraphQL-only).

Exposes the project's grocery automation to an MCP client (e.g. VS Code Copilot
Chat) so you can drive the whole flow conversationally:

    "what's my login status" -> auth_status
    "add penne, spinach"     -> add_groceries           (GraphQL search + add)
    "I want palak paneer"    -> add_recipe_ingredients   (DB matcher + GraphQL)
    "show my saved recipes"  -> query_recipes            (DB browse/search)
    "add these recipes ..."  -> seed_recipes             (DB insert one recipe)
    "what's in my cart"      -> get_cart                 (GraphQL)
    "empty my cart"          -> clear_cart               (GraphQL)
    "set store 737"          -> set_store                (GraphQL)
    "show pickup slots"      -> list_timeslots           (GraphQL)
    "reserve slot X"         -> reserve_timeslot         (GraphQL)
    "check out"              -> checkout                 (GraphQL, review only)
    "place my order"         -> place_order              (GraphQL, charges - guarded)

ARCHITECTURE
------------
This server is PURE GraphQL and contains NO browser automation. It talks to
HEB's internal GraphQL API through the vendored ``texas_grocery_mcp`` client,
reusing an authenticated session previously exported to
``~/.texas-grocery-mcp/auth.json``.

Producing/refreshing that session, and refreshing HEB's rotating persisted-query
hashes (including the timeslot/checkout operations), is the job of a SEPARATE
maintenance workflow driven by undetected-chromedriver:

    MODE=update_graphql_hashes python main.py

That workflow logs in, exercises the site, and writes:
  * ~/.texas-grocery-mcp/auth.json                (session for this server)
  * ~/.texas-grocery-mcp/persisted_queries.json   (current operation hashes)
  * ~/.texas-grocery-mcp/captured_operations.json (timeslot/checkout payloads)

If a tool reports NOT_AUTHENTICATED or OPERATION_NOT_CAPTURED, re-run that
maintenance workflow, then call refresh_session here.

Run standalone:
    python mcp_server.py
"""
import os
import asyncio

from fastmcp import FastMCP

from claude import parse_config
from classes.IngredientList import IngredientList
from classes.Ingredient import Ingredient
from recipe_grabber import clean_ingredient
from utility.graphql_cart import graphql_cart_sync
from utility.graphql_store import select_store
from utility.graphql_checkout import (
    list_timeslots_sync,
    reserve_timeslot_sync,
    checkout_sync,
)

_PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
_CONFIG_PATH = os.path.join(_PROJECT_ROOT, "config.txt")

# Set to True to permit the place_order tool to actually submit a paid order.
# Left False by default so checkout can never charge accidentally.
_ALLOW_PLACE_ORDER = os.environ.get("AUTO_GROCIER_ALLOW_PLACE_ORDER", "").lower() in (
    "1", "true", "yes",
)

_NOT_AUTHED = {
    "error": True,
    "code": "NOT_AUTHENTICATED",
    "message": (
        "No valid HEB session. Run the maintenance workflow "
        "(MODE=update_graphql_hashes python main.py) to log in and export a "
        "session, then call refresh_session."
    ),
}


def _config():
    try:
        return parse_config(_CONFIG_PATH)
    except Exception:
        return {}


def _store_id(override: str = "") -> str:
    """Resolve the store id: explicit override > config STORE_ID > default."""
    if override:
        return str(override).strip()
    return _config().get("STORE_ID", "737").strip() or "737"


def _is_authed() -> bool:
    """Return True if a valid exported HEB session is available for GraphQL."""
    try:
        from texas_grocery_mcp.auth.session import is_authenticated
        return bool(is_authenticated())
    except Exception:
        return False


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
        {"ingredient": a.get("ingredient"), "product": a.get("product"), "price": a.get("price")}
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
        from texas_grocery_mcp.clients.graphql import HEBGraphQLClient
        client = HEBGraphQLClient()
        try:
            return await client.get_cart()
        finally:
            await client.close()
    return asyncio.run(_run())


def _search_products_sync(query: str, store_id: str, limit: int) -> list:
    async def _run():
        from texas_grocery_mcp.clients.graphql import HEBGraphQLClient
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


# ---------------------------------------------------------------------------
# MCP server + tools
# ---------------------------------------------------------------------------
mcp = FastMCP(
    name="auto-grocier",
    instructions=(
        "Drive HEB grocery automation over GraphQL. This server reuses an "
        "exported HEB session - if tools report NOT_AUTHENTICATED, run the "
        "maintenance workflow (MODE=update_graphql_hashes python main.py) to "
        "log in and refresh hashes, then call refresh_session. Typical order: "
        "add_groceries / add_recipe_ingredients -> get_cart -> list_timeslots "
        "-> reserve_timeslot -> checkout (review only). place_order is guarded "
        "and will charge."
    ),
)


@mcp.tool()
def auth_status() -> dict:
    """Report whether a valid HEB session is available and the active store. Reads the exported session file; does not open a browser."""
    return {
        "authenticated": _is_authed(),
        "store_id": _store_id(),
        "place_order_enabled": _ALLOW_PLACE_ORDER,
    }


@mcp.tool()
def refresh_session() -> dict:
    """Reload the exported session and the latest persisted-query hashes after running the maintenance workflow. Call this if tools start reporting NOT_AUTHENTICATED or OPERATION_NOT_CAPTURED."""
    try:
        from texas_grocery_mcp.utils.config import get_settings
        get_settings.cache_clear()
    except Exception:
        pass
    try:
        from texas_grocery_mcp.clients.graphql import reload_persisted_query_overrides
        reload_persisted_query_overrides()
    except Exception:
        pass
    return {"authenticated": _is_authed(), "store_id": _store_id()}


@mcp.tool()
def search_products(query: str, limit: int = 10, store_id: str = "") -> dict:
    """
    Search HEB products via GraphQL without adding anything to the cart.

    Args:
        query: Search term, e.g. "organic spinach" or "chicken breast".
        limit: Maximum number of results to return.
        store_id: Optional HEB store id. Defaults to STORE_ID in config.txt.
    """
    if not _is_authed():
        return _NOT_AUTHED
    products = _search_products_sync(query, _store_id(store_id), limit)
    return {"query": query, "count": len(products), "products": products}


@mcp.tool()
def add_groceries(items: list[str], clear_first: bool = False) -> dict:
    """
    Search for and add a list of grocery items to the cart via GraphQL (fast).

    Each item is a free-form string like "2 lb chicken breast" or "spinach".
    Produce items are searched as organic automatically.

    Args:
        items: List of grocery item descriptions to add.
        clear_first: If True, empty the cart before adding.
    """
    if not _is_authed():
        return _NOT_AUTHED
    IL = _ingredient_list_from_items(items)
    report = graphql_cart_sync(IL, _store_id(), do_clear=clear_first)
    return _summarize(report)


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
    if not _is_authed():
        return _NOT_AUTHED

    from database.db_connection import get_db_session
    from database.recipe_repository import RecipeRepository
    from database.ingredient_repository import IngredientRepository
    from utility.recipe_matcher import parse_and_match, build_ingredient_list

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
    from database.recipe_repository import RecipeRepository
    from database.ingredient_repository import IngredientRepository

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
def seed_recipes(
    title: str,
    url: str,
    ingredients: list,
    description: str = "",
) -> dict:
    """
    Insert ONE recipe (with its ingredients) into the recipe database. No HEB
    login required - this is a pure database write.

    Intended workflow: when the user pastes a list of recipes
    ("add these recipes to my database: ..."), the assistant visits each recipe
    link, extracts EVERY ingredient (name, quantity, unit), shows the full list
    in chat, then calls this tool ONCE PER RECIPE to persist it.

    Ingredients are auto-tagged (vegetable, fruit, meat, fish, cheese, pasta,
    oil, spice, wine, tree_nut, eggs, milk) using the project's word
    dictionaries so downstream cart/organic logic works. Re-seeding the same URL
    updates the existing recipe and replaces its ingredients instead of creating
    a duplicate.

    Args:
        title: Recipe name/title (e.g. "Palak Paneer").
        url: Source URL. Used as the unique key; required.
        ingredients: List of ingredient dicts. Each item supports:
            - name (str, required) e.g. "spinach"
            - amount (number, default 1) e.g. 2
            - unit (str, default "none") e.g. "cup", "tablespoon", "lb"
            - tags (list[str], optional; auto-derived from name if omitted)
        description: Optional short description for natural-language matching.
    """
    from database.db_connection import get_db_session
    from database.recipe_repository import RecipeRepository
    from database.ingredient_repository import IngredientRepository

    if not url or not str(url).strip():
        return {"error": True, "code": "INVALID_INPUT", "message": "A recipe 'url' is required."}
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
    if not _is_authed():
        return _NOT_AUTHED
    return _graphql_get_cart_sync()


@mcp.tool()
def clear_cart() -> dict:
    """Empty all items from the cart via GraphQL."""
    if not _is_authed():
        return _NOT_AUTHED
    report = graphql_cart_sync(IngredientList(), _store_id(), do_clear=True)
    return {"status": "cleared", "cart": report.get("cart")}


@mcp.tool()
def set_store(store_id: str) -> dict:
    """
    Set the active pickup store for GraphQL operations.

    Args:
        store_id: HEB store id to make active.
    """
    if not _is_authed():
        return _NOT_AUTHED
    result = asyncio.run(select_store(str(store_id)))
    return {"store_id": str(store_id), "result": result}


@mcp.tool()
def list_timeslots(store_id: str = "") -> dict:
    """
    List available curbside pickup time slots via GraphQL.

    Returns OPERATION_NOT_CAPTURED if the timeslot operation hasn't been
    captured yet - run the maintenance workflow and refresh_session.

    Args:
        store_id: Optional HEB store id. Defaults to STORE_ID in config.txt.
    """
    if not _is_authed():
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
        store_id: Optional HEB store id. Defaults to STORE_ID in config.txt.
    """
    if not _is_authed():
        return _NOT_AUTHED
    return reserve_timeslot_sync(slot_id, _store_id(store_id))


@mcp.tool()
def checkout() -> dict:
    """
    Advance to the order-review stage via GraphQL. This DOES NOT place the order
    and never charges. Reserve a timeslot first. Use place_order to actually
    submit the paid order.
    """
    if not _is_authed():
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
    if not _is_authed():
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
