"""Browser-based session refresh using embedded Playwright.

This module provides fast session refresh (~10-15 seconds) by embedding
Playwright directly, eliminating the orchestration overhead of the
Playwright MCP approach (~4 minutes).

Requires optional dependency: pip install texas-grocery-mcp[browser]
After install, run: playwright install chromium
"""

import asyncio
import glob
import os
import time
from pathlib import Path
from typing import Any, Literal, TypedDict

import structlog

logger = structlog.get_logger()

# Check if playwright is available (optional dependency)
try:
    from playwright.async_api import async_playwright

    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False
    async_playwright = None  # type: ignore[assignment]


class PlaywrightNotInstalledError(Exception):
    """Raised when playwright is not installed."""

    pass


class BrowserRefreshError(Exception):
    """Raised when browser refresh fails."""

    pass


class LoginRequiredError(Exception):
    """Raised when HEB requires full login (not just token refresh)."""

    pass


# Lock to prevent concurrent refreshes
_refresh_lock = asyncio.Lock()

class PendingLoginState(TypedDict, total=False):
    """State for an interactive login/refresh flow that spans tool calls."""

    flow: Literal["auto_login", "manual_login", "unknown"]
    stage: str
    start_time: float
    auth_path: Path

    # Playwright objects (kept open between calls)
    playwright: Any
    browser: Any
    context: Any
    page: Any

    # Optional (auto-login) fields
    email: str
    password: str


# Module-level state to track a pending interactive login/refresh flow
_pending_login_state: PendingLoginState | None = None


def is_playwright_available() -> bool:
    """Check if Playwright is installed and available."""
    return PLAYWRIGHT_AVAILABLE


def _detect_security_challenge_html(html: str) -> bool:
    """Detect if HTML content is a WAF/captcha challenge page.

    HEB uses Incapsula/Imperva and other anti-bot measures that sometimes
    return interstitials instead of the real site.

    IMPORTANT: This function must NOT trigger on normal HEB pages.
    - "reese84" appears on ALL HEB pages (bot detection script) - NOT a challenge
    - "incapsula" may appear in normal page headers - need context

    True challenge pages are interstitials with minimal content and specific phrases.
    """
    html_lower = html.lower()

    # First, check if this looks like a normal HEB page (has real content)
    # If so, it's NOT a challenge page even if some indicators are present
    normal_page_indicators = [
        "heb.com",  # Site branding
        "add to cart",  # Shopping functionality
        "my cart",  # Cart link
        "my account",  # Account link
        "curbside",  # HEB service
        "delivery",  # HEB service
        "weekly ad",  # HEB feature
        "shop now",  # Call to action
        "products",  # Product content
        '<nav',  # Navigation element
        '<header',  # Header element
        'data-testid',  # React test IDs (HEB uses React)
    ]

    # If we find normal page indicators, this is NOT a challenge page
    normal_indicator_count = sum(1 for ind in normal_page_indicators if ind in html_lower)
    if normal_indicator_count >= 3:
        # Has multiple signs of being a real HEB page
        return False

    # Challenge-specific phrases that indicate a true interstitial block page
    # These are phrases that appear ONLY on challenge pages, not normal pages
    strong_challenge_indicators = [
        "please verify you are a human",
        "enable javascript and cookies",
        "request unsuccessful",
        "sorry, you have been blocked",
        "access denied",
        "checking your browser",
        "please wait while we verify",
        "just a moment",  # Cloudflare-style challenge
        "ray id:",  # Cloudflare block page
        "performance & security by",  # Cloudflare footer
        "why have i been blocked",
        "this website is using a security service",
    ]

    # If any strong indicator is present, it's definitely a challenge
    if any(indicator in html_lower for indicator in strong_challenge_indicators):
        return True

    # Check for challenge pages with minimal content (interstitials are usually sparse)
    # A real HEB page has thousands of characters; a challenge page is typically < 5000
    is_minimal_content = len(html) < 5000

    # Weak indicators that only count on minimal content pages
    weak_challenge_indicators = [
        "_incapsula_resource",  # Incapsula resource loading
        "challenge-platform",  # Challenge platform marker
        "cf-browser-verification",  # Cloudflare verification
    ]

    return is_minimal_content and any(
        indicator in html_lower for indicator in weak_challenge_indicators
    )


async def _detect_security_challenge(page: Any) -> bool:
    """Detect security challenge in the current page."""
    try:
        content = await page.content()
        return _detect_security_challenge_html(content)
    except Exception:
        return False


async def _detect_login_form(page: Any) -> bool:
    """Check whether a login form is present (email/password fields)."""
    selectors = [
        'input[name="email"]',
        'input[type="email"]',
        "#email",
        'input[placeholder*="email" i]',
        'input[name="password"]',
        'input[type="password"]',
        "#password",
    ]
    for selector in selectors:
        try:
            el = await page.query_selector(selector)
            if el:
                return True
        except Exception:
            continue
    return False


async def _take_login_screenshot(page: Any, action: str) -> str | None:
    """Take screenshot of current page and return path.

    Args:
        page: Playwright page object
        action: Type of action (e.g., "captcha", "2fa")

    Returns:
        Path to screenshot file, or None if failed
    """
    timestamp = int(time.time())
    path = f"/tmp/heb-login-{action}-{timestamp}.png"
    try:
        await page.screenshot(path=path, full_page=True)
        logger.info("Screenshot saved", path=path, action=action)
        return path
    except Exception as e:
        logger.warning("Screenshot failed", error=str(e), action=action)
        return None


