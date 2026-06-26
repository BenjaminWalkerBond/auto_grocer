"""Async mode dispatcher for the auto_grocier browser automation (nodriver).

Supported modes (read from the MODE setting in .env, or the MODE env var which overrides):

    login_export                  - log in and export auth.json (refresh the MCP session).
    test                          - login, clear cart, reserve slot, add ingredients (no checkout).
    checkout_with_prompt          - test flow, then prompt before advancing to checkout.
    auto_checkout                 - test flow, then advance to checkout automatically.
    graphql                       - login + export, then add ingredients via the GraphQL API.
    graphql_checkout_with_prompt  - GraphQL add + browser timeslot, prompt before checkout.
    graphql_auto_checkout         - GraphQL add + browser timeslot, then checkout automatically.
    update_graphql_hashes         - login, exercise flows, capture GraphQL hashes via CDP.

Note: the checkout flow only advances to HEB's checkout page; it does NOT place a
paid order (no payment step). Placing a paid order is the MCP server's guarded
``place_order`` tool.

Run:
    python -m grocery_browser.run        # uses MODE from .env
    MODE=test python -m grocery_browser.run
"""
from __future__ import annotations

import os
import asyncio

import nodriver

from claude import get_setting
from classes.IngredientList import IngredientList
from classes.Ingredient import Ingredient
from recipe_grabber import clean_ingredient, populate_ingredient_list
from utility.graphql_cart import graphql_cart_sync
from utility.graphql_hash_capture import TARGET_OPERATIONS

from grocery_browser.browser import start_browser, stop_browser
from grocery_browser.logger import AsyncDriverLogger
from grocery_browser.auth_export import export_session_to_authjson
from grocery_browser.self_healing import self_healing_call
from grocery_browser.hash_capture import GraphQLHashCapturer
from grocery_browser import flows


# Hardcoded fallback ingredient list (matches main.py's sample recipe).
HARDCODED_INGREDIENTS = [
    "1 tablespoon: olive oil",
    "1 medium: shallot",
    "2 large: garlic cloves",
    "¼ teaspoon: red chilli flakes",
    "75 ml (⅓ cup): dry white wine",
    "2 tablespoons: tomato paste",
    "1 teaspoon: Italian seasoning mix",
    "200 ml (1 cup): water",
    "100 g (3.5 oz): fresh spinach",
    "180 g (6.5 oz): cream cheese",
    "500 g (1 lb): gnocchi",
    "225 g (½ lb): hot smoked salmon",
]

# Recipe URLs used when INGREDIENT_SOURCE=urls.
RECIPE_URLS = [
    "https://skinnyspatula.com/salmon-gnocchi/",
]


def _build_hardcoded_list() -> IngredientList:
    IL = IngredientList()
    for raw in HARDCODED_INGREDIENTS:
        name, amount, unit = clean_ingredient(raw)
        IL.add_ingredient(Ingredient(name, amount, unit))
    return IL


def _load_ingredients() -> IngredientList:
    """Build the ingredient list per INGREDIENT_SOURCE in .env.

    Sources: 'database' (ask which recipes, match from DB), 'urls' (scrape recipe
    URLs), or 'hardcoded' (default sample list). Mirrors the old main.py logic.
    """
    source = (get_setting("INGREDIENT_SOURCE", "") or "").strip().lower() or "hardcoded"

    if source == "database":
        print("🗄️  Loading recipes from the database...\n")
        from database.db_connection import get_db_session
        from database.recipe_repository import RecipeRepository
        from database.ingredient_repository import IngredientRepository
        from utility.recipe_matcher import parse_and_match, build_ingredient_list

        user_request = input("What recipes do you want this week? ").strip()
        db = get_db_session()
        try:
            matched, unmatched = parse_and_match(user_request, RecipeRepository(db))
            if matched:
                print("\n✓ Matched recipes:")
                for r in matched:
                    print(f"   - {r.title or r.url}")
            if unmatched:
                print("\n⚠️  Could not match:")
                for u in unmatched:
                    print(f"   - {u}")
            return build_ingredient_list(matched, IngredientRepository(db))
        finally:
            db.close()

    if source == "urls":
        print("📡 Fetching ingredients from recipe URLs...\n")
        return populate_ingredient_list(RECIPE_URLS)

    print("📝 Using hardcoded ingredient list...\n")
    return _build_hardcoded_list()


async def _prompt(msg: str) -> str:
    """Non-blocking input() for the async loop."""
    return (await asyncio.to_thread(input, msg)).strip()


