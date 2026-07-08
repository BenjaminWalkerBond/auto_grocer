"""Tests for session refresh tool and session freshness checking."""

import json
import time

import pytest


@pytest.fixture
def mock_auth_path(tmp_path, monkeypatch):
    """Create a temporary auth file path."""
    auth_file = tmp_path / "auth.json"

    # Mock get_settings to return our temp path
    class MockSettings:
        auth_state_path = auth_file

    def mock_get_settings():
        return MockSettings()

    monkeypatch.setattr(
        "texas_grocery_mcp.auth.session.get_settings",
        mock_get_settings,
    )
    monkeypatch.setattr(
        "texas_grocery_mcp.tools.session.get_settings",
        mock_get_settings,
    )

    return auth_file


@pytest.fixture
def valid_session_cookies():
    """Create valid session cookies with plenty of time remaining."""
    future_time = time.time() + 86400  # 24 hours from now
    return {
        "cookies": [
            {
                "name": "sat",
                "value": "test-token",
                "domain": "www.heb.com",
                "path": "/",
                "expires": future_time,
                "httpOnly": True,
                "secure": True,
                "sameSite": "Lax",
            },
            {
                "name": "DYN_USER_ID",
                "value": "12345678",
                "domain": "www.heb.com",
                "path": "/",
                "expires": future_time,
                "httpOnly": True,
                "secure": True,
                "sameSite": "Lax",
            },
            {
                "name": "reese84",
                "value": "test-reese84-token",
                "domain": ".heb.com",
                "path": "/",
                "expires": future_time,
                "httpOnly": False,
                "secure": True,
                "sameSite": "None",
            },
        ],
        "origins": [
            {
                "origin": "https://www.heb.com",
                "localStorage": [
                    {
                        "name": "reese84",
                        "value": json.dumps({
                            "renewTime": (time.time() + 18000) * 1000,  # 5 hours from now (ms)
                            "renewInSec": 850,
                        }),
                    }
                ],
            }
        ],
    }


@pytest.fixture
def expiring_soon_session_cookies():
    """Create session cookies with token expiring within 4 hours."""
    future_time = time.time() + 86400  # 24 hours from now
    return {
        "cookies": [
            {
                "name": "sat",
                "value": "test-token",
                "domain": "www.heb.com",
                "path": "/",
                "expires": future_time,
            },
            {
                "name": "DYN_USER_ID",
                "value": "12345678",
                "domain": "www.heb.com",
                "path": "/",
                "expires": future_time,
            },
        ],
        "origins": [
            {
                "origin": "https://www.heb.com",
                "localStorage": [
                    {
                        "name": "reese84",
                        # 2 hours from now (< 4h threshold)
                        "value": json.dumps(
                            {
                                "renewTime": (time.time() + 7200) * 1000,
                                "renewInSec": 850,
                            }
                        ),
                    }
                ],
            }
        ],
    }


@pytest.fixture
def expired_session_cookies():
    """Create session with expired reese84 token."""
    future_time = time.time() + 86400  # 24 hours from now
    past_time = time.time() - 3600  # 1 hour ago
    return {
        "cookies": [
            {
                "name": "sat",
                "value": "test-token",
                "domain": "www.heb.com",
                "path": "/",
                "expires": future_time,
            },
            {
                "name": "DYN_USER_ID",
                "value": "12345678",
                "domain": "www.heb.com",
                "path": "/",
                "expires": future_time,
            },
        ],
        "origins": [
            {
                "origin": "https://www.heb.com",
                "localStorage": [
                    {
                        "name": "reese84",
                        "value": json.dumps({
                            "renewTime": past_time * 1000,  # Expired
                        }),
                    }
                ],
            }
        ],
    }


@pytest.fixture
def stale_session_cookies():
    """Create session with stale reese84 token (cookie-based, no localStorage)."""
    future_time = time.time() + 86400  # 24 hours from now
    past_time = time.time() - 3600  # 1 hour ago
    return {
        "cookies": [
            {
                "name": "sat",
                "value": "test-token",
                "domain": "www.heb.com",
                "path": "/",
                "expires": future_time,
                "httpOnly": True,
                "secure": True,
                "sameSite": "Lax",
            },
            {
                "name": "DYN_USER_ID",
                "value": "12345678",
                "domain": "www.heb.com",
                "path": "/",
                "expires": future_time,
                "httpOnly": True,
                "secure": True,
                "sameSite": "Lax",
            },
            {
                "name": "reese84",
                "value": "test-reese84-token",
                "domain": ".heb.com",
                "path": "/",
                "expires": past_time,  # Expired
                "httpOnly": False,
                "secure": True,
                "sameSite": "None",
            },
        ],
        "origins": [],
    }


