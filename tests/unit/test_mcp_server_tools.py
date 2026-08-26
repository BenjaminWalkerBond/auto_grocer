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
    m._reset_capture_job()
    monkeypatch.setattr(
        m, "_capture_hashes", lambda target_operation="": {"ok": True, "hashes_ok": True}
    )
    monkeypatch.setattr(m, "_is_authed", lambda: True)
    monkeypatch.setattr(m, "_hashes_ok", lambda: True)
    monkeypatch.setattr(m, "_store_id", lambda override="": "243")

    try:
        result = m.capture_hashes(wait_seconds=10)

        assert result["authenticated"] is True
        assert result["hashes_ok"] is True
        assert result["store_id"] == "243"
        # The helper's payload is merged into the job status envelope.
        assert result["capture"]["status"] == "completed"
        assert result["capture"]["ok"] is True
    finally:
        m._reset_capture_job()


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

# ---------------------------------------------------------------------------
# capture_hashes must never block past the MCP client's cancel deadline
# ---------------------------------------------------------------------------
# The browser hash-capture flow takes minutes (_CAPTURE_HASHES_TIMEOUT is 600s),
# but MCP clients cancel a tool call after ~240s. In production every
# capture_hashes call was cancelled at exactly 4 minutes, so the tool could
# never report a result. It now runs the capture on a background thread and
# returns a bounded-wait status that later calls can poll.


def test_capture_hashes_returns_running_status_when_slow(monkeypatch):
    """A capture that outlives the wait budget returns status 'running'."""
    import threading

    release = threading.Event()

    def _slow_capture(target_operation: str = ""):
        release.wait(timeout=30)
        return {"ok": True}

    m._reset_capture_job()
    monkeypatch.setattr(m, "_capture_hashes", _slow_capture)
    monkeypatch.setattr(m, "_is_authed", lambda: True)
    monkeypatch.setattr(m, "_hashes_ok", lambda: False)
    monkeypatch.setattr(m, "_store_id", lambda override="": "243")

    try:
        result = m.capture_hashes(wait_seconds=0.2)
        assert result["capture"]["status"] == "running"
        assert result["capture"]["started"] is True
    finally:
        release.set()
        m._reset_capture_job()


def test_capture_hashes_second_call_joins_running_job(monkeypatch):
    """A concurrent call must join the in-flight capture, not launch another."""
    import threading

    release = threading.Event()
    starts: list[str] = []

    def _slow_capture(target_operation: str = ""):
        starts.append(target_operation)
        release.wait(timeout=30)
        return {"ok": True}

    m._reset_capture_job()
    monkeypatch.setattr(m, "_capture_hashes", _slow_capture)
    monkeypatch.setattr(m, "_is_authed", lambda: True)
    monkeypatch.setattr(m, "_hashes_ok", lambda: False)
    monkeypatch.setattr(m, "_store_id", lambda override="": "243")

    try:
        first = m.capture_hashes(wait_seconds=0.2)
        second = m.capture_hashes(wait_seconds=0.2)

        assert first["capture"]["status"] == "running"
        assert second["capture"]["status"] == "running"
        assert second["capture"]["started"] is False
        assert len(starts) == 1, "a second browser capture was launched"
    finally:
        release.set()
        m._reset_capture_job()


def test_capture_hashes_reports_completed_result(monkeypatch):
    """When the capture finishes within the budget the real result is returned."""
    m._reset_capture_job()
    monkeypatch.setattr(m, "_capture_hashes", lambda target_operation="": {"ok": True})
    monkeypatch.setattr(m, "_is_authed", lambda: True)
    monkeypatch.setattr(m, "_hashes_ok", lambda: True)
    monkeypatch.setattr(m, "_store_id", lambda override="": "243")

    try:
        result = m.capture_hashes(wait_seconds=10)

        assert result["capture"]["status"] == "completed"
        assert result["capture"]["ok"] is True
        assert result["authenticated"] is True
        assert result["hashes_ok"] is True
    finally:
        m._reset_capture_job()


def test_capture_hashes_default_wait_is_under_client_timeout():
    """The default wait must leave headroom before the ~240s client cancel."""
    assert 0 < m._CAPTURE_WAIT_SECONDS <= 180


# ---------------------------------------------------------------------------
# Honest reporting: never claim success on a failed call
# ---------------------------------------------------------------------------
# The mirror image of the false WAF alarm. When HEB's WAF returns an HTML
# challenge page, /graphql responses stop being JSON and every cart call fails
# with "Expecting value: line 1 column 1 (char 0)". Observed in production:
#   clear_cart -> {"status": "cleared", "cart": {"error": true, ...}}
#   get_cart   -> raised an unhandled traceback out of the tool
# A tool that reports "cleared" when nothing was cleared is worse than one that
# cries wolf, because the caller proceeds on a false premise.


def test_clear_cart_reports_failure_when_backend_errors(monkeypatch):
    """clear_cart must not claim 'cleared' when the underlying call failed."""
    monkeypatch.setattr(m, "_is_authed", lambda: True)
    monkeypatch.setattr(m, "_store_id", lambda override="": "243")
    monkeypatch.setattr(
        m,
        "graphql_cart_sync",
        lambda *a, **k: {
            "cart": {"error": True, "message": "Expecting value: line 1 column 1 (char 0)"}
        },
    )

    result = m.clear_cart()

    assert result.get("error") is True, f"reported success on a failure: {result}"
    assert result.get("status") != "cleared"
    assert "Expecting value" in str(result.get("message"))


def test_clear_cart_reports_success_when_backend_succeeds(monkeypatch):
    """The happy path still reports 'cleared'."""
    monkeypatch.setattr(m, "_is_authed", lambda: True)
    monkeypatch.setattr(m, "_store_id", lambda override="": "243")
    monkeypatch.setattr(
        m, "graphql_cart_sync", lambda *a, **k: {"cart": {"cartV2": {"items": []}}}
    )

    result = m.clear_cart()

    assert result.get("status") == "cleared"
    assert not result.get("error")


def test_get_cart_returns_structured_error_instead_of_raising(monkeypatch):
    """A non-JSON WAF response must surface as an error dict, not a traceback."""
    def _boom():
        raise ValueError("Expecting value: line 1 column 1 (char 0)")

    monkeypatch.setattr(m, "_is_authed", lambda: True)
    monkeypatch.setattr(m, "_graphql_get_cart_sync", _boom)

    result = m.get_cart()

    assert isinstance(result, dict)
    assert result.get("error") is True
    assert result.get("code") == "CART_FETCH_FAILED"
    assert "Expecting value" in str(result.get("message"))
