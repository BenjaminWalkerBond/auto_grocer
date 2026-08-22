"""Unit tests for the nodriver browser search fallback helpers.

These guard two regressions observed in production logs:

* ``'float' object has no attribute 'to_json'`` when injecting session cookies
  (a bare ``float`` was passed where a CDP ``TimeSinceEpoch`` was required).
* ``json.JSONDecodeError`` ("Unterminated string") when the fetch loop returned
  the page while the ``__NEXT_DATA__`` script was still streaming.
"""

from __future__ import annotations

import json

import pytest

from auto_grocer_mcp.clients.nodriver_search import (
    _cookie_to_cdp_param,
    _next_data_is_complete,
)

cdp_network = pytest.importorskip("nodriver.cdp.network")


def test_cookie_expires_wrapped_serializes_to_json() -> None:
    """A cookie with a float ``expires`` must serialize without AttributeError."""
    cookie = {
        "name": "session",
        "value": "abc",
        "domain": ".heb.com",
        "path": "/",
        "secure": True,
        "httpOnly": False,
        "expires": 1893456000.0,
    }

    param = _cookie_to_cdp_param(cookie, cdp_network)

    assert param is not None
    # Must not raise "'float' object has no attribute 'to_json'".
    serialized = param.to_json()
    assert serialized["name"] == "session"
    assert isinstance(param.expires, cdp_network.TimeSinceEpoch)


def test_cookie_without_expires_serializes() -> None:
    """A session cookie with no positive expiry still serializes cleanly."""
    param = _cookie_to_cdp_param(
        {"name": "n", "value": "v", "expires": -1}, cdp_network
    )

    assert param is not None
    assert param.to_json()["name"] == "n"


def test_cookie_missing_name_or_value_skipped() -> None:
    assert _cookie_to_cdp_param({"value": "v"}, cdp_network) is None
    assert _cookie_to_cdp_param({"name": "n"}, cdp_network) is None


def _wrap_next_data(payload: str) -> str:
    return (
        '<html><body><script id="__NEXT_DATA__" '
        f'type="application/json">{payload}</script></body></html>'
    )


def test_next_data_complete_for_full_json() -> None:
    html = _wrap_next_data(json.dumps({"props": {"pageProps": {}}}))
    assert _next_data_is_complete(html) is True


def test_next_data_incomplete_when_script_still_streaming() -> None:
    # Opening tag present, JSON truncated, closing </script> not yet rendered.
    truncated = '<html><body><script id="__NEXT_DATA__" type="application/json">{"props": {"pag'
    assert _next_data_is_complete(truncated) is False


def test_next_data_incomplete_when_json_malformed() -> None:
    # Closing tag present but the captured payload is not valid JSON.
    html = _wrap_next_data('{"props": {"pageProps": ')
    assert _next_data_is_complete(html) is False


def test_next_data_incomplete_when_marker_absent() -> None:
    assert _next_data_is_complete("<html><body>challenge</body></html>") is False
    assert _next_data_is_complete("") is False
