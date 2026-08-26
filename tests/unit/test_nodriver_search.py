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


# ---------------------------------------------------------------------------
# Event-loop rebinding regression (production hang)
# ---------------------------------------------------------------------------
# Every MCP tool is a sync ``def`` that calls ``asyncio.run(...)``, so each tool
# call gets a BRAND NEW event loop. The process-wide NodriverSearchClient
# singleton cached an ``asyncio.Lock`` and a live CDP browser bound to the loop
# that created them. On the second tool call this surfaced as
# ``<asyncio.locks.Lock ...> is bound to a different event loop`` and, worse, a
# permanent hang awaiting a websocket owned by a closed loop (Claude cancelled
# the tool call after 4 minutes).


def test_search_client_rebinds_lock_to_current_event_loop() -> None:
    """A second ``asyncio.run`` must get a lock bound to its own loop."""
    import asyncio

    from auto_grocer_mcp.clients.nodriver_search import NodriverSearchClient

    client = NodriverSearchClient()

    async def _acquire() -> tuple[asyncio.Lock, asyncio.AbstractEventLoop]:
        lock = client._lock_for_loop()
        async with lock:
            pass
        return lock, asyncio.get_running_loop()

    lock_a, loop_a = asyncio.run(_acquire())
    lock_b, loop_b = asyncio.run(_acquire())

    assert loop_a is not loop_b, "test requires two distinct event loops"
    assert lock_a is not lock_b, "lock was not rebound to the new event loop"


def test_search_client_discards_browser_from_dead_loop() -> None:
    """A browser created on a closed loop must not be reused on a new loop."""
    import asyncio

    from auto_grocer_mcp.clients.nodriver_search import NodriverSearchClient

    client = NodriverSearchClient()
    terminated: list[str] = []

    class _FakeProcess:
        def terminate(self) -> None:
            terminated.append("terminated")

    class _FakeBrowser:
        def __init__(self) -> None:
            self._process = _FakeProcess()

    async def _seed() -> None:
        client._adopt_browser(_FakeBrowser())

    asyncio.run(_seed())

    async def _check() -> object | None:
        # New loop: the cached browser belongs to a dead loop and must be dropped.
        return client._reusable_browser()

    assert asyncio.run(_check()) is None
    assert terminated == ["terminated"], "stale browser process was not reclaimed"


def test_search_client_reuses_browser_within_same_loop() -> None:
    """Within one event loop the warm browser is still reused."""
    import asyncio

    from auto_grocer_mcp.clients.nodriver_search import NodriverSearchClient

    client = NodriverSearchClient()

    class _FakeBrowser:
        def stop(self) -> None:  # pragma: no cover - must not be called
            raise AssertionError("browser stopped inside its own loop")

    async def _run() -> object | None:
        browser = _FakeBrowser()
        client._adopt_browser(browser)
        return client._reusable_browser()

    assert isinstance(asyncio.run(_run()), _FakeBrowser)


def test_cross_loop_discard_kills_process_without_touching_connection() -> None:
    """Discarding a dead-loop browser must not schedule cross-loop async I/O.

    nodriver's ``Browser.stop()`` does
    ``asyncio.get_event_loop().create_task(self.aclose())``. When the browser's
    websocket belongs to a *previous* loop that task raises
    ``got Future ... attached to a different loop``, and because nobody awaits
    it asyncio logs it at ERROR level — noisy false alarms on a routine
    relaunch. The cross-loop path must terminate the OS process instead.
    """
    import asyncio

    from auto_grocer_mcp.clients.nodriver_search import NodriverSearchClient

    events: list[str] = []

    class _FakeProcess:
        pid = 4321

        def terminate(self) -> None:
            events.append("terminate")

    class _FakeBrowser:
        def __init__(self) -> None:
            self._process = _FakeProcess()

        def stop(self) -> None:
            events.append("stop")

    client = NodriverSearchClient()

    async def _seed() -> None:
        client._adopt_browser(_FakeBrowser())

    asyncio.run(_seed())

    async def _discard() -> object | None:
        return client._reusable_browser()

    assert asyncio.run(_discard()) is None
    assert "stop" not in events, "stop() schedules aclose() on the wrong loop"
    assert events == ["terminate"]
