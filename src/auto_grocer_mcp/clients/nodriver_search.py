"""In-process nodriver browser search fallback.

HEB's Incapsula WAF challenges browser-navigation routes (``/``, ``/search``,
``/_next/data/...``) with a reese84 JavaScript challenge that a plain ``httpx``
client cannot solve. The ``/graphql`` POST API is *not* challenged, but HEB
exposes product search only through those server-rendered navigation routes.

When the httpx SSR search is blocked, this module drives a persistent,
in-process ``nodriver`` Chrome (which solves the JS challenge in-container under
Xvfb) to fetch the search-results page and returns its HTML. The GraphQL
client's existing ``__NEXT_DATA__`` parser then extracts products, so the browser
is only responsible for *fetching* the page — cart operations still go over
``/graphql``.

A single browser is launched lazily and reused (warm) across searches, guarded
by an ``asyncio`` lock, with a short-TTL cache keyed on ``(store_id, query)``.
"""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING, Any
from urllib.parse import quote_plus

import structlog

if TYPE_CHECKING:  # pragma: no cover - typing only
    import nodriver

logger = structlog.get_logger()

_SEARCH_URL = "https://www.heb.com/search?q={query}"
# The server-rendered results page always embeds this script tag; a challenge
# interstitial never does. Polling for it is how we know the page resolved.
_NEXT_DATA_MARKER = 'id="__NEXT_DATA__"'
# How long to wait for the browser to clear the challenge and render results.
_RENDER_TIMEOUT_SECONDS = 30.0
_POLL_INTERVAL_SECONDS = 1.0
# Default cache lifetime for a (store, query) HTML result.
_DEFAULT_CACHE_TTL_SECONDS = 120.0


class NodriverSearchError(Exception):
    """Raised when the nodriver browser search fails irrecoverably."""


class NodriverSearchClient:
    """Persistent in-process nodriver browser used as a search fallback.

    The browser is launched on first use and reused for subsequent searches.
    Authenticated HEB cookies from the exported session are injected so the
    server renders store-context pricing.
    """

    def __init__(self, *, cache_ttl: float = _DEFAULT_CACHE_TTL_SECONDS) -> None:
        self._browser: nodriver.Browser | None = None
        self._lock = asyncio.Lock()
        self._cache: dict[str, tuple[float, str]] = {}
        self._cache_ttl = cache_ttl

    # ------------------------------------------------------------------
    # Browser lifecycle
    # ------------------------------------------------------------------
    async def _ensure_browser(self) -> nodriver.Browser:
        """Launch the browser once (warm) and inject session cookies."""
        if self._browser is not None:
            return self._browser

        # Reuse the maintained nodriver launcher (Xvfb / --no-sandbox aware).
        from auto_grocer.session_maintenance.browser import start_browser

        logger.info("Launching in-process nodriver browser for search fallback")
        browser = await start_browser(headless=False)
        self._browser = browser
        try:
            await self._inject_session_cookies(browser)
        except Exception as exc:  # noqa: BLE001 - cookie injection is best-effort
            logger.warning("Failed to inject session cookies into browser", error=str(exc))
        return browser

    async def _inject_session_cookies(self, browser: nodriver.Browser) -> None:
        """Load the exported HEB session cookies into the browser.

        Converts the Playwright-format cookies persisted in ``auth.json`` into
        CDP ``CookieParam`` objects so the rendered page carries the same
        authenticated session the httpx client uses.
        """
        from auto_grocer_mcp.auth.session import get_cookies

        cookies = get_cookies()
        if not cookies:
            logger.debug("No session cookies to inject into browser")
            return

        import nodriver.cdp.network as cdp_network

        params: list[Any] = []
        for cookie in cookies:
            name = cookie.get("name")
            value = cookie.get("value")
            if not name or value is None:
                continue

            kwargs: dict[str, Any] = {
                "name": str(name),
                "value": str(value),
                "domain": cookie.get("domain") or ".heb.com",
                "path": cookie.get("path") or "/",
                "secure": bool(cookie.get("secure", True)),
                "http_only": bool(cookie.get("httpOnly", False)),
            }
            expires = cookie.get("expires", -1)
            try:
                expires_f = float(expires)
            except (TypeError, ValueError):
                expires_f = -1.0
            if expires_f and expires_f > 0:
                kwargs["expires"] = expires_f

            params.append(cdp_network.CookieParam(**kwargs))

        if params:
            await browser.cookies.set_all(params)
            logger.debug("Injected session cookies into browser", count=len(params))

    async def close(self) -> None:
        """Stop the browser, ignoring shutdown errors."""
        browser = self._browser
        self._browser = None
        if browser is None:
            return
        try:
            browser.stop()
        except Exception:  # noqa: BLE001 - best-effort shutdown
            pass

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------
    async def search_html(self, query: str, store_id: str) -> str | None:
        """Return the search-results page HTML for ``query`` (or ``None``).

        Results are cached for a short TTL keyed on ``(store_id, query)`` to
        avoid re-driving the browser for repeated searches within a session.
        """
        key = f"{store_id}::{query.strip().lower()}"

        cached = self._cache.get(key)
        if cached and (time.monotonic() - cached[0]) < self._cache_ttl:
            logger.debug("nodriver search cache hit", query=query, store_id=store_id)
            return cached[1]

        # Serialize browser access: a single Chrome tab drives all searches.
        async with self._lock:
            cached = self._cache.get(key)
            if cached and (time.monotonic() - cached[0]) < self._cache_ttl:
                return cached[1]

            html = await self._fetch_search_html(query)
            if html:
                self._cache[key] = (time.monotonic(), html)
            return html

    async def _fetch_search_html(self, query: str) -> str | None:
        """Navigate to the search page and return HTML once it renders."""
        browser = await self._ensure_browser()
        url = _SEARCH_URL.format(query=quote_plus(query))

        logger.info("nodriver browser search", url=url)
        tab = await browser.get(url)

        deadline = time.monotonic() + _RENDER_TIMEOUT_SECONDS
        html = ""
        while time.monotonic() < deadline:
            try:
                html = await tab.get_content() or ""
            except Exception:  # noqa: BLE001 - transient during navigation/challenge
                html = ""
            if _NEXT_DATA_MARKER in html:
                logger.info("nodriver search rendered results", query=query)
                return html
            await tab.sleep(_POLL_INTERVAL_SECONDS)

        logger.warning(
            "nodriver search timed out waiting for results",
            query=query,
            response_length=len(html),
        )
        return html or None


_client: NodriverSearchClient | None = None


def get_nodriver_search_client() -> NodriverSearchClient:
    """Return the process-wide nodriver search client (lazily created)."""
    global _client
    if _client is None:
        _client = NodriverSearchClient()
    return _client
