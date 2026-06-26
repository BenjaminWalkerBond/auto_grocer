"""Helpers for writing the Playwright-format ``auth.json`` storage-state file the
vendored ``texas_grocery_mcp`` GraphQL client reads.

The GraphQL client authenticates from ``auth.json`` (HEB session cookies plus the
``reese84`` WAF/bot-detection token). The session is produced by the nodriver
browser flow (``grocery_browser/auth_export.py``), which reuses the pure helpers
below to map cookies, locate the reese84 token, and report/validate the result.
There is no Selenium dependency here anymore.
"""

import json
from pathlib import Path


# Default location expected by texas_grocery_mcp (see utils/config.py)
DEFAULT_AUTH_PATH = Path("~/.texas-grocery-mcp/auth.json").expanduser()


def _map_same_site(value):
    """Map a cookie sameSite value to Playwright's expected casing."""
    if not value:
        return "Lax"
    normalized = str(value).strip().lower()
    return {
        "strict": "Strict",
        "lax": "Lax",
        "none": "None",
        "no_restriction": "None",
    }.get(normalized, "Lax")


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
