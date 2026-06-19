"""Session management tools for MCP."""

from pathlib import Path
from typing import Any

import structlog

from texas_grocery_mcp.auth.browser_refresh import (
    BrowserRefreshError,
    LoginRequiredError,
    PlaywrightNotInstalledError,
    auto_login_with_credentials,
    is_playwright_available,
    refresh_session_with_browser,
)
from texas_grocery_mcp.auth.credentials import CredentialError, CredentialStore
from texas_grocery_mcp.auth.session import (
    check_session_freshness,
    get_session_info,
    get_session_status,
    is_authenticated,
)
from texas_grocery_mcp.utils.config import get_settings

logger = structlog.get_logger()


async def session_status() -> dict[str, Any]:
    """Get current session status including token lifecycle and credential storage.

    Returns comprehensive session information:
    - authenticated: Whether session is valid
    - needs_refresh: Whether refresh is required now (token expired)
    - refresh_recommended: Whether proactive refresh is advised (< 4 hours remaining)
    - time_remaining_hours: Hours until token expires
    - expires_at: ISO timestamp of expiration
    - message: Human-readable status
    - credentials_stored: Whether HEB credentials are saved for auto-login

    Use this to check session health before operations or to decide
    when to proactively refresh.
    """
    status = get_session_status()

    # Also include basic session info
    basic_info = get_session_info()

    # Check credential storage status
    settings = get_settings()
    auth_dir = Path(settings.auth_state_path).expanduser().parent
    cred_store = CredentialStore(auth_dir)
    cred_info = cred_store.get_storage_info()

    return {
        # Lifecycle status (new fields)
        "authenticated": status["authenticated"],
        "needs_refresh": status["needs_refresh"],
        "refresh_recommended": status["refresh_recommended"],
        "time_remaining_hours": status["time_remaining_hours"],
        "expires_at": status["expires_at"],
        "reese84_present": status["reese84_present"],
        "message": status["message"],
        # Basic info
        "auth_path": basic_info.get("auth_path"),
        "store_id": basic_info.get("store_id"),
        "user_id": basic_info.get("user_id"),
        "cookies_count": basic_info.get("cookies_count", 0),
        # Credential storage info
        "credentials_stored": cred_info["credentials_stored"],
        "credential_storage_method": cred_info["storage_method"],
    }


