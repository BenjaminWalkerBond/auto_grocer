"""Session management for HEB authentication.

Uses Playwright MCP's storage state for authentication.
Provides cookie conversion for httpx-based API requests.
"""

import json
import time
from collections.abc import Awaitable, Callable
from contextlib import suppress
try:
    from datetime import UTC
except ImportError:  # Python < 3.11
    from datetime import timezone as _timezone
    UTC = _timezone.utc
from datetime import datetime
from functools import wraps
from typing import Any, ParamSpec, TypedDict

import structlog

from auto_grocier_mcp.utils.config import get_settings

logger = structlog.get_logger()


# Track last auto-refresh to prevent rapid retries
_last_auto_refresh_attempt: float = 0
_auto_refresh_min_interval: float = 60.0  # Don't retry more than once per minute


class SessionStatus(TypedDict):
    """Session status with lifecycle information."""

    authenticated: bool
    needs_refresh: bool
    refresh_recommended: bool
    time_remaining_hours: float | None
    expires_at: str | None  # ISO format
    reese84_present: bool
    message: str

# Module state for testing
_is_authenticated: bool = False

# Key cookies required for authenticated requests
REQUIRED_COOKIES = ["sat", "sst", "JSESSIONID"]
# Cookies that indicate an active session
SESSION_INDICATOR_COOKIES = ["sat", "DYN_USER_ID"]


def _reset_auth_state() -> None:
    """Reset authentication state. For testing only."""
    global _is_authenticated
    _is_authenticated = False


def _is_cookie_expired(cookie: dict[str, Any]) -> bool:
    """Check if a cookie has expired.

    Args:
        cookie: Playwright-format cookie dict with 'expires' field

    Returns:
        True if cookie is expired, False otherwise
    """
    expires_raw = cookie.get("expires", -1)
    # -1 means session cookie (no expiry)
    if expires_raw == -1:
        return False
    try:
        expires = float(expires_raw)
    except (TypeError, ValueError):
        # If we can't parse expiration, treat cookie as expired.
        return True
    # Check if expired (expires is Unix timestamp)
    return time.time() > expires


def _is_reese84_valid(state: dict[str, Any]) -> bool:
    """Check if reese84 bot detection token is present and not expired.

    The reese84 token is stored in localStorage and contains a renewTime
    that indicates when the token expires. HEB's WAF rejects requests
    with expired tokens.

    Args:
        state: Playwright storage state dict with 'origins' containing localStorage

    Returns:
        True if reese84 token exists and is not expired, False otherwise
    """
    # Extract localStorage from origins
    origins = state.get("origins", [])
    if not origins:
        return False

    local_storage = origins[0].get("localStorage", [])

    # Find reese84 token
    reese84_data: dict[str, Any] | None = None
    for item in local_storage:
        if item.get("name") == "reese84":
            with suppress(json.JSONDecodeError):
                reese84_data = json.loads(item.get("value", "{}"))
            break

    if not reese84_data:
        return False

    # Check expiration via renewTime (absolute timestamp in milliseconds)
    renew_time_ms = reese84_data.get("renewTime")
    if renew_time_ms:
        try:
            expires_at = datetime.fromtimestamp(renew_time_ms / 1000, tz=UTC)
            now = datetime.now(UTC)
            if now >= expires_at:
                return False  # Token expired
        except (ValueError, OSError):
            return False

    # Also check renewInSec + serverTimestamp as fallback
    renew_in_sec = reese84_data.get("renewInSec")
    server_timestamp = reese84_data.get("serverTimestamp")
    if not renew_time_ms and renew_in_sec and server_timestamp:
        try:
            server_ts = server_timestamp / 1000 if server_timestamp > 1e12 else server_timestamp
            expires_at = datetime.fromtimestamp(server_ts + renew_in_sec, tz=UTC)
            now = datetime.now(UTC)
            if now >= expires_at:
                return False  # Token expired
        except (ValueError, OSError):
            return False

    return True