def _cleanup_old_screenshots(max_age_seconds: int = 3600) -> int:
    """Delete old login screenshots older than max_age_seconds.

    Args:
        max_age_seconds: Maximum age in seconds (default 1 hour)

    Returns:
        Number of files deleted
    """
    deleted = 0
    pattern = "/tmp/heb-login-*.png"
    now = time.time()

    for filepath in glob.glob(pattern):
        try:
            file_age = now - os.path.getmtime(filepath)
            if file_age > max_age_seconds:
                os.remove(filepath)
                deleted += 1
                logger.debug("Deleted old screenshot", path=filepath)
        except OSError as e:
            logger.debug("Could not delete screenshot", path=filepath, error=str(e))

    return deleted


def clear_pending_login() -> None:
    """Clear any pending login state and close the browser.

    Call this to reset state if login flow needs to be restarted.
    """
    global _pending_login_state
    if _pending_login_state:
        try:
            playwright = _pending_login_state.get("playwright")
            browser = _pending_login_state.get("browser")
            if playwright or browser:
                # Full cleanup (browser + playwright) in the event loop
                asyncio.create_task(_cleanup_browser(playwright, browser))
        except Exception as e:
            logger.debug("Error closing pending browser", error=str(e))
        _pending_login_state = None
        logger.info("Pending login state cleared")


async def _check_authenticated(context: Any) -> bool:
    """Check if session has authentication cookies."""
    cookies = await context.cookies()
    # HEB uses 'sat' or 'DYN_USER_ID' cookies for authenticated sessions
    auth_cookie_names = {"sat", "DYN_USER_ID"}
    return any(c["name"] in auth_cookie_names for c in cookies)