async def session_refresh(
    headless: bool = True,
    timeout: int = 30000,
    login_timeout: int = 300000,
    use_saved_credentials: bool = True,
) -> dict[str, Any]:
    """Refresh HEB session cookies and tokens.

    Uses embedded browser when available (fast: ~10-15 seconds).
    If credentials are saved and login is required, attempts automatic login.
    Falls back to returning Playwright MCP commands if browser
    dependencies aren't installed.

    Args:
        headless: Run browser without visible window (default True).
                  Set to False if you need to complete a manual login
                  (e.g., when your session has fully expired).
        timeout: Maximum time to wait for page load in milliseconds.
                 Default 30000 (30 seconds).
        login_timeout: Maximum time to wait for manual login in milliseconds.
                       Default 300000 (5 minutes). Only used when headless=False.
        use_saved_credentials: If True and credentials are stored, attempt
                               automatic login when session is expired.
                               Default True.

    Returns:
        dict with one of these statuses:
        - {"status": "success", ...} - Login/refresh completed successfully
        - {"status": "human_action_required", "action": "login" | "captcha" | "2fa" | "waf", ...}
          Human intervention required (login form, CAPTCHA, 2FA, or a WAF/security interstitial).
          The browser remains open; complete the action, then call session_refresh() again.
        - {"status": "failed", ...} - Login/refresh failed with error details

    Use this tool when:
    - session_status shows needs_refresh: true
    - session_status shows refresh_recommended: true
    - product_search returns security_challenge_detected: true
    - You want to proactively refresh before token expires

    CAPTCHA/2FA handling:
    - When CAPTCHA or 2FA is detected, returns immediately with screenshot_path
    - The screenshot shows exactly what the user sees in the browser
    - Use the Read tool to view the screenshot and describe it to the user
    - The browser stays open - user solves CAPTCHA/enters code in that window
    - After solving, call session_refresh() again to continue the login flow
    - Repeat until status is "success" or "failed"
    """
    settings = get_settings()
    auth_path = Path(settings.auth_state_path).expanduser()
    auth_dir = auth_path.parent

    # Check for saved credentials
    cred_store = CredentialStore(auth_dir)
    has_credentials = cred_store.has_credentials() if use_saved_credentials else False

    # Try embedded Playwright first (fast path)
    if is_playwright_available():
        try:
            result = await refresh_session_with_browser(
                auth_path=auth_path,
                headless=headless,
                timeout=timeout,
                login_timeout=login_timeout,
            )
            return result

        except PlaywrightNotInstalledError:
            # Fall through to command-based approach
            pass

        except LoginRequiredError as e:
            # Session expired - try auto-login if we have credentials
            if has_credentials:
                logger.info("Session expired, attempting auto-login with saved credentials")
                credentials = cred_store.get()
                if credentials:
                    email, password = credentials
                    # Use visible browser for auto-login (needed for CAPTCHA handoff)
                    result = await auto_login_with_credentials(
                        auth_path=auth_path,
                        email=email,
                        password=password,
                        headless=False,  # Always visible for human handoff
                        timeout=timeout,
                        login_timeout=login_timeout,
                    )
                    return result

            # No credentials or auto-login not attempted
            suggestion = (
                "Your session has fully expired. Try:\n"
                "  session_refresh(headless=False)\n"
                "to login in a visible browser window."
            )
            if not has_credentials:
                suggestion += (
                    "\n\nTip: Save your credentials with session_save_credentials() "
                    "for automatic login next time."
                )

            return {
                "success": False,
                "status": "failed",
                "error": str(e),
                "error_type": "login_required",
                "credentials_available": has_credentials,
                "suggestion": suggestion,
            }

        except BrowserRefreshError as e:
            return {
                "success": False,
                "status": "failed",
                "error": str(e),
                "error_type": "browser_error",
                "suggestion": "Check your internet connection and try again.",
            }

    # Fallback: return Playwright MCP commands for external execution
    expanded_auth_path = str(auth_path)
    freshness = check_session_freshness()

    # Build the JavaScript code to extract and save session
    extract_code = f"""
// Extract session data and save to auth.json
const fs = require('fs');
const path = require('path');

// Get cookies
const cookies = await page.context().cookies();

// Get localStorage
const localStorage = await page.evaluate(() => {{
    const items = [];
    for (let i = 0; i < window.localStorage.length; i++) {{
        const name = window.localStorage.key(i);
        const value = window.localStorage.getItem(name);
        items.push({{ name, value }});
    }}
    return items;
}});

// Build auth state matching Playwright's storageState format
const authState = {{
    cookies: cookies,
    origins: [{{
        origin: "https://www.heb.com",
        localStorage: localStorage
    }}]
}};

// Ensure directory exists
const authPath = '{expanded_auth_path}';
const dir = path.dirname(authPath);
if (!fs.existsSync(dir)) {{
    fs.mkdirSync(dir, {{ recursive: true }});
}}

// Save auth state
fs.writeFileSync(authPath, JSON.stringify(authState, null, 2));

return {{
    success: true,
    message: 'Session saved to ' + authPath,
    cookies_count: cookies.length,
    localStorage_count: localStorage.length
}};
"""

    return {
        "message": (
            "Playwright not installed. Execute these Playwright MCP commands to refresh "
            "session:"
        ),
        "install_for_fast_refresh": (
            "pip install texas-grocery-mcp[browser] && playwright install chromium"
        ),
        "current_status": {
            "authenticated": freshness.get("authenticated", False),
            "needs_refresh": freshness.get("needs_refresh", True),
            "reason": freshness.get("reason"),
        },
        "commands": [
            {
                "tool": "browser_navigate",
                "parameters": {"url": "https://www.heb.com"},
                "description": "Navigate to HEB homepage to trigger reese84 token generation",
            },
            {
                "tool": "browser_wait_for",
                "parameters": {"time": 5},
                "description": "Wait for page load and reese84 token initialization",
            },
            {
                "tool": "browser_run_code",
                "parameters": {"code": extract_code},
                "description": "Extract cookies and localStorage, save to auth.json",
            },
        ],
        "after_refresh": "Call session_status to verify the refresh succeeded.",
        "auth_path": expanded_auth_path,
        "troubleshooting": {
            "no_playwright": "Install Playwright MCP: https://github.com/microsoft/playwright-mcp",
            "still_failing": (
                "Try browser_navigate with a longer wait, or check if HEB requires login"
            ),
            "login_required": (
                "If HEB prompts for login, use browser_fill_form to enter credentials or "
                "complete login manually"
            ),
        },
    }


def session_save_instructions() -> dict[str, Any]:
    """Get instructions for saving browser session cookies.

    Call this to get step-by-step instructions for authenticating
    via Playwright MCP and saving the session for fast API access.

    For automatic session extraction, use session_refresh instead.
    """
    settings = get_settings()

    return {
        "instructions": [
            "1. Navigate to HEB login page:",
            "   browser_navigate('https://www.heb.com/my-account/login')",
            "",
            "2. Complete the login process in the browser",
            "   (Enter credentials and click Sign In)",
            "",
            "3. After successful login, save the browser state:",
            "   browser_run_code with this code:",
            f"   await page.context().storageState({{ path: '{settings.auth_state_path}' }})",
            "",
            "4. Verify session was saved:",
            "   Call session_status to confirm authentication",
        ],
        "auth_path": str(settings.auth_state_path),
        "current_status": {
            "authenticated": is_authenticated(),
        },
        "alternative": "Use session_refresh for automatic session extraction without manual login.",
    }