def is_authenticated() -> bool:
    """Check if user is authenticated with valid, non-expired session.

    Checks for:
    1. Valid auth state file from Playwright MCP
    2. Key session cookies present and not expired
    3. reese84 bot detection token present and not expired

    All three conditions must be met for authenticated operations to succeed.
    """
    global _is_authenticated

    # Check override for testing
    if _is_authenticated:
        return True

    settings = get_settings()
    auth_path = settings.auth_state_path

    if not auth_path.exists():
        return False

    try:
        with open(auth_path) as f:
            state = json.load(f)

        # Check for HEB session cookies
        cookies = state.get("cookies", [])
        heb_cookies = [c for c in cookies if "heb.com" in c.get("domain", "")]

        if not heb_cookies:
            return False

        # Check for session indicator cookies (not expired)
        valid_session_cookies = []
        for cookie in heb_cookies:
            name = cookie.get("name", "")
            if name in SESSION_INDICATOR_COOKIES and not _is_cookie_expired(cookie):
                valid_session_cookies.append(name)

        if not valid_session_cookies:
            return False

        # reese84 (bot token) is intentionally NOT used as a hard gate here: its
        # localStorage renewTime is only ~10 min, while the reese84 cookie and
        # the sat/sst session cookies remain valid for weeks. The real limiter
        # is the session cookies above; GraphQL hash validity is verified
        # separately via a live probe (see auth_status).
        return True

    except (json.JSONDecodeError, OSError) as e:
        logger.warning("Failed to read auth state", error=str(e))
        return False


def get_auth_instructions() -> list[str]:
    """Get instructions for authenticating with Playwright MCP."""
    settings = get_settings()
    return [
        "1. Use Playwright MCP: browser_navigate('https://www.heb.com/my-account/login')",
        "2. Complete the login process in the browser",
        "3. Use Playwright MCP: browser_run_code to save storage state:",
        f"   await page.context().storageState({{ path: '{settings.auth_state_path}' }})",
        "4. Retry this operation",
    ]


def check_auth() -> dict[str, Any]:
    """Check authentication status and return appropriate response."""
    if is_authenticated():
        return {
            "authenticated": True,
            "message": "Authenticated with HEB",
        }

    return {
        "authenticated": False,
        "auth_required": True,
        "message": "Login required for cart operations",
        "instructions": get_auth_instructions(),
    }


def get_cookies() -> list[dict[str, Any]]:
    """Get cookies for authenticated requests (Playwright format)."""
    settings = get_settings()
    auth_path = settings.auth_state_path

    if not auth_path.exists():
        return []

    try:
        with open(auth_path) as f:
            state = json.load(f)
        return [c for c in state.get("cookies", []) if "heb.com" in c.get("domain", "")]
    except (json.JSONDecodeError, OSError):
        return []


def get_httpx_cookies() -> dict[str, str]:
    """Get cookies in httpx-compatible format.

    Converts Playwright storage state cookies to a simple dict
    that can be passed to httpx.AsyncClient.

    Returns:
        Dict mapping cookie names to values for HEB domains
    """
    cookies = get_cookies()
    httpx_cookies: dict[str, str] = {}

    for cookie in cookies:
        # Skip expired cookies
        if _is_cookie_expired(cookie):
            continue

        name = cookie.get("name", "")
        value = cookie.get("value", "")

        if name and value:
            httpx_cookies[name] = value

    logger.debug("Loaded cookies for httpx", count=len(httpx_cookies))
    return httpx_cookies


def save_browser_cookies(cookies: list[dict[str, Any]]) -> bool:
    """Save browser cookies to auth state file.

    Args:
        cookies: List of Playwright-format cookies to save

    Returns:
        True if saved successfully, False otherwise
    """
    settings = get_settings()
    auth_path = settings.auth_state_path

    try:
        # Ensure parent directory exists
        auth_path.parent.mkdir(parents=True, exist_ok=True)

        # Load existing state or create new
        state: dict[str, Any] = {"cookies": [], "origins": []}
        if auth_path.exists():
            with open(auth_path) as f:
                state = json.load(f)

        # Filter to only HEB cookies from input
        heb_cookies = [c for c in cookies if "heb.com" in c.get("domain", "")]

        # Merge: replace existing HEB cookies with new ones
        existing_non_heb = [
            c for c in state.get("cookies", [])
            if "heb.com" not in c.get("domain", "")
        ]
        state["cookies"] = existing_non_heb + heb_cookies

        # Write back with secure permissions
        from auto_grocier_mcp.utils.secure_file import write_secure_json

        write_secure_json(auth_path, state)

        logger.info("Saved browser cookies", count=len(heb_cookies), path=str(auth_path))
        return True

    except (OSError, json.JSONDecodeError) as e:
        logger.error("Failed to save browser cookies", error=str(e))
        return False