# ---------------------------------------------------------------------------
# Modes
# ---------------------------------------------------------------------------
async def _add_all_ingredients(tab, logger, ingredient_list):
    """Browser-add every ingredient in the list (with self-healing)."""
    items = ingredient_list.get_ingredients()
    print(f"\n🛒 Adding {len(items)} ingredients to cart...")
    while ingredient_list.get_ingredients():
        ingredient = ingredient_list.remove_last_ingredient()
        print(f"  Adding: {ingredient.get_name()}")
        await self_healing_call(flows.add_ingredient, ingredient, tab, tab=tab, logger=logger)
        await flows.random_time()


async def _try_reserve(tab, logger):
    """Reserve a timeslot, logging but tolerating failure (sold-out days, etc.)."""
    print("\n📅 Attempting to reserve time slot...")
    try:
        await self_healing_call(flows.reserve_time_slot, tab, tab=tab, logger=logger)
        print("✓ Time slot reserved")
    except Exception as e:  # noqa: BLE001
        print(f"⚠️  Could not reserve time slot - continuing anyway ({type(e).__name__})")


async def _checkout_with_optional_prompt(tab, logger, *, prompt: bool):
    """Advance to checkout, optionally prompting the user first.

    NOTE: the checkout flow stops at HEB's checkout page; it does NOT place a
    paid order (no payment step).
    """
    if prompt:
        print("\n" + "=" * 60)
        print("🛒 Ready to checkout!")
        print("=" * 60)
        response = (await _prompt("\nProceed to checkout? (yes/no): ")).lower()
        if response not in ("yes", "y"):
            print("\n❌ Checkout cancelled by user.")
            await _prompt("Press Enter to close the browser and exit...")
            return
    print("\n💳 Proceeding to checkout...")
    await self_healing_call(flows.checkout, tab, tab=tab, logger=logger)
    print("\n✓ Reached checkout page (no order placed).")


async def login_export_mode(browser, tab, logger, store_id):
    print("\n🔐 LOGIN + EXPORT MODE (refresh auth.json)\n")
    await self_healing_call(flows.login, tab, tab=tab, logger=logger)
    await flows.dismiss_modals(tab)
    print("\n🔐 Exporting browser session for the GraphQL/MCP client...")
    await export_session_to_authjson(browser, tab, store_id=store_id)
    print("✅ Session exported.")


async def test_mode(browser, tab, logger, ingredient_list, store_id):
    print("\n🧪 TEST MODE (no checkout)\n")
    await self_healing_call(flows.login, tab, tab=tab, logger=logger)
    await flows.dismiss_modals(tab)
    await self_healing_call(flows.clear_cart, tab, tab=tab, logger=logger)
    await _try_reserve(tab, logger)

    print("\n🏠 Navigating to homepage for ingredient search...")
    await tab.get(flows.HEB_HOME)
    await flows.random_time()

    await _add_all_ingredients(tab, logger, ingredient_list)

    print("\n🧪 TEST MODE COMPLETE - browser left open for inspection.")
    await _prompt("Press Enter to close the browser and exit...")


async def checkout_with_prompt_mode(browser, tab, logger, ingredient_list, store_id):
    print("\n🤔 CHECKOUT WITH PROMPT MODE\n")
    await self_healing_call(flows.login, tab, tab=tab, logger=logger)
    await flows.dismiss_modals(tab)
    await self_healing_call(flows.clear_cart, tab, tab=tab, logger=logger)
    await _try_reserve(tab, logger)

    print("\n🏠 Navigating to homepage for ingredient search...")
    await tab.get(flows.HEB_HOME)
    await flows.random_time()

    await _add_all_ingredients(tab, logger, ingredient_list)
    await _checkout_with_optional_prompt(tab, logger, prompt=True)


async def auto_checkout_mode(browser, tab, logger, ingredient_list, store_id):
    print("\n🤖 AUTO CHECKOUT MODE\n")
    confirm = await _prompt("Type 'CONFIRM' to proceed with automatic checkout: ")
    if confirm != "CONFIRM":
        print("\n❌ Auto checkout cancelled.")
        return
    await self_healing_call(flows.login, tab, tab=tab, logger=logger)
    await flows.dismiss_modals(tab)
    await self_healing_call(flows.clear_cart, tab, tab=tab, logger=logger)
    await _try_reserve(tab, logger)

    print("\n🏠 Navigating to homepage for ingredient search...")
    await tab.get(flows.HEB_HOME)
    await flows.random_time()

    await _add_all_ingredients(tab, logger, ingredient_list)
    await _checkout_with_optional_prompt(tab, logger, prompt=False)


