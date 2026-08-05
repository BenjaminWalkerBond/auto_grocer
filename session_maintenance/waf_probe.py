"""WAF baseline probe: characterize how HEB's Incapsula WAF sees this browser.

Reuses the SAME ``start_browser`` config the container/login flow uses, then:
  1. Dumps the bot-detection fingerprint (navigator.webdriver, UA, WebGL
     vendor/renderer, canvas hash, screen, etc.).
  2. Does ONE controlled navigation to https://www.heb.com and reports the
     document HTTP status (via a same-origin fetch).
  3. Reports whether a real ``reese84`` token got minted (localStorage + cookie)
     and whether the response looks like an Incapsula challenge.

Run standalone (host, real display):
    DISPLAY=:0 python -m session_maintenance.waf_probe

Run in the container (Xvfb via the image entrypoint):
    docker run --rm --network host \
        -v auto_grocier_session:/root/.texas-grocery-mcp --env-file .env \
        auto_grocier_mcp python -m session_maintenance.waf_probe
"""
from __future__ import annotations

import json
import os
import time
from datetime import datetime

import nodriver

from session_maintenance.browser import start_browser, stop_browser

HEB_HOME = "https://www.heb.com/"

# JS that returns a JSON string describing the browser fingerprint. Kept as a
# single expression (IIFE) so tab.evaluate can return its value directly.
_FINGERPRINT_JS = r"""
(() => {
  const out = {};
  try { out.webdriver = navigator.webdriver; } catch (e) { out.webdriver = 'err'; }
  out.userAgent = navigator.userAgent;
  out.appVersion = navigator.appVersion;
  out.platform = navigator.platform;
  out.vendor = navigator.vendor;
  out.languages = navigator.languages;
  out.hardwareConcurrency = navigator.hardwareConcurrency;
  out.deviceMemory = navigator.deviceMemory;
  out.maxTouchPoints = navigator.maxTouchPoints;
  out.pluginsLength = (navigator.plugins || {}).length;
  out.screen = { w: screen.width, h: screen.height, colorDepth: screen.colorDepth,
                 availW: screen.availWidth, availH: screen.availHeight };
  out.devicePixelRatio = window.devicePixelRatio;
  out.hasChrome = !!window.chrome;
  out.hasChromeRuntime = !!(window.chrome && window.chrome.runtime);
  try {
    out.notificationPermission = (typeof Notification !== 'undefined')
      ? Notification.permission : 'no-Notification';
  } catch (e) { out.notificationPermission = 'err'; }
  try {
    const c = document.createElement('canvas');
    const gl = c.getContext('webgl') || c.getContext('experimental-webgl');
    if (gl) {
      const dbg = gl.getExtension('WEBGL_debug_renderer_info');
      out.webglVendor = dbg ? gl.getParameter(dbg.UNMASKED_VENDOR_WEBGL)
                            : gl.getParameter(gl.VENDOR);
      out.webglRenderer = dbg ? gl.getParameter(dbg.UNMASKED_RENDERER_WEBGL)
                              : gl.getParameter(gl.RENDERER);
      out.glVersion = gl.getParameter(gl.VERSION);
      out.glShading = gl.getParameter(gl.SHADING_LANGUAGE_VERSION);
    } else {
      out.webglVendor = out.webglRenderer = out.glVersion = null;
    }
  } catch (e) { out.webglError = String(e); }
  try {
    const cc = document.createElement('canvas');
    cc.width = 200; cc.height = 50;
    const ctx = cc.getContext('2d');
    ctx.textBaseline = 'top';
    ctx.font = "14px 'Arial'";
    ctx.fillStyle = '#f60'; ctx.fillRect(0, 0, 100, 20);
    ctx.fillStyle = '#069'; ctx.fillText('auto_grocier waf probe \u2728', 2, 15);
    const data = cc.toDataURL();
    let h = 0;
    for (let i = 0; i < data.length; i++) { h = (h * 31 + data.charCodeAt(i)) | 0; }
    out.canvasHash = h;
  } catch (e) { out.canvasError = String(e); }
  return JSON.stringify(out);
})()
"""


def _looks_like_challenge(html: str) -> bool:
    """Heuristic: does the page look like an Incapsula/Imperva interstitial?"""
    if not html:
        return True
    low = html.lower()
    strong = [
        "request unsuccessful. incapsula",
        "_incapsula_resource",
        "incident id",
        "powered by imperva",
        "/_incapsula_",
    ]
    if any(s in low for s in strong):
        real = sum(s in low for s in ("add to cart", "my cart", "curbside", "weekly ad"))
        return real < 2
    return False


def _has_real_content(html: str) -> bool:
    """True if the page looks like the real HEB site (not a block interstitial)."""
    if not html:
        return False
    low = html.lower()
    markers = ("add to cart", "my cart", "curbside", "weekly ad", "__next_data__",
               "my account", "data-testid", "shop now")
    return sum(m in low for m in markers) >= 2


async def _dump_fingerprint(tab) -> dict:
    try:
        raw = await tab.evaluate(_FINGERPRINT_JS)
    except Exception as e:  # noqa: BLE001
        return {"error": f"fingerprint eval failed: {e}"}
    if isinstance(raw, dict):
        return raw
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return {"error": "could not parse fingerprint", "raw": str(raw)[:500]}