async def refresh_session_with_browser(
    auth_path: Path,
    headless: bool = True,
    timeout: int = 30000,
    login_timeout: int = 300000,  # 5 minutes for manual login
) -> dict[str, Any]:
    """Refresh HEB session using embedded Playwright.

    This is the FAST method (10-15 seconds) that runs Playwright directly
    instead of orchestrating it through MCP tool calls.

    SMART REFRESH LOGIC:
    - Loads existing auth.json cookies into browser before navigating
    - This allows headless refresh to work even when reese84 token expired
    - Only requires manual login when session cookies are truly expired
    - Visiting HEB.com regenerates the reese84 bot detection token

    Args:
        auth_path: Path to save auth.json (cookies + localStorage)
        headless: Run browser in headless mode (default True).
                  Set to False if you need to complete a manual login.
        timeout: Navigation timeout in milliseconds (default 30000)
        login_timeout: Deprecated (non-headless mode returns immediately for human handoff).

    Returns:
        dict with success status, message, and timing info:
        {
            "success": True,
            "message": "Session refreshed successfully in 12.3s",
            "elapsed_seconds": 12.3,
            "auth_path": "/path/to/auth.json",
            "cookies_count": 25,
            "local_storage_count": 5
        }

    Raises:
        PlaywrightNotInstalledError: If playwright is not installed
        BrowserRefreshError: If browser operation fails
        LoginRequiredError: If HEB requires full login
    """
    if not PLAYWRIGHT_AVAILABLE:
        raise PlaywrightNotInstalledError(
            "Playwright not installed. Install with:\n"
            "  pip install texas-grocery-mcp[browser]\n"
            "  playwright install chromium"
        )

    assert async_playwright is not None

    # Use lock to prevent concurrent refresh attempts
    async with _refresh_lock:
        # If we already have an interactive flow in progress, resume it instead
        # of starting a new browser (prevents "stuck" calls and duplicate windows).
        global _pending_login_state
        _cleanup_old_screenshots()
        if _pending_login_state:
            return await _resume_pending_login(auth_path)

        start_time = time.monotonic()
        playwright: Any | None = None
        browser: Any | None = None

        # Headless mode: refresh tokens quickly, but cannot handle human interaction.
        if headless:
            try:
                async with async_playwright() as p:
                    logger.info("Launching browser for session refresh", headless=headless)
                    browser = await p.chromium.launch(
                        headless=True,
                        args=[
                            "--disable-blink-features=AutomationControlled",
                            "--no-first-run",
                            "--no-default-browser-check",
                            "--disable-infobars",
                        ],
                    )

                    storage_state = str(auth_path) if auth_path.exists() else None
                    context = await browser.new_context(
                        user_agent=(
                            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                            "AppleWebKit/537.36 (KHTML, like Gecko) "
                            "Chrome/120.0.0.0 Safari/537.36"
                        ),
                        storage_state=storage_state,
                    )

                    page = await context.new_page()
                    logger.info("Navigating to HEB.com...")
                    response = await page.goto(
                        "https://www.heb.com",
                        wait_until="load",
                        timeout=timeout,
                    )

                    if response and response.status >= 400:
                        await browser.close()
                        raise BrowserRefreshError(f"HEB.com returned HTTP status {response.status}")

                    # Fail fast if we're on a security interstitial.
                    if await _detect_security_challenge(page) or await _detect_captcha(page):
                        await browser.close()
                        raise BrowserRefreshError(
                            "Security challenge detected in headless mode. "
                            "Run session_refresh(headless=False) to complete it."
                        )

                    if not await _check_authenticated(context):
                        await browser.close()
                        raise LoginRequiredError(
                            "HEB requires login. Your session has expired.\n"
                            "Run session_refresh(headless=False) to login manually."
                        )

                    logger.info("Waiting for reese84 token generation...")
                    await page.wait_for_timeout(5000)

                    logger.info("Saving session state", auth_path=str(auth_path))
                    auth_path.parent.mkdir(parents=True, exist_ok=True)
                    await context.storage_state(path=str(auth_path))

                    # Ensure secure permissions on auth file
                    from texas_grocery_mcp.utils.secure_file import ensure_secure_permissions

                    ensure_secure_permissions(auth_path)

                    cookies = await context.cookies()
                    local_storage_count = await page.evaluate("() => window.localStorage.length")
                    await browser.close()

                    elapsed = time.monotonic() - start_time
                    logger.info(
                        "Session refreshed successfully",
                        elapsed_seconds=round(elapsed, 1),
                        cookies_count=len(cookies),
                        local_storage_count=local_storage_count,
                    )

                    return {
                        "success": True,
                        "status": "success",
                        "message": f"Session refreshed successfully in {elapsed:.1f}s",
                        "elapsed_seconds": round(elapsed, 1),
                        "auth_path": str(auth_path),
                        "cookies_count": len(cookies),
                        "local_storage_count": local_storage_count,
                    }

            except PlaywrightNotInstalledError:
                raise
            except LoginRequiredError:
                raise
            except TimeoutError as e:
                elapsed = time.monotonic() - start_time
                logger.error("Browser refresh timed out", elapsed_seconds=elapsed)
                raise BrowserRefreshError(
                    f"Browser navigation timed out after {elapsed:.1f}s. "
                    "Check your internet connection and try again."
                ) from e
            except Exception as e:
                elapsed = time.monotonic() - start_time
                logger.error(
                    "Browser refresh failed",
                    error=str(e),
                    elapsed_seconds=round(elapsed, 1),
                )
                raise BrowserRefreshError(f"Browser refresh failed: {e}") from e

        # Non-headless mode: NEVER block waiting for login. Start an interactive
        # flow, take a screenshot, and return control to the agent/user immediately.
        playwright = None
        browser = None
        try:
            playwright = await async_playwright().start()

            logger.info("Launching browser for session refresh", headless=False)
            browser = await playwright.chromium.launch(
                headless=False,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-first-run",
                    "--no-default-browser-check",
                    "--disable-infobars",
                ],
            )

            storage_state = str(auth_path) if auth_path.exists() else None
            if storage_state:
                logger.info(
                    "Loading existing auth state for smart refresh",
                    auth_path=str(auth_path),
                )

            context = await browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
                storage_state=storage_state,
            )
            page = await context.new_page()

            # Step 1: Try homepage refresh (may succeed without login)
            logger.info("Navigating to HEB.com...")
            response = await page.goto(
                "https://www.heb.com",
                wait_until="load",
                timeout=timeout,
            )
            if response and response.status >= 400:
                raise BrowserRefreshError(f"HEB.com returned HTTP status {response.status}")

            # If we hit a security challenge, hand off immediately.
            if await _detect_security_challenge(page):
                await _inject_status_banner(
                    page,
                    (
                        "Security check detected. Complete it in this browser, "
                        "then tell your agent 'done'."
                    ),
                    is_waiting=True,
                )
                screenshot_path = await _take_login_screenshot(page, "waf")

                _pending_login_state = PendingLoginState(
                    flow="manual_login",
                    stage="manual_login",
                    start_time=start_time,
                    auth_path=auth_path,
                    playwright=playwright,
                    browser=browser,
                    context=context,
                    page=page,
                )
                return _build_human_action_response("waf", screenshot_path)

            if await _detect_captcha(page):
                await _inject_status_banner(
                    page,
                    "CAPTCHA detected. Solve it in this browser, then tell your agent 'done'.",
                    is_waiting=True,
                )
                screenshot_path = await _take_login_screenshot(page, "captcha")

                _pending_login_state = PendingLoginState(
                    flow="manual_login",
                    stage="manual_login",
                    start_time=start_time,
                    auth_path=auth_path,
                    playwright=playwright,
                    browser=browser,
                    context=context,
                    page=page,
                )
                return _build_human_action_response("captcha", screenshot_path)

            # If already authenticated, just refresh and save.
            if await _check_authenticated(context):
                logger.info("Already authenticated - refreshing session tokens")
                logger.info("Waiting for reese84 token generation...")
                await page.wait_for_timeout(5000)

                logger.info("Saving session state", auth_path=str(auth_path))
                auth_path.parent.mkdir(parents=True, exist_ok=True)
                await context.storage_state(path=str(auth_path))

                # Ensure secure permissions on auth file
                from texas_grocery_mcp.utils.secure_file import ensure_secure_permissions

                ensure_secure_permissions(auth_path)

                cookies = await context.cookies()
                local_storage_count = await page.evaluate("() => window.localStorage.length")
                await _cleanup_browser(playwright, browser)

                elapsed = time.monotonic() - start_time
                return {
                    "success": True,
                    "status": "success",
                    "message": f"Session refreshed successfully in {elapsed:.1f}s",
                    "elapsed_seconds": round(elapsed, 1),
                    "auth_path": str(auth_path),
                    "cookies_count": len(cookies),
                    "local_storage_count": local_storage_count,
                }

            # Step 2: Not authenticated - open login and hand off immediately.
            logger.info("Not authenticated - opening login page for user")
            await page.goto(
                "https://www.heb.com/my-account/login",
                wait_until="load",
                timeout=timeout,
            )

            await _inject_status_banner(
                page,
                "Please log in to HEB in this browser, then tell your agent 'done'.",
                is_waiting=True,
            )

            # Detect blockers on the login page and hand off with a screenshot.
            action: Literal["login", "captcha", "2fa", "waf"] = "login"
            if await _detect_security_challenge(page):
                action = "waf"
            elif await _detect_captcha(page):
                action = "captcha"
            elif await _detect_2fa(page):
                action = "2fa"
            elif not await _detect_login_form(page):
                # Sometimes HEB changes login flow or returns an error page. Treat as WAF/error.
                action = "waf"

            screenshot_path = await _take_login_screenshot(page, action)

            _pending_login_state = PendingLoginState(
                flow="manual_login",
                stage="manual_login",
                start_time=start_time,
                auth_path=auth_path,
                playwright=playwright,
                browser=browser,
                context=context,
                page=page,
            )

            return _build_human_action_response(action, screenshot_path)

        except TimeoutError as e:
            elapsed = time.monotonic() - start_time
            logger.error("Browser refresh timed out", elapsed_seconds=elapsed)
            await _cleanup_browser(playwright, browser)
            raise BrowserRefreshError(
                f"Browser navigation timed out after {elapsed:.1f}s. "
                "Check your internet connection and try again."
            ) from e
        except Exception as e:
            elapsed = time.monotonic() - start_time
            logger.error("Browser refresh failed", error=str(e), elapsed_seconds=round(elapsed, 1))
            await _cleanup_browser(playwright, browser)
            raise BrowserRefreshError(f"Browser refresh failed: {e}") from e


