"""Async nodriver port of the HEB browser flows from main.py.

Each function takes a nodriver ``tab`` (and ``browser`` where cookies are
needed) instead of a Selenium driver. They are awaited by the mode dispatcher
in run.py, optionally wrapped by self_healing.self_healing_call.

Ported flows: login, clear_cart, reserve_time_slot (incl. the tiered-modal
Step 4.5 fix), change_store_via_ui, add_ingredient, checkout.
"""
from __future__ import annotations

import os
import asyncio
from urllib.parse import quote_plus

from claude import get_setting
from utility.read_email import fetch_verification_code

from grocery_browser.primitives import (
    random_time,
    human_like_delay,
    human_like_typing,
    scroll_to_element,
    attr,
    is_visible,
    is_enabled,
    click_element,
    js_click,
    select_one,
    select_all,
    xpath_all,
    select_first_of,
    check_exists_by_xpath,
    find_by_text,
    dismiss_modals,
)

HEB_HOME = "https://www.heb.com/"
HEB_CART = "https://www.heb.com/cart/"


async def _current_url(tab) -> str:
    try:
        return await tab.evaluate("location.href") or ""
    except Exception:  # noqa: BLE001
        return ""


async def _page_source(tab) -> str:
    try:
        return await tab.get_content() or ""
    except Exception:  # noqa: BLE001
        return ""


async def _click_first_xpath(tab, xpath) -> bool:
    """Click the first element matching an XPath. Returns True on success."""
    for el in await xpath_all(tab, xpath):
        try:
            await scroll_to_element(el)
            if await click_element(tab, el):
                return True
        except Exception:  # noqa: BLE001
            continue
    return False


# ---------------------------------------------------------------------------
# login
# ---------------------------------------------------------------------------
async def login(tab):
    """Log in to heb.com using EMAIL/PASSWORD from .env (async)."""
    print("🔐 Starting login process...")

    email_address = get_setting("EMAIL", "")
    password = get_setting("PASSWORD", "")
    if not email_address or not password:
        raise ValueError("EMAIL and PASSWORD must be set in your .env file")

    # STEP 1: home page
    print("  Step 1: Navigating to HEB home page...")
    await tab.get(HEB_HOME)
    await random_time()

    # STEP 2: click cart icon to trigger login
    print("  Step 2: Clicking cart icon to trigger login...")
    cart_button = await select_one(tab, 'a[data-qe-id="headerCartButtonDesktop"]', timeout=10)
    if cart_button:
        await click_element(tab, cart_button)
    await random_time()

    # STEP 3: enter email
    print("  Step 3: Entering email...")
    email_input = await select_one(tab, 'input[type="email"]', timeout=10)
    if email_input is None:
        raise Exception("Email input not found on login page")
    await email_input.send_keys(email_address)
    await random_time()

    # STEP 4: continue
    print("  Step 4: Clicking 'Continue' button...")
    if not await _click_first_xpath(tab, '//button[contains(., "Continue")]'):
        btn = await find_by_text(tab, "Continue")
        if btn:
            await click_element(tab, btn)
    await random_time()

    # STEP 5: choose "Enter password"
    print("  Step 5: Selecting 'Enter password' option...")
    radio = await select_one(tab, "#credentials", timeout=5)
    if radio:
        await click_element(tab, radio)
    else:
        await _click_first_xpath(tab, '//label[@for="credentials"]')
    await random_time()

    # STEP 6: enter password
    print("  Step 6: Entering password...")
    pwd = await select_one(tab, "#password-input", timeout=5)
    if pwd is None:
        pwd = await select_one(tab, 'input[type="password"]', timeout=5)
    if pwd is None:
        raise Exception("Password input not found")
    await pwd.send_keys(password)
    await random_time()

    # STEP 7: submit
    print("  Step 7: Clicking 'Submit' button...")
    submit = await select_one(tab, 'button[type="submit"]', timeout=5)
    if submit:
        await click_element(tab, submit)
    await random_time()

    # STEP 8: email verification, if required
    print("  Step 8: Checking for verification requirement...")
    page = await _page_source(tab)
    if "Choose a way to verify" in page or await check_exists_by_xpath(
        tab, '//input[@name="channel"]'
    ):
        print("  ⚠️  Verification required - selecting email option...")
        await _click_first_xpath(tab, '//input[@name="channel"][@value="email"]')
        await random_time()

        print("  📧 Clicking 'Send code' button...")
        if not await _click_first_xpath(
            tab, '//button[@type="submit" and contains(., "Send code")]'
        ):
            btn = await find_by_text(tab, "Send code")
            if btn:
                await click_element(tab, btn)
        await random_time()

        print("  ⏳ Waiting for verification code input fields...")
        await select_one(tab, 'input[name="code_input_1"]', timeout=15)

        print("  📨 Fetching verification code from email...")
        verification_code = await asyncio.to_thread(fetch_verification_code)
        print(f"  ✓ Got verification code: {verification_code}")

        if verification_code and len(verification_code) >= 6:
            print("  ⌨️  Entering verification code digits...")
            for i, digit in enumerate(verification_code[:6], start=1):
                field = await select_one(tab, f'input[name="code_input_{i}"]', timeout=5)
                if field:
                    await field.send_keys(digit)
            await random_time()
        else:
            print("  ⚠️  Verification code missing/short.")

        print("  ✅ Submitting verification code...")
        if not await _click_first_xpath(
            tab, '//button[@type="submit" and contains(., "Verify")]'
        ):
            btn = await find_by_text(tab, "Verify")
            if btn:
                await click_element(tab, btn)
        await random_time()

    # STEP 9: passkey registration prompt
    print("  Step 9: Checking for passkey registration prompt...")
    if "passkey_registration" in await _current_url(tab):
        print("  ⚠️  Passkey registration prompt detected - clicking 'Not now'...")
        if not await _click_first_xpath(tab, '//button[contains(., "Not now")]'):
            btn = await find_by_text(tab, "Not now")
            if btn:
                await click_element(tab, btn)
        await random_time()
        print("  ✓ Skipped passkey registration")
    else:
        print("  ✓ No passkey prompt detected")

    print("✓ Login successful!\n")
    return True


