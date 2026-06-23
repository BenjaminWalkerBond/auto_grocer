"""Async mode dispatcher for the nodriver prototype.

Mirrors the MODES in main.py but on the async nodriver stack. Supported modes
(read from config.txt MODE):

    login_export            - log in and export auth.json (refresh the MCP session).
    test                    - login, clear cart, reserve slot, add ingredients (no checkout).
    graphql                 - login + export, then add ingredients via the GraphQL API.
    update_graphql_hashes   - login, exercise flows, capture GraphQL hashes via CDP.

Run:
    python -m migration.nodriver.run
"""
from __future__ import annotations

import os
import asyncio

import nodriver

from claude import parse_config
from classes.IngredientList import IngredientList
from classes.Ingredient import Ingredient
from recipe_grabber import clean_ingredient
from utility.graphql_cart import graphql_cart_sync
from utility.graphql_hash_capture import TARGET_OPERATIONS

from migration.nodriver.browser import start_browser, stop_browser
from migration.nodriver.logger import AsyncDriverLogger
from migration.nodriver.auth_export import export_session_to_authjson
from migration.nodriver.self_healing import self_healing_call
from migration.nodriver.hash_capture import GraphQLHashCapturer
from migration.nodriver import flows


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


def _build_ingredient_list() -> IngredientList:
    IL = IngredientList()
    for raw in HARDCODED_INGREDIENTS:
        name, amount, unit = clean_ingredient(raw)
        IL.add_ingredient(Ingredient(name, amount, unit))
    return IL


async def _prompt(msg: str) -> str:
    """Non-blocking input() for the async loop."""
    return (await asyncio.to_thread(input, msg)).strip()


# ---------------------------------------------------------------------------
# Modes
# ---------------------------------------------------------------------------
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

    print("\n📅 Attempting to reserve time slot...")
    try:
        await self_healing_call(flows.reserve_time_slot, tab, tab=tab, logger=logger)
    except Exception as e:  # noqa: BLE001
        print(f"⚠️  Could not reserve time slot - continuing anyway ({type(e).__name__})")

    print("\n🏠 Navigating to homepage for ingredient search...")
    await tab.get(flows.HEB_HOME)
    await flows.random_time()

    items = ingredient_list.get_ingredients()
    print(f"\n🛒 Adding {len(items)} ingredients to cart...")
    while ingredient_list.get_ingredients():
        ingredient = ingredient_list.remove_last_ingredient()
        print(f"  Adding: {ingredient.get_name()}")
        await self_healing_call(flows.add_ingredient, ingredient, tab, tab=tab, logger=logger)
        await flows.random_time()

    print("\n🧪 TEST MODE COMPLETE - browser left open for inspection.")
    await _prompt("Press Enter to close the browser and exit...")


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
    cfg = parse_config(os.path.join(os.getcwd(), "config.txt"))
    # An explicit MODE environment variable overrides config.txt so the
    # prototype can be exercised without editing config (e.g. MODE=test ...).
    mode = (os.environ.get("MODE") or cfg.get("MODE", "test")).strip()
    store_id = cfg.get("STORE_ID", "737").strip()
    store_search_address = cfg.get("STORE_SEARCH_ADDRESS", "").strip()

    print("\n" + "=" * 60)
    print("🥗 AUTO GROCIER - HEB AUTOMATION (nodriver prototype)")
    print("=" * 60)
    print(f"Mode: {mode.upper()}")
    print("=" * 60 + "\n")

    ingredient_list = _build_ingredient_list()
    logger = AsyncDriverLogger(log_dir="debug_logs")

    print("🌐 Starting browser...")
    browser = await start_browser(headless=False)
    tab = await browser.get(flows.HEB_HOME)
    print("✓ Browser started\n")

    keep_open = mode == "test"
    try:
        if mode == "login_export":
            await login_export_mode(browser, tab, logger, store_id)
        elif mode == "test":
            await test_mode(browser, tab, logger, ingredient_list, store_id)
        elif mode == "graphql":
            await graphql_mode(browser, tab, logger, ingredient_list, store_id)
        elif mode == "update_graphql_hashes":
            await update_graphql_hashes_mode(browser, tab, logger, store_id, store_search_address)
        else:
            print(f"❌ Unsupported MODE for the prototype: '{mode}'")
            print("Supported: login_export, test, graphql, update_graphql_hashes")
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