# CAPTCHA detection selectors
CAPTCHA_SELECTORS = [
    'iframe[src*="recaptcha"]',
    '#g-recaptcha',
    '.g-recaptcha',
    'iframe[src*="hcaptcha"]',
    '[data-hcaptcha-sitekey]',
    '[data-friendly-captcha]',
    'iframe[src*="captcha"]',
]

# 2FA detection patterns
TWO_FA_INDICATORS = [
    "verification code",
    "one-time code",
    "we sent a code",
    "enter the code",
    "security code",
    "verify your identity",
]


class AutoLoginError(Exception):
    """Raised when auto-login fails."""

    pass


class CaptchaRequiredError(Exception):
    """Raised when CAPTCHA needs human solving."""

    def __init__(
        self,
        message: str,
        browser: Any | None = None,
        page: Any | None = None,
        context: Any | None = None,
    ):
        super().__init__(message)
        self.browser = browser
        self.page = page
        self.context = context


class TwoFactorRequiredError(Exception):
    """Raised when 2FA verification is needed."""

    def __init__(
        self,
        message: str,
        browser: Any | None = None,
        page: Any | None = None,
        context: Any | None = None,
    ):
        super().__init__(message)
        self.browser = browser
        self.page = page
        self.context = context


async def _detect_captcha(page: Any) -> bool:
    """Check if CAPTCHA is present on page.

    Returns:
        True if CAPTCHA detected, False otherwise
    """
    for selector in CAPTCHA_SELECTORS:
        try:
            element = await page.query_selector(selector)
            if element:
                logger.info("CAPTCHA detected", selector=selector)
                return True
        except Exception:
            continue

    # Also check page content for CAPTCHA-related text
    try:
        content = await page.content()
        content_lower = content.lower()
        if "captcha" in content_lower and ("solve" in content_lower or "verify" in content_lower):
            logger.info("CAPTCHA detected via page content")
            return True
    except Exception:
        pass

    return False


async def _detect_2fa(page: Any) -> bool:
    """Check if 2FA verification is required.

    Returns:
        True if 2FA prompt detected, False otherwise
    """
    try:
        content = await page.content()
        content_lower = content.lower()

        for indicator in TWO_FA_INDICATORS:
            if indicator in content_lower:
                logger.info("2FA detected", indicator=indicator)
                return True

        # Check for 6-digit code input field
        code_input = await page.query_selector('input[maxlength="6"]')
        if code_input:
            logger.info("2FA detected via 6-digit input field")
            return True

    except Exception as e:
        logger.warning("Error checking for 2FA", error=str(e))

    return False


async def _verify_login_success(page: Any, context: Any) -> bool:
    """Verify that login completed successfully.

    Checks:
    - URL redirect to profile/account page
    - Presence of auth cookies
    - "Hi, [Name]" in page content

    Returns:
        True if login appears successful
    """
    try:
        # Check URL
        current_url = page.url
        success_url_patterns = ["/my-account", "/profile", "/account"]
        url_indicates_success = any(pattern in current_url for pattern in success_url_patterns)

        # Check auth cookies
        has_auth_cookies = await _check_authenticated(context)

        # Check for user greeting
        try:
            content = await page.content()
            has_greeting = "hi," in content.lower() or "hello," in content.lower()
        except Exception:
            has_greeting = False

        # Success if we have auth cookies AND (URL or greeting)
        is_success = has_auth_cookies and (url_indicates_success or has_greeting)

        logger.debug(
            "Login success check",
            url_indicates_success=url_indicates_success,
            has_auth_cookies=has_auth_cookies,
            has_greeting=has_greeting,
            is_success=is_success,
        )

        return is_success

    except Exception as e:
        logger.warning("Error verifying login success", error=str(e))
        return False


