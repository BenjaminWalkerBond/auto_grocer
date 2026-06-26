"""Async primitives for the nodriver prototype.

These mirror the small Selenium helpers in main.py (random_time, human_like_*,
scroll_to_element, check_exists_by_xpath, dismiss_modals) plus a couple of
select-with-fallback helpers that replace the WebDriverWait/EC retry loops.

nodriver notes:
  * tab.select(css, timeout) returns an Element or raises on timeout -> we wrap
    everything and treat "not found" as None.
  * Elements expose .attrs (dict), .text, .click(), .send_keys(), .apply(js).
    There is no get_attribute(); use attr(el, name) below.
"""
from __future__ import annotations

import asyncio
import random


async def random_time():
    """Async sleep for a human-like 2.0-3.5s."""
    await asyncio.sleep(random.uniform(2.0, 3.5))


async def human_like_delay():
    """Very short async delay (0.3-0.8s) to simulate reaction time."""
    await asyncio.sleep(random.uniform(0.3, 0.8))


async def human_like_typing(element, text):
    """Type text one character at a time with small random delays."""
    for char in str(text):
        await element.send_keys(char)
        await asyncio.sleep(random.uniform(0.05, 0.15))
    await human_like_delay()


async def scroll_to_element(element):
    """Scroll an element into view (best-effort)."""
    try:
        await element.scroll_into_view()
        await human_like_delay()
    except Exception as e:  # noqa: BLE001
        print(f"    ⚠️  Could not scroll to element: {e}")


def attr(element, name, default=None):
    """Return an element attribute value (replacement for get_attribute)."""
    try:
        value = element.attrs.get(name)
        return value if value is not None else default
    except Exception:  # noqa: BLE001
        return default


async def is_visible(element) -> bool:
    """Return True if the element is rendered (has layout boxes)."""
    try:
        return bool(await element.apply(
            "(e) => !!(e.offsetWidth || e.offsetHeight || "
            "e.getClientRects().length)"
        ))
    except Exception:  # noqa: BLE001
        return False


async def is_enabled(element) -> bool:
    """Return True if the element is not disabled / aria-disabled."""
    try:
        return bool(await element.apply(
            "(e) => !e.disabled && e.getAttribute('aria-disabled') !== 'true'"
        ))
    except Exception:  # noqa: BLE001
        return True


async def js_click(tab, element) -> bool:
    """Click an element from JavaScript (last-resort click). Returns success."""
    try:
        await element.apply("(e) => e.click()")
        return True
    except Exception:  # noqa: BLE001
        return False


async def click_element(tab, element) -> bool:
    """Try a normal click, then a JS click. Returns True if either worked."""
    try:
        await element.click()
        return True
    except Exception:  # noqa: BLE001
        return await js_click(tab, element)


async def select_one(tab, css, timeout=10):
    """Return the first element matching a CSS selector, or None."""
    try:
        el = await tab.select(css, timeout=timeout)
        return el
    except Exception:  # noqa: BLE001 - timeout / not found
        return None


async def select_all(tab, css, timeout=5):
    """Return all elements matching a CSS selector (empty list on failure)."""
    try:
        return await tab.select_all(css, timeout=timeout) or []
    except Exception:  # noqa: BLE001
        return []


async def xpath_all(tab, xpath, timeout=2.5):
    """Return all elements matching an XPath (empty list on failure)."""
    try:
        return [e for e in (await tab.xpath(xpath, timeout=timeout) or []) if e] 
    except Exception:  # noqa: BLE001
        return []


async def select_first_of(tab, css_selectors, timeout=5):
    """Try several CSS selectors in order; return (element, selector) or (None, None)."""
    for sel in css_selectors:
        el = await select_one(tab, sel, timeout=timeout)
        if el is not None:
            return el, sel
    return None, None


async def check_exists_by_xpath(tab, xpath) -> bool:
    """Return True if at least one element matches the XPath."""
    els = await xpath_all(tab, xpath)
    return len(els) > 0


async def find_by_text(tab, text, timeout=10):
    """Resilient text-based lookup (nodriver's find). Returns Element or None."""
    try:
        return await tab.find(text, best_match=True, timeout=timeout)
    except Exception:  # noqa: BLE001
        return None


async def dismiss_modals(tab):
    """Dismiss modal overlays blocking interaction (best-effort, async)."""
    closed_any = False

    close_selectors = [
        '[data-qe-id="modalClose"]',
        'button[aria-label="Close"]',
        'button[aria-label="close"]',
        '.modal-close',
    ]
    for selector in close_selectors:
        for btn in await select_all(tab, selector, timeout=1):
            try:
                if await is_visible(btn):
                    await js_click(tab, btn)
                    await asyncio.sleep(0.5)
                    closed_any = True
            except Exception:  # noqa: BLE001
                pass

    # Remove modal overlay/container divs via JavaScript as a fallback.
    try:
        removed = await tab.evaluate(
            "(() => {"
            "  var n = 0;"
            "  document.querySelectorAll('[data-component=\"modal-cover-container\"]')"
            "    .forEach(function(el){ el.remove(); n++; });"
            "  document.querySelectorAll('[data-component=\"modal-container\"]')"
            "    .forEach(function(el){ el.remove(); n++; });"
            "  return n;"
            "})()"
        )
        if removed:
            closed_any = True
    except Exception:  # noqa: BLE001
        pass

    if closed_any:
        print("    ℹ️  Dismissed blocking modal(s)")
        await asyncio.sleep(0.5)