# ---------------------------------------------------------------------------
# clear_cart
# ---------------------------------------------------------------------------
async def clear_cart(tab):
    """Empty the HEB cart (async). Returns 0 if already empty/not found."""
    # Close any modal intercepting clicks.
    close_btn = await select_one(tab, "button[aria-label='close']", timeout=2)
    if close_btn and await is_visible(close_btn):
        await click_element(tab, close_btn)
        await random_time()

    if "/cart" not in await _current_url(tab):
        await tab.get(HEB_CART)
        await random_time()

    if not await _click_first_xpath(tab, '//button[contains(., "Empty cart")]'):
        return 0
    await random_time()

    # Confirm the empty action.
    await _click_first_xpath(tab, '//button[contains(., "Empty")]')
    await random_time()

    home = await select_one(tab, 'a[href="/"]', timeout=3)
    if home:
        await click_element(tab, home)
        await random_time()
    return 1


# ---------------------------------------------------------------------------
# reserve_time_slot (with the tiered-modal Step 4.5 fix)
# ---------------------------------------------------------------------------
async def reserve_time_slot(tab):
    """Reserve a curbside pickup time slot (async, handles the tiered modal)."""
    # STEP 1: ensure on cart
    print("  Step 1: Navigating to cart...")
    if "/cart" not in await _current_url(tab):
        await tab.get(HEB_CART)
        await random_time()

    if await check_exists_by_xpath(tab, '//*[contains(text(), "Change time")]'):
        print("  ✓ Time slot already reserved")
        return True

    # STEP 2: let blocking modals settle
    print("  Step 2: Waiting for any blocking modals to clear...")
    await asyncio.sleep(1)

    # STEP 3: open the reservation modal
    print("  Step 3: Opening reservation modal...")
    reserve_button, _ = await select_first_of(
        tab,
        [
            'button[data-qe-id="chooseReservationTime"]',
            'button[aria-label*="Choose reservation time"]',
        ],
        timeout=10,
    )
    if reserve_button is not None:
        await scroll_to_element(reserve_button)
        await click_element(tab, reserve_button)
        print("    ✓ Clicked 'Choose pickup time' button")
    elif await _click_first_xpath(
        tab,
        '//button[contains(., "Choose pickup time") or contains(., "Choose a time") '
        'or contains(@aria-label, "Choose")]',
    ):
        print("    ✓ Clicked 'Choose pickup time' button (fallback)")
    else:
        raise Exception("Could not find 'Choose pickup time' button")
    await random_time()
    await asyncio.sleep(3)

    # STEP 4: ensure Curbside tab is selected
    print("  Step 4: Ensuring Curbside tab is selected...")
    for tab_el in await xpath_all(
        tab, '//button[contains(text(), "Curbside")] | //*[@role="tab" and contains(text(), "Curbside")]'
    ):
        try:
            if attr(tab_el, "aria-selected") != "true":
                await click_element(tab, tab_el)
                await random_time()
                print("    ✓ Selected Curbside tab")
            else:
                print("    ✓ Curbside tab already selected")
        except Exception:  # noqa: BLE001
            pass
        break
    await asyncio.sleep(2)

    # STEP 4.5: select a delivery tier (refreshed tiered timeslot UI).
    print("  Step 4.5: Selecting a delivery tier...")
    tier_buttons = await select_all(tab, 'button[class*="TimeslotSummary_button"]', timeout=3)
    if not tier_buttons:
        tier_buttons = await xpath_all(tab, '//button[contains(@aria-label, "time slots for")]')

    visible_tiers = []
    for b in tier_buttons:
        if await is_visible(b):
            visible_tiers.append(b)

    if not visible_tiers:
        print("    ℹ️  No tier buttons found; assuming legacy date-grid layout.")
    else:
        preferred = None
        for b in visible_tiers:
            label = attr(b, "aria-label", "") or ""
            if "Scheduled" in label or "for Free" in label:
                preferred = b
                break
        target = preferred or visible_tiers[-1]
        label = (attr(target, "aria-label", "tier") or "tier").strip()
        await scroll_to_element(target)
        await click_element(tab, target)
        print(f"    ✓ Selected delivery tier: {label[:60]}")
        await random_time()
        await asyncio.sleep(2)

    # STEP 5: select a date
    print("  Step 5: Selecting a date...")
    date_buttons = []
    for selector in [
        'button[id^="date-button-"]',
        'input[type="radio"][name*="date"]',
        'button[aria-label*="date"]',
        'label[for^="date-button-"]',
        '[role="button"][id*="date"]',
    ]:
        date_buttons = await select_all(tab, selector, timeout=2)
        if date_buttons:
            print(f"    Found {len(date_buttons)} date options using selector: {selector}")
            break
    if not date_buttons:
        date_buttons = await xpath_all(
            tab,
            '//button[contains(@class, "date") or contains(@class, "Date")] | '
            '//div[contains(@class, "date") or contains(@class, "Date")]//button',
        )

    date_selected = False
    for btn in date_buttons:
        try:
            if not await is_visible(btn) or not await is_enabled(btn):
                continue
            text_content = (btn.text or "")
            aria_label = attr(btn, "aria-label", "") or ""
            if "Free" in text_content or "Free" in aria_label or attr(btn, "aria-disabled") != "true":
                if await click_element(tab, btn):
                    label = (text_content.strip()[:50] or aria_label[:50])
                    print(f"    📅 Selected date: {label}")
                    date_selected = True
                    await random_time()
                    break
        except Exception:  # noqa: BLE001
            continue

    if not date_selected and date_buttons:
        if await click_element(tab, date_buttons[0]):
            print("    📅 Selected first available date")
            date_selected = True
            await random_time()

    if not date_selected:
        raise Exception(
            f"No dates found or could not select date. Found {len(date_buttons)} elements."
        )
    await asyncio.sleep(2)

    # STEP 6: select a timeslot
    print("  Step 6: Selecting a timeslot...")
    timeslot_elements = []
    for selector in [
        'input[type="radio"][data-qe-id="timeslotRadioButton"]',
        'input[type="radio"][name*="timeslot"]',
        'input[type="radio"][name*="time"]',
        'button[data-qe-id*="timeslot"]',
        '[role="radio"][aria-label*="time"]',
    ]:
        timeslot_elements = await select_all(tab, selector, timeout=2)
        if timeslot_elements:
            print(f"    Found {len(timeslot_elements)} timeslot options using selector: {selector}")
            break
    if not timeslot_elements:
        timeslot_elements = await xpath_all(tab, '//input[@type="radio"]')

    timeslot_selected = False
    for slot in timeslot_elements:
        try:
            if attr(slot, "disabled") is not None or attr(slot, "aria-disabled") == "true":
                continue
            if not await js_click(tab, slot):
                await click_element(tab, slot)
            aria_label = attr(slot, "aria-label", "") or ""
            print(f"    🕐 Selected timeslot: {aria_label[:60] or 'timeslot'}")
            timeslot_selected = True
            break
        except Exception:  # noqa: BLE001
            continue

    if not timeslot_selected:
        raise Exception(f"No timeslots found or could not select. Found {len(timeslot_elements)} elements.")

    # STEP 7: let it register + close modal
    print("  Step 7: Waiting for timeslot selection to register...")
    await asyncio.sleep(3)
    for selector in ['[aria-label="close"]', '[aria-label="Close"]',
                     'button[class*="close"]', 'button[class*="Close"]']:
        closed = False
        for btn in await select_all(tab, selector, timeout=1):
            if await is_visible(btn):
                await click_element(tab, btn)
                print("    ✓ Closed modal")
                closed = True
                break
        if closed:
            break
    await asyncio.sleep(2)

    if await check_exists_by_xpath(tab, '//*[contains(text(), "Change time")]'):
        print("  ✓ Time slot successfully reserved!")
    else:
        print("  ✓ Time slot reservation process completed (could not verify)")
    return True