async def auto_login_with_credentials(
    auth_path: Path,
    email: str,
    password: str,
    headless: bool = False,  # Default to visible for human handoff
    timeout: int = 30000,
    login_timeout: int = 300000,
) -> dict[str, Any]:
    """Perform automatic login using stored credentials.

    This implements "Smart Semi-Automated Login with Human Handoff":
    1. Navigate to login page
    2. Fill email and password automatically
    3. Click Continue/Submit
    4. If CAPTCHA detected: take screenshot, return immediately for human solving
    5. If 2FA detected: take screenshot, return immediately for code entry
    6. Call again after human action to continue
    7. Verify success and save session

    The browser stays open between calls when waiting for human action.
    Call session_refresh() again after solving CAPTCHA/2FA to continue.

    Args:
        auth_path: Path to save auth.json
        email: HEB account email
        password: HEB account password
        headless: Run browser without visible window (default False for handoff)
        timeout: Navigation timeout in milliseconds
        login_timeout: Max time for entire login process

    Returns:
        dict with status and next action:
        - {"status": "success", ...} - Login completed
        - {"status": "human_action_required", "action": "captcha", ...} - Solve CAPTCHA
        - {"status": "human_action_required", "action": "2fa", ...} - Enter 2FA code
        - {"status": "failed", ...} - Login failed
    """
    global _pending_login_state

    if not PLAYWRIGHT_AVAILABLE:
        raise PlaywrightNotInstalledError(
            "Playwright not installed. Install with:\n"
            "  pip install texas-grocery-mcp[browser]\n"
            "  playwright install chromium"
        )

    # Cleanup old screenshots on each call
    _cleanup_old_screenshots()

    async with _refresh_lock:
        start_time = time.monotonic()

        # Check if we have a pending login to resume
        if _pending_login_state:
            return await _resume_pending_login(auth_path)

        # Start fresh login
        playwright = None
        browser = None

        try:
            playwright = await async_playwright().start()

            # Launch browser (visible by default for human handoff)
            logger.info("Launching browser for auto-login", headless=headless)
            browser = await playwright.chromium.launch(
                headless=headless,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-first-run",
                    "--no-default-browser-check",
                    "--disable-infobars",
                ],
            )

            context = await browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
            )

            page = await context.new_page()

            # Navigate to HEB login page (must use /my-account/login, not /login)
            logger.info("Navigating to HEB login page...")
            await page.goto(
                "https://www.heb.com/my-account/login",
                wait_until="load",
                timeout=timeout,
            )

            # Wait for actual login form to appear
            logger.info("Waiting for login form to load...")
            login_form_loaded = False
            form_wait_start = time.monotonic()
            max_form_wait = 30000  # 30 seconds max

            while not login_form_loaded:
                await page.wait_for_timeout(1000)

                # Check if login form is present (email field exists)
                for selector in ['input[name="email"]', 'input[type="email"]', '#email']:
                    try:
                        email_field = await page.query_selector(selector)
                        if email_field:
                            login_form_loaded = True
                            logger.info("Login form loaded", selector=selector)
                            break
                    except Exception:
                        continue

                # Check for timeout
                if (time.monotonic() - form_wait_start) * 1000 >= max_form_wait:
                    current_url = page.url
                    logger.warning("Login form not found after waiting", url=current_url)
                    break

            # If login form never loaded, check if we're on an error page
            if not login_form_loaded:
                current_url = page.url
                page_title = await page.title()

                # Check for common error indicators
                is_error_page = (
                    "error" in current_url.lower()
                    or "error" in page_title.lower()
                    or "something went wrong" in page_title.lower()
                    or "page not found" in page_title.lower()
                )

                # Take screenshot to show what happened
                screenshot_path = await _take_login_screenshot(page, "error")

                if is_error_page:
                    logger.error(
                        "HEB returned an error page",
                        url=current_url,
                        title=page_title,
                    )
                    await _cleanup_browser(playwright, browser)
                    return {
                        "status": "failed",
                        "message": f"HEB returned an error page: {page_title}",
                        "error": "heb_error_page",
                        "screenshot_path": screenshot_path,
                        "url": current_url,
                        "suggestion": "HEB.com may be having issues. Try again in a few minutes.",
                    }
                else:
                    logger.error(
                        "Login form not found",
                        url=current_url,
                        title=page_title,
                    )
                    await _cleanup_browser(playwright, browser)
                    return {
                        "status": "failed",
                        "message": f"Could not find login form. Page: {page_title}",
                        "error": "login_form_not_found",
                        "screenshot_path": screenshot_path,
                        "url": current_url,
                        "suggestion": (
                            "Check the screenshot to see what page loaded. "
                            "HEB may have changed their login flow."
                        ),
                    }

            # Check for CAPTCHA before filling form
            await _inject_status_banner(page, "Checking for CAPTCHA...")
            await page.wait_for_timeout(1000)

            if await _detect_captcha(page):
                logger.info("CAPTCHA detected on login page - returning for human action")
                await _inject_status_banner(
                    page,
                    "CAPTCHA detected! Please solve it, then tell the AI 'done'.",
                    is_waiting=True,
                )
                screenshot_path = await _take_login_screenshot(page, "captcha")

                # Store state for resume
                _pending_login_state = {
                    "flow": "auto_login",
                    "playwright": playwright,
                    "browser": browser,
                    "context": context,
                    "page": page,
                    "auth_path": auth_path,
                    "email": email,
                    "password": password,
                    "stage": "pre_credentials",
                    "start_time": start_time,
                }

                return _build_human_action_response("captcha", screenshot_path)

            # Fill credentials
            await _inject_status_banner(page, "Filling credentials automatically...")
            await page.wait_for_timeout(500)

            # Fill email
            email_filled = False
            email_selectors = [
                'input[name="email"]',
                'input[type="email"]',
                "#email",
                'input[placeholder*="email" i]',
            ]
            for selector in email_selectors:
                try:
                    email_field = await page.query_selector(selector)
                    if email_field:
                        await email_field.fill(email)
                        email_filled = True
                        logger.debug("Filled email field", selector=selector)
                        break
                except Exception:
                    continue

            if not email_filled:
                await _cleanup_browser(playwright, browser)
                return {
                    "status": "failed",
                    "message": "Could not find email field on login page",
                    "error": "selector_not_found",
                }

            # Fill password
            password_filled = False
            for selector in ['input[name="password"]', 'input[type="password"]', '#password']:
                try:
                    password_field = await page.query_selector(selector)
                    if password_field:
                        await password_field.fill(password)
                        password_filled = True
                        logger.debug("Filled password field", selector=selector)
                        break
                except Exception:
                    continue

            if not password_filled:
                await _cleanup_browser(playwright, browser)
                return {
                    "status": "failed",
                    "message": "Could not find password field on login page",
                    "error": "selector_not_found",
                }

            # Click Continue button
            await _inject_status_banner(page, "Clicking Continue...")
            await page.wait_for_timeout(500)

            continue_selectors = [
                'button:has-text("Continue")',
                'button[type="submit"]:has-text("Continue")',
                'input[type="submit"][value*="Continue" i]',
            ]
            for selector in continue_selectors:
                try:
                    button = await page.query_selector(selector)
                    if button:
                        await button.click()
                        logger.debug("Clicked Continue button", selector=selector)
                        break
                except Exception:
                    continue

            await page.wait_for_timeout(2000)

            # Check for CAPTCHA after Continue
            if await _detect_captcha(page):
                logger.info("CAPTCHA detected after Continue - returning for human action")
                await _inject_status_banner(
                    page,
                    "CAPTCHA detected! Please solve it, then tell the AI 'done'.",
                    is_waiting=True,
                )
                screenshot_path = await _take_login_screenshot(page, "captcha")

                _pending_login_state = {
                    "flow": "auto_login",
                    "playwright": playwright,
                    "browser": browser,
                    "context": context,
                    "page": page,
                    "auth_path": auth_path,
                    "email": email,
                    "password": password,
                    "stage": "post_continue",
                    "start_time": start_time,
                }

                return _build_human_action_response("captcha", screenshot_path)

            # Click Submit button
            await _inject_status_banner(page, "Clicking Submit...")
            await page.wait_for_timeout(500)

            submit_selectors = [
                'button:has-text("Submit")',
                'button:has-text("Sign in")',
                'button:has-text("Log in")',
                'button[type="submit"]',
            ]
            for selector in submit_selectors:
                try:
                    button = await page.query_selector(selector)
                    if button:
                        await button.click()
                        logger.debug("Clicked Submit button", selector=selector)
                        break
                except Exception:
                    continue

            await page.wait_for_timeout(3000)

            # Check for CAPTCHA after Submit
            if await _detect_captcha(page):
                logger.info("CAPTCHA detected after Submit - returning for human action")
                await _inject_status_banner(
                    page,
                    "CAPTCHA detected! Please solve it, then tell the AI 'done'.",
                    is_waiting=True,
                )
                screenshot_path = await _take_login_screenshot(page, "captcha")

                _pending_login_state = {
                    "flow": "auto_login",
                    "playwright": playwright,
                    "browser": browser,
                    "context": context,
                    "page": page,
                    "auth_path": auth_path,
                    "email": email,
                    "password": password,
                    "stage": "post_submit",
                    "start_time": start_time,
                }

                return _build_human_action_response("captcha", screenshot_path)

            # Check for 2FA
            if await _detect_2fa(page):
                logger.info("2FA detected - returning for human action")
                await _inject_status_banner(
                    page,
                    "Verification code required! Enter the code sent to your email.",
                    is_waiting=True,
                )
                screenshot_path = await _take_login_screenshot(page, "2fa")

                _pending_login_state = {
                    "flow": "auto_login",
                    "playwright": playwright,
                    "browser": browser,
                    "context": context,
                    "page": page,
                    "auth_path": auth_path,
                    "email": email,
                    "password": password,
                    "stage": "2fa",
                    "start_time": start_time,
                }

                return _build_human_action_response("2fa", screenshot_path)

            # Check for login errors
            for selector in ['.error-message', '.alert-danger', '[role="alert"]', '.login-error']:
                try:
                    error_el = await page.query_selector(selector)
                    if error_el:
                        error_text = await error_el.text_content()
                        if error_text and len(error_text.strip()) > 0:
                            await _cleanup_browser(playwright, browser)
                            return {
                                "status": "failed",
                                "message": f"Login failed: {error_text.strip()}",
                                "error": "invalid_credentials",
                                "suggestion": (
                                    "Update your credentials with session_save_credentials()."
                                ),
                            }
                except Exception:
                    continue

            # Verify login success
            if await _verify_login_success(page, context):
                return await _complete_login(
                    playwright,
                    browser,
                    context,
                    page,
                    auth_path,
                    start_time,
                )

            # Wait and check again
            await page.wait_for_timeout(3000)

            if await _verify_login_success(page, context):
                return await _complete_login(
                    playwright,
                    browser,
                    context,
                    page,
                    auth_path,
                    start_time,
                )

            # Unknown state
            await _cleanup_browser(playwright, browser)
            return {
                "status": "failed",
                "message": (
                    "Login result unclear. Please try manual login with "
                    "session_refresh(headless=False)"
                ),
                "error": "unknown_state",
            }

        except PlaywrightNotInstalledError:
            raise
        except TimeoutError:
            elapsed = time.monotonic() - start_time
            await _cleanup_browser(playwright, browser)
            return {
                "status": "failed",
                "message": f"Login timed out after {elapsed:.1f}s",
                "error": "timeout",
            }
        except Exception as e:
            elapsed = time.monotonic() - start_time
            logger.error("Auto-login failed", error=str(e), elapsed_seconds=round(elapsed, 1))
            await _cleanup_browser(playwright, browser)
            return {
                "status": "failed",
                "message": f"Auto-login failed: {e}",
                "error": "exception",
            }


