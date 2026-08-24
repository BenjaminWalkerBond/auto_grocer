"""Regression tests for the deployed ``auto_grocer.mcp_server`` tools.

These guard against the class of bug where an edit deletes/renames a private
helper (e.g. ``_ensure_authed``) that the ``@mcp.tool()`` functions call, which
only surfaces at call time as a ``NameError`` — not at import time and not from a
tool-registration check. Each test drives the real tool function with auth forced
off, so the tool body (and every helper name it references before the auth gate)
must resolve.
"""

import pytest

from auto_grocer import mcp_server as m


def test_auth_helpers_are_defined():
    """The private helpers the tools depend on must exist as callables."""
    for name in ("_ensure_authed", "_is_authed", "_auto_authenticate", "_capture_hashes"):
        assert callable(getattr(m, name, None)), f"{name} is missing or not callable"


def test_ensure_authed_returns_false_without_session(monkeypatch):
    """_ensure_authed must run end-to-end (regression for the NameError bug)."""
    monkeypatch.setattr(m, "_is_authed", lambda: False)
    monkeypatch.setattr(m, "_AUTO_LOGIN", False)
    assert m._ensure_authed() is False


# Auth-gated tools that short-circuit to NOT_AUTHENTICATED. Each entry is
# (tool_name, args) chosen to reach the auth gate without needing the network.
_AUTH_GATED_TOOLS = [
    ("add_groceries", (["whole milk"],)),
    ("add_products_by_id", (["1234"],)),
    ("search_products", ("whole milk",)),
    ("set_store", ("14",)),
    ("get_cart", ()),
    ("clear_cart", ()),
    ("get_product_details", ("1234",)),
    ("list_timeslots", ()),
    ("checkout", ()),
]


@pytest.mark.parametrize("tool_name,args", _AUTH_GATED_TOOLS)
def test_auth_gated_tool_returns_not_authenticated(tool_name, args, monkeypatch):
    """Each auth-gated tool must reach its auth gate without a NameError.

    With no session and auto-login disabled, the tool should return the
    structured NOT_AUTHENTICATED payload rather than raising.
    """
    monkeypatch.setattr(m, "_is_authed", lambda: False)
    monkeypatch.setattr(m, "_AUTO_LOGIN", False)

    tool = getattr(m, tool_name)
    result = tool(*args)

    assert isinstance(result, dict)
    assert result.get("code") == "NOT_AUTHENTICATED"


def test_capture_hashes_tool_reports_status(monkeypatch):
    """The capture_hashes tool wires the helper result + live probes together."""
    monkeypatch.setattr(m, "_capture_hashes", lambda: {"ok": True, "hashes_ok": True})
    monkeypatch.setattr(m, "_is_authed", lambda: True)
    monkeypatch.setattr(m, "_hashes_ok", lambda: True)
    monkeypatch.setattr(m, "_store_id", lambda override="": "243")

    result = m.capture_hashes()

    assert result["authenticated"] is True
    assert result["hashes_ok"] is True
    assert result["store_id"] == "243"
    assert result["capture"] == {"ok": True, "hashes_ok": True}


def test_set_store_does_not_double_wrap_asyncio_run(monkeypatch):
    """Regression: set_store must call the sync `select_store` helper directly.

    `select_store` (auto_grocer.utility.graphql_store) already runs its own
    event loop internally and returns a plain dict — it is NOT an async
    function. Wrapping its call in `asyncio.run(select_store(...))` evaluates
    select_store() eagerly (synchronously) first, then hands asyncio.run() its
    already-resolved dict return value instead of a coroutine, which raises
    `ValueError: a coroutine was expected, got {...}` on every call regardless
    of whether the store change succeeded or failed. This was observed live
    (see debug_logs / MCP server logs) as `Error calling tool 'set_store'`.
    """
    monkeypatch.setattr(m, "_is_authed", lambda: True)
    monkeypatch.setattr(m, "get_cached_store", lambda store_id: None)
    monkeypatch.setattr(
        m, "select_store", lambda store_id: {"error": True, "code": "STORE_CHANGE_FAILED"}
    )

    # Must not raise ValueError("a coroutine was expected, got {...}").
    result = m.set_store("14")

    assert result["error"] is True
    assert result["code"] == "STORE_CHANGE_FAILED"
    assert result["store_id"] == "14"


def test_set_store_enriches_error_with_cached_store_name(monkeypatch):
    """set_store should include a cached store's name/address on failure too
    (mirrors texas-grocery-mcp's store_change error payload shape)."""
    monkeypatch.setattr(m, "_is_authed", lambda: True)

    class _FakeStore:
        name = "Kyle H-E-B"
        address = "100 Main St, Kyle, TX"

    monkeypatch.setattr(m, "get_cached_store", lambda store_id: _FakeStore())
    monkeypatch.setattr(
        m,
        "select_store",
        lambda store_id: {
            "error": True,
            "code": "CART_CONFLICT",
            "message": "conflict",
            "expected_store": store_id,
            "actual_store": "243",
        },
    )

    result = m.set_store("14")

    assert result["store_name"] == "Kyle H-E-B"
    assert result["actual_store"] == "243"
    assert "help" in result  # CART_CONFLICT-specific guidance


def test_set_store_success_reports_verified_and_cached_name(monkeypatch):
    """set_store should report success/verified and a cached store name."""
    monkeypatch.setattr(m, "_is_authed", lambda: True)

    class _FakeStore:
        name = "Kyle H-E-B"
        address = "100 Main St, Kyle, TX"

    monkeypatch.setattr(m, "get_cached_store", lambda store_id: _FakeStore())
    monkeypatch.setattr(
        m, "select_store", lambda store_id: {"success": True, "store_id": store_id, "verified": True}
    )

    result = m.set_store("14")

    assert result["success"] is True
    assert result["store_name"] == "Kyle H-E-B"
    assert result["verified"] is True