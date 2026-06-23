"""Start/stop a nodriver Browser for the auto_grocier prototype.

nodriver auto-detects the installed Chrome/Chromium, so there is no chromedriver
binary and no version pin (the old code forced ``uc.Chrome(version_main=116)``).
"""
from __future__ import annotations

import os
import json
import tempfile

import nodriver


# Browser flags mirroring the old undetected_chromedriver options that reduce
# popups/notifications and silence Chrome's update banner. Password-manager
# prefs (an experimental option in Selenium) are approximated with flags.
DEFAULT_BROWSER_ARGS = [
    "--disable-notifications",
    "--disable-popup-blocking",
    "--no-first-run",
    "--no-service-autorun",
    "--password-store=basic",
    "--disable-component-update",
    "--disable-background-networking",
    "--disable-features=ChromeWhatsNewUI,UpgradeDetector,"
    "PasswordManagerOnboarding,AutofillServerCommunication",
]


def _make_profile_with_prefs():
    """Create a fresh user-data dir seeded with prefs that disable the Chrome
    "Save password?" bubble + autofill prompts.

    Those are profile *preferences* (not command-line flags), which the old
    Selenium code set via ``add_experimental_option('prefs', ...)``. nodriver
    takes a ``user_data_dir`` instead, so we write a Default/Preferences file.

    Returns the path to the user-data directory.
    """
    user_data_dir = tempfile.mkdtemp(prefix="auto_grocier_nodriver_")
    default_dir = os.path.join(user_data_dir, "Default")
    os.makedirs(default_dir, exist_ok=True)

    prefs = {
        "credentials_enable_service": False,
        "profile": {
            "password_manager_enabled": False,
            "password_manager_leak_detection": False,
        },
        "autofill": {"credit_card_enabled": False, "profile_enabled": False},
    }
    with open(os.path.join(default_dir, "Preferences"), "w", encoding="utf-8") as f:
        json.dump(prefs, f)

    return user_data_dir


async def start_browser(headless: bool = False, extra_args=None):
    """Launch a nodriver Browser and return it.

    Args:
        headless: Run without a visible window. On a headless host use Xvfb or
            set this True. Defaults to False (matches the old visible flow).
        extra_args: Optional list of additional Chrome flags.

    Returns:
        nodriver.Browser
    """
    args = list(DEFAULT_BROWSER_ARGS)
    if extra_args:
        args.extend(extra_args)

    browser = await nodriver.start(
        headless=headless,
        browser_args=args,
        user_data_dir=_make_profile_with_prefs(),
    )
    return browser


async def stop_browser(browser):
    """Stop the browser, ignoring shutdown errors."""
    if browser is None:
        return
    try:
        browser.stop()
    except Exception:  # noqa: BLE001 - best-effort shutdown
        pass