def _build_human_action_response(action: str, screenshot_path: str | None) -> dict[str, Any]:
    """Build standardized response for human action required."""
    action_messages = {
        "captcha": "CAPTCHA detected. Please solve it in the browser window.",
        "2fa": "Verification code required. Check your email and enter the code in the browser.",
        "login": "Login required. Please log in to your HEB account in the browser window.",
        "waf": "Security check detected. Please complete it in the browser window.",
    }

    action_instructions = {
        "captcha": [
            "1. Look at the browser window that opened",
            "2. Solve the CAPTCHA challenge shown",
            "3. After solving, tell me 'done' and I'll continue the login",
        ],
        "2fa": [
            "1. Check your email for a verification code from HEB",
            "2. Enter the code in the browser window",
            "3. After entering, tell me 'done' and I'll continue the login",
        ],
        "login": [
            "1. Look at the browser window that opened",
            "2. Log in to your HEB account",
            "3. Complete any prompts (CAPTCHA/2FA) if they appear",
            "4. After you're logged in, tell me 'done' and I'll save the session",
        ],
        "waf": [
            "1. Look at the browser window that opened",
            "2. Complete any security check shown (CAPTCHA, 'verify you are human', etc.)",
            "3. If it's a hard block, try refreshing or switching networks/VPN settings",
            "4. After the page is unblocked, tell me 'done' and I'll continue",
        ],
    }

    response = {
        "status": "human_action_required",
        "success": False,
        "action": action,
        "message": action_messages.get(action, f"{action} required"),
        "screenshot_path": screenshot_path,
        "instructions": action_instructions.get(action, ["Complete the action in the browser"]),
        "next_step": "Call session_refresh() again after completing the action",
    }

    if screenshot_path:
        response["screenshot_info"] = (
            f"Screenshot saved to: {screenshot_path} - "
            "You can view this to see what's shown in the browser."
        )
    else:
        response["screenshot_error"] = "Could not capture screenshot"

    return response