# =============================================================================
# get_session_status() tests
# =============================================================================


def test_get_session_status_no_auth_file(mock_auth_path):
    """get_session_status should indicate no auth when file missing."""
    from texas_grocery_mcp.auth.session import get_session_status

    result = get_session_status()

    assert result["authenticated"] is False
    assert result["needs_refresh"] is True
    assert result["refresh_recommended"] is True
    assert result["time_remaining_hours"] is None
    assert "No auth file" in result["message"]


def test_get_session_status_valid_session(mock_auth_path, valid_session_cookies):
    """get_session_status should show healthy session with time remaining."""
    from texas_grocery_mcp.auth.session import get_session_status

    mock_auth_path.write_text(json.dumps(valid_session_cookies))

    result = get_session_status()

    assert result["authenticated"] is True
    assert result["needs_refresh"] is False
    assert result["refresh_recommended"] is False  # > 4 hours remaining
    assert result["time_remaining_hours"] is not None
    assert result["time_remaining_hours"] > 4
    assert result["expires_at"] is not None
    assert result["reese84_present"] is True
    assert "healthy" in result["message"].lower()


def test_get_session_status_refresh_recommended(mock_auth_path, expiring_soon_session_cookies):
    """get_session_status should recommend refresh when < 4 hours remaining."""
    from texas_grocery_mcp.auth.session import get_session_status

    mock_auth_path.write_text(json.dumps(expiring_soon_session_cookies))

    result = get_session_status()

    assert result["authenticated"] is True
    assert result["needs_refresh"] is False
    assert result["refresh_recommended"] is True  # < 4 hours remaining
    assert result["time_remaining_hours"] is not None
    assert result["time_remaining_hours"] < 4
    assert "expiring soon" in result["message"].lower() or "consider" in result["message"].lower()


def test_get_session_status_expired(mock_auth_path, expired_session_cookies):
    """get_session_status should detect expired session."""
    from texas_grocery_mcp.auth.session import get_session_status

    mock_auth_path.write_text(json.dumps(expired_session_cookies))

    result = get_session_status()

    assert result["authenticated"] is False
    assert result["needs_refresh"] is True
    assert result["refresh_recommended"] is True
    assert "expired" in result["message"].lower() or "refresh" in result["message"].lower()


def test_get_session_status_missing_reese84(mock_auth_path):
    """get_session_status should detect missing reese84 token."""
    from texas_grocery_mcp.auth.session import get_session_status

    # Session without reese84
    cookies = {
        "cookies": [
            {
                "name": "sat",
                "value": "test",
                "domain": "www.heb.com",
                "expires": time.time() + 3600,
            }
        ],
        "origins": [],
    }
    mock_auth_path.write_text(json.dumps(cookies))

    result = get_session_status()

    assert result["reese84_present"] is False
    assert result["needs_refresh"] is True
    assert "reese84" in result["message"].lower()


def test_get_session_status_corrupted_file(mock_auth_path):
    """get_session_status should handle corrupted auth file."""
    from texas_grocery_mcp.auth.session import get_session_status

    mock_auth_path.write_text("not valid json {{{")

    result = get_session_status()

    assert result["authenticated"] is False
    assert result["needs_refresh"] is True
    assert "corrupted" in result["message"].lower()


# =============================================================================
# session_status() tool tests
# =============================================================================


@pytest.mark.asyncio
async def test_session_status_no_auth_file(mock_auth_path):
    """session_status tool should indicate no auth when file missing."""
    from texas_grocery_mcp.tools.session import session_status

    result = await session_status()

    assert result["authenticated"] is False
    assert result["needs_refresh"] is True
    assert "No auth file" in result["message"]


@pytest.mark.asyncio
async def test_session_status_valid_session(mock_auth_path, valid_session_cookies):
    """session_status tool should show healthy session with time remaining."""
    from texas_grocery_mcp.tools.session import session_status

    mock_auth_path.write_text(json.dumps(valid_session_cookies))

    result = await session_status()

    assert result["authenticated"] is True
    assert result["needs_refresh"] is False
    assert result["time_remaining_hours"] is not None
    assert result["time_remaining_hours"] > 0
    assert result["expires_at"] is not None
    assert "auth_path" in result


