"""Launch a patched (patchright) Chromium context for the HEB stealth spike.

Mirrors the env contract of ``auto_grocer.session_maintenance.browser`` so it
drops into the existing Docker image unchanged:

    NODRIVER_BROWSER_PATH / CHROME_BIN  - explicit Chromium/Chrome binary.
    AUTO_GROCER_NO_SANDBOX=1            - add --no-sandbox (root in a container).
    AUTO_GROCER_HEADLESS=1             - run headless (default: headed).
    PATCHRIGHT_CHANNEL=chrome          - use real Chrome channel (best stealth).

Patchright's strongest stealth is a **real headed browser** (its "completely
undetected" config uses ``headless=False, no_viewport=True`` and NO injected
user_agent/headers). In Docker that means headed Chromium under Xvfb — exactly
how the nodriver path already runs — so the default here is headed.
"""
from __future__ import annotations

import json
import os
import tempfile


def _is_true(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes")


async def start_context(playwright, headless: bool | None = None):
    """Launch a persistent patchright context and return ``(context, page)``.

    Uses ``launch_persistent_context`` (patchright's recommended, most-stealthy
    entry point). Deliberately sets no custom ``user_agent`` or extra headers —
    fingerprint injection defeats the patches.
    """
    if headless is None:
        headless = _is_true("AUTO_GROCER_HEADLESS")

    args: list[str] = []
    if _is_true("AUTO_GROCER_NO_SANDBOX"):
        args += ["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"]

    executable_path = (
        os.environ.get("NODRIVER_BROWSER_PATH") or os.environ.get("CHROME_BIN") or None
    )
    channel = os.environ.get("PATCHRIGHT_CHANNEL") or None  # e.g. "chrome"

    user_data_dir = tempfile.mkdtemp(prefix="patchright_spike_")

    context = await playwright.chromium.launch_persistent_context(
        user_data_dir=user_data_dir,
        channel=channel,
        headless=headless,
        no_viewport=True,
        args=args,
        executable_path=executable_path,
    )
    page = context.pages[0] if context.pages else await context.new_page()
    return context, page


async def seed_cookies(context, storage_state_path) -> int:
    """Seed a context's cookies from a Playwright storage-state file.

    Lets a hash-only run reuse an existing session instead of logging in again
    (``launch_persistent_context`` can't take ``storage_state`` directly).
    Returns the number of cookies added.
    """
    try:
        with open(storage_state_path, encoding="utf-8") as f:
            state = json.load(f)
    except (OSError, json.JSONDecodeError):
        return 0

    cookies = state.get("cookies", []) or []
    if not cookies:
        return 0
    await context.add_cookies(cookies)
    return len(cookies)