# ---------------------------------------------------------------------------
# change_store_via_ui
# ---------------------------------------------------------------------------
async def change_store_via_ui(tab, search_text):
    """Exercise HEB's store-change UI (StoreSearch + SelectPickupFulfillment)."""
    print("  Step 1: Opening the store/fulfillment selector...")
    await tab.get(HEB_HOME)
    await random_time()

    opener, used = await select_first_of(
        tab,
        ['[data-qe-id="headerFulfillmentButton"]', '[data-qe-id="fulfillmentSelector"]'],
        timeout=5,
    )
    opened = False
    if opener is not None:
        await js_click(tab, opener)
        opened = True
        print(f"    ✓ Opened selector via {used}")
    else:
        for xp in [
            '//button[contains(., "Curbside") or contains(., "Pickup") or contains(., "store")]',
            '//button[contains(@aria-label, "store") or contains(@aria-label, "fulfillment")]',
        ]:
            if await _click_first_xpath(tab, xp):
                opened = True
                print(f"    ✓ Opened selector via {xp}")
                break
    if not opened:
        raise Exception("Could not find the store/fulfillment selector button.")
    await random_time()

    # Optional "change store" affordance.
    for xp in [
        '//button[contains(., "Change store") or contains(., "Change my store")]',
        '//a[contains(., "Change store")]',
        '//button[contains(., "Find a store") or contains(., "store near")]',
    ]:
        if await _click_first_xpath(tab, xp):
            print(f"    ✓ Clicked change-store via {xp}")
            await random_time()
            break

    print("  Step 3: Searching stores by location...")
    await asyncio.sleep(1)
    search_input = None
    for xp in [
        '//div[@role="dialog"]//input[@type="text"]',
        '//div[@role="dialog"]//input[@placeholder]',
        '//input[contains(@placeholder, "address")]',
        '//input[contains(@placeholder, "zip")]',
        '//input[contains(@placeholder, "city")]',
    ]:
        for el in await xpath_all(tab, xp):
            if await is_visible(el):
                search_input = el
                print(f"    ✓ Found store search input via {xp}")
                break
        if search_input:
            break
    if search_input is None:
        raise Exception("Could not find a dedicated store-search input.")

    await human_like_typing(search_input, str(search_text))
    await asyncio.sleep(0.8)
    await search_input.send_keys("\r")
    await random_time()
    await random_time()

    print("  Step 4: Selecting the first store result...")
    for xp in [
        '//button[contains(., "Selected Store")]',
        '//button[contains(., "Select Store")]',
        '//button[contains(., "Make my store") or contains(., "Select") or contains(., "Shop this store")]',
        '//button[contains(@aria-label, "Select") and contains(@aria-label, "store")]',
    ]:
        if await _click_first_xpath(tab, xp):
            print(f"    ✓ Selected a store via {xp}")
            await random_time()
            return True

    sel_btn = await select_one(tab, '[data-qe-id="selectStoreButton"]', timeout=2)
    if sel_btn:
        await click_element(tab, sel_btn)
        await random_time()
        return True

    print("    ⚠️  Could not click a store-select button; StoreSearch may still be captured.")
    return True


