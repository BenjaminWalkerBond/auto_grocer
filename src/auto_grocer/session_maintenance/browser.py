"""Start/stop a nodriver Browser for the auto_grocer prototype.

nodriver auto-detects the installed Chrome/Chromium, so there is no chromedriver
binary and no version pin (the old code forced ``uc.Chrome(version_main=116)``).
"""
from __future__ import annotations

import json
import os
import tempfile

import nodriver

# Browser flags that reduce popups/notifications and silence Chrome's update
# banner. Password-manager prefs are seeded via a profile (see below) since
# nodriver takes a user-data dir rather than experimental prefs options.
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
    user_data_dir = tempfile.mkdtemp(prefix="auto_grocer_nodriver_")
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

    Environment overrides (used by the Docker image):
        NODRIVER_BROWSER_PATH / CHROME_BIN  - explicit Chrome/Chromium binary.
        AUTO_GROCER_NO_SANDBOX=1           - add --no-sandbox (required when
                                              running as root inside a container).
    """
    args = list(DEFAULT_BROWSER_ARGS)

    # Containers run as root, where Chrome's sandbox refuses to start; disable it
    # when explicitly requested.
    if os.environ.get("AUTO_GROCER_NO_SANDBOX", "").lower() in ("1", "true", "yes"):
        args += ["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"]

    if extra_args:
        args.extend(extra_args)

    # Allow pinning the browser binary (the Docker image installs Chromium at a
    # known path); otherwise let nodriver auto-detect the installed browser.
    browser_path = (
        os.environ.get("NODRIVER_BROWSER_PATH")
        or os.environ.get("CHROME_BIN")
        or None
    )

    browser = await nodriver.start(
        headless=headless,
        browser_args=args,
        user_data_dir=_make_profile_with_prefs(),
        browser_executable_path=browser_path,
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
