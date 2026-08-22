"""Helpers for writing the Playwright-format ``auth.json`` storage-state file the
vendored ``auto_grocer_mcp`` GraphQL client reads.

The GraphQL client authenticates from ``auth.json`` (HEB session cookies plus the
``reese84`` WAF/bot-detection token). The session is produced by the nodriver
browser flow (``session_maintenance/auth_export.py``), which reuses the pure helpers
below to map cookies, locate the reese84 token, and report/validate the result.
There is no Selenium dependency here anymore.
"""

import json
import os
import time
from datetime import datetime
from pathlib import Path

# Default location expected by auto_grocer_mcp (see utils/config.py)
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


def validate_reese84(reese84):
    """Validate a reese84 WAF/bot-detection token the way the MCP session check does.

    Mirrors ``auto_grocer_mcp.auth.session._is_reese84_valid``: the token must be
    a JSON object; if it carries a ``renewTime`` (absolute ms) or a
    ``renewInSec`` + ``serverTimestamp`` pair, it must not be past expiry.

    Returns a status dict::

        {
            "present": bool,             # a token value was found at all
            "valid":   bool,             # parses as JSON and is not expired
            "reason":  str,              # ok | missing | not_json | expired | no_expiry
            "expires_at": float | None,  # unix seconds, when derivable
        }
    """
    if not reese84:
        return {"present": False, "valid": False, "reason": "missing", "expires_at": None}

    try:
        data = json.loads(reese84)
    except (TypeError, ValueError):
        return {"present": True, "valid": False, "reason": "not_json", "expires_at": None}
    if not isinstance(data, dict):
        return {"present": True, "valid": False, "reason": "not_json", "expires_at": None}

    now = time.time()

    renew_time_ms = data.get("renewTime")
    if renew_time_ms:
        try:
            expires_at = float(renew_time_ms) / 1000.0
        except (TypeError, ValueError):
            return {"present": True, "valid": False, "reason": "not_json", "expires_at": None}
        reason = "ok" if now < expires_at else "expired"
        return {"present": True, "valid": reason == "ok", "reason": reason, "expires_at": expires_at}

    renew_in_sec = data.get("renewInSec")
    server_ts = data.get("serverTimestamp")
    if renew_in_sec and server_ts:
        try:
            server_s = float(server_ts) / 1000.0 if float(server_ts) > 1e12 else float(server_ts)
            expires_at = server_s + float(renew_in_sec)
        except (TypeError, ValueError):
            return {"present": True, "valid": False, "reason": "not_json", "expires_at": None}
        reason = "ok" if now < expires_at else "expired"
        return {"present": True, "valid": reason == "ok", "reason": reason, "expires_at": expires_at}

    # JSON object but no expiry metadata: the MCP treats this as present/valid.
    return {"present": True, "valid": True, "reason": "no_expiry", "expires_at": None}


def _fmt_ts(ts):
    """Format a unix-seconds timestamp for logs, or '?' when unavailable."""
    if not ts:
        return "?"
    try:
        return datetime.fromtimestamp(ts).isoformat(timespec="seconds")
    except (ValueError, OSError, OverflowError):
        return "?"


def _report_session(playwright_cookies, reese84, auth_path):
    """Print a short summary + an honest reese84 validation. Returns the status dict.

    Unlike the old behaviour, this no longer silently forces the MCP into an
    authenticated state when the token is unusable — it reports the real reason
    so a stale/opaque/expired token is visible instead of masked. The legacy
    override remains available only when ``AUTO_GROCER_FORCE_AUTH`` is set.
    """
    cookie_names = {c["name"] for c in playwright_cookies}
    required = {"sat", "sst", "JSESSIONID"}
    missing = required - cookie_names

    print(f"    🔐 Exported {len(playwright_cookies)} cookies to {auth_path}")
    if missing:
        print(f"    ⚠️  Missing session cookies: {', '.join(sorted(missing))}")

    status = validate_reese84(reese84)
    reason = status["reason"]
    if reason == "missing":
        print("    ⚠️  reese84 token NOT found - GraphQL calls will be blocked by the WAF.")
    elif reason == "not_json":
        print(
            "    ⚠️  reese84 token is not JSON (opaque cookie only) - the MCP session "
            "check will reject it. Re-run capture so localStorage is exported."
        )
    elif reason == "expired":
        print(
            f"    ⚠️  reese84 token is EXPIRED (renewed by {_fmt_ts(status['expires_at'])}) "
            "- refresh the session."
        )
    elif reason == "no_expiry":
        print("    ✓ reese84 token present (JSON, no expiry metadata) - accepted.")
    else:  # ok
        print(f"    ✓ reese84 token valid (renews by {_fmt_ts(status['expires_at'])}).")

    # Opt-in escape hatch only: never lie about auth state by default.
    if not status["valid"] and os.environ.get("AUTO_GROCER_FORCE_AUTH", "").lower() in (
        "1",
        "true",
        "yes",
    ):
        print(
            "    ⚙️  AUTO_GROCER_FORCE_AUTH set - forcing authenticated mode despite "
            f"invalid reese84 ({reason})."
        )
        _force_authenticated()

    return status


def _force_authenticated():
    """Override the MCP's auth check (opt-in via AUTO_GROCER_FORCE_AUTH only).

    Pragmatic escape hatch: cookies are present but the reese84 token could not
    be validated in the expected JSON shape. Lets requests proceed and relies on
    HEB's response to reveal whether the WAF accepts them. No longer called
    automatically — ``_report_session`` reports the real status instead.
    """
    try:
        import auto_grocer_mcp.auth.session as session

        session._is_authenticated = True
    except Exception:  # noqa: BLE001
        pass
