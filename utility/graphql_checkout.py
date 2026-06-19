"""GraphQL-based timeslot reservation and checkout for auto_grocier.

The vendored ``texas_grocery_mcp`` GraphQL client implements product search,
cart, store, and coupon operations, but it has **no** operations for reserving
a pickup time slot or for checkout / placing an order. HEB's real operation
names, persisted-query sha256 hashes, and request-variable shapes for those
flows are not known ahead of time - they have to be captured from a live
browser session.

The ``update_graphql_hashes`` program mode (see ``main.py``) drives a real
browser through the timeslot and checkout flows and records every GraphQL
operation it sees - name, hash, and variables - into
``~/.texas-grocery-mcp/captured_operations.json`` (see
``utility/graphql_hash_capture.py``).

This module reads that capture file, resolves which captured operation
corresponds to "list timeslots", "reserve timeslot", "checkout review", and
"place order" (by keyword-matching the operation names, since the exact names
aren't known in advance), registers their hashes with the GraphQL client, and
replays them as authenticated GraphQL calls.

Until a capture run has populated the samples file, every public function
returns a structured ``OPERATION_NOT_CAPTURED`` error instead of raising, so
the MCP tools degrade gracefully.

Public sync entry points (used by ``mcp_server.py``):
    list_timeslots_sync(store_id)
    reserve_timeslot_sync(slot_id, store_id, extra_variables)
    checkout_sync(place_order=False)
"""

import asyncio
import json
from pathlib import Path


DEFAULT_OPERATIONS_PATH = Path(
    "~/.texas-grocery-mcp/captured_operations.json"
).expanduser()

# Keyword hints used to map captured operation names onto the four flows we
# need. Matching is case-insensitive substring matching against the operation
# name. ``prefer`` boosts a candidate; ``avoid`` disqualifies it.
_TIMESLOT_LIST = {
    "include": ("timeslot", "time_slot", "slot", "window", "reservation", "fulfillment"),
    "prefer": ("available", "windows", "slots", "timeslots", "get", "list"),
    "avoid": ("reserve", "select", "book", "set", "update", "create", "cart", "store"),
}
_TIMESLOT_RESERVE = {
    "include": ("timeslot", "time_slot", "slot", "window", "reservation", "reserve"),
    "prefer": ("reserve", "select", "book", "set", "update", "create", "schedule"),
    "avoid": ("available", "list", "cart", "store", "search"),
}
_CHECKOUT_REVIEW = {
    "include": ("checkout", "order", "review", "fulfillment"),
    "prefer": ("checkout", "review", "begin", "start", "init", "summary", "get"),
    "avoid": ("place", "submit", "confirm", "pay", "cart", "coupon"),
}
_PLACE_ORDER = {
    "include": ("order", "checkout", "place", "submit", "confirm"),
    "prefer": ("place", "submit", "confirm", "createorder", "pay"),
    "avoid": ("review", "available", "list", "cart", "coupon", "search"),
}


def _not_captured(flow):
    """Structured error returned when an operation hasn't been captured yet."""
    return {
        "error": True,
        "code": "OPERATION_NOT_CAPTURED",
        "flow": flow,
        "message": (
            f"No captured GraphQL operation matches '{flow}'. Run the "
            "undetected-chromedriver maintenance workflow "
            "(MODE=update_graphql_hashes python main.py) to capture the "
            "timeslot/checkout operations from a live session, then retry."
        ),
    }


def _load_samples(path=None):
    """Load the captured operation samples file: {name: {hash, variables}}."""
    path = Path(path).expanduser() if path else DEFAULT_OPERATIONS_PATH
    if not path.exists():
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def _score(name, spec):
    """Score a captured operation name against a keyword spec.

    Returns ``None`` if the name is disqualified (no include hit, or an avoid
    hit), otherwise an integer score (higher is a better match).
    """
    lowered = name.lower()
    if not any(k in lowered for k in spec["include"]):
        return None
    if any(k in lowered for k in spec["avoid"]):
        return None
    return 1 + sum(1 for k in spec["prefer"] if k in lowered)


def _resolve(spec, samples):
    """Return (op_name, sample_dict) for the best-matching captured operation.

    ``sample_dict`` is ``{"hash": str, "variables": dict}``. Returns
    ``(None, None)`` when nothing matches.
    """
    best_name = None
    best_score = 0
    for name, sample in samples.items():
        if not isinstance(sample, dict) or not sample.get("hash"):
            continue
        score = _score(name, spec)
        if score is not None and score > best_score:
            best_name, best_score = name, score
    if best_name is None:
        return None, None
    return best_name, samples[best_name]