@pytest.mark.asyncio
async def test_session_status_refresh_recommended(mock_auth_path, expiring_soon_session_cookies):
    """session_status tool should recommend refresh when < 4 hours remaining."""
    from texas_grocery_mcp.tools.session import session_status

    mock_auth_path.write_text(json.dumps(expiring_soon_session_cookies))

    result = await session_status()

    assert result["refresh_recommended"] is True
    assert result["time_remaining_hours"] < 4


# =============================================================================
# session_refresh() tool tests
# =============================================================================


@pytest.fixture
def mock_no_playwright(monkeypatch):
    """Mock Playwright as unavailable to test fallback behavior."""
    monkeypatch.setattr(
        "texas_grocery_mcp.tools.session.is_playwright_available",
        lambda: False,
    )


@pytest.mark.asyncio
async def test_session_refresh_returns_commands_when_no_playwright(
    mock_auth_path,
    mock_no_playwright,
):
    """session_refresh should return structured Playwright commands when browser not available."""
    from texas_grocery_mcp.tools.session import session_refresh

    result = await session_refresh()

    assert "commands" in result
    assert len(result["commands"]) == 3

    # Check command structure
    commands = result["commands"]
    assert commands[0]["tool"] == "browser_navigate"
    assert commands[0]["parameters"]["url"] == "https://www.heb.com"

    assert commands[1]["tool"] == "browser_wait_for"
    assert commands[1]["parameters"]["time"] == 5

    assert commands[2]["tool"] == "browser_run_code"
    assert "code" in commands[2]["parameters"]

    # Each command should have parameters and description
    for cmd in commands:
        assert "parameters" in cmd
        assert "description" in cmd


@pytest.mark.asyncio
async def test_session_refresh_includes_auth_path(mock_auth_path, mock_no_playwright):
    """session_refresh should include the auth file path."""
    from texas_grocery_mcp.tools.session import session_refresh

    result = await session_refresh()

    assert "auth_path" in result
    # Path should be expanded (no ~)
    assert "~" not in result["auth_path"]


@pytest.mark.asyncio
async def test_session_refresh_includes_current_status(
    mock_auth_path,
    mock_no_playwright,
    valid_session_cookies,
):
    """session_refresh should include current session status."""
    from texas_grocery_mcp.tools.session import session_refresh

    mock_auth_path.write_text(json.dumps(valid_session_cookies))

    result = await session_refresh()

    assert "current_status" in result
    assert "authenticated" in result["current_status"]
    assert "needs_refresh" in result["current_status"]


@pytest.mark.asyncio
async def test_session_refresh_includes_troubleshooting(mock_auth_path, mock_no_playwright):
    """session_refresh should include troubleshooting tips."""
    from texas_grocery_mcp.tools.session import session_refresh

    result = await session_refresh()

    assert "troubleshooting" in result
    assert "no_playwright" in result["troubleshooting"]
    assert "still_failing" in result["troubleshooting"]
    assert "login_required" in result["troubleshooting"]


@pytest.mark.asyncio
async def test_session_refresh_code_saves_to_correct_path(mock_auth_path, mock_no_playwright):
    """session_refresh code should save to the correct auth path."""
    from texas_grocery_mcp.tools.session import session_refresh

    result = await session_refresh()

    # The JavaScript code in the third command should reference the auth path
    code = result["commands"][2]["parameters"]["code"]
    assert str(mock_auth_path) in code or result["auth_path"] in code


# =============================================================================
# session_clear() tests
# =============================================================================


def test_session_clear_removes_file(mock_auth_path, valid_session_cookies):
    """session_clear should remove auth file."""
    from texas_grocery_mcp.tools.session import session_clear

    mock_auth_path.write_text(json.dumps(valid_session_cookies))
    assert mock_auth_path.exists()

    result = session_clear()

    assert result["success"] is True
    assert not mock_auth_path.exists()
    assert "cleared_path" in result


def test_session_clear_handles_missing_file(mock_auth_path):
    """session_clear should handle missing file gracefully."""
    from texas_grocery_mcp.tools.session import session_clear

    result = session_clear()

    assert result["success"] is True
    assert "No session file" in result["message"]


# =============================================================================
# Legacy tests for check_session_freshness and get_reese84_info
# =============================================================================


def test_check_session_freshness_with_valid_localstorage(mock_auth_path, valid_session_cookies):
    """check_session_freshness should check localStorage renewTime."""
    from texas_grocery_mcp.auth.session import check_session_freshness

    mock_auth_path.write_text(json.dumps(valid_session_cookies))

    result = check_session_freshness()

    assert result["needs_refresh"] is False
    assert result["bot_detection_status"] == "valid"