async def _resume_pending_login(auth_path: Path) -> dict[str, Any]:
    """Resume a pending login after human action (CAPTCHA/2FA solved)."""
    global _pending_login_state

    if not _pending_login_state:
        return {
            "status": "failed",
            "message": "No pending login to resume",
            "error": "no_pending_state",
        }

    playwright = _pending_login_state.get("playwright")
    browser = _pending_login_state.get("browser")
    context = _pending_login_state.get("context")
    page = _pending_login_state.get("page")
    stage = _pending_login_state.get("stage", "unknown")
    flow = _pending_login_state.get("flow", "unknown")
    start_time = float(_pending_login_state.get("start_time", time.monotonic()))
    saved_auth_path = _pending_login_state.get("auth_path", auth_path)
    email = _pending_login_state.get("email")
    password = _pending_login_state.get("password")

    logger.info("Resuming pending login", stage=stage, flow=flow)

    try:
        # Check if browser is still open
        if not browser or not page:
            _pending_login_state = None
            return {
                "status": "failed",
                "message": "Browser was closed. Please start login again.",
                "error": "browser_closed",
            }

        # Manual login flow: never click/fill, just hand off until auth cookies appear.
        if stage == "manual_login" or flow == "manual_login":
            # If a security check is still present, keep handing off.
            if await _detect_security_challenge(page):
                screenshot_path = await _take_login_screenshot(page, "waf")
                return _build_human_action_response("waf", screenshot_path)

            if await _detect_captcha(page):
                screenshot_path = await _take_login_screenshot(page, "captcha")
                return _build_human_action_response("captcha", screenshot_path)

            if await _detect_2fa(page):
                screenshot_path = await _take_login_screenshot(page, "2fa")
                return _build_human_action_response("2fa", screenshot_path)

            # If authenticated, save session and cleanup.
            if await _check_authenticated(context):
                _pending_login_state = None
                return await _complete_login(
                    playwright,
                    browser,
                    context,
                    page,
                    saved_auth_path,
                    start_time,
                )

            # Not authenticated yet; keep handing off (don't block).
            screenshot_path = await _take_login_screenshot(page, "login")
            return _build_human_action_response("login", screenshot_path)

        # Check current page state
        # If CAPTCHA is still present, return again for human action
        if await _detect_captcha(page):
            logger.info("CAPTCHA still detected - waiting for human")
            screenshot_path = await _take_login_screenshot(page, "captcha")
            return _build_human_action_response("captcha", screenshot_path)

        # If 2FA is still present, return again for human action
        if await _detect_2fa(page):
            logger.info("2FA still detected - waiting for human")
            screenshot_path = await _take_login_screenshot(page, "2fa")
            return _build_human_action_response("2fa", screenshot_path)

        # If we ended up on a WAF/security page, hand off.
        if await _detect_security_challenge(page):
            screenshot_path = await _take_login_screenshot(page, "waf")
            return _build_human_action_response("waf", screenshot_path)

        # CAPTCHA/2FA appears to be solved, continue the flow based on stage
        await _inject_status_banner(page, "Continuing login...")

        if stage == "pre_credentials":
            # Need to fill credentials and continue
            await page.wait_for_timeout(1000)

            # Fill email
            for selector in ['input[name="email"]', 'input[type="email"]', '#email']:
                try:
                    email_field = await page.query_selector(selector)
                    if email_field:
                        await email_field.fill(email)
                        break
                except Exception:
                    continue

            # Fill password
            for selector in ['input[name="password"]', 'input[type="password"]', '#password']:
                try:
                    password_field = await page.query_selector(selector)
                    if password_field:
                        await password_field.fill(password)
                        break
                except Exception:
                    continue

            # Click Continue
            await page.wait_for_timeout(500)
            for selector in ['button:has-text("Continue")', 'button[type="submit"]']:
                try:
                    button = await page.query_selector(selector)
                    if button:
                        await button.click()
                        break
                except Exception:
                    continue

            await page.wait_for_timeout(2000)

            # Check for CAPTCHA after Continue
            if await _detect_captcha(page):
                screenshot_path = await _take_login_screenshot(page, "captcha")
                _pending_login_state["stage"] = "post_continue"
                return _build_human_action_response("captcha", screenshot_path)

        if stage in ["pre_credentials", "post_continue"]:
            # Click Submit
            await _inject_status_banner(page, "Clicking Submit...")
            await page.wait_for_timeout(500)

            resume_submit_selectors = [
                'button:has-text("Submit")',
                'button:has-text("Sign in")',
                'button[type="submit"]',
            ]
            for selector in resume_submit_selectors:
                try:
                    button = await page.query_selector(selector)
                    if button:
                        await button.click()
                        break
                except Exception:
                    continue

            await page.wait_for_timeout(3000)

            # Check for CAPTCHA after Submit
            if await _detect_captcha(page):
                screenshot_path = await _take_login_screenshot(page, "captcha")
                _pending_login_state["stage"] = "post_submit"
                return _build_human_action_response("captcha", screenshot_path)

            # Check for 2FA
            if await _detect_2fa(page):
                screenshot_path = await _take_login_screenshot(page, "2fa")
                _pending_login_state["stage"] = "2fa"
                return _build_human_action_response("2fa", screenshot_path)

        # Check for login success
        if await _verify_login_success(page, context):
            _pending_login_state = None
            return await _complete_login(
                playwright,
                browser,
                context,
                page,
                saved_auth_path,
                start_time,
            )

        # Wait and check again
        await page.wait_for_timeout(3000)

        if await _verify_login_success(page, context):
            _pending_login_state = None
            return await _complete_login(
                playwright,
                browser,
                context,
                page,
                saved_auth_path,
                start_time,
            )

        # Still not logged in - check for errors
        for selector in ['.error-message', '.alert-danger', '[role="alert"]']:
            try:
                error_el = await page.query_selector(selector)
                if error_el:
                    error_text = await error_el.text_content()
                    if error_text and len(error_text.strip()) > 0:
                        _pending_login_state = None
                        await _cleanup_browser(playwright, browser)
                        return {
                            "status": "failed",
                            "message": f"Login failed: {error_text.strip()}",
                            "error": "invalid_credentials",
                        }
            except Exception:
                continue

        # Unknown state
        _pending_login_state = None
        await _cleanup_browser(playwright, browser)
        return {
            "status": "failed",
            "message": "Login result unclear after human action. Please try again.",
            "error": "unknown_state",
        }

    except Exception as e:
        logger.error("Error resuming pending login", error=str(e))
        _pending_login_state = None
        await _cleanup_browser(playwright, browser)
        return {
            "status": "failed",
            "message": f"Error resuming login: {e}",
            "error": "exception",
        }


