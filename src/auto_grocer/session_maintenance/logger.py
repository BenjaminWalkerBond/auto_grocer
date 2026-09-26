"""Async debug logger for the nodriver prototype.

Mirrors utility/driver_logger.py (timestamped session dir, HTML + screenshot +
error JSON) but uses nodriver's async tab API instead of the Selenium driver:
  * driver.page_source        -> await tab.get_content()
  * driver.save_screenshot()  -> await tab.save_screenshot(path)
  * driver.get_screenshot_as_base64() -> await tab.save_screenshot(as_base64=True)
"""
from __future__ import annotations

import datetime
import json
import os
import traceback


class AsyncDriverLogger:
    """Captures HTML snapshots, screenshots, and error details on failures."""

    def __init__(self, log_dir="debug_logs"):
        self.log_dir = log_dir
        self.session_dir = None
        self._create_log_directory()

    def _create_log_directory(self):
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        self.session_dir = os.path.join(self.log_dir, f"session_{timestamp}")
        os.makedirs(self.session_dir, exist_ok=True)
        print(f"📁 Debug logs will be saved to: {self.session_dir}")

    async def save_html_snapshot(self, tab, function_name, error_type="unknown"):
        """Save the current page HTML. Returns the file path or None."""
        try:
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            filename = f"{timestamp}_{function_name}_{error_type}.html"
            filepath = os.path.join(self.session_dir, filename)

            html_content = await tab.get_content()
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(html_content or "")

            print(f"📄 HTML snapshot saved: {filepath}")
            return filepath
        except Exception as e:  # noqa: BLE001
            print(f"⚠️  Failed to save HTML snapshot: {e}")
            return None

    async def save_screenshot(self, tab, function_name, error_type="unknown"):
        """Save a screenshot of the current page. Returns the file path or None."""
        try:
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            filename = f"{timestamp}_{function_name}_{error_type}.png"
            filepath = os.path.join(self.session_dir, filename)

            await tab.save_screenshot(filepath, format="png")
            print(f"📸 Screenshot saved: {filepath}")
            return filepath
        except Exception as e:  # noqa: BLE001
            print(f"⚠️  Failed to save screenshot: {e}")
            return None

    async def screenshot_b64(self, tab):
        """Return a base64-encoded PNG screenshot (for Claude vision), or None."""
        try:
            return await tab.save_screenshot(format="png", as_base64=True)
        except Exception as e:  # noqa: BLE001
            print(f"    ⚠️  Could not capture screenshot: {e}")
            return None

    async def save_error_log(self, function_name, error, tab=None, additional_info=None):
        """Save structured exception details to a JSON file. Returns path or None."""
        try:
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            filename = f"{timestamp}_{function_name}_error.json"
            filepath = os.path.join(self.session_dir, filename)

            error_data = {
                "timestamp": datetime.datetime.now().isoformat(),
                "function_name": function_name,
                "error_type": type(error).__name__,
                "error_message": str(error),
                "traceback": traceback.format_exc(),
                "additional_info": additional_info or {},
            }
            if tab is not None:
                try:
                    error_data["url"] = await tab.evaluate("location.href")
                except Exception:  # noqa: BLE001
                    pass

            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(error_data, f, indent=2, default=str)
            return filepath
        except Exception as e:  # noqa: BLE001
            print(f"⚠️  Failed to save error log: {e}")
            return None

    async def log_failure(self, tab, function_name, error, additional_info=None):
        """Capture screenshot + HTML + error JSON for a failed operation."""
        await self.save_screenshot(tab, function_name, type(error).__name__)
        await self.save_html_snapshot(tab, function_name, type(error).__name__)
        await self.save_error_log(function_name, error, tab, additional_info)