def _register_hash(op_name, sha):
    """Register a captured operation hash with the GraphQL client.

    The client's executor rejects any operation name not present in its
    ``PERSISTED_QUERIES`` map, so we inject the captured hash before replaying.
    Also re-applies the persisted_queries.json overrides so any rotated hashes
    are current.
    """
    from texas_grocery_mcp.clients import graphql as gql

    gql.reload_persisted_query_overrides()
    gql.PERSISTED_QUERIES[op_name] = sha


async def _run_operation(client, op_name, variables):
    """Execute a captured operation as an authenticated persisted query."""
    auth_client = await client._get_authenticated_client()
    if not auth_client:
        return {"error": True, "code": "NOT_AUTHENTICATED", "message": "Login required"}
    return await client._execute_persisted_query_with_client(
        auth_client, op_name, variables
    )


async def _list_timeslots(store_id):
    from texas_grocery_mcp.clients.graphql import HEBGraphQLClient

    samples = _load_samples()
    op_name, sample = _resolve(_TIMESLOT_LIST, samples)
    if not op_name:
        return _not_captured("list_timeslots")

    client = HEBGraphQLClient()
    try:
        _register_hash(op_name, sample["hash"])
        variables = dict(sample.get("variables") or {})
        variables.setdefault("userIsLoggedIn", True)
        if store_id is not None:
            for key in ("storeId", "pickupStoreId"):
                if key in variables:
                    variables[key] = (
                        int(store_id) if key == "storeId" else str(store_id)
                    )
        result = await _run_operation(client, op_name, variables)
        return {"operation": op_name, "result": result}
    except Exception as e:  # noqa: BLE001
        return {"error": True, "code": "OPERATION_FAILED", "operation": op_name, "message": str(e)}
    finally:
        await client.close()


async def _reserve_timeslot(slot_id, store_id, extra_variables):
    from texas_grocery_mcp.clients.graphql import HEBGraphQLClient

    samples = _load_samples()
    op_name, sample = _resolve(_TIMESLOT_RESERVE, samples)
    if not op_name:
        return _not_captured("reserve_timeslot")

    client = HEBGraphQLClient()
    try:
        _register_hash(op_name, sample["hash"])
        variables = dict(sample.get("variables") or {})
        variables.setdefault("userIsLoggedIn", True)
        if store_id is not None:
            for key in ("storeId", "pickupStoreId"):
                if key in variables:
                    variables[key] = (
                        int(store_id) if key == "storeId" else str(store_id)
                    )
        if slot_id is not None:
            # The exact slot field name varies; set the common candidates that
            # already exist in the captured template, and always pass slotId.
            matched = False
            for key in ("timeslotId", "timeSlotId", "slotId", "reservationId", "windowId"):
                if key in variables:
                    variables[key] = slot_id
                    matched = True
            if not matched:
                variables["slotId"] = slot_id
        if extra_variables:
            variables.update(extra_variables)
        result = await _run_operation(client, op_name, variables)
        return {"operation": op_name, "result": result}
    except Exception as e:  # noqa: BLE001
        return {"error": True, "code": "OPERATION_FAILED", "operation": op_name, "message": str(e)}
    finally:
        await client.close()


async def _checkout(place_order):
    from texas_grocery_mcp.clients.graphql import HEBGraphQLClient

    samples = _load_samples()
    spec = _PLACE_ORDER if place_order else _CHECKOUT_REVIEW
    op_name, sample = _resolve(spec, samples)
    if not op_name:
        return _not_captured("place_order" if place_order else "checkout")

    client = HEBGraphQLClient()
    try:
        _register_hash(op_name, sample["hash"])
        variables = dict(sample.get("variables") or {})
        variables.setdefault("userIsLoggedIn", True)
        result = await _run_operation(client, op_name, variables)
        payload = {"operation": op_name, "result": result}
        if not place_order:
            payload["note"] = "Order review only. No order placed, no charge."
        return payload
    except Exception as e:  # noqa: BLE001
        return {"error": True, "code": "OPERATION_FAILED", "operation": op_name, "message": str(e)}
    finally:
        await client.close()


# ---------------------------------------------------------------------------
# Synchronous entry points
# ---------------------------------------------------------------------------
def list_timeslots_sync(store_id=None):
    """List available pickup time slots via GraphQL."""
    return asyncio.run(_list_timeslots(store_id))


def reserve_timeslot_sync(slot_id, store_id=None, extra_variables=None):
    """Reserve a pickup time slot via GraphQL.

    Args:
        slot_id: The time slot id to reserve (from list_timeslots_sync).
        store_id: Optional store id to target.
        extra_variables: Optional dict merged into the request variables to
            cover fields whose names differ from the defaults.
    """
    return asyncio.run(_reserve_timeslot(slot_id, store_id, extra_variables))


def checkout_sync(place_order=False):
    """Run checkout via GraphQL.

    With ``place_order=False`` (default) this only advances to order review and
    never charges. With ``place_order=True`` it replays the place-order
    operation, which submits the paid order.
    """
    return asyncio.run(_checkout(place_order))