async def graphql_mode(browser, tab, logger, ingredient_list, store_id):
    print("\n⚡ GRAPHQL MODE (add via API, no checkout)\n")
    await self_healing_call(flows.login, tab, tab=tab, logger=logger)
    await flows.dismiss_modals(tab)
    print("\n🔐 Exporting browser session for GraphQL client...")
    await export_session_to_authjson(browser, tab, store_id=store_id)

    print(f"\n⚡ Adding {len(ingredient_list.get_ingredients())} ingredients via GraphQL...")
    # graphql_cart_sync is a sync wrapper that runs its own event loop, so run
    # it in a worker thread to avoid nesting inside this async loop.
    report = await asyncio.to_thread(
        graphql_cart_sync, ingredient_list, store_id, True
    )
    added = report.get("added", [])
    failed = report.get("failed", [])
    print(f"\n🛒 GraphQL cart summary: {len(added)} added, {len(failed)} failed")
    await _prompt("\nPress Enter to close the browser and exit...")


async def _graphql_login_add(browser, tab, logger, ingredient_list, store_id):
    """Shared GraphQL setup: login, export session, add ingredients via the API.

    Returns the graphql_cart_sync report.
    """
    await self_healing_call(flows.login, tab, tab=tab, logger=logger)
    await flows.dismiss_modals(tab)
    print("\n🔐 Exporting browser session for GraphQL client...")
    await export_session_to_authjson(browser, tab, store_id=store_id)

    print(f"\n⚡ Adding {len(ingredient_list.get_ingredients())} ingredients via GraphQL...")
    report = await asyncio.to_thread(graphql_cart_sync, ingredient_list, store_id, True)
    added = report.get("added", [])
    failed = report.get("failed", [])
    print(f"🛒 GraphQL cart summary: {len(added)} added, {len(failed)} failed")
    return report


async def graphql_checkout_with_prompt_mode(browser, tab, logger, ingredient_list, store_id):
    print("\n⚡🤔 GRAPHQL CHECKOUT WITH PROMPT MODE\n")
    await _graphql_login_add(browser, tab, logger, ingredient_list, store_id)
    await _try_reserve(tab, logger)
    await _checkout_with_optional_prompt(tab, logger, prompt=True)


async def graphql_auto_checkout_mode(browser, tab, logger, ingredient_list, store_id):
    print("\n⚡🤖 GRAPHQL AUTO CHECKOUT MODE\n")
    confirm = await _prompt("Type 'CONFIRM' to proceed with automatic checkout: ")
    if confirm != "CONFIRM":
        print("\n❌ Auto checkout cancelled.")
        return
    await _graphql_login_add(browser, tab, logger, ingredient_list, store_id)
    await _try_reserve(tab, logger)
    await _checkout_with_optional_prompt(tab, logger, prompt=False)


async def update_graphql_hashes_mode(browser, tab, logger, store_id, store_search_address):
    print("\n🔄 UPDATE GRAPHQL HASHES MODE (CDP capture)\n")

    capturer = GraphQLHashCapturer(tab)
    await capturer.start()

    async def _run_step(label, fn, *args):
        print(f"\n{label}")
        try:
            await self_healing_call(fn, *args, tab=tab, logger=logger)
        except Exception as e:  # noqa: BLE001
            print(f"⚠️  {label} incomplete ({type(e).__name__}: {e}) - continuing")
            try:
                await logger.log_failure(
                    tab, getattr(fn, "__name__", str(fn)), e,
                    {"mode": "update_graphql_hashes", "step": label},
                )
            except Exception:  # noqa: BLE001
                pass
        await flows.random_time()
        print(f"    📡 Captured {len(capturer.operations)} GraphQL op(s) so far.")

    # Login + homepage to trigger navigation queries.
    await self_healing_call(flows.login, tab, tab=tab, logger=logger)
    await flows.dismiss_modals(tab)
    print("\n🏠 Loading homepage to trigger navigation queries...")
    await tab.get(flows.HEB_HOME)
    await flows.random_time()

    await _run_step("📅 Exercising time slot reservation...", flows.reserve_time_slot, tab)
    await _run_step("🛒 Visiting cart to trigger cart estimate query...", flows.clear_cart, tab)

    print("\n➕ Adding a sample item to trigger cart mutation...")
    await tab.get(flows.HEB_HOME)
    await flows.random_time()
    await _run_step("➕ Adding sample item 'milk'...", flows.add_ingredient,
                    Ingredient("milk", ["1"], []), tab)

    search_text = store_search_address or "78701"
    await _run_step(f"🏪 Exercising store search/change (near '{search_text}')...",
                    flows.change_store_via_ui, tab, search_text)
    await _run_step("🧾 Walking into checkout to trigger timeslot/checkout queries...",
                    flows.checkout, tab)

    print("\n🔎 Finalizing GraphQL capture...")
    hashes = capturer.hashes
    if not hashes:
        print("\n❌ No GraphQL hashes captured.")
        await _prompt("Press Enter to close the browser and exit...")
        return

    path, samples_path = capturer.save()
    print("\n" + "=" * 60)
    print(f"✅ Captured {len(hashes)} GraphQL operation hash(es)")
    print("=" * 60)
    for name in sorted(hashes):
        marker = "🎯" if name in TARGET_OPERATIONS else "  "
        print(f"  {marker} {name}: {hashes[name][:16]}...")
    print(f"\n💾 Saved to: {path}")
    if samples_path:
        print(f"💾 Operation samples saved to: {samples_path}")
    # Also export auth.json so the MCP session is refreshed in one run.
    print("\n🔐 Exporting browser session for the GraphQL/MCP client...")
    await export_session_to_authjson(browser, tab, store_id=store_id)
    await _prompt("\nPress Enter to close the browser and exit...")


