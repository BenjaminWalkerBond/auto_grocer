"""Capture HEB GraphQL persisted-query hashes from a live browser session.

HEB uses Apollo "persisted queries": each GraphQL operation is sent with only a
sha256 hash instead of the full query text. HEB rotates these hashes on every
front-end deploy, which invalidates the hard-coded values bundled in
``texas_grocery_mcp``. This module sniffs the hashes out of the browser's
network traffic (via Chrome DevTools performance logs) while the user-driven
flow exercises the real site, then writes them to a JSON override file that the
GraphQL client loads at runtime.

Usage is driven by the ``update_graphql_hashes`` program mode in ``main.py``.
"""

import json
import os
from pathlib import Path


# Override file consumed by texas_grocery_mcp.clients.graphql._load_persisted_query_overrides
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


def _extract_post_data(driver, message_params):
    """Return the request body for a CDP requestWillBeSent event.

    Falls back to ``Network.getRequestPostData`` when the body is not inlined
    in the performance-log event (Chrome omits large/streamed bodies).
    """
    request = message_params.get("request", {}) or {}
    post_data = request.get("postData")
    if post_data:
        return post_data

    if not request.get("hasPostData"):
        return None

    request_id = message_params.get("requestId")
    if not request_id:
        return None

    try:
        result = driver.execute_cdp_cmd(
            "Network.getRequestPostData", {"requestId": request_id}
        )
        return result.get("postData")
    except Exception:  # noqa: BLE001 - body may no longer be retainable
        return None


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
    """Extract (operationName, sha256Hash, variables) from a GraphQL request body.

    Like :func:`_parse_operation` but also captures the request ``variables`` so
    we learn the payload shape of operations the GraphQL client doesn't
    implement yet (timeslot reservation, checkout). Returns a list of
    (name, hash, variables) tuples for every operation carrying a persisted
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
            variables = op.get("variables")
            if not isinstance(variables, dict):
                variables = {}
            found.append((str(name), str(sha), variables))
    return found


def capture_graphql_hashes(driver):
    """Read the browser's performance log and return {operationName: sha256Hash}.

    Requires the driver to have been started with performance logging enabled
    (``goog:loggingPrefs = {"performance": "ALL"}``).
    """
    hashes = {}

    try:
        logs = driver.get_log("performance")
    except Exception as e:  # noqa: BLE001
        print(f"    ⚠️  Could not read performance log: {e}")
        return hashes

    for entry in logs:
        try:
            message = json.loads(entry["message"])["message"]
        except (KeyError, ValueError, TypeError):
            continue

        if message.get("method") != "Network.requestWillBeSent":
            continue

        params = message.get("params", {}) or {}
        request = params.get("request", {}) or {}
        url = request.get("url", "")
        if "/graphql" not in url or request.get("method") != "POST":
            continue

        post_data = _extract_post_data(driver, params)
        if not post_data:
            continue

        for name, sha in _parse_operation(post_data):
            hashes[name] = sha

    return hashes


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


def capture_graphql_operations(driver, into=None):
    """Drain the performance log and return {operationName: {hash, variables}}.

    Records the full request shape (persisted-query hash plus the request
    ``variables``) for every GraphQL operation seen. This is how we discover
    the operation names and payload shapes for flows the vendored GraphQL
    client doesn't implement yet (timeslot reservation, checkout), so they can
    later be replayed as pure GraphQL calls.

    IMPORTANT: ``driver.get_log("performance")`` is DESTRUCTIVE - each call
    returns only the entries logged since the previous call and clears the
    buffer. The buffer is also bounded, so on a long session early requests can
    roll off before the end. To capture reliably, call this helper repeatedly
    throughout the flow and pass the same accumulator via ``into`` so results
    are merged instead of lost.

    Args:
        driver: Selenium WebDriver with performance logging enabled
            (``goog:loggingPrefs = {"performance": "ALL"}``).
        into: Optional existing ``{name: {hash, variables}}`` dict to merge new
            captures into. A new dict is created when omitted.

    Returns:
        The accumulator dict (the same object passed as ``into`` when given).
    """
    operations = into if into is not None else {}

    try:
        logs = driver.get_log("performance")
    except Exception as e:  # noqa: BLE001
        print(f"    ⚠️  Could not read performance log: {e}")
        return operations

    for entry in logs:
        try:
            message = json.loads(entry["message"])["message"]
        except (KeyError, ValueError, TypeError):
            continue

        if message.get("method") != "Network.requestWillBeSent":
            continue

        params = message.get("params", {}) or {}
        request = params.get("request", {}) or {}
        url = request.get("url", "")
        if "/graphql" not in url or request.get("method") != "POST":
            continue

        post_data = _extract_post_data(driver, params)
        if not post_data:
            continue

        for name, sha, variables in _parse_operation_samples(post_data):
            # Last-seen wins; later requests usually carry fuller variables.
            operations[name] = {"hash": sha, "variables": variables}

    return operations


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

