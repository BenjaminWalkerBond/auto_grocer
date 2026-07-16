"""Async mode dispatcher for the auto_grocier browser automation (nodriver).

Canonical modes (read from the MODE setting in .env, or the MODE env var which
overrides):

    login_export           - log in and export auth.json (refresh the MCP session).
    update_graphql_hashes  - login, exercise flows, capture GraphQL persisted-query
                             hashes via CDP, and re-export auth.json.
    shop                   - end-to-end shopping. Tunables (env / .env):
                               SHOP_SOURCE = graphql (default) | browser
                               CHECKOUT    = none (default) | prompt | auto

Deprecated aliases (still work; they map onto `shop` and print a warning):
    test, checkout_with_prompt, auto_checkout,
    graphql, graphql_checkout_with_prompt, graphql_auto_checkout

Note: no mode places a paid order; checkout only advances to HEB's checkout page.
Placing a paid order is the MCP server's guarded ``place_order`` tool. The WAF
baseline probe is separate: ``python -m grocery_browser.waf_probe``.

Run:
    python -m grocery_browser.run                    # uses MODE from .env
    MODE=shop CHECKOUT=prompt python -m grocery_browser.run
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

from session_maintenance.browser import start_browser, stop_browser
from session_maintenance.logger import AsyncDriverLogger
from session_maintenance.auth_export import export_session_to_authjson
from session_maintenance.self_healing import self_healing_call
from session_maintenance.hash_capture import GraphQLHashCapturer
from session_maintenance import flows


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


# Deprecated MODE names -> (SHOP_SOURCE, CHECKOUT) for the unified `shop` mode.
# Kept so existing .env / scripts don't break; they print a deprecation notice.
_DEPRECATED_MODE_ALIASES = {
    "test": ("browser", "none"),
    "checkout_with_prompt": ("browser", "prompt"),
    "auto_checkout": ("browser", "auto"),
    "graphql": ("graphql", "none"),
    "graphql_checkout_with_prompt": ("graphql", "prompt"),
    "graphql_auto_checkout": ("graphql", "auto"),
}


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


async def shop_mode(browser, tab, logger, ingredient_list, store_id, *,
                    via_graphql=True, checkout="none"):
    """Unified shopping flow (replaces test / *_checkout / graphql* modes).

    Args:
        via_graphql: True adds ingredients through the GraphQL API (fast); False
            drives the browser UI (legacy path, useful for testing the flows).
        checkout: "none" (add only, leave the browser open), "prompt" (advance to
            HEB's checkout page after confirming), or "auto" (advance without a
            per-step prompt). No value ever places a paid order.
    """
    src_label = "GraphQL" if via_graphql else "browser UI"
    print(f"\n🛒 SHOP MODE (add via {src_label}, checkout={checkout})\n")

    if checkout == "auto":
        confirm = await _prompt("Type 'CONFIRM' to proceed with automatic checkout: ")
        if confirm != "CONFIRM":
            print("\n❌ Auto checkout cancelled.")
            return

    await self_healing_call(flows.login, tab, tab=tab, logger=logger)
    await flows.dismiss_modals(tab)

    if via_graphql:
        print("\n🔐 Exporting browser session for the GraphQL client...")
        await export_session_to_authjson(browser, tab, store_id=store_id)
        n = len(ingredient_list.get_ingredients())
        print(f"\n⚡ Adding {n} ingredients via GraphQL...")
        # graphql_cart_sync runs its own event loop, so offload to a thread.
        report = await asyncio.to_thread(graphql_cart_sync, ingredient_list, store_id, True)
        print(f"🛒 GraphQL cart summary: {len(report.get('added', []))} added, "
              f"{len(report.get('failed', []))} failed")
        # For GraphQL adds, reserve a slot only when we're actually checking out.
        if checkout != "none":
            await _try_reserve(tab, logger)
    else:
        await self_healing_call(flows.clear_cart, tab, tab=tab, logger=logger)
        await _try_reserve(tab, logger)
        print("\n🏠 Navigating to homepage for ingredient search...")
        await tab.get(flows.HEB_HOME)
        await flows.random_time()
        await _add_all_ingredients(tab, logger, ingredient_list)

    if checkout == "none":
        if not via_graphql:
            print("\n🧹 Clearing cart at end of browser test...")
            await self_healing_call(flows.clear_cart, tab, tab=tab, logger=logger)
        print("\n🧪 SHOP COMPLETE (no checkout) - browser left open for inspection.")
    else:
        await _checkout_with_optional_prompt(tab, logger, prompt=(checkout == "prompt"))

    # Leave the browser open for inspection except in fully-automatic checkout.
    if checkout != "auto":
        await _prompt("\nPress Enter to close the browser and exit...")


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
    await _run_step("🛒 Visiting cart to trigger cart estimate query...", flows.visit_cart, tab)

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

    # Clean up ONLY the sample 'milk' item we added above. It exists solely to
    # trigger the cart-mutation hash; removing just this line leaves any items
    # the user is accumulating through the week untouched (never clear the cart).
    await _run_step("🧹 Removing sample item 'milk'...", flows.remove_ingredient,
                    "milk", tab)

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
    # any mode can be exercised without editing .env (e.g. MODE=shop ...).
    mode = (os.environ.get("MODE") or get_setting("MODE", "shop")).strip()
    store_id = (get_setting("STORE_ID", "737") or "737").strip()
    store_search_address = (get_setting("STORE_SEARCH_ADDRESS", "") or "").strip()

    # Resolve deprecated aliases onto the canonical `shop` mode + its tunables.
    shop_via_graphql = True
    shop_checkout = "none"
    if mode in _DEPRECATED_MODE_ALIASES:
        src, chk = _DEPRECATED_MODE_ALIASES[mode]
        print(f"⚠️  MODE '{mode}' is deprecated -> use "
              f"MODE=shop SHOP_SOURCE={src} CHECKOUT={chk}")
        shop_via_graphql = (src == "graphql")
        shop_checkout = chk
        mode = "shop"
    elif mode == "shop":
        src = (get_setting("SHOP_SOURCE", "graphql") or "graphql").strip().lower()
        shop_via_graphql = (src != "browser")
        shop_checkout = (get_setting("CHECKOUT", "none") or "none").strip().lower()

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

    try:
        if mode == "login_export":
            await login_export_mode(browser, tab, logger, store_id)
        elif mode == "update_graphql_hashes":
            await update_graphql_hashes_mode(browser, tab, logger, store_id, store_search_address)
        elif mode == "shop":
            await shop_mode(browser, tab, logger, ingredient_list, store_id,
                            via_graphql=shop_via_graphql, checkout=shop_checkout)
        else:
            print(f"❌ Unsupported MODE: '{mode}'")
            print("Supported: login_export, update_graphql_hashes, shop "
                  "(SHOP_SOURCE=graphql|browser, CHECKOUT=none|prompt|auto).")
    except Exception as e:  # noqa: BLE001
        print(f"\n❌ Unexpected error: {e}")
        try:
            await logger.log_failure(tab, "run_main", e, {"mode": mode})
        except Exception:  # noqa: BLE001
            pass
    finally:
        print("\nClosing browser...")
        await stop_browser(browser)
        print("✓ Browser closed\n")


if __name__ == "__main__":
    # nodriver ships its own loop helper; asyncio.run is unreliable with it.
    nodriver.loop().run_until_complete(main())