# ---------------------------------------------------------------------------
# Entry
# ---------------------------------------------------------------------------
async def main():
    # An explicit MODE environment variable overrides the .env MODE setting so
    # any mode can be exercised without editing .env (e.g. MODE=test ...).
    mode = (os.environ.get("MODE") or get_setting("MODE", "test")).strip()
    store_id = (get_setting("STORE_ID", "737") or "737").strip()
    store_search_address = (get_setting("STORE_SEARCH_ADDRESS", "") or "").strip()

    print("\n" + "=" * 60)
    print("🥗 AUTO GROCIER - HEB AUTOMATION (nodriver)")
    print("=" * 60)
    print(f"Mode: {mode.upper()}")
    print("=" * 60 + "\n")

    # Only modes that actually shop need an ingredient list. login_export and
    # update_graphql_hashes just drive the browser for auth/hash capture, so
    # loading ingredients there is pointless — and with INGREDIENT_SOURCE=database
    # it blocks on an interactive recipe prompt, which hangs the MCP server's
    # non-interactive auto-login subprocess.
    if mode in ("login_export", "update_graphql_hashes"):
        ingredient_list = IngredientList()
    else:
        ingredient_list = _load_ingredients()
    logger = AsyncDriverLogger(log_dir="debug_logs")

    print("🌐 Starting browser...")
    browser = await start_browser(headless=False)
    tab = await browser.get(flows.HEB_HOME)
    print("✓ Browser started\n")

    keep_open = mode in ("test", "checkout_with_prompt")
    try:
        if mode == "login_export":
            await login_export_mode(browser, tab, logger, store_id)
        elif mode == "test":
            await test_mode(browser, tab, logger, ingredient_list, store_id)
        elif mode == "checkout_with_prompt":
            await checkout_with_prompt_mode(browser, tab, logger, ingredient_list, store_id)
        elif mode == "auto_checkout":
            await auto_checkout_mode(browser, tab, logger, ingredient_list, store_id)
        elif mode == "graphql":
            await graphql_mode(browser, tab, logger, ingredient_list, store_id)
        elif mode == "graphql_checkout_with_prompt":
            await graphql_checkout_with_prompt_mode(browser, tab, logger, ingredient_list, store_id)
        elif mode == "graphql_auto_checkout":
            await graphql_auto_checkout_mode(browser, tab, logger, ingredient_list, store_id)
        elif mode == "update_graphql_hashes":
            await update_graphql_hashes_mode(browser, tab, logger, store_id, store_search_address)
        else:
            print(f"❌ Unsupported MODE: '{mode}'")
            print("Supported: login_export, test, checkout_with_prompt, auto_checkout, "
                  "graphql, graphql_checkout_with_prompt, graphql_auto_checkout, "
                  "update_graphql_hashes")
    except Exception as e:  # noqa: BLE001
        print(f"\n❌ Unexpected error: {e}")
        try:
            await logger.log_failure(tab, "run_main", e, {"mode": mode})
        except Exception:  # noqa: BLE001
            pass
    finally:
        if not keep_open:
            print("\nClosing browser...")
            await stop_browser(browser)
            print("✓ Browser closed\n")


if __name__ == "__main__":
    # nodriver ships its own loop helper; asyncio.run is unreliable with it.
    nodriver.loop().run_until_complete(main())
