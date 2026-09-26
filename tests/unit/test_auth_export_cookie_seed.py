"""Unit tests for auth_export's cookie -> CDP CookieParam conversion.

Guards a regression observed in production (auto-grocer capture_hashes tool):
``'float' object has no attribute 'to_json'`` when seeding cookies into a fresh
nodriver browser from ``auth.json`` (``load_session_into_browser``). The CDP
``CookieParam.expires`` field must be wrapped in
``cdp.network.TimeSinceEpoch`` (a ``float`` subclass exposing ``to_json``); a
bare Python ``float`` breaks CDP serialization. This is the same bug class
already fixed once in ``auto_grocer_mcp.clients.nodriver_search`` (see
``tests/unit/test_nodriver_search.py``) — kept here as its own regression test
since the two call sites are independent code paths.
"""

from __future__ import annotations

import pytest

from auto_grocer.session_maintenance.auth_export import _playwright_cookie_to_cdp_param

cdp_network = pytest.importorskip("nodriver.cdp.network")


def test_cookie_expires_wrapped_serializes_to_json() -> None:
    """A cookie with a float ``expires`` must serialize without AttributeError."""
    cookie = {
        "name": "reese84",
        "value": "abc",
        "domain": ".heb.com",
        "path": "/",
        "secure": True,
        "httpOnly": False,
        "sameSite": "None",
        "expires": 1893456000.0,
    }

    param = _playwright_cookie_to_cdp_param(cookie, cdp_network)

    assert param is not None
    # Must not raise "'float' object has no attribute 'to_json'".
    serialized = param.to_json()
    assert serialized["name"] == "reese84"
    assert isinstance(param.expires, cdp_network.TimeSinceEpoch)


def test_cookie_without_expires_serializes() -> None:
    """A session cookie with expires=-1 (session cookie) still serializes cleanly."""
    param = _playwright_cookie_to_cdp_param(
        {"name": "sat", "value": "v", "expires": -1}, cdp_network
    )

    assert param is not None
    assert param.expires is None
    serialized = param.to_json()  # must not raise
    assert serialized["name"] == "sat"


def test_cookie_missing_name_is_skipped() -> None:
    assert _playwright_cookie_to_cdp_param({"value": "v"}, cdp_network) is None
