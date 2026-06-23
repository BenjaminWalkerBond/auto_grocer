"""Refresh the exported HEB session (auth.json) used by the MCP server.

Runs the existing self-healing Selenium login from main.py, then exports the
authenticated browser session (cookies + reese84 token) to
~/.texas-grocery-mcp/auth.json via export_selenium_session_to_authjson.

This does NOT touch the cart, reserve timeslots, or change the store. It only
re-authenticates so the GraphQL MCP tools stop reporting NOT_AUTHENTICATED.

Usage:
    python scripts/refresh_authjson.py [STORE_ID]
"""
import os
import sys
import signal

import undetected_chromedriver as uc

# Ensure the project root (parent of this scripts/ dir) is importable so
# `import main` works regardless of the current working directory.
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

# Reuse all of main.py's helpers + module globals (importing does NOT run the
# __main__ block, so no browser is launched on import).
import main


def _build_driver():
    """Create a Chrome driver using the same options as main.py."""
    options = uc.ChromeOptions()
    prefs = {
        "credentials_enable_service": False,
        "profile.password_manager_enabled": False,
    }
    options.add_experimental_option("prefs", prefs)
    options.add_argument("--disable-notifications")
    options.add_argument("--disable-popup-blocking")
    options.add_argument("--no-first-run")
    options.add_argument("--no-service-autorun")
    options.add_argument("--password-store=basic")
    options.add_argument("--disable-component-update")
    options.add_argument("--disable-background-networking")
    options.add_argument("--disable-features=ChromeWhatsNewUI,UpgradeDetector")

    original_sigint = signal.getsignal(signal.SIGINT)
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    driver = uc.Chrome(version_main=116, options=options, use_subprocess=False)
    signal.signal(signal.SIGINT, original_sigint)
    return driver


def main_refresh(store_id):
    print("\n" + "=" * 60)
    print("🔐 REFRESHING HEB SESSION (auth.json) — login + export only")
    print("=" * 60)

    print("🌐 Starting browser...")
    driver = _build_driver()
    try:
        # Reuse the existing self-healing Selenium login.
        main.self_healing_call(main.login, driver, driver=driver)
        main.random_time()
        try:
            driver.maximize_window()
        except Exception:
            pass
        main.dismiss_modals(driver)

        print("\n🔐 Exporting browser session for the GraphQL/MCP client...")
        main.export_selenium_session_to_authjson(driver, store_id=store_id)
        print("✅ Session exported. The MCP server can now refresh_session.")
    finally:
        try:
            driver.quit()
        except Exception:
            pass


if __name__ == "__main__":
    store = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("STORE_ID", "243")
    main_refresh(str(store))
