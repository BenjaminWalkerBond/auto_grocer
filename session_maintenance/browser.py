"""Start/stop a nodriver Browser for the auto_grocier prototype.

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
    # Without these WebGL is simply absent (renderer reports NO_WEBGL), which is
    # a strong bot signal - real browsers always have a renderer. Software ANGLE
    # gives us a working WebGL context on machines with no usable GPU (Xvfb in
    # Docker, WSLg on Windows).
    "--use-gl=angle",
    "--use-angle=swiftshader",
    "--enable-unsafe-swiftshader",
    "--disable-features=ChromeWhatsNewUI,UpgradeDetector,"
    "PasswordManagerOnboarding,AutofillServerCommunication",
]

# Persistent profile location. HEB sits behind Imperva, which decides whether to
# challenge a client largely on accumulated trust (the reese84 token, cookies,
# history). A throwaway profile per run means re-earning that trust every single
# time, and being blocked whenever the bar is raised. Inside Docker this path is
# the mounted auto_grocier_session volume, so it survives `--rm` for free.
DEFAULT_PROFILE_DIR = "~/.texas-grocery-mcp/chrome_profile"


def _resolve_profile_dir():
    """Return (user_data_dir, is_ephemeral) for the browser profile.

    AUTO_GROCIER_CHROME_PROFILE:
      unset      -> persistent default (recommended)
      "temp"     -> throwaway dir, the old behaviour (use for a clean-room run)
      any path   -> use that directory
    """
    override = os.environ.get("AUTO_GROCIER_CHROME_PROFILE", "").strip()
    if override.lower() in ("temp", "tmp", "ephemeral"):
        return tempfile.mkdtemp(prefix="auto_grocier_nodriver_"), True
    if override:
        return os.path.expanduser(override), False
    return os.path.expanduser(DEFAULT_PROFILE_DIR), False


def _make_profile_with_prefs():
    """Return the Chrome user-data dir, seeding password/autofill prefs.

    Those are profile *preferences* (not command-line flags), which the old
    Selenium code set via ``add_experimental_option('prefs', ...)``. nodriver
    takes a ``user_data_dir`` instead, so we write a Default/Preferences file.

    The prefs are only written when the profile is new: rewriting them on every
    launch would discard the state Chrome accumulates there, which is the whole
    point of keeping the profile around.
    """
    user_data_dir, ephemeral = _resolve_profile_dir()
    default_dir = os.path.join(user_data_dir, "Default")
    os.makedirs(default_dir, exist_ok=True)

    prefs_path = os.path.join(default_dir, "Preferences")
    if not ephemeral and os.path.exists(prefs_path):
        return user_data_dir

    prefs = {
        "credentials_enable_service": False,
        "profile": {
            "password_manager_enabled": False,
            "password_manager_leak_detection": False,
        },
        "autofill": {"credit_card_enabled": False, "profile_enabled": False},
    }
    with open(prefs_path, "w", encoding="utf-8") as f:
        json.dump(prefs, f)

    return user_data_dir
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
        AUTO_GROCIER_NO_SANDBOX=1           - add --no-sandbox (required when
                                              running as root inside a container).
    """
    args = list(DEFAULT_BROWSER_ARGS)

    # Containers run as root, where Chrome's sandbox refuses to start; disable it
    # when explicitly requested. Note --disable-gpu is deliberately NOT added:
    # it removes the WebGL context entirely, and software ANGLE (above) is what
    # keeps the fingerprint looking like a real browser.
    if os.environ.get("AUTO_GROCIER_NO_SANDBOX", "").lower() in ("1", "true", "yes"):
        args += ["--no-sandbox", "--disable-dev-shm-usage"]

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