async def _complete_login(
    playwright: Any,
    browser: Any,
    context: Any,
    page: Any,
    auth_path: Path,
    start_time: float,
) -> dict[str, Any]:
    """Complete the login process - save session and cleanup."""
    global _pending_login_state

    try:
        # Give the site a moment to finalize cookies/localStorage (reese84, etc.)
        await page.wait_for_timeout(2000)

        # Best-effort: visit homepage to trigger bot token/localStorage generation.
        # If this hits a security interstitial, don't block; we'll still save state.
        try:
            await page.goto("https://www.heb.com", wait_until="load", timeout=30000)
            await page.wait_for_timeout(3000)
        except Exception:
            pass

        # Save session
        auth_path.parent.mkdir(parents=True, exist_ok=True)
        await context.storage_state(path=str(auth_path))

        # Ensure secure permissions on auth file
        from texas_grocery_mcp.utils.secure_file import ensure_secure_permissions

        ensure_secure_permissions(auth_path)

        cookies = await context.cookies()
        local_storage_count = await page.evaluate("() => window.localStorage.length")

        elapsed = time.monotonic() - start_time

        logger.info(
            "Login/session save successful",
            elapsed_seconds=round(elapsed, 1),
            cookies_count=len(cookies),
        )

        # Cleanup
        _pending_login_state = None
        await _cleanup_browser(playwright, browser)

        return {
            "status": "success",
            "success": True,
            "message": f"Logged in successfully in {elapsed:.1f}s",
            "elapsed_seconds": round(elapsed, 1),
            "auth_path": str(auth_path),
            "cookies_count": len(cookies),
            "local_storage_count": local_storage_count,
        }

    except Exception as e:
        logger.error("Error completing login", error=str(e))
        _pending_login_state = None
        await _cleanup_browser(playwright, browser)
        return {
            "status": "failed",
            "message": f"Error saving session: {e}",
            "error": "save_failed",
        }


async def _cleanup_browser(playwright: Any, browser: Any) -> None:
    """Safely cleanup browser and playwright instances."""
    global _pending_login_state
    _pending_login_state = None

    try:
        if browser:
            await browser.close()
    except Exception:
        pass

    try:
        if playwright:
            await playwright.stop()
    except Exception:
        pass



async def _inject_status_banner(
    page: Any,
    message: str,
    is_waiting: bool = False,
) -> None:
    """Inject or update a status banner on the page.

    Args:
        page: Playwright page
        message: Status message to display
        is_waiting: If True, show pulsing indicator
    """
    try:
        indicator = "⏳" if is_waiting else "🤖"
        await page.evaluate(
            f"""
            () => {{
                let banner = document.getElementById('mcp-auto-login-banner');
                if (!banner) {{
                    banner = document.createElement('div');
                    banner.id = 'mcp-auto-login-banner';
                    banner.style.cssText = `
                        position: fixed;
                        top: 0;
                        left: 0;
                        right: 0;
                        background: linear-gradient(135deg, #e31837 0%, #c41230 100%);
                        color: white;
                        padding: 16px 20px;
                        font-family: -apple-system, BlinkMacSystemFont,
                            'Segoe UI', Roboto, sans-serif;
                        font-size: 16px;
                        font-weight: 500;
                        text-align: center;
                        z-index: 999999;
                        box-shadow: 0 4px 12px rgba(0,0,0,0.3);
                    `;
                    document.body.prepend(banner);
                    document.body.style.marginTop = '60px';

                    const style = document.createElement('style');
                    style.textContent = (
                        '@keyframes pulse {{ 0%, 100% {{ opacity: 1; }} '
                        '50% {{ opacity: 0.5; }} }}'
                    );
                    document.head.appendChild(style);
                }}
                banner.innerHTML = '{indicator} ' + `{message}`;
                if ({str(is_waiting).lower()}) {{
                    banner.style.animation = 'pulse 1.5s infinite';
                }} else {{
                    banner.style.animation = 'none';
                }}
            }}
        """
        )
    except Exception as e:
        logger.debug("Could not inject status banner", error=str(e))