def session_clear() -> dict[str, Any]:
    """Clear saved session cookies.

    Use this to log out or clear invalid session data.
    After clearing, you will need to run session_refresh again.

    Note: This does NOT clear saved credentials. Use session_clear_credentials()
    to remove stored login credentials.
    """
    settings = get_settings()
    auth_path = settings.auth_state_path

    if not auth_path.exists():
        return {
            "success": True,
            "message": "No session file to clear.",
        }

    try:
        auth_path.unlink()
        return {
            "success": True,
            "message": "Session cleared. Run session_refresh to re-authenticate.",
            "cleared_path": str(auth_path),
        }
    except OSError as e:
        return {
            "error": True,
            "code": "CLEAR_FAILED",
            "message": f"Failed to clear session: {e!s}",
        }


async def session_save_credentials(email: str, password: str) -> dict[str, Any]:
    """Save HEB login credentials for automatic login.

    Credentials are stored securely using:
    - OS keyring (macOS Keychain, Windows Credential Manager, Linux Secret Service)
    - Encrypted file fallback when keyring is unavailable

    After saving, session_refresh will automatically use these credentials
    when your session expires, eliminating manual browser login.

    Args:
        email: Your HEB.com account email address
        password: Your HEB.com account password

    Returns:
        dict with success status and storage method used

    Security notes:
    - Credentials are encrypted at rest
    - Password is never logged or exposed in output
    - Use session_clear_credentials() to remove stored credentials

    Example:
        session_save_credentials("user@example.com", "mypassword")
        # Now session_refresh will auto-login when session expires
    """
    if not email or not password:
        return {
            "success": False,
            "error": "Email and password are required",
        }

    # Basic email validation
    if "@" not in email or "." not in email:
        return {
            "success": False,
            "error": "Invalid email format",
        }

    settings = get_settings()
    auth_dir = Path(settings.auth_state_path).expanduser().parent
    cred_store = CredentialStore(auth_dir)

    try:
        result = cred_store.save(email, password)
        storage_info = cred_store.get_storage_info()

        # Mask email for response
        masked_email = _mask_email(email)

        logger.info("Credentials saved successfully", email_masked=masked_email)

        return {
            "success": True,
            "message": f"Credentials saved for {masked_email}",
            "storage_method": result.get("method", "unknown"),
            "storage_backend": storage_info.get("storage_backend", "unknown"),
            "next_steps": (
                "Your credentials are now saved. When your session expires, "
                "session_refresh will automatically log you in. "
                "If CAPTCHA or 2FA is required, you'll be prompted to complete it."
            ),
        }

    except CredentialError as e:
        logger.error("Failed to save credentials", error=str(e))
        return {
            "success": False,
            "error": str(e),
            "suggestion": "Check that your system supports secure credential storage.",
        }
    except Exception as e:
        logger.error("Unexpected error saving credentials", error=str(e))
        return {
            "success": False,
            "error": f"Failed to save credentials: {e}",
        }


def session_clear_credentials() -> dict[str, Any]:
    """Remove stored HEB login credentials.

    After clearing, session_refresh will fall back to manual browser login
    when your session expires.

    Returns:
        dict with success status

    Note: This does NOT clear your current session. Use session_clear()
    to remove session cookies.
    """
    settings = get_settings()
    auth_dir = Path(settings.auth_state_path).expanduser().parent
    cred_store = CredentialStore(auth_dir)

    try:
        had_credentials = cred_store.has_credentials()
        cred_store.clear()

        if had_credentials:
            logger.info("Credentials cleared successfully")
            return {
                "success": True,
                "message": "Credentials cleared. Auto-login is now disabled.",
                "had_credentials": True,
            }
        else:
            return {
                "success": True,
                "message": "No credentials were stored.",
                "had_credentials": False,
            }

    except Exception as e:
        logger.error("Failed to clear credentials", error=str(e))
        return {
            "success": False,
            "error": f"Failed to clear credentials: {e}",
        }


def _mask_email(email: str) -> str:
    """Mask email for safe display (e.g., u***r@example.com)."""
    if not email or "@" not in email:
        return "***"

    local, domain = email.split("@", 1)
    if len(local) <= 2:
        masked_local = "*" * len(local)
    else:
        masked_local = local[0] + "*" * (len(local) - 2) + local[-1]

    return f"{masked_local}@{domain}"