def get_reese84_info() -> dict[str, Any] | None:
    """Extract reese84 bot detection token metadata if available.

    The reese84 cookie is used by Incapsula WAF for bot detection.
    It contains or references a token with renewal time information.

    Returns:
        Dict with expires/renewTime metadata, or None if not found
    """
    settings = get_settings()
    auth_path = settings.auth_state_path

    if not auth_path.exists():
        return None

    try:
        with open(auth_path) as f:
            state = json.load(f)

        # Check cookies for reese84
        cookies = state.get("cookies", [])
        for cookie in cookies:
            if cookie.get("name") == "reese84" and "heb.com" in cookie.get("domain", ""):
                expires = cookie.get("expires", -1)
                return {
                    "source": "cookie",
                    "expires": expires if expires > 0 else None,
                    "domain": cookie.get("domain"),
                }

        # Check localStorage (origins) for reese84 with renewTime
        for origin in state.get("origins", []):
            if "heb.com" in origin.get("origin", ""):
                for item in origin.get("localStorage", []):
                    if item.get("name") == "reese84":
                        try:
                            value = json.loads(item.get("value", "{}"))
                            return {
                                "source": "localStorage",
                                "renew_time": value.get("renewTime"),
                                "renew_in_sec": value.get("renewInSec"),
                                "server_timestamp": value.get("serverTimestamp"),
                            }
                        except json.JSONDecodeError:
                            pass

        return None

    except (json.JSONDecodeError, OSError) as e:
        logger.warning("Failed to read reese84 info", error=str(e))
        return None


def check_session_freshness() -> dict[str, Any]:
    """Check if the session needs refresh due to stale bot detection tokens.

    Returns:
        Dict with needs_refresh bool and diagnostic information
    """
    info: dict[str, Any] = {
        "needs_refresh": False,
        "authenticated": is_authenticated(),
        "reason": None,
        "bot_detection_status": "unknown",
    }

    if not info["authenticated"]:
        info["needs_refresh"] = True
        info["reason"] = "not_authenticated"
        return info

    # Check reese84 token
    reese84_info = get_reese84_info()
    if reese84_info is None:
        info["bot_detection_status"] = "missing"
        info["needs_refresh"] = True
        info["reason"] = "reese84_missing"
        return info

    current_time = time.time()

    # Check cookie expiration
    expires = reese84_info.get("expires")
    if expires and expires > 0 and current_time > expires - 300:
        info["bot_detection_status"] = "cookie_expired"
        info["needs_refresh"] = True
        info["reason"] = "reese84_cookie_expired"
        info["expired_at"] = expires
        return info

    # Check localStorage renewTime (milliseconds)
    renew_time_ms = reese84_info.get("renew_time")
    if renew_time_ms:
        renew_time = renew_time_ms / 1000  # Convert to seconds
        if current_time > renew_time:
            info["bot_detection_status"] = "token_stale"
            info["needs_refresh"] = True
            info["reason"] = "reese84_renew_time_passed"
            info["renew_time_passed_at"] = renew_time
            return info

    info["bot_detection_status"] = "valid"
    return info


def get_session_refresh_instructions() -> list[str]:
    """Get instructions for refreshing the session via Playwright MCP.

    Returns:
        List of step-by-step instructions
    """
    settings = get_settings()
    return [
        "To refresh your HEB session (solves bot detection challenges):",
        "",
        "1. Navigate to HEB homepage to trigger bot detection refresh:",
        "   browser_navigate('https://www.heb.com')",
        "",
        "2. Wait for page to fully load (bot detection runs in background):",
        "   browser_wait_for({ state: 'networkidle' })",
        "",
        "3. Perform a search to verify session is working:",
        "   browser_type('input[data-qe-id=\"headerSearchInput\"]', 'milk')",
        "   browser_press_key('Enter')",
        "",
        "4. Wait for search results:",
        "   browser_wait_for({ selector: '[data-qe-id=\"productCard\"]', timeout: 10000 })",
        "",
        "5. Save the refreshed session:",
        (
            "   browser_run_code with: await page.context().storageState({ path: '"
            f"{settings.auth_state_path}"
            "' })"
        ),
        "",
        "6. Verify with session_status and session_refresh",
    ]


