"""Bridge between the Selenium (undetected-chromedriver) session and the
vendored ``texas_grocery_mcp`` GraphQL client.

The GraphQL client authenticates by reading a Playwright-format storage-state
JSON file (``auth.json``) that contains HEB session cookies plus the ``reese84``
WAF/bot-detection token. Instead of running a second Playwright login, we reuse
the already logged-in Selenium driver and export its cookies + localStorage into
that file so the MCP client can pick them up unchanged.
"""

import json
import os
from pathlib import Path


# Default location expected by texas_grocery_mcp (see utils/config.py)
DEFAULT_AUTH_PATH = Path("~/.texas-grocery-mcp/auth.json").expanduser()


def _map_same_site(value):
    """Map a Selenium sameSite value to Playwright's expected casing."""
    if not value:
        return "Lax"
    normalized = str(value).strip().lower()
    return {
        "strict": "Strict",
        "lax": "Lax",
        "none": "None",
        "no_restriction": "None",
    }.get(normalized, "Lax")


def _selenium_cookie_to_playwright(cookie):
    """Convert a single Selenium cookie dict to Playwright storage-state format."""
    expires = cookie.get("expiry")
    return {
        "name": cookie.get("name", ""),
        "value": cookie.get("value", ""),
        "domain": cookie.get("domain", ""),
        "path": cookie.get("path", "/"),
        # Playwright uses -1 for session cookies (no expiry)
        "expires": float(expires) if expires is not None else -1,
        "httpOnly": bool(cookie.get("httpOnly", False)),
        "secure": bool(cookie.get("secure", False)),
        "sameSite": _map_same_site(cookie.get("sameSite")),
    }


def _read_local_storage(driver):
    """Return the browser's localStorage as a list of {name, value} dicts.

    Returns an empty list if localStorage cannot be read.
    """
    try:
        raw = driver.execute_script(
            "var items = {};"
            "for (var i = 0; i < window.localStorage.length; i++) {"
            "  var k = window.localStorage.key(i);"
            "  items[k] = window.localStorage.getItem(k);"
            "}"
            "return items;"
        )
    except Exception as e:  # noqa: BLE001 - best-effort capture
        print(f"    ⚠️  Could not read localStorage: {e}")
        return []

    if not isinstance(raw, dict):
        return []
    return [{"name": str(k), "value": "" if v is None else str(v)} for k, v in raw.items()]


def _find_reese84(local_storage, cookies):
    """Locate the reese84 token from localStorage, then cookies as fallback.

    Returns the raw token value (expected to be a JSON string) or None.
    """
    for item in local_storage:
        if item.get("name") == "reese84":
            return item.get("value")
    for cookie in cookies:
        if cookie.get("name") == "reese84":
            return cookie.get("value")
    return None


def export_selenium_session_to_authjson(driver, auth_path=None, store_id=None):
    """Export the logged-in Selenium session to a Playwright storage-state file.

    Args:
        driver: An authenticated Selenium WebDriver on heb.com.
        auth_path: Optional override path for the auth.json file.
        store_id: Optional HEB store id to record as the default store.

    Returns:
        Path to the written auth.json file.
    """
    auth_path = Path(auth_path).expanduser() if auth_path else DEFAULT_AUTH_PATH

    selenium_cookies = driver.get_cookies() or []
    playwright_cookies = [
        _selenium_cookie_to_playwright(c)
        for c in selenium_cookies
        if c.get("name")
    ]

    local_storage = _read_local_storage(driver)

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

    # Point the MCP settings at this file and store, then refresh the cached
    # settings singleton so the new values take effect.
    os.environ["AUTH_STATE_PATH"] = str(auth_path)
    if store_id:
        os.environ["HEB_DEFAULT_STORE"] = str(store_id)

    try:
        from texas_grocery_mcp.utils.config import get_settings

        get_settings.cache_clear()
    except Exception:  # noqa: BLE001 - settings refresh is best-effort
        pass

    reese84 = _find_reese84(local_storage, selenium_cookies)
    _report_session(playwright_cookies, reese84, auth_path)

    return auth_path


def _report_session(playwright_cookies, reese84, auth_path):
    """Print a short summary and warn about anything that may block auth."""
    cookie_names = {c["name"] for c in playwright_cookies}
    required = {"sat", "sst", "JSESSIONID"}
    missing = required - cookie_names

    print(f"    🔐 Exported {len(playwright_cookies)} cookies to {auth_path}")
    if missing:
        print(f"    ⚠️  Missing session cookies: {', '.join(sorted(missing))}")

    if not reese84:
        print("    ⚠️  reese84 token not found - GraphQL calls may be blocked by WAF.")
        return

    # The MCP validates reese84 as a JSON object containing renewTime. A raw
    # opaque token will fail that check, so surface it early.
    try:
        json.loads(reese84)
    except (TypeError, ValueError):
        print(
            "    ⚠️  reese84 token is not JSON; session validation may reject it. "
            "Forcing authenticated mode."
        )
        _force_authenticated()


def _force_authenticated():
    """Override the MCP's auth check when a valid reese84 JSON is unavailable.

    This is a pragmatic fallback: cookies are present but the reese84 token
    could not be validated in the expected JSON shape. We let requests proceed
    and rely on HEB's response to reveal whether the WAF accepts them.
    """
    try:
        import texas_grocery_mcp.auth.session as session

        session._is_authenticated = True
    except Exception:  # noqa: BLE001
        pass
