"""Parse + persist HEB GraphQL persisted-query hashes captured from live traffic.

HEB uses Apollo "persisted queries": each GraphQL operation is sent with only a
sha256 hash instead of the full query text. HEB rotates these hashes on every
front-end deploy, which invalidates the hard-coded values bundled in
``auto_grocer_mcp``. The nodriver browser flow
(``session_maintenance/hash_capture.py``) subscribes to CDP ``Network`` events and
feeds request bodies into the pure parsers here; the savers write the results to
the JSON override files the GraphQL client loads at runtime.

Usage is driven by the ``capture_hashes`` operation
(``MODE=nodriver OPERATION=capture_hashes python -m session_maintenance.run``).
"""

import json
import os
from pathlib import Path

# Override file consumed by auto_grocer_mcp.clients.graphql._load_persisted_query_overrides
DEFAULT_HASHES_PATH = Path("~/.texas-grocery-mcp/persisted_queries.json").expanduser()

# Sample file recording the full request shape (hash + variables) for every
# operation seen. This is how we discover the operation names and variable
# payloads for flows the vendored client doesn't implement yet (timeslot
# reservation, checkout). Consumed by utility/graphql_checkout.py.
DEFAULT_OPERATIONS_PATH = Path("~/.texas-grocery-mcp/captured_operations.json").expanduser()

# Operations we care about for cart/store flows. We still record any others seen.
# The timeslot/checkout names below are *candidates* - HEB's real operation
# names are discovered at capture time; these just flag the ones we're hunting
# for so the capture summary highlights whether the flows were exercised.
TARGET_OPERATIONS = {
    "cartEstimated",
    "cartItemV2",
    "SelectPickupFulfillment",
    "StoreSearch",
    "ShopNavigation",
    "typeaheadContent",
    "alertEntryPoint",
    "CouponClip",
}


def _parse_operation(post_data):
    """Extract (operationName, sha256Hash) from a GraphQL request body.

    The body may be a single operation object or a list (batched). Returns a
    list of (name, hash) tuples for every operation that carries a persisted
    query hash.
    """
    try:
        payload = json.loads(post_data)
    except (TypeError, ValueError):
        return []

    operations = payload if isinstance(payload, list) else [payload]
    found = []
    for op in operations:
        if not isinstance(op, dict):
            continue
        name = op.get("operationName")
        extensions = op.get("extensions", {}) or {}
        persisted = extensions.get("persistedQuery", {}) or {}
        sha = persisted.get("sha256Hash")
        if name and sha:
            found.append((str(name), str(sha)))
    return found


def _parse_operation_samples(post_data):
    """Extract (operationName, sha256Hash, variables, query) from a request body.

    Like :func:`_parse_operation` but also captures the request ``variables`` and
    the full ``query`` text when present. HEB's Apollo client sends the full
    query only on an APQ cache MISS (the registration round-trip); capturing it
    lets the GraphQL client re-register low-traffic operations (e.g.
    ``SelectPickupFulfillment``) that HEB evicts from its shared APQ cache.
    Returns a list of (name, hash, variables, query|None) tuples for every
    operation carrying a persisted query hash.
    """
    try:
        payload = json.loads(post_data)
    except (TypeError, ValueError):
        return []

    operations = payload if isinstance(payload, list) else [payload]
    found = []
    for op in operations:
        if not isinstance(op, dict):
            continue
        name = op.get("operationName")
        extensions = op.get("extensions", {}) or {}
        persisted = extensions.get("persistedQuery", {}) or {}
        sha = persisted.get("sha256Hash")
        if name and sha:
            variables = op.get("variables")
            if not isinstance(variables, dict):
                variables = {}
            query = op.get("query")
            query = query if isinstance(query, str) and query.strip() else None
            found.append((str(name), str(sha), variables, query))
    return found


def save_hashes(hashes, path=None):
    """Merge captured hashes into the override file and write it.

    Existing entries are preserved unless a freshly captured hash replaces them.
    Returns the path written to.
    """
    path = Path(path).expanduser() if path else DEFAULT_HASHES_PATH

    existing = {}
    if path.exists():
        try:
            with open(path, encoding="utf-8") as f:
                loaded = json.load(f)
            if isinstance(loaded, dict):
                existing = loaded
        except (json.JSONDecodeError, OSError):
            existing = {}

    merged = {**existing, **hashes}

    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(merged, f, indent=2, sort_keys=True)

    # Make the override file the active one for this process too.
    os.environ.setdefault("GRAPHQL_HASHES_PATH", str(path))

    return path


def save_operation_samples(operations, path=None):
    """Merge captured operation samples into the samples file and write it.

    Existing entries are preserved unless a freshly captured sample replaces
    them. Returns the path written to. The samples file is consumed by
    ``utility/graphql_checkout.py`` to resolve operation names and build
    request variables for timeslot/checkout calls.
    """
    path = Path(path).expanduser() if path else DEFAULT_OPERATIONS_PATH

    existing = {}
    if path.exists():
        try:
            with open(path, encoding="utf-8") as f:
                loaded = json.load(f)
            if isinstance(loaded, dict):
                existing = loaded
        except (json.JSONDecodeError, OSError):
            existing = {}

    merged = {**existing, **operations}

    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(merged, f, indent=2, sort_keys=True)

    return path

