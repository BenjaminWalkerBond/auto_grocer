"""Store search and selection for the GraphQL cart modes.

Lets the user find the closest HEB stores to an address and pick one to use as
the active store for searching/pricing and (when authenticated) for pickup
fulfillment. Backed by the vendored ``auto_grocer_mcp`` GraphQL client.
"""

import asyncio
import re
import threading

# Process-local cache of stores seen via search_stores, keyed by store_id.
# Mirrors texas-grocery-mcp's StateManager.cache_stores_sync/get_cached_store:
# lets set_store enrich error/success messages with a store's name/address
# without a second network round-trip, and is intentionally best-effort/
# in-memory only (lost on restart; repopulated by the next search).
_STORE_CACHE_LOCK = threading.Lock()
_STORE_CACHE: dict[str, object] = {}


def cache_stores(stores):
    """Cache a list of store objects/dicts (from a search_stores result) by id."""
    with _STORE_CACHE_LOCK:
        for store in stores or []:
            store_id = str(
                store.get("store_id") if isinstance(store, dict) else getattr(store, "store_id", "")
            )
            if store_id:
                _STORE_CACHE[store_id] = store


def get_cached_store(store_id):
    """Return the cached store object/dict for ``store_id``, or None."""
    with _STORE_CACHE_LOCK:
        return _STORE_CACHE.get(str(store_id))


def _store_sort_key(store):
    """Sort key putting nearest stores first; unknown distances go last."""
    distance = getattr(store, "distance_miles", None)
    return distance if distance is not None else float("inf")


async def _find_nearest_stores(address, radius_miles, limit):
    """Search for stores near an address and return the closest ``limit``."""
    from auto_grocer_mcp.clients.graphql import HEBGraphQLClient

    client = HEBGraphQLClient()
    try:
        result = await client.search_stores(address=address, radius_miles=radius_miles)
        stores = sorted(getattr(result, "stores", []) or [], key=_store_sort_key)
        cache_stores(stores)
        return stores[:limit], getattr(result, "error", None)
    finally:
        await client.close()


async def _select_store(store_id):
    """Set the active pickup store via GraphQL (requires authentication)."""
    from auto_grocer_mcp.clients.graphql import HEBGraphQLClient

    client = HEBGraphQLClient()
    try:
        return await client.select_store(str(store_id))
    finally:
        await client.close()


def find_nearest_stores(address, radius_miles=25, limit=3):
    """Synchronous wrapper around :func:`_find_nearest_stores`."""
    return asyncio.run(_find_nearest_stores(address, radius_miles, limit))


def select_store(store_id):
    """Synchronous wrapper around :func:`_select_store`."""
    return asyncio.run(_select_store(store_id))


def _format_store(store):
    """Build a one-line display string for a store."""
    name = getattr(store, "name", "Unknown")
    addr = getattr(store, "address", "")
    distance = getattr(store, "distance_miles", None)
    dist_str = f"{distance:.1f} mi" if distance is not None else "? mi"
    store_id = getattr(store, "store_id", "?")
    return f"{name} (#{store_id}) - {addr} [{dist_str}]"


def select_store_interactive(default_store_id, default_address="", radius_miles=25):
    """Interactively let the user search for and pick an HEB store.

    Args:
        default_store_id: The currently configured store id (kept if unchanged).
        default_address: Address/zip used as the prompt default for searching.
        radius_miles: Search radius.

    Returns:
        The chosen store id (string). Falls back to ``default_store_id``.
    """
    print("\n" + "="*60)
    print("🏪 STORE SELECTION")
    print("="*60)
    if default_store_id:
        print(f"Current store: #{default_store_id}")

    prompt = "Search for a different store? (Enter = keep current, 's' = search): "
    choice = input(prompt).strip().lower()
    if choice not in ("s", "search", "y", "yes"):
        print(f"Keeping current store #{default_store_id}.")
        return default_store_id

    addr_prompt = "Enter a zip code or address"
    if default_address:
        addr_prompt += f" (Enter = {default_address})"
    addr_prompt += ": "
    address = input(addr_prompt).strip() or default_address

    if not address:
        print("⚠️  No address provided - keeping current store.")
        return default_store_id

    print(f"\n🔎 Searching for stores near '{address}'...")
    try:
        stores, error = find_nearest_stores(address, radius_miles=radius_miles, limit=3)
    except Exception as e:  # noqa: BLE001
        print(f"⚠️  Store search failed ({e}). Keeping current store.")
        return default_store_id

    if error:
        print(f"⚠️  Store search returned an error: {error}")
    if not stores:
        print("⚠️  No stores found - keeping current store.")
        return default_store_id

    print("\nClosest stores:")
    for idx, store in enumerate(stores, start=1):
        print(f"  {idx}. {_format_store(store)}")

    pick = input(f"\nSelect a store (1-{len(stores)}, Enter = keep current): ").strip()
    if not pick:
        print(f"Keeping current store #{default_store_id}.")
        return default_store_id

    try:
        index = int(pick) - 1
        chosen = stores[index]
    except (ValueError, IndexError):
        print("⚠️  Invalid selection - keeping current store.")
        return default_store_id

    chosen_id = str(getattr(chosen, "store_id", default_store_id))
    print(f"\n✓ Selected: {_format_store(chosen)}")

    # Activate the store for pickup fulfillment (best-effort; requires auth).
    try:
        result = select_store(chosen_id)
        if isinstance(result, dict) and result.get("error"):
            print(
                "⚠️  Could not set active pickup store via GraphQL "
                f"({result.get('message') or result.get('code')}). "
                "Continuing with it as the search/pricing store."
            )
    except Exception as e:  # noqa: BLE001
        print(f"⚠️  select_store failed ({e}). Continuing with chosen store anyway.")

    return chosen_id


def update_config_value(key, value, config_path):
    """Update or append ``KEY=VALUE`` in a ``.env``-style file.

    Preserves comments and other lines. Returns True on success.
    """
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
    except OSError:
        return False

    pattern = re.compile(rf"^\s*{re.escape(key)}\s*=")
    updated = False
    for i, line in enumerate(lines):
        if pattern.match(line):
            lines[i] = f"{key}={value}\n"
            updated = True
            break

    if not updated:
        if lines and not lines[-1].endswith("\n"):
            lines[-1] += "\n"
        lines.append(f"{key}={value}\n")

    try:
        with open(config_path, "w", encoding="utf-8") as f:
            f.writelines(lines)
    except OSError:
        return False

    return True
