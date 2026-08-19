"""Session management tools for MCP."""

import asyncio
import os
import sys
from pathlib import Path
from typing import Any

import structlog

from auto_grocier_mcp.auth.credentials import CredentialError, CredentialStore
from auto_grocier_mcp.auth.session import (
    check_session_freshness,
    get_session_info,
    get_session_status,
    is_authenticated,
)
from auto_grocier_mcp.utils.config import get_settings

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


async def _run_nodriver_login(env: dict[str, str], *, timeout_ms: int = 300000) -> tuple[int, str]:
    """Run the nodriver ``login_export`` flow as an isolated subprocess.

    Drives the maintained nodriver login flow (the same one the
    refresh-heb-login skill uses): it logs in headfully under the container's
    Xvfb display, handles email verification, and writes a fresh ``auth.json``.
    No Playwright is involved.

    Kept as a module-level function so tests can patch it without spawning a
    real browser.

    Returns:
        (returncode, combined_stdout+stderr)
    """
    proc = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "auto_grocier.session_maintenance.run",
        env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    try:
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout_ms / 1000)
    except (TimeoutError, asyncio.TimeoutError):
        proc.kill()
        await proc.wait()
        return 1, "nodriver login timed out"
    output = stdout.decode("utf-8", errors="replace") if stdout else ""
    return proc.returncode or 0, output


async def session_refresh(
    headless: bool = True,
    timeout: int = 30000,
    login_timeout: int = 300000,
    use_saved_credentials: bool = True,
) -> dict[str, Any]:
    """Refresh HEB session cookies and tokens.

    Runs the maintained nodriver login flow in an isolated subprocess: it logs
    in headfully under the container's Xvfb display, handles email
    verification, and exports a fresh auth.json for the GraphQL client. If
    credentials are saved they are used for automatic login. No Playwright is
    involved.

    Args:
        headless: Accepted for backwards compatibility. The nodriver login flow
                  always runs headfully under Xvfb, so this is ignored.
        timeout: Accepted for backwards compatibility; unused.
        login_timeout: Maximum time to wait for the login subprocess in
                       milliseconds. Default 300000 (5 minutes).
        use_saved_credentials: If True and credentials are stored, pass them to
                               the login subprocess for automatic login.
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

    # Refresh via the nodriver login flow (isolated subprocess). This runs the
    # same maintenance flow as the refresh-heb-login skill: it logs in headfully
    # under the container's Xvfb display, handles email verification, and exports
    # a fresh auth.json for the GraphQL client. No Playwright is involved.
    env: dict[str, str] = dict(os.environ)
    env["MODE"] = "nodriver"
    env["OPERATION"] = "login_export"
    # Avoid the interactive recipe prompt in the login_export path.
    env.setdefault("INGREDIENT_SOURCE", "hardcoded")

    if has_credentials:
        credentials = cred_store.get()
        if credentials:
            email, password = credentials
            env["EMAIL"] = email
            env["PASSWORD"] = password

    logger.info("Refreshing session via nodriver login subprocess")
    returncode, output = await _run_nodriver_login(env, timeout_ms=login_timeout)

    if returncode == 0 and is_authenticated():
        return {
            "success": True,
            "status": "success",
            "message": "Session refreshed via nodriver login.",
            "auth_path": str(auth_path),
            "session": get_session_info(),
        }

    freshness = check_session_freshness()
    suggestion = (
        "Automated nodriver login did not produce a valid session. Verify your "
        "HEB credentials in the environment/.env and try again. If HEB is "
        "requiring email verification, ensure IMAP settings are configured."
    )
    if not has_credentials:
        suggestion += (
            "\n\nTip: save credentials with session_save_credentials() so the "
            "login can run automatically."
        )

    return {
        "success": False,
        "status": "failed",
        "error_type": "login_failed" if returncode == 0 else "browser_error",
        "returncode": returncode,
        "current_status": {
            "authenticated": freshness.get("authenticated", False),
            "needs_refresh": freshness.get("needs_refresh", True),
            "reason": freshness.get("reason"),
        },
        "auth_path": str(auth_path),
        "credentials_available": has_credentials,
        "suggestion": suggestion,
        "output_tail": output[-2000:] if output else "",
    }


def session_save_instructions() -> dict[str, Any]:
    """Get instructions for refreshing and saving the browser session.

    For automatic session extraction, use session_refresh instead — it runs the
    nodriver login flow and writes auth.json for you.
    """
    settings = get_settings()

    return {
        "instructions": [
            "1. Preferred: call session_refresh to log in via the nodriver flow",
            "   and export a fresh session automatically.",
            "",
            "2. If session_refresh cannot log in automatically, run the",
            "   refresh-heb-login maintenance skill, which drives the same",
            "   nodriver login inside the Docker container and writes auth.json",
            "   straight into the session volume.",
            "",
            "3. After a refresh, call session_status to confirm authentication.",
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