def test_get_reese84_info_from_localstorage(mock_auth_path):
    """get_reese84_info should extract from localStorage when no cookie."""
    from texas_grocery_mcp.auth.session import get_reese84_info

    future_time = time.time() + 86400
    cookies_with_reese84_in_localstorage = {
        "cookies": [
            {
                "name": "sat",
                "value": "test-token",
                "domain": "www.heb.com",
                "path": "/",
                "expires": future_time,
            },
            {
                "name": "DYN_USER_ID",
                "value": "12345678",
                "domain": "www.heb.com",
                "path": "/",
                "expires": future_time,
            },
        ],
        "origins": [
            {
                "origin": "https://www.heb.com",
                "localStorage": [
                    {
                        "name": "reese84",
                        "value": json.dumps({
                            "renewTime": (time.time() + 3600) * 1000,
                            "renewInSec": 850,
                        }),
                    }
                ],
            }
        ],
    }
    mock_auth_path.write_text(json.dumps(cookies_with_reese84_in_localstorage))

    result = get_reese84_info()

    assert result is not None
    assert result["source"] == "localStorage"
    assert "renew_time" in result


def test_get_reese84_info_from_cookie(mock_auth_path, stale_session_cookies):
    """get_reese84_info should fall back to cookie expires."""
    from texas_grocery_mcp.auth.session import get_reese84_info

    mock_auth_path.write_text(json.dumps(stale_session_cookies))

    result = get_reese84_info()

    assert result is not None
    assert result["source"] == "cookie"
    assert "expires" in result


def test_get_reese84_info_missing(mock_auth_path):
    """get_reese84_info should return None when no reese84 present."""
    from texas_grocery_mcp.auth.session import get_reese84_info

    cookies = {
        "cookies": [
            {
                "name": "sat",
                "value": "test",
                "domain": "www.heb.com",
                "path": "/",
                "expires": time.time() + 3600,
            }
        ],
        "origins": [],
    }
    mock_auth_path.write_text(json.dumps(cookies))

    result = get_reese84_info()

    assert result is None


# =============================================================================
# is_authenticated() tests - verifying reese84 token check
# =============================================================================


def test_is_authenticated_with_valid_session(mock_auth_path, valid_session_cookies):
    """is_authenticated should return True when both cookies and reese84 are valid."""
    from texas_grocery_mcp.auth.session import is_authenticated

    mock_auth_path.write_text(json.dumps(valid_session_cookies))

    assert is_authenticated() is True


def test_is_authenticated_with_expired_reese84(mock_auth_path, expired_session_cookies):
    """is_authenticated should return True on valid cookies even if reese84 expired.

    auto_grocier fork behavior: reese84 is NOT a hard gate. Its localStorage
    renewTime is only ~10 min, while the sat/sst session cookies last for weeks
    and are the real limiter. reese84 is auto-refreshed at runtime, so a valid
    cookie session is considered authenticated. (get_session_status still tracks
    reese84 lifecycle for diagnostics — see the divergence test below.)
    """
    from texas_grocery_mcp.auth.session import is_authenticated

    mock_auth_path.write_text(json.dumps(expired_session_cookies))

    assert is_authenticated() is True


def test_is_authenticated_with_missing_reese84(mock_auth_path):
    """is_authenticated should return True on valid cookies with no reese84.

    auto_grocier fork behavior: reese84 absence does not fail authentication;
    the sat/DYN_USER_ID session cookies drive validity.
    """
    from texas_grocery_mcp.auth.session import is_authenticated

    # Valid cookies but no reese84 in localStorage
    future_time = time.time() + 86400
    cookies_without_reese84 = {
        "cookies": [
            {
                "name": "sat",
                "value": "test-token",
                "domain": "www.heb.com",
                "path": "/",
                "expires": future_time,
            },
            {
                "name": "DYN_USER_ID",
                "value": "12345678",
                "domain": "www.heb.com",
                "path": "/",
                "expires": future_time,
            },
        ],
        "origins": [],  # No localStorage, so no reese84
    }
    mock_auth_path.write_text(json.dumps(cookies_without_reese84))

    assert is_authenticated() is True


def test_is_authenticated_with_no_auth_file(mock_auth_path):
    """is_authenticated should return False when auth file doesn't exist."""
    from texas_grocery_mcp.auth.session import is_authenticated

    # Don't create the auth file
    assert is_authenticated() is False