async def _get_local_storage(tab) -> dict:
    try:
        ls = await tab.get_local_storage()
        return ls if isinstance(ls, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


async def _get_cookies(browser) -> list:
    try:
        return await browser.cookies.get_all() or []
    except Exception:  # noqa: BLE001
        return []


def _reese84_shape(value: str) -> str:
    """Classify a reese84 value: valid JSON (real token) vs opaque vs absent."""
    if not value:
        return "absent"
    try:
        obj = json.loads(value)
    except (TypeError, ValueError):
        return "opaque"
    if isinstance(obj, dict) and ("renewTime" in obj or "token" in obj):
        return "json-with-renewTime"
    return "json-other"


async def run_probe() -> dict:
    display = os.environ.get("DISPLAY", "(unset)")
    print("=" * 64)
    print("HEB WAF BASELINE PROBE")
    print("=" * 64)
    print(f"DISPLAY={display}  NO_SANDBOX={os.environ.get('AUTO_GROCIER_NO_SANDBOX')}"
          f"  CHROME={os.environ.get('NODRIVER_BROWSER_PATH')}")

    browser = await start_browser(headless=False)
    tab = await browser.get("about:blank")

    print("\nDumping browser fingerprint...")
    fingerprint = await _dump_fingerprint(tab)
    for k in ("webdriver", "webglVendor", "webglRenderer", "glVersion",
              "userAgent", "hardwareConcurrency", "deviceMemory", "hasChromeRuntime"):
        print(f"    {k:>18}: {fingerprint.get(k)}")

    print(f"\nNavigating to {HEB_HOME} (single hit)...")
    nav_error = None
    try:
        await tab.get(HEB_HOME)
    except Exception as e:  # noqa: BLE001
        nav_error = str(e)
        print(f"    navigation raised: {e}")

    print("Waiting up to 20s for reese84 to mint...")
    reese84_ls = ""
    for _ in range(20):
        ls = await _get_local_storage(tab)
        if ls.get("reese84"):
            reese84_ls = ls["reese84"]
            break
        time.sleep(1)

    html = ""
    try:
        html = await tab.get_content() or ""
    except Exception:  # noqa: BLE001
        pass

    cookies = await _get_cookies(browser)
    cookie_names = {getattr(c, "name", "") for c in cookies}
    reese84_cookie = next(
        (getattr(c, "value", "") for c in cookies if getattr(c, "name", "") == "reese84"),
        "",
    )
    session_cookies_present = sorted(
        n for n in ("sat", "sst", "JSESSIONID", "DYN_USER_ID") if n in cookie_names
    )

    # Best-effort HTTP status via a same-origin fetch. (We avoid the CDP Network
    # domain: this nodriver build's event parser crashes on some response
    # headers, and the reese84 mint below is the authoritative pass signal.)
    doc_status = None
    try:
        doc_status = await tab.evaluate(
            "fetch(location.origin + '/', {method: 'GET', cache: 'no-store'})"
            ".then(r => r.status).catch(() => null)",
            await_promise=True,
        )
    except Exception:  # noqa: BLE001
        doc_status = None

    real_content = _has_real_content(html)
    challenge = _looks_like_challenge(html) or (doc_status in (401, 403))
    reese84_valid = _reese84_shape(reese84_ls) == "json-with-renewTime"
    minted = bool(reese84_ls or reese84_cookie)
    passed = (reese84_valid or minted) and not challenge and real_content

    report = {
        "timestamp": datetime.now().isoformat(),
        "display": display,
        "env": {
            "no_sandbox": os.environ.get("AUTO_GROCIER_NO_SANDBOX"),
            "chrome_path": os.environ.get("NODRIVER_BROWSER_PATH"),
        },
        "fingerprint": fingerprint,
        "heb_document_status": doc_status,
        "nav_error": nav_error,
        "html_len": len(html),
        "real_content": real_content,
        "looks_like_challenge": challenge,
        "reese84": {
            "localStorage_shape": _reese84_shape(reese84_ls),
            "cookie_shape": _reese84_shape(reese84_cookie),
            "valid": reese84_valid,
            "minted": minted,
        },
        "session_cookies_present": session_cookies_present,
        "cookie_count": len(cookies),
        "passed": passed,
    }

    print("\n" + "=" * 64)
    print("VERDICT")
    print("=" * 64)
    print(f"    HEB document HTTP status : {doc_status}")
    print(f"    Real HEB content         : {real_content}")
    print(f"    Looks like challenge     : {challenge}")
    print(f"    reese84 minted           : {minted} "
          f"(ls={report['reese84']['localStorage_shape']}, "
          f"cookie={report['reese84']['cookie_shape']})")
    print(f"    Session cookies present  : {session_cookies_present or 'none'}")
    print(f"    WebGL renderer           : {fingerprint.get('webglRenderer')}")
    if passed:
        print("\n    PASS: environment cleared Incapsula and minted a reese84.")
    else:
        print("\n    BLOCKED: no valid reese84 / challenge detected. "
              "See webglRenderer + status above for the tell.")

    out_dir = "debug_logs"
    os.makedirs(out_dir, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = os.path.join(out_dir, f"waf_probe_{stamp}.json")
    try:
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, default=str)
        print(f"\nFull report saved to {out_path}")
    except Exception as e:  # noqa: BLE001
        print(f"Could not save report: {e}")

    await stop_browser(browser)
    return report


def main():
    nodriver.loop().run_until_complete(run_probe())


if __name__ == "__main__":
    main()
