"""Regression tests for the set_store MCP tool.

set_store used to call ``asyncio.run(select_store(...))`` even though
``utility.graphql_store.select_store`` is itself a synchronous wrapper around
``asyncio.run``. That double-wrap raised "a coroutine was expected, got {...}"
on every single invocation.
"""

from unittest.mock import patch

import pytest


@pytest.fixture
def set_store_fn():
    import mcp_server

    return getattr(mcp_server.set_store, "fn", mcp_server.set_store)


def test_set_store_does_not_double_wrap_async(set_store_fn):
    """A plain dict from select_store must not be passed to asyncio.run."""
    with patch("mcp_server._ensure_authed", return_value=True), patch(
        "mcp_server.select_store", return_value={"success": True, "verified": True}
    ) as mock_select:
        result = set_store_fn("14")

    mock_select.assert_called_once_with("14")
    assert result["store_id"] == "14"
    assert result["result"] == {"success": True, "verified": True}


def test_set_store_surfaces_errors(set_store_fn):
    """Failures should come back as a structured error, not a raw nested dict."""
    with patch("mcp_server._ensure_authed", return_value=True), patch(
        "mcp_server.select_store",
        return_value={"error": True, "code": "STORE_CHANGE_FAILED", "message": "nope"},
    ):
        result = set_store_fn("14")

    assert result["error"] is True
    assert result["code"] == "STORE_CHANGE_FAILED"
    assert result["message"] == "nope"
    assert result["store_id"] == "14"
