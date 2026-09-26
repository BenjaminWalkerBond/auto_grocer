"""HEB cold-login + GraphQL hash capture + session export, on patchright.

Faithfully mirrors the nodriver login flow in
``auto_grocer.session_maintenance.flows.login`` (email -> Continue -> password ->
submit -> email OTP -> dismiss passkey), but expressed in patchright's
Playwright-compatible API. Reuses the project's pure helpers for settings, email
OTP retrieval, GraphQL hash parsing/saving, and reese84 validation so the spike
measures the *browser engine*, not a reimplemented pipeline.
"""
from __future__ import annotations

import asyncio
import json
import random
from pathlib import Path

from auto_grocer.claude import get_setting
from auto_grocer.utility.graphql_auth import DEFAULT_AUTH_PATH, validate_reese84
from auto_grocer.utility.graphql_hash_capture import (
    TARGET_OPERATIONS,
    _parse_operation_samples,
    save_hashes,
    save_operation_samples,
)
from auto_grocer.utility.read_email import fetch_verification_code

HEB_HOME = "https://www.heb.com/"

# Substrings that mean HEB is asking us to verify (email OTP challenge).
_VERIFY_MARKERS = (
    "Choose a way to verify",
    "Verify it's you",
    "Enter verification code",
)


async def _settle(lo: float = 1.5, hi: float = 3.0) -> None:
    """Randomised human-ish pause between steps."""
    await asyncio.sleep(random.uniform(lo, hi))


async def _click_text(page, *candidates, timeout: int = 6000) -> bool:
    """Click the first button/role/text locator that resolves. Best-effort."""
    for how in candidates:
        try:
            if how[0] == "role":
                loc = page.get_by_role("button", name=how[1]).first
            else:  # css
                loc = page.locator(how[1]).first
            await loc.click(timeout=timeout)
            return True
        except Exception:  # noqa: BLE001
            continue
    return False


async def _otp_boxes(page):
    """Return a list of the six OTP input locators, or [] if not present.

    Mirrors flows._find_otp_inputs: legacy ``code_input_N`` names first, then a
    structural fallback on single-char / numeric inputs, excluding the hidden
    ``otpCode``/``requestId`` helper inputs.
    """
    named = [page.locator(f'input[name="code_input_{i}"]') for i in range(1, 7)]
    counts = [await loc.count() for loc in named]
    if all(c >= 1 for c in counts):
        return [loc.first for loc in named]

    for sel in (
        'input[maxlength="1"]:not([name="otpCode"]):not([name="requestId"])',
        'input[inputmode="numeric"]:not([name="otpCode"]):not([name="requestId"])',
    ):
        loc = page.locator(sel)
        n = await loc.count()
        if n >= 6:
            return [loc.nth(i) for i in range(6)]
    return []


async def _handle_verification(page) -> str:
    """Complete an email-OTP challenge if one is present. Returns a status label."""
    challenged = False
    for _ in range(20):
        content = await page.content()
        if any(m in content for m in _VERIFY_MARKERS) or await page.locator(
            'input[name="channel"], input[name="otpCode"], input[name="code_input_1"]'
        ).count():
            challenged = True
            break
        if "accounts.heb.com" not in page.url and "/login" not in page.url:
            return "no_challenge"  # recognised device
        await asyncio.sleep(1)

    if not challenged:
        return "no_challenge"

    # Channel-selection screen (pick email + Send code), or straight to code entry.
    content = await page.content()
    if "Choose a way to verify" in content or await page.locator('input[name="channel"]').count():
        try:
            await page.locator('input[name="channel"][value="email"]').first.click(timeout=5000)
        except Exception:  # noqa: BLE001
            pass
        await _settle()
        await _click_text(page, ("role", "Send code"), ("css", 'button:has-text("Send code")'))
        await _settle()

    # Wait for the code boxes to render.
    boxes = []
    for _ in range(15):
        boxes = await _otp_boxes(page)
        if boxes:
            break
        await asyncio.sleep(1)

    code = await asyncio.to_thread(fetch_verification_code)
    digits = [c for c in (code or "") if c.isdigit()][:6]
    if len(digits) < 6:
        return "otp_code_missing"

    if boxes and len(boxes) >= len(digits):
        for box, digit in zip(boxes, digits):
            try:
                await box.fill(digit)
                await asyncio.sleep(0.1)
            except Exception:  # noqa: BLE001
                continue
    else:
        # Segmented component that auto-advances: type the whole code into input 0.
        target = boxes[0] if boxes else page.locator("input").first
        try:
            await target.fill("".join(digits))
        except Exception:  # noqa: BLE001
            pass

    await _settle()
    await _click_text(page, ("role", "Verify"), ("css", 'button:has-text("Verify")'))
    await _settle()
    return "otp_entered"


