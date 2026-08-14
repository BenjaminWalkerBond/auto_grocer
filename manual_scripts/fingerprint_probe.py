"""Fingerprint the automated browser the way a bot-detection script would.

Loads about:blank only - makes no request to heb.com - so it is safe to run
while the WAF is angry.
"""
import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from session_maintenance.browser import start_browser, stop_browser

PROBE_JS = """
(() => {
  const out = {};
  out.webdriver = navigator.webdriver;
  out.userAgent = navigator.userAgent;
  out.appVersion = navigator.appVersion;
  out.platform = navigator.platform;
  out.languages = navigator.languages;
  out.hardwareConcurrency = navigator.hardwareConcurrency;
  out.deviceMemory = navigator.deviceMemory;
  out.pluginCount = navigator.plugins ? navigator.plugins.length : -1;
  out.mimeTypes = navigator.mimeTypes ? navigator.mimeTypes.length : -1;
  out.hasChromeObj = typeof window.chrome !== 'undefined';
  out.chromeKeys = window.chrome ? Object.keys(window.chrome) : [];
  out.screen = [screen.width, screen.height, screen.availWidth, screen.availHeight];
  out.colorDepth = screen.colorDepth;
  out.devicePixelRatio = window.devicePixelRatio;
  out.timezone = Intl.DateTimeFormat().resolvedOptions().timeZone;
  out.notificationPermission = (typeof Notification !== 'undefined') ? Notification.permission : 'n/a';
  out.maxTouchPoints = navigator.maxTouchPoints;
  out.pdfViewerEnabled = navigator.pdfViewerEnabled;

  try {
    const c = document.createElement('canvas');
    const gl = c.getContext('webgl') || c.getContext('experimental-webgl');
    if (gl) {
      const dbg = gl.getExtension('WEBGL_debug_renderer_info');
      out.webglVendor = dbg ? gl.getParameter(dbg.UNMASKED_VENDOR_WEBGL) : gl.getParameter(gl.VENDOR);
      out.webglRenderer = dbg ? gl.getParameter(dbg.UNMASKED_RENDERER_WEBGL) : gl.getParameter(gl.RENDERER);
    } else {
      out.webglVendor = out.webglRenderer = 'NO_WEBGL';
    }
  } catch (e) { out.webglError = String(e); }

  out.userAgentData = navigator.userAgentData
    ? {brands: navigator.userAgentData.brands, mobile: navigator.userAgentData.mobile}
    : null;

  return JSON.stringify(out);
})()
"""


async def main() -> None:
    browser = await start_browser(headless=False)
    try:
        tab = await browser.get("about:blank")
        await asyncio.sleep(1)
        raw = await tab.evaluate(PROBE_JS)
        data = json.loads(raw)
        for key, value in data.items():
            print(f"{key:24} {value}")
    finally:
        await stop_browser(browser)


asyncio.run(main())