def get_session_info() -> dict[str, Any]:
    """Get detailed session information.

    Returns:
        Dict with session status, expiration info, and store ID
    """
    settings = get_settings()
    auth_path = settings.auth_state_path

    info: dict[str, Any] = {
        "authenticated": False,
        "auth_path": str(auth_path),
        "auth_file_exists": auth_path.exists(),
        "cookies_count": 0,
        "store_id": None,
        "expires_at": None,
        "user_id": None,
    }

    if not auth_path.exists():
        return info

    try:
        with open(auth_path) as f:
            state = json.load(f)

        cookies = state.get("cookies", [])
        heb_cookies = [c for c in cookies if "heb.com" in c.get("domain", "")]
        info["cookies_count"] = len(heb_cookies)

        # Extract useful info from cookies
        for cookie in heb_cookies:
            name = cookie.get("name", "")
            value = cookie.get("value", "")
            expires = cookie.get("expires", -1)

            if name == "CURR_SESSION_STORE":
                info["store_id"] = value
            elif name == "DYN_USER_ID":
                info["user_id"] = value
            elif name == "sat" and expires > 0:
                # sat token expiration is a good indicator of session validity
                info["expires_at"] = expires

        info["authenticated"] = is_authenticated()

    except (json.JSONDecodeError, OSError) as e:
        logger.warning("Failed to read session info", error=str(e))

    return info


# Refresh threshold: recommend refresh when less than this many hours remain
SESSION_REFRESH_THRESHOLD_HOURS = 4


def get_session_status() -> SessionStatus:
    """Get comprehensive session status including token lifecycle.

    Analyzes the reese84 bot detection token to determine:
    - How much time remains before the token expires
    - Whether refresh is recommended (< 4 hours remaining)
    - Whether refresh is required (expired)

    Returns:
        SessionStatus with authentication state, time remaining, and recommendations.
    """
    settings = get_settings()
    auth_path = settings.auth_state_path

    # Check if auth file exists
    if not auth_path.exists():
        return SessionStatus(
            authenticated=False,
            needs_refresh=True,
            refresh_recommended=True,
            time_remaining_hours=None,
            expires_at=None,
            reese84_present=False,
            message="No auth file found. Run session_refresh to authenticate.",
        )

    # Load and analyze auth state
    try:
        with open(auth_path) as f:
            auth_data = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("Failed to read auth file", error=str(e))
        return SessionStatus(
            authenticated=False,
            needs_refresh=True,
            refresh_recommended=True,
            time_remaining_hours=None,
            expires_at=None,
            reese84_present=False,
            message=f"Auth file corrupted: {e}. Run session_refresh.",
        )

    # Extract reese84 info from localStorage
    local_storage: list[dict[str, Any]] = []
    origins = auth_data.get("origins", [])
    if origins:
        local_storage = origins[0].get("localStorage", [])

    reese84_data: dict[str, Any] | None = None
    for item in local_storage:
        if item.get("name") == "reese84":
            with suppress(json.JSONDecodeError):
                reese84_data = json.loads(item.get("value", "{}"))
            break

    # Calculate time remaining
    time_remaining_hours: float | None = None
    expires_at: str | None = None
    needs_refresh = True
    refresh_recommended = True
    reese84_present = reese84_data is not None

    if reese84_data:
        # reese84 has renewTime (Unix ms) or renewInSec
        renew_time_ms = reese84_data.get("renewTime")
        renew_in_sec = reese84_data.get("renewInSec")
        server_timestamp = reese84_data.get("serverTimestamp")

        now = time.time()

        if renew_time_ms:
            # renewTime is absolute Unix timestamp in milliseconds
            renew_timestamp = renew_time_ms / 1000
            remaining_seconds = renew_timestamp - now
            time_remaining_hours = remaining_seconds / 3600
            expires_at = datetime.fromtimestamp(
                renew_timestamp, tz=UTC
            ).isoformat()
        elif renew_in_sec and server_timestamp:
            # Calculate from relative values
            server_ts = (
                server_timestamp / 1000 if server_timestamp > 1e12 else server_timestamp
            )
            renew_timestamp = server_ts + renew_in_sec
            remaining_seconds = renew_timestamp - now
            time_remaining_hours = remaining_seconds / 3600
            expires_at = datetime.fromtimestamp(
                renew_timestamp, tz=UTC
            ).isoformat()

        if time_remaining_hours is not None:
            needs_refresh = time_remaining_hours <= 0
            # Recommend refresh when < threshold hours remaining
            refresh_recommended = time_remaining_hours < SESSION_REFRESH_THRESHOLD_HOURS

    # Check cookies for session validity
    cookies = auth_data.get("cookies", [])
    has_valid_cookies = any(
        c.get("name") in ("sat", "DYN_USER_ID")
        and "heb.com" in c.get("domain", "")
        and (c.get("expires", 0) == -1 or c.get("expires", 0) > time.time())
        for c in cookies
    )

    authenticated = reese84_present and has_valid_cookies and not needs_refresh

    # Generate message
    if not authenticated:
        if not reese84_present:
            message = "Session missing reese84 token. Run session_refresh."
        elif needs_refresh:
            message = "Session expired. Run session_refresh."
        else:
            message = "Session invalid. Run session_refresh."
    elif refresh_recommended:
        hours = round(time_remaining_hours, 1) if time_remaining_hours else 0
        message = f"Session valid but expiring soon ({hours}h remaining). Consider session_refresh."
    else:
        hours_str = (
            str(round(time_remaining_hours, 1))
            if time_remaining_hours is not None
            else "unknown"
        )
        message = f"Session healthy ({hours_str}h remaining)."

    return SessionStatus(
        authenticated=authenticated,
        needs_refresh=needs_refresh,
        refresh_recommended=refresh_recommended,
        time_remaining_hours=(
            round(time_remaining_hours, 2) if time_remaining_hours else None
        ),
        expires_at=expires_at,
        reese84_present=reese84_present,
        message=message,
    )