async def login(page) -> dict:
    """Run a full HEB cold login. Returns a status dict (never raises)."""
    email = get_setting("EMAIL", "")
    password = get_setting("PASSWORD", "")
    if not email or not password:
        return {"ok": False, "stage": "config", "detail": "EMAIL/PASSWORD not set in .env"}

    try:
        await page.goto(HEB_HOME, wait_until="load", timeout=45000)
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "stage": "homepage", "detail": f"{type(e).__name__}: {e}"}
    await _settle()

    # Trigger the login panel via the cart button.
    try:
        await page.locator('a[data-qe-id="headerCartButtonDesktop"]').first.click(timeout=15000)
    except Exception:  # noqa: BLE001
        pass
    await _settle()

    try:
        await page.locator('input[type="email"]').first.fill(email, timeout=15000)
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "stage": "email", "detail": f"{type(e).__name__}: {e}"}
    await _settle()

    await _click_text(page, ("role", "Continue"), ("css", 'button:has-text("Continue")'))
    await _settle()

    # Choose "Enter password".
    try:
        await page.locator("#credentials").first.click(timeout=5000)
    except Exception:  # noqa: BLE001
        await _click_text(page, ("css", 'label[for="credentials"]'))
    await _settle()

    try:
        pwd = page.locator("#password-input")
        if not await pwd.count():
            pwd = page.locator('input[type="password"]')
        await pwd.first.fill(password, timeout=8000)
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "stage": "password", "detail": f"{type(e).__name__}: {e}"}
    await _settle()

    await _click_text(page, ("css", 'button[type="submit"]'))
    await _settle()

    verify_status = await _handle_verification(page)

    # Dismiss the passkey-registration interstitial if present.
    if "passkey_registration" in page.url:
        await _click_text(page, ("role", "Not now"), ("css", 'button:has-text("Not now")'))
        await _settle()

    return {"ok": True, "stage": "done", "verify": verify_status, "url": page.url}


def attach_hash_capturer(context) -> dict:
    """Subscribe to GraphQL POSTs on ``context`` and accumulate operations live.

    Returns the (mutating) ``operations`` dict: {name: {"hash", "variables"}}.
    """
    operations: dict = {}

    def _on_request(request):
        try:
            if request.method != "POST" or "/graphql" not in request.url:
                return
            post = request.post_data
            if not post:
                return
            for name, sha, variables, query in _parse_operation_samples(post):
                existing = operations.get(name) or {}
                if query is None:
                    query = existing.get("query")
                operations[name] = {"hash": sha, "variables": variables, "query": query}
        except Exception:  # noqa: BLE001 - never let a handler crash navigation
            return

    context.on("request", _on_request)
    return operations


async def exercise_for_hashes(page) -> None:
    """Drive a homepage search to trigger the common GraphQL operations."""
    try:
        await page.goto(HEB_HOME, wait_until="load", timeout=30000)
        await _settle()
        search = page.locator('input[data-qe-id="headerSearchInput"]').first
        await search.fill("milk", timeout=10000)
        await search.press("Enter")
        await page.locator('[data-qe-id="productCard"]').first.wait_for(timeout=15000)
    except Exception:  # noqa: BLE001
        pass
    await _settle()


def save_captured(operations: dict, hashes_path=None, samples_path=None):
    """Persist captured hashes + samples. Returns (hashes_path, samples_path).

    Pass explicit paths to avoid clobbering the production
    ``persisted_queries.json`` / ``captured_operations.json`` (the spike defaults
    to NOT writing these at all).
    """
    hashes = {name: op["hash"] for name, op in operations.items() if op.get("hash")}
    if not hashes:
        return None, None
    return save_hashes(hashes, hashes_path), save_operation_samples(operations, samples_path)


async def export_and_validate(context, auth_path=None) -> dict:
    """Write ``auth.json`` (native Playwright storage_state) and validate reese84."""
    auth_path = Path(auth_path).expanduser() if auth_path else DEFAULT_AUTH_PATH
    auth_path.parent.mkdir(parents=True, exist_ok=True)
    await context.storage_state(path=str(auth_path))

    with open(auth_path, encoding="utf-8") as f:
        state = json.load(f)

    reese84 = None
    for origin in state.get("origins", []):
        for item in origin.get("localStorage", []):
            if item.get("name") == "reese84":
                reese84 = item.get("value")
                break
        if reese84:
            break

    cookie_names = {c.get("name") for c in state.get("cookies", [])}
    return {
        "auth_path": str(auth_path),
        "authenticated": bool({"sat", "DYN_USER_ID"} & cookie_names),
        "cookie_count": len(state.get("cookies", [])),
        "reese84": validate_reese84(reese84),
    }


def target_hits(operations: dict) -> list[str]:
    """Return which TARGET_OPERATIONS were captured."""
    return sorted(set(operations) & TARGET_OPERATIONS)