# ---------------------------------------------------------------------------
# add_ingredient
# ---------------------------------------------------------------------------
async def add_ingredient(ingredient, tab):
    """Search for an ingredient and click Add to cart (async).

    Returns 1 on success, 0 on skip. Unlike the Selenium version this does not
    block on interactive input(); on exhaustion it returns 0 and lets the caller
    (and self-healing) decide. Produce is searched as organic.

    The search is driven by navigating directly to HEB's search-results URL
    (``/search?q=...``) rather than typing into the global search box. The box
    is a React-controlled input that did not reliably clear between calls, so
    typed queries concatenated across ingredients; a direct URL avoids that
    entirely and is more robust.
    """
    max_retries = 3
    tag = ingredient.get_tag()
    name = ingredient.get_name()
    search_term = f"organic {name}" if tag in ("vegetable", "fruit") else name
    search_url = f"https://www.heb.com/search?q={quote_plus(search_term)}"

    for attempt in range(max_retries):
        try:
            print(f"    🔍 Searching for: {search_term}")
            await tab.get(search_url)

            # The search-results grid is a large React render (100+ cards).
            # nodriver's CDP-based tab.select() can miss these dynamically
            # hydrated nodes, so locate AND click the first Add-to-cart button
            # via page JavaScript, polling until the grid hydrates (~up to 18s).
            clicked = False
            for _ in range(18):
                result = await tab.evaluate(
                    "(() => {"
                    "  const b = document.querySelector('button[data-qe-id=\"addToCart\"]')"
                    "    || document.querySelector('button[class*=\"AddByQuantityButton_button\"]');"
                    "  if (!b) return 'NOTREADY';"
                    "  b.scrollIntoView({block: 'center'});"
                    "  b.click();"
                    "  return 'CLICKED';"
                    "})()"
                )
                if result == "CLICKED":
                    clicked = True
                    break
                await asyncio.sleep(1)

            if clicked:
                await asyncio.sleep(1.5)
                print(f"    ✅ Added {name} to cart")
                return 1
            else:
                print(f"    ⚠️  Add to cart button not found for: {name} "
                      f"(attempt {attempt + 1}/{max_retries})")
                await asyncio.sleep(1.5)
        except Exception as e:  # noqa: BLE001
            print(f"    ❌ Error on attempt {attempt + 1}/{max_retries}: {e}")
            await asyncio.sleep(2)

    print(f"\n    ⏭️  Skipping {ingredient.get_name()} after {max_retries} attempts")
    return 0


# ---------------------------------------------------------------------------
# checkout
# ---------------------------------------------------------------------------
async def checkout(tab):
    """Advance to the checkout page (does NOT place the order)."""
    print("\n🛒 Starting checkout process...")
    await tab.get(HEB_CART)
    await random_time()

    checkout_button, used = await select_first_of(
        tab,
        ['[data-qe-id="footerStartCheckout"]', '[data-qe-id="proceedToCheckout"]'],
        timeout=10,
    )
    if checkout_button is None:
        if not await _click_first_xpath(
            tab,
            '//button[contains(., "Start checkout") or contains(., "Proceed to checkout") '
            'or contains(., "Checkout")]',
        ):
            raise Exception("Could not find the checkout button on the cart page.")
        used = "text-match"
    else:
        await scroll_to_element(checkout_button)
        await click_element(tab, checkout_button)
    print(f"    ✓ Clicked checkout button ({used})")
    await random_time()
    print("✓ Reached checkout page")
    return True
