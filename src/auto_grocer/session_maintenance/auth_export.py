"""Export a live nodriver session to the Playwright-format auth.json the MCP
GraphQL client reads.

This is the async counterpart of utility/graphql_auth.export_selenium_session_to_authjson.
It reuses that module's pure mapping/reporting helpers and only swaps the parts
that read from the browser:
  * driver.get_cookies()                 -> await browser.cookies.get_all()
  * driver.execute_script(localStorage)  -> await tab.get_local_storage()
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from auto_grocer.utility.graphql_auth import (
    DEFAULT_AUTH_PATH,
    _find_reese84,
    _map_same_site,
    _report_session,
)


def _cdp_cookie_to_playwright(cookie):
    """Convert a nodriver/CDP cookie object to Playwright storage-state format."""
    # CDP cookie objects expose attributes; expires is -1 for session cookies.
    expires = getattr(cookie, "expires", None)
    same_site = getattr(cookie, "same_site", None)
    # same_site may be a CDP enum, a string, or None.
    same_site_str = None
    if same_site is not None:
        same_site_str = getattr(same_site, "value", None) or str(same_site)

    return {
        "name": getattr(cookie, "name", "") or "",
        "value": getattr(cookie, "value", "") or "",
        "domain": getattr(cookie, "domain", "") or "",
        "path": getattr(cookie, "path", "/") or "/",
        "expires": float(expires) if expires is not None else -1,
        "httpOnly": bool(getattr(cookie, "http_only", False)),
        "secure": bool(getattr(cookie, "secure", False)),
        "sameSite": _map_same_site(same_site_str),
    }


def _cdp_same_site(value):
    """Map a Playwright sameSite string to a nodriver CDP CookieSameSite enum."""
    from nodriver import cdp

    if not value:
        return None
    return {
        "strict": cdp.network.CookieSameSite.STRICT,
        "lax": cdp.network.CookieSameSite.LAX,
        "none": cdp.network.CookieSameSite.NONE,
    }.get(str(value).strip().lower())


def _playwright_cookie_to_cdp_param(cookie, cdp_network):
    """Convert a Playwright-format cookie dict into a CDP ``CookieParam``.

    Returns ``None`` for cookies lacking a name. The ``expires`` field MUST be
    wrapped in ``cdp_network.TimeSinceEpoch`` (a ``float`` subclass exposing
    ``to_json``) — passing a bare Python ``float`` makes CDP serialization raise
    ``'float' object has no attribute 'to_json'`` when the cookie is set. This
    is the same class of bug already fixed once in
    ``auto_grocer_mcp.clients.nodriver_search._cookie_to_cdp_param``; kept here
    as its own small, unit-tested function so it can't regress independently.
    """
    name = cookie.get("name")
    if not name:
        return None

    expires = cookie.get("expires", -1)
    expires_val = (
        cdp_network.TimeSinceEpoch(float(expires)) if expires not in (None, -1) else None
    )

    return cdp_network.CookieParam(
        name=name,
        value=cookie.get("value", "") or "",
        domain=cookie.get("domain") or None,
        path=cookie.get("path", "/") or "/",
        secure=bool(cookie.get("secure", False)),
        http_only=bool(cookie.get("httpOnly", False)),
        same_site=_cdp_same_site(cookie.get("sameSite")),
        expires=expires_val,
    )


async def load_session_into_browser(browser, auth_path=None):
    """Seed a fresh nodriver browser with cookies from an exported ``auth.json``.

    Lets the hash-capture flow reuse an already-authenticated session instead of
    re-running the full browser login (auth and hash refresh are separate
    concerns: log in once via ``login_export``, then refresh hashes at will).

    Args:
        browser: nodriver.Browser to seed (via ``browser.cookies.set_all``).
        auth_path: Optional override path for auth.json.

    Returns:
        The number of cookies seeded (0 when the file is missing, unreadable, or
        has no cookies — the caller should then fall back to a full login).
    """
    from nodriver import cdp

    auth_path = Path(auth_path).expanduser() if auth_path else DEFAULT_AUTH_PATH
    if not auth_path.exists():
        print(f"    ⚠️  No auth.json at {auth_path} to seed the session from.")
        return 0

    try:
        with open(auth_path, encoding="utf-8") as f:
            state = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        print(f"    ⚠️  Could not read {auth_path}: {e}")
        return 0

    params = []
    for c in state.get("cookies", []) or []:
        param = _playwright_cookie_to_cdp_param(c, cdp.network)
        if param is not None:
            params.append(param)

    if not params:
        print("    ⚠️  auth.json has no cookies to seed.")
        return 0

    try:
        await browser.cookies.set_all(params)
    except Exception as e:  # noqa: BLE001
        print(f"    ⚠️  Failed to seed cookies into the browser: {e}")
        return 0

    print(f"    🍪 Seeded {len(params)} cookies from {auth_path} (skipping login).")
    return len(params)


async def _read_local_storage(tab):
    """Return localStorage as a list of {name, value} dicts (best-effort)."""
    try:
        raw = await tab.get_local_storage()
    except Exception as e:  # noqa: BLE001
        print(f"    ⚠️  Could not read localStorage: {e}")
        return []

    if not isinstance(raw, dict):
        return []
    return [
        {"name": str(k), "value": "" if v is None else str(v)}
        for k, v in raw.items()
    ]


async def export_session_to_authjson(browser, tab, auth_path=None, store_id=None):
    """Export the logged-in nodriver session to a Playwright storage-state file.

    Args:
        browser: nodriver.Browser (source of cookies via browser.cookies).
        tab: A nodriver Tab on heb.com (source of localStorage).
        auth_path: Optional override path for auth.json.
        store_id: Optional HEB store id to record as the default store.

    Returns:
        Path to the written auth.json file.
    """
    auth_path = Path(auth_path).expanduser() if auth_path else DEFAULT_AUTH_PATH

    try:
        cdp_cookies = await browser.cookies.get_all() or []
    except Exception as e:  # noqa: BLE001
        print(f"    ⚠️  Could not read cookies: {e}")
        cdp_cookies = []

    playwright_cookies = [
        _cdp_cookie_to_playwright(c)
        for c in cdp_cookies
        if getattr(c, "name", None)
    ]

    local_storage = await _read_local_storage(tab)

    state = {
        "cookies": playwright_cookies,
        "origins": [
            {
                "origin": "https://www.heb.com",
                "localStorage": local_storage,
            }
        ],
    }

    auth_path.parent.mkdir(parents=True, exist_ok=True)
    with open(auth_path, "w", encoding="utf-8") as f:
        json.dump(state, f)

    # Point the MCP settings at this file and store, then refresh cached settings.
    os.environ["AUTH_STATE_PATH"] = str(auth_path)
    if store_id:
        os.environ["HEB_DEFAULT_STORE"] = str(store_id)
    try:
        from auto_grocer_mcp.utils.config import get_settings

        get_settings.cache_clear()
    except Exception:  # noqa: BLE001
        pass

    # reese84 lookup: localStorage first, then the (dict-form) cookies.
    reese84 = _find_reese84(local_storage, playwright_cookies)
    _report_session(playwright_cookies, reese84, auth_path)

    return auth_path
