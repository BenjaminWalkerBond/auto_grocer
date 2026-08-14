"""Detection for HEB's "security setting on your device" block page.

When Imperva/Incapsula rate-limits or fingerprint-blocks the automation, HEB
does not return a normal Incapsula interstitial. It renders a JS-built overlay
that blames the *client*:

    "The page can't load due to a security setting on your device."
    "It looks like an ad blocker, antivirus software, VPN, or firewall is
     causing an issue..."

That page is terminal. No selector will ever appear, so retrying (or letting
Claude rewrite a flow function against it) only burns time and adds more
requests, which deepens the rate limit. Detect it early and abort the whole
session instead.
"""
from __future__ import annotations

# Substrings unique to the block overlay. Any single hit is conclusive: none of
# these strings appear on the real storefront. The overlay is built by inline JS,
# so the apostrophe arrives escaped ("can\'t") — match on the tail of the
# sentence instead of the contraction.
_BLOCK_MARKERS = (
    "load due to a security setting on your device",
    "it looks like an ad blocker, antivirus software, vpn, or firewall",
    "ad blocker, antivirus software, vpn, or firewall is causing an issue",
)


class WafBlockedError(Exception):
    """HEB served the ad-blocker/security-setting block page.

    Treated as fatal: the session must be abandoned, not retried or healed.
    """


def detect_block(html):
    """Return the matched marker if ``html`` is the block page, else None."""
    if not html:
        return None
    low = html.lower()
    for marker in _BLOCK_MARKERS:
        if marker in low:
            return marker
    return None


async def assert_not_blocked(tab, context="", logger=None):
    """Raise WafBlockedError if the current page is the HEB block page.

    Args:
        tab: nodriver Tab to inspect.
        context: Label for the step being guarded, used in the error message.
        logger: Optional AsyncDriverLogger; captures screenshot/HTML on a hit.
    """
    try:
        html = await tab.get_content()
    except Exception:  # noqa: BLE001
        return  # Can't read the page; let the normal flow surface the failure.

    marker = detect_block(html)
    if not marker:
        return

    url = None
    try:
        url = await tab.evaluate("location.href")
    except Exception:  # noqa: BLE001
        pass

    where = f" during {context}" if context else ""
    print(
        f"\n🚫 HEB BLOCK PAGE detected{where}.\n"
        f"    marker : {marker}\n"
        f"    page url: {url}\n"
        "    HEB is serving the 'ad blocker / security setting on your device'\n"
        "    overlay, which means this client is WAF rate-limited. Retrying or\n"
        "    self-healing against it cannot succeed and makes the block worse.\n"
        "    Aborting the session. Wait before trying again."
    )

    error = WafBlockedError(
        f"HEB WAF block page{where} (marker: {marker!r}, url: {url}). "
        "Client is rate-limited; abandon this session and retry later."
    )
    if logger is not None:
        try:
            await logger.log_failure(
                tab,
                "waf_block",
                error,
                additional_info={
                    "reason": "heb_block_page",
                    "marker": marker,
                    "context": context,
                    "page_url": url,
                },
            )
        except Exception:  # noqa: BLE001
            pass
    raise error