async def auto_refresh_session_if_needed() -> dict[str, Any] | None:
    """Check session status and auto-refresh if needed.

    Called by the @ensure_session decorator before authenticated operations.

    Returns:
        None if session is healthy or refresh succeeded.
        Error dict if manual login is required.
    """
    global _last_auto_refresh_attempt

    settings = get_settings()

    # Check if auto-refresh is enabled
    if not settings.auto_refresh_enabled:
        return None

    # If the user has never logged in / saved storage state, don't block read-only tools.
    # Auth-required tools will provide explicit login instructions on their own.
    auth_path = settings.auth_state_path
    if not auth_path.exists():
        return None

    # Get current session status
    status = get_session_status()

    # Check if refresh is needed
    threshold = settings.auto_refresh_threshold_hours
    needs_auto_refresh = (
        status["needs_refresh"]
        or (
            status["time_remaining_hours"] is not None
            and status["time_remaining_hours"] < threshold
        )
    )

    if not needs_auto_refresh:
        return None

    # Prevent rapid retries
    current_time = time.time()
    if current_time - _last_auto_refresh_attempt < _auto_refresh_min_interval:
        logger.debug(
            "Skipping auto-refresh (too soon since last attempt)",
            seconds_since_last=round(current_time - _last_auto_refresh_attempt, 1),
        )
        return None

    _last_auto_refresh_attempt = current_time

    # Attempt headless refresh
    logger.info(
        "Auto-refreshing session",
        needs_refresh=status["needs_refresh"],
        time_remaining_hours=status["time_remaining_hours"],
    )

    try:
        # Import here to avoid circular imports
        from auto_grocier_mcp.auth.browser_refresh import (
            BrowserRefreshError,
            LoginRequiredError,
            is_playwright_available,
            refresh_session_with_browser,
        )

        if not is_playwright_available():
            logger.warning("Auto-refresh unavailable: Playwright not installed")
            return None

        result = await refresh_session_with_browser(
            auth_path=auth_path,
            headless=True,
            timeout=30000,
        )

        logger.info(
            "Session auto-refreshed successfully",
            elapsed_seconds=result.get("elapsed_seconds"),
        )
        return None

    except LoginRequiredError:
        logger.warning("Auto-refresh failed: manual login required")
        return {
            "error": True,
            "code": "LOGIN_REQUIRED",
            "message": (
                "Your HEB session has expired and requires manual login. "
                "Run session_refresh(headless=False) to log in."
            ),
            "auto_refresh_attempted": True,
        }

    except BrowserRefreshError as e:
        logger.warning("Auto-refresh failed", error=str(e))
        # Don't block the operation - let it try with potentially stale session
        return None

    except Exception as e:
        logger.warning("Auto-refresh failed with unexpected error", error=str(e))
        return None


P = ParamSpec("P")
ToolResult = dict[str, Any]


def ensure_session(func: Callable[P, Awaitable[ToolResult]]) -> Callable[P, Awaitable[ToolResult]]:
    """Decorator to ensure valid session before executing authenticated tools.

    Checks session status and auto-refreshes if:
    - Session is expired (needs_refresh=True)
    - Session is expiring soon (< auto_refresh_threshold_hours remaining)

    If auto-refresh fails and manual login is required, returns an error
    instead of executing the tool.

    Usage:
        @ensure_session
        async def cart_add(...):
            ...
    """

    @wraps(func)
    async def wrapper(*args: P.args, **kwargs: P.kwargs) -> ToolResult:
        # Check and refresh session if needed
        error = await auto_refresh_session_if_needed()
        if error:
            return error

        # Execute the original function
        return await func(*args, **kwargs)

    return wrapper