def test_is_authenticated_with_expired_cookies(mock_auth_path):
    """is_authenticated should return False when session cookies are expired."""
    from texas_grocery_mcp.auth.session import is_authenticated

    past_time = time.time() - 3600  # 1 hour ago
    expired_cookies = {
        "cookies": [
            {
                "name": "sat",
                "value": "test-token",
                "domain": "www.heb.com",
                "path": "/",
                "expires": past_time,  # Expired
            },
            {
                "name": "DYN_USER_ID",
                "value": "12345678",
                "domain": "www.heb.com",
                "path": "/",
                "expires": past_time,  # Expired
            },
        ],
        "origins": [
            {
                "origin": "https://www.heb.com",
                "localStorage": [
                    {
                        "name": "reese84",
                        "value": json.dumps({
                            "renewTime": (time.time() + 18000) * 1000,  # Valid reese84
                        }),
                    }
                ],
            }
        ],
    }
    mock_auth_path.write_text(json.dumps(expired_cookies))

    assert is_authenticated() is False


def test_is_authenticated_diverges_from_get_session_status_on_expired_reese84(
    mock_auth_path,
    expired_session_cookies,
):
    """In the auto_grocier fork, the two functions intentionally differ.

    Upstream tied both to reese84 so they always agreed. Our fork decouples them:
      * is_authenticated() -> "can I make authenticated calls?" -> cookie-based,
        so valid sat/sst cookies mean True even with an expired reese84.
      * get_session_status() -> a richer diagnostic that still tracks the reese84
        lifecycle, so it reports authenticated=False when reese84 is expired.
    """
    from texas_grocery_mcp.auth.session import get_session_status, is_authenticated

    mock_auth_path.write_text(json.dumps(expired_session_cookies))

    is_auth = is_authenticated()
    status = get_session_status()

    # Cookie-based auth passes; reese84-aware diagnostic flags a refresh.
    assert is_auth is True
    assert status["authenticated"] is False
    assert is_auth != status["authenticated"]


def test_is_authenticated_consistency_with_get_session_status_valid(
    mock_auth_path,
    valid_session_cookies,
):
    """is_authenticated and get_session_status should agree on valid sessions."""
    from texas_grocery_mcp.auth.session import get_session_status, is_authenticated

    mock_auth_path.write_text(json.dumps(valid_session_cookies))

    is_auth = is_authenticated()
    status = get_session_status()

    # Both should agree that the session IS authenticated
    assert is_auth == status["authenticated"]
    assert is_auth is True


# =============================================================================
# WAF/Security Challenge Detection Tests
# =============================================================================


class TestSecurityChallengeDetection:
    """Tests for _detect_security_challenge_html function.

    These tests ensure we don't get false positives on normal HEB pages.
    The bug was that "reese84" and "incapsula" were triggering WAF detection
    on normal pages because they appear in the page's JavaScript.
    """

    def test_normal_heb_homepage_not_detected_as_waf(self):
        """Normal HEB homepage should NOT be detected as WAF challenge."""
        from texas_grocery_mcp.auth.browser_refresh import _detect_security_challenge_html

        # Simulated normal HEB homepage HTML (simplified)
        normal_page_html = """
        <!DOCTYPE html>
        <html>
        <head>
            <title>H-E-B | Grocery, Pharmacy, Curbside Pickup & Delivery</title>
            <script src="https://www.heb.com/static/reese84.js"></script>
        </head>
        <body>
            <header data-testid="header">
                <nav>
                    <a href="/my-account">My Account</a>
                    <a href="/my-cart">My Cart</a>
                </nav>
            </header>
            <main>
                <h1>Welcome to HEB.com</h1>
                <section data-testid="products">
                    <div class="product">
                        <button>Add to Cart</button>
                    </div>
                </section>
                <a href="/curbside">Curbside Pickup</a>
                <a href="/delivery">Delivery</a>
            </main>
        </body>
        </html>
        """

        assert _detect_security_challenge_html(normal_page_html) is False

    def test_page_with_reese84_script_not_detected(self):
        """Page containing reese84 script should NOT be detected as WAF."""
        from texas_grocery_mcp.auth.browser_refresh import _detect_security_challenge_html

        html_with_reese84 = """
        <!DOCTYPE html>
        <html>
        <head>
            <title>HEB</title>
            <script>
                window.reese84 = {"token": "abc123", "renewTime": 1234567890};
            </script>
        </head>
        <body>
            <nav><a href="/my-cart">My Cart</a></nav>
            <main>
                <div data-testid="homepage">
                    <button>Add to Cart</button>
                    <a href="/delivery">Delivery</a>
                    <a href="/curbside">Curbside</a>
                </div>
            </main>
        </body>
        </html>
        """

        assert _detect_security_challenge_html(html_with_reese84) is False

    def test_page_with_incapsula_headers_not_detected(self):
        """Page with incapsula in headers should NOT be detected as WAF if it has content."""
        from texas_grocery_mcp.auth.browser_refresh import _detect_security_challenge_html

        html_with_incapsula = """
        <!DOCTYPE html>
        <html>
        <head>
            <title>HEB</title>
            <meta name="incapsula-cdn" content="true">
        </head>
        <body>
            <header><nav><a href="/my-account">My Account</a></nav></header>
            <main data-testid="content">
                <button>Add to Cart</button>
                <a href="/delivery">Delivery</a>
                <a href="/curbside">Curbside</a>
                <a href="/weekly-ad">Weekly Ad</a>
            </main>
        </body>
        </html>
        """

        assert _detect_security_challenge_html(html_with_incapsula) is False

    def test_real_waf_challenge_page_detected(self):
        """Actual WAF challenge interstitial should be detected."""
        from texas_grocery_mcp.auth.browser_refresh import _detect_security_challenge_html

        waf_challenge_html = """
        <!DOCTYPE html>
        <html>
        <head><title>Access Denied</title></head>
        <body>
            <h1>Please verify you are a human</h1>
            <p>Enable JavaScript and cookies to continue.</p>
        </body>
        </html>
        """

        assert _detect_security_challenge_html(waf_challenge_html) is True

    def test_cloudflare_challenge_detected(self):
        """Cloudflare-style challenge should be detected."""
        from texas_grocery_mcp.auth.browser_refresh import _detect_security_challenge_html

        cloudflare_html = """
        <!DOCTYPE html>
        <html>
        <head><title>Just a moment...</title></head>
        <body>
            <h1>Checking your browser before accessing the site</h1>
            <p>Please wait while we verify your browser...</p>
            <p>Ray ID: abc123xyz</p>
            <p>Performance & security by Cloudflare</p>
        </body>
        </html>
        """

        assert _detect_security_challenge_html(cloudflare_html) is True

    def test_blocked_page_detected(self):
        """'Sorry, you have been blocked' page should be detected."""
        from texas_grocery_mcp.auth.browser_refresh import _detect_security_challenge_html

        blocked_html = """
        <!DOCTYPE html>
        <html>
        <head><title>Blocked</title></head>
        <body>
            <h1>Sorry, you have been blocked</h1>
            <p>This website is using a security service to protect itself.</p>
            <p>Why have I been blocked?</p>
        </body>
        </html>
        """

        assert _detect_security_challenge_html(blocked_html) is True

    def test_minimal_incapsula_challenge_detected(self):
        """Minimal page with _incapsula_resource should be detected as challenge."""
        from texas_grocery_mcp.auth.browser_refresh import _detect_security_challenge_html

        # A small challenge page (< 5000 chars) with incapsula resource
        minimal_challenge = """
        <!DOCTYPE html>
        <html>
        <head>
            <script src="/_incapsula_resource?test=1"></script>
        </head>
        <body>
            <p>Loading...</p>
        </body>
        </html>
        """

        assert _detect_security_challenge_html(minimal_challenge) is True

    def test_large_page_with_incapsula_not_detected(self):
        """Large page (> 5000 chars) with incapsula should NOT be detected."""
        from texas_grocery_mcp.auth.browser_refresh import _detect_security_challenge_html

        # Create a large HTML page that includes _incapsula_resource but is clearly a real page
        large_page = """
        <!DOCTYPE html>
        <html>
        <head>
            <title>HEB Products</title>
            <script src="/_incapsula_resource?test=1"></script>
        </head>
        <body>
            <header><nav><a href="/my-account">My Account</a></nav></header>
            <main data-testid="products">
                <button>Add to Cart</button>
                <a href="/delivery">Delivery</a>
                <a href="/curbside">Curbside</a>
        """ + ("<!-- padding -->" * 500) + """
            </main>
        </body>
        </html>
        """

        assert len(large_page) > 5000  # Verify it's actually large
        assert _detect_security_challenge_html(large_page) is False
