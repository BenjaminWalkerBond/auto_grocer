"""HEB API client using persisted queries and Next.js data endpoints.

Supports both unauthenticated (typeahead) and authenticated (full product search)
modes. Authenticated mode uses browser session cookies for faster API access.
"""

import json
import os
import re
import threading
import time
from collections.abc import Callable
from typing import Any, cast

import httpx
import structlog

from auto_grocer_mcp.auth.session import get_httpx_cookies, is_authenticated
from auto_grocer_mcp.models import (
    Coupon,
    CouponCategory,
    CouponSearchResult,
    GeocodedLocation,
    NutrientInfo,
    Product,
    ProductDetails,
    ProductSearchAttempt,
    ProductSearchResult,
    SearchAttempt,
    Store,
    StoreSearchResult,
)
from auto_grocer_mcp.reliability import (
    CircuitBreaker,
    RetryConfig,
    ThrottleConfig,
    Throttler,
    TTLCache,
    with_retry,
)
from auto_grocer_mcp.services.geocoding import GeocodingResult, GeocodingService
from auto_grocer_mcp.utils.config import get_settings

logger = structlog.get_logger()


class GraphQLError(Exception):
    """Raised when GraphQL returns errors."""

    def __init__(self, errors: list[dict[str, Any]]):
        self.errors = errors
        messages = [e.get("message", "Unknown error") for e in errors]
        super().__init__(f"GraphQL error: {'; '.join(messages)}")


class PersistedQueryNotFoundError(Exception):
    """Raised when a persisted query hash is not found on the server."""

    pass


# Persisted Query Hashes (discovered via reverse engineering)
# These may change when HEB deploys new code
PERSISTED_QUERIES = {
    "ShopNavigation": "0e669423cef683226cb8eb295664619c8e0f95945734e0a458095f51ee89efb3",
    "alertEntryPoint": "3e3ccd248652e8fce4674d0c5f3f30f2ddc63da277bfa0ff36ea9420e5dffd5e",
    "cartEstimated": "7b033abaf2caa80bc49541e51d2b89e3cc6a316e37c4bd576d9b5c498a51e9c5",
    "typeaheadContent": "1ed956c0f10efcfc375321f33c40964bc236fff1397a4e86b7b53cb3b18ad329",
    "cartItemV2": "ade8ec1365c185244d42f9cc4c13997fec4b633ac3c38ff39558df92b210c6d0",
    "StoreSearch": "e01fa39e66c3a2c7881322bc48af6a5af97d49b1442d433f2d09d273de2db4b6",
    "CouponClip": "88b18ac22cee98372428d9a91d759ffb5e919026ee61c747f9f88d11336b846b",
    # Store change mutation - changes the active pickup store
    "SelectPickupFulfillment": "8fa3c683ee37ad1bab9ce22b99bd34315b2a89cfc56208d63ba9efc0c49a6323",
}


def _load_persisted_query_overrides() -> None:
    """Merge freshly captured persisted-query hashes into PERSISTED_QUERIES.

    HEB rotates these sha256 hashes whenever it deploys new front-end code,
    which invalidates the hard-coded values above. The ``update_graphql_hashes``
    program mode captures current hashes from a live browser session and writes
    them to a JSON file. This loader applies that file (if present) so the
    client always uses the latest known hashes.

    Override file location (first match wins):
      1. ``GRAPHQL_HASHES_PATH`` environment variable
      2. ``~/.texas-grocery-mcp/persisted_queries.json``
    """
    import json
    import os
    from pathlib import Path

    candidate = os.environ.get("GRAPHQL_HASHES_PATH")
    path = Path(candidate).expanduser() if candidate else (
        Path("~/.texas-grocery-mcp/persisted_queries.json").expanduser()
    )

    if not path.exists():
        return

    try:
        with open(path, encoding="utf-8") as f:
            overrides = json.load(f)
    except (json.JSONDecodeError, OSError):
        return

    if isinstance(overrides, dict):
        for name, value in overrides.items():
            if isinstance(name, str) and isinstance(value, str) and value:
                PERSISTED_QUERIES[name] = value


# Apply any captured hash overrides at import time.
_load_persisted_query_overrides()


# ---------------------------------------------------------------------------
# Full GraphQL query documents (Apollo APQ registration)
# ---------------------------------------------------------------------------
# HEB uses Apollo Automatic Persisted Queries: a sha256 hash only resolves while
# the server has the matching query registered in its shared APQ cache. High-
# traffic operations (product/store search) stay resident, but low-traffic ones
# (notably ``SelectPickupFulfillment``, the store-change mutation) get evicted,
# after which HEB returns ``PersistedQueryNotFound`` for EVERY hash value -- so
# capturing a "fresh" hash never helps. The fix is standard APQ recovery: resend
# the request with the full ``query`` text, which re-registers it and executes.
#
# The capture flow now records the full query text (sniffed on the browser's APQ
# registration MISS) into ``captured_operations.json``; this loads those docs so
# the client can perform the registration round-trip itself.
PERSISTED_QUERY_DOCUMENTS: dict[str, str] = {}

# Operations for which an automatic browser hash-refresh cannot help: the failure
# is APQ registration (evicted query), not a rotated hash. For these we fail fast
# with clear guidance instead of launching a doomed multi-minute browser capture.
_APQ_ONLY_OPERATIONS = {"SelectPickupFulfillment"}


def _load_persisted_query_documents() -> None:
    """Load captured full-query documents for APQ registration.

    Reads ``captured_operations.json`` (same directory as the hash overrides)
    and populates ``PERSISTED_QUERY_DOCUMENTS`` with every operation that has a
    non-empty ``query`` string.

    Override file location (first match wins):
      1. ``GRAPHQL_OPERATIONS_PATH`` environment variable
      2. ``~/.texas-grocery-mcp/captured_operations.json``
    """
    import json
    import os
    from pathlib import Path

    candidate = os.environ.get("GRAPHQL_OPERATIONS_PATH")
    path = Path(candidate).expanduser() if candidate else (
        Path("~/.texas-grocery-mcp/captured_operations.json").expanduser()
    )

    if not path.exists():
        return

    try:
        with open(path, encoding="utf-8") as f:
            operations = json.load(f)
    except (json.JSONDecodeError, OSError):
        return

    if isinstance(operations, dict):
        for name, entry in operations.items():
            if not isinstance(name, str) or not isinstance(entry, dict):
                continue
            query = entry.get("query")
            if isinstance(query, str) and query.strip():
                PERSISTED_QUERY_DOCUMENTS[name] = query


# Apply any captured query documents at import time.
_load_persisted_query_documents()


def reload_persisted_query_overrides() -> None:
    """Public helper to re-apply hash overrides after they are updated."""
    _load_persisted_query_overrides()
    _load_persisted_query_documents()


# ---------------------------------------------------------------------------
# Automatic stale-hash recovery
# ---------------------------------------------------------------------------
# HEB rotates its persisted-query hashes on every front-end deploy. When a
# rotation happens, every persisted query starts failing with
# ``PersistedQueryNotFound`` until fresh hashes are captured. Rather than surface
# the failure to the user and wait for a manual ``capture_hashes`` run, the
# client can invoke a registered callback that re-captures the hashes, reload the
# updated overrides, and transparently retry the failed operation.
#
# The high-level MCP layer (``auto_grocer.mcp_server``) registers the browser
# ``capture_hashes`` flow as this callback at import time. The callback is a
# *blocking* subprocess that drives a real browser and can take minutes -- far
# longer than an MCP client's tool-call timeout (observed ~240s). So the
# refresh is dispatched to a plain background thread that is NOT awaited: the
# triggering operation fails fast with a "refresh in progress, retry shortly"
# error instead of blocking until the capture finishes. A cooldown lets
# operations that fail shortly after a successful refresh retry immediately
# instead of re-triggering a capture. The callback receives the operation name
# so the refresh can target just the flow needed for that operation instead of
# walking every flow (see auto_grocer.session_maintenance.run).
_hash_refresh_callback: Callable[[str], bool] | None = None
_hash_refresh_state_lock = threading.Lock()
_hash_refresh_in_progress: bool = False
_last_hash_refresh_monotonic: float = 0.0
_HASH_REFRESH_COOLDOWN_SECONDS: float = float(
    os.environ.get("AUTO_GROCER_HASH_REFRESH_COOLDOWN", "600")
)


def register_hash_refresh_callback(callback: Callable[[str], bool] | None) -> None:
    """Register a callback used to re-capture rotated persisted-query hashes.

    The callback receives the stale operation's name and runs synchronously (it
    drives a browser via subprocess), returning ``True`` when fresh hashes were
    captured. It is invoked from a background thread, never awaited directly.
    Pass ``None`` to disable automatic recovery. Intended to be called once
    from the MCP server layer.
    """
    global _hash_refresh_callback
    _hash_refresh_callback = callback


def _run_hash_refresh(operation_name: str) -> None:
    """Run the registered callback on a background thread and record the result."""
    global _last_hash_refresh_monotonic, _hash_refresh_in_progress

    callback = _hash_refresh_callback
    ok = False
    try:
        if callback is not None:
            ok = bool(callback(operation_name))
    except Exception as exc:  # noqa: BLE001 - refresh is best-effort
        logger.error(
            "Background hash refresh raised", operation=operation_name, error=str(exc)
        )
        ok = False
    finally:
        with _hash_refresh_state_lock:
            _hash_refresh_in_progress = False
            if ok:
                _last_hash_refresh_monotonic = time.monotonic()
        reload_persisted_query_overrides()
        if ok:
            logger.info("Background hash refresh completed", operation=operation_name)
        else:
            logger.error(
                "Background hash refresh did not resolve hashes", operation=operation_name
            )


async def _attempt_hash_refresh(operation_name: str) -> str:
    """React to a stale persisted-query hash without blocking the caller.

    Never awaits the (multi-minute, browser-driven) refresh. Returns one of:

        "retry"       - hashes were refreshed very recently (within the
                        cooldown); overrides reloaded, caller should retry now.
        "started"     - no refresh was running; one was just launched on a
                        background thread. Caller should fail fast.
        "in_progress" - a refresh triggered by an earlier operation is still
                        running. Caller should fail fast.
        "disabled"    - no callback registered; caller should raise the
                        original stale-hash error unchanged.
    """
    global _hash_refresh_in_progress

    with _hash_refresh_state_lock:
        now = time.monotonic()
        # A refresh may have completed very recently (triggered by another
        # operation); reuse it instead of starting another capture. Checked
        # BEFORE the "no callback" bail-out so a cooldown grant still lets a
        # caller retry even if nothing is currently registered.
        if _last_hash_refresh_monotonic and (
            now - _last_hash_refresh_monotonic
        ) < _HASH_REFRESH_COOLDOWN_SECONDS:
            status = "retry"
        elif _hash_refresh_callback is None:
            status = "disabled"
        elif _hash_refresh_in_progress:
            status = "in_progress"
        else:
            _hash_refresh_in_progress = True
            status = "started"

    if status == "retry":
        logger.info(
            "Reusing recent hash refresh within cooldown; retrying operation",
            operation=operation_name,
        )
        reload_persisted_query_overrides()
        return status

    if status == "in_progress":
        logger.info(
            "Hash refresh already running in background; failing fast",
            operation=operation_name,
        )
        return status

    if status == "disabled":
        return status

    logger.warning(
        "Stale GraphQL persisted-query hash detected; triggering background hash refresh",
        operation=operation_name,
    )
    threading.Thread(
        target=_run_hash_refresh,
        args=(operation_name,),
        name="hash-refresh",
        daemon=True,
    ).start()
    return status


# Well-known HEB stores (fallback for store search)
KNOWN_STORES = {
    "737": Store(
        store_id="737",
        name="The Heights H-E-B",
        address="2300 N. SHEPHERD DR., HOUSTON, TX 77008",
        phone="(713) 802-9090",
        latitude=29.8028,
        longitude=-95.4103,
    ),
    "579": Store(
        store_id="579",
        name="Buffalo Speedway H-E-B",
        address="5601 S BRAESWOOD BLVD, HOUSTON, TX 77096",
        phone="(713) 432-1400",
        latitude=29.6916,
        longitude=-95.4587,
    ),
    "150": Store(
        store_id="150",
        name="Montrose H-E-B",
        address="1701 W ALABAMA ST, HOUSTON, TX 77098",
        phone="(713) 523-4481",
        latitude=29.7419,
        longitude=-95.3979,
    ),
}


class HEBGraphQLClient:
    """Client for HEB's API using persisted queries and Next.js data endpoints.

    Supports two modes:
    - Unauthenticated: Basic operations like typeahead (always available)
    - Authenticated: Full product search and cart operations (requires cookies)
    """

    # Standard headers for browser-like requests
    _BROWSER_HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
        "Origin": "https://www.heb.com",
        "Referer": "https://www.heb.com/",
    }

    def __init__(self, base_url: str | None = None):
        settings = get_settings()
        self.base_url = base_url or settings.heb_graphql_url
        self.circuit_breaker = CircuitBreaker("heb_api")
        self._client: httpx.AsyncClient | None = None
        self._auth_client: httpx.AsyncClient | None = None
        self._build_id: str | None = None

        # Initialize throttlers for rate limiting
        self._ssr_throttler = Throttler(
            ThrottleConfig(
                max_concurrent=settings.max_concurrent_ssr_searches,
                min_delay_ms=settings.min_ssr_delay_ms,
                jitter_ms=settings.ssr_jitter_ms,
                enabled=settings.throttling_enabled,
            ),
            name="ssr",
        )
        self._graphql_throttler = Throttler(
            ThrottleConfig(
                max_concurrent=settings.max_concurrent_graphql,
                min_delay_ms=settings.min_graphql_delay_ms,
                jitter_ms=settings.graphql_jitter_ms,
                enabled=settings.throttling_enabled,
            ),
            name="graphql",
        )

        # Initialize cache for product details (24-hour TTL)
        self._product_details_cache: TTLCache[ProductDetails] = TTLCache(
            ttl_hours=24,
            max_size=500,  # Cache up to 500 products
        )

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create basic HTTP client (no auth cookies)."""
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(30.0),
                headers={
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                    **self._BROWSER_HEADERS,
                },
                follow_redirects=True,
            )
        return self._client

    async def _get_authenticated_client(self) -> httpx.AsyncClient | None:
        """Get HTTP client with authentication cookies.

        Returns:
            Authenticated client if cookies available, None otherwise
        """
        if not is_authenticated():
            return None

        # Always recreate to get fresh cookies
        if self._auth_client:
            await self._auth_client.aclose()

        cookies = get_httpx_cookies()
        if not cookies:
            return None

        self._auth_client = httpx.AsyncClient(
            timeout=httpx.Timeout(30.0),
            headers=self._BROWSER_HEADERS,
            cookies=cookies,
            follow_redirects=True,
        )

        logger.debug("Created authenticated client", cookie_count=len(cookies))
        return self._auth_client

    async def close(self) -> None:
        """Close HTTP clients."""
        if self._client:
            await self._client.aclose()
            self._client = None
        if self._auth_client:
            await self._auth_client.aclose()
            self._auth_client = None

    async def _get_build_id(self) -> str:
        """Extract Next.js build ID from HEB homepage.

        The build ID is required for accessing _next/data endpoints.
        It changes with each deployment.

        Uses authenticated client when available to bypass WAF challenges.
        """
        if self._build_id:
            return self._build_id

        # Prefer authenticated client to bypass WAF/security challenges
        client = await self._get_authenticated_client()
        if not client:
            client = await self._get_client()

        response = await client.get("https://www.heb.com")
        response.raise_for_status()

        # Check for security challenge
        if self._detect_security_challenge(response.text):
            logger.warning("Security challenge detected when fetching build ID")
            raise RuntimeError(
                "Security challenge blocked build ID extraction. Try session_refresh."
            )

        # Look for build ID in the HTML
        # Pattern: /_next/static/{buildId}/_buildManifest.js
        match = re.search(r'/_next/static/([a-zA-Z0-9_-]+)/_buildManifest\.js', response.text)
        if match:
            self._build_id = match.group(1)
            logger.info("Extracted Next.js build ID", build_id=self._build_id)
            return self._build_id

        # Fallback: try to find it in data-nscript tags
        match = re.search(r'"buildId":"([a-zA-Z0-9_-]+)"', response.text)
        if match:
            self._build_id = match.group(1)
            logger.info("Extracted Next.js build ID from JSON", build_id=self._build_id)
            return self._build_id

        # Log the response for debugging
        logger.error(
            "Could not extract build ID",
            response_length=len(response.text),
            response_preview=response.text[:500] if response.text else "empty",
        )
        raise RuntimeError("Could not extract Next.js build ID from HEB homepage")

    @with_retry(config=RetryConfig(max_attempts=3, base_delay=1.0))
    async def _execute_persisted_query(
        self,
        operation_name: str,
        variables: dict[str, Any],
    ) -> dict[str, Any]:
        """Execute a persisted GraphQL query.

        Args:
            operation_name: The name of the persisted operation
            variables: Query variables

        Returns:
            Response data

        Raises:
            GraphQLError: If GraphQL returns errors
            PersistedQueryNotFoundError: If the hash is not recognized
            CircuitBreakerOpenError: If circuit is open
        """
        async with self._graphql_throttler:
            self.circuit_breaker.check()

            if operation_name not in PERSISTED_QUERIES:
                raise ValueError(f"Unknown operation: {operation_name}")

            client = await self._get_client()

            refreshed = False
            apq_tried = False
            while True:
                payload = {
                    "operationName": operation_name,
                    "variables": variables,
                    "extensions": {
                        "persistedQuery": {
                            "version": 1,
                            "sha256Hash": PERSISTED_QUERIES[operation_name],
                        }
                    },
                }
                # APQ registration round-trip: include the full query text so HEB
                # re-registers + executes an operation evicted from its APQ cache.
                if apq_tried and operation_name in PERSISTED_QUERY_DOCUMENTS:
                    payload["query"] = PERSISTED_QUERY_DOCUMENTS[operation_name]

                try:
                    response = await client.post(self.base_url, json=payload)
                    response.raise_for_status()

                    data: Any = response.json()

                    # Check for persisted query errors
                    if "errors" in data:
                        for error in data["errors"]:
                            if "PersistedQueryNotFound" in str(error):
                                raise PersistedQueryNotFoundError(
                                    f"Persisted query hash for '{operation_name}' is no longer valid"
                                )

                        raise GraphQLError(data["errors"])

                    self.circuit_breaker.record_success()

                    if isinstance(data, dict):
                        payload_data = data.get("data")
                        if isinstance(payload_data, dict):
                            return cast(dict[str, Any], payload_data)
                    return {}

                except PersistedQueryNotFoundError as e:
                    # 1) APQ full-query fallback (no browser): resend WITH the
                    #    captured query document to register + execute.
                    if not apq_tried and operation_name in PERSISTED_QUERY_DOCUMENTS:
                        apq_tried = True
                        logger.info(
                            "Retrying with full query (APQ registration)",
                            operation=operation_name,
                        )
                        continue
                    # 2) Operations a browser hash-refresh cannot fix: fail fast.
                    if operation_name in _APQ_ONLY_OPERATIONS:
                        raise PersistedQueryNotFoundError(
                            f"'{operation_name}' could not be resolved. Its full query "
                            "document has not been captured yet, so an automatic hash "
                            "refresh cannot help (the query is evicted from HEB's APQ "
                            "cache). Run the capture_hashes tool once - it now records "
                            "the query document - then retry."
                        ) from e
                    # 3) Rotated-hash path: non-blocking background hash refresh.
                    status = None if refreshed else await _attempt_hash_refresh(operation_name)
                    if status == "retry":
                        refreshed = True
                        logger.info(
                            "Retrying persisted query after hash refresh",
                            operation=operation_name,
                        )
                        continue
                    if status in ("started", "in_progress"):
                        raise PersistedQueryNotFoundError(
                            f"Persisted query hash for '{operation_name}' is stale; a "
                            "hash refresh has "
                            + ("just started" if status == "started" else "already been triggered")
                            + " in the background. Retry this operation in about "
                            "60-90 seconds."
                        ) from e
                    raise

                except (httpx.HTTPError, GraphQLError) as e:
                    self.circuit_breaker.record_failure()
                    logger.error(
                        "Persisted query failed",
                        operation=operation_name,
                        error=str(e),
                    )
                    raise

    @with_retry(config=RetryConfig(max_attempts=3, base_delay=1.0))
    async def _fetch_nextjs_data(
        self,
        path: str,
        params: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Fetch data from Next.js _next/data endpoint.

        Args:
            path: The page path (e.g., "search" for /search)
            params: Query parameters

        Returns:
            Page props data
        """
        self.circuit_breaker.check()

        build_id = await self._get_build_id()
        client = await self._get_client()

        url = f"https://www.heb.com/_next/data/{build_id}/en/{path}.json"

        try:
            response = await client.get(url, params=params)
            response.raise_for_status()

            data: Any = response.json()
            self.circuit_breaker.record_success()

            # Next.js data is wrapped in pageProps
            if not isinstance(data, dict):
                return {}

            page_props = data.get("pageProps")
            if isinstance(page_props, dict):
                return cast(dict[str, Any], page_props)
            return cast(dict[str, Any], data)

        except httpx.HTTPError as e:
            self.circuit_breaker.record_failure()
            logger.error(
                "Next.js data fetch failed",
                path=path,
                error=str(e),
            )
            raise

    async def search_stores(
        self,
        address: str,
        radius_miles: int = 25,
    ) -> StoreSearchResult:
        """Search for HEB stores near an address.

        Uses geocoding to handle informal location queries (neighborhoods,
        landmarks) and tries multiple query variations against HEB's API.

        Args:
            address: Address, zip code, neighborhood, or landmark to search near
            radius_miles: Search radius in miles

        Returns:
            StoreSearchResult with stores, geocoded location, and search feedback
        """
        logger.info(
            "Searching for stores",
            address=address,
            radius_miles=radius_miles,
        )

        attempts: list[SearchAttempt] = []
        geocoded: GeocodedLocation | None = None
        geocoding_result: GeocodingResult | None = None

        # Step 1: Geocode the address
        geocoding_service = GeocodingService()
        try:
            geocoding_result = await geocoding_service.geocode(address)
            if geocoding_result:
                geocoded = GeocodedLocation(
                    latitude=geocoding_result.latitude,
                    longitude=geocoding_result.longitude,
                    display_name=geocoding_result.display_name,
                )
                logger.info(
                    "Geocoding successful",
                    address=address,
                    lat=geocoding_result.latitude,
                    lon=geocoding_result.longitude,
                )
        except Exception as e:
            logger.warning("Geocoding failed", address=address, error=str(e))
        finally:
            await geocoding_service.close()

        # Step 2: Generate query variations
        if geocoding_result:
            query_variations = geocoding_result.get_query_variations(address)
        else:
            # Geocoding failed - just try the original query
            query_variations = [address]

        # Step 3: Try each query variation until we get results
        stores: list[Store] = []
        for query in query_variations:
            try:
                result_stores = await self._execute_store_search(query, radius_miles)
                attempts.append(SearchAttempt(
                    query=query,
                    result="success" if result_stores else "no_stores",
                ))

                if result_stores:
                    stores = result_stores
                    logger.info(
                        "Store search successful",
                        query=query,
                        result_count=len(stores),
                    )
                    break

            except Exception as e:
                logger.warning(
                    "Store search query failed",
                    query=query,
                    error=str(e),
                )
                attempts.append(SearchAttempt(query=query, result="error"))
                continue

        # Step 4: Calculate distances from geocoded point and sort
        if stores and geocoding_result:
            for store in stores:
                if store.latitude is not None and store.longitude is not None:
                    store.distance_miles = GeocodingService.haversine_miles(
                        geocoding_result.latitude,
                        geocoding_result.longitude,
                        store.latitude,
                        store.longitude,
                    )
            # Sort by calculated distance
            stores.sort(
                key=lambda s: (
                    s.distance_miles
                    if s.distance_miles is not None
                    else float("inf")
                )
            )

        # Step 5: Build response with feedback
        error: str | None = None
        suggestions: list[str] = []

        if not stores:
            if not geocoding_result:
                error = f"Couldn't locate '{address}'. Try a zip code or street address."
                suggestions = [
                    "Use a Texas zip code (e.g., 77007)",
                    "Try a specific street address",
                ]
            else:
                location = geocoded.display_name if geocoded else address
                error = (
                    f"No HEB stores found within {radius_miles} miles of {location}."
                )
                suggestions = [
                    "HEB operates primarily in Texas",
                    "Try increasing the search radius",
                    "Verify this is a Texas location",
                ]

        return StoreSearchResult(
            stores=stores,
            count=len(stores),
            search_address=address,
            geocoded=geocoded,
            attempts=attempts,
            error=error,
            suggestions=suggestions,
        )

    async def _execute_store_search(
        self,
        query: str,
        radius_miles: int,
    ) -> list[Store]:
        """Execute a single store search query against HEB's API.

        Args:
            query: Search query (zip, city/state, or address)
            radius_miles: Search radius in miles

        Returns:
            List of stores (may be empty)
        """
        data = await self._execute_persisted_query(
            "StoreSearch",
            {
                "address": query,
                "radius": radius_miles,
                "fulfillmentChannels": [],
                "includeEcommInactive": False,
                "retailFormatCodes": ["P", "NP"],
            },
        )

        stores = []
        # API returns data in searchStoresByAddress.stores (not storeSearch)
        store_search_data = data.get("searchStoresByAddress", {}) or data.get("storeSearch", {})
        store_list = store_search_data.get("stores", [])

        for store_result in store_list:
            try:
                store = self._parse_store_result(store_result)
                if store:
                    stores.append(store)
            except Exception as e:
                logger.debug("Failed to parse store data", error=str(e))
                continue

        return stores

    def _parse_store_result(self, store_result: dict[str, Any]) -> Store | None:
        """Parse store result from searchStoresByAddress response.

        The API returns results with distanceMiles at top level and
        store details nested in a 'store' object.

        Args:
            store_result: Store result dict from GraphQL response

        Returns:
            Store object or None if parsing fails
        """
        # Distance is at the top level
        distance = store_result.get("distanceMiles")

        # Store details are nested
        store_data = store_result.get("store", store_result)

        store_id = store_data.get("storeNumber") or store_data.get("id")
        if not store_id:
            return None

        name = store_data.get("name", "")

        # Build address from components (new format uses streetAddress/locality/region)
        address_obj = store_data.get("address", {})
        address_parts = []

        street = address_obj.get("streetAddress") or store_data.get("address1", "")
        if street:
            address_parts.append(street)

        city = address_obj.get("locality") or store_data.get("city", "")
        state = address_obj.get("region") or store_data.get("state", "")
        postal_code = address_obj.get("postalCode") or store_data.get("postalCode", "")

        if city and state:
            address_parts.append(f"{city}, {state} {postal_code}".strip())

        address = ", ".join(address_parts) if address_parts else ""

        # Extract coordinates
        latitude = store_data.get("latitude")
        longitude = store_data.get("longitude")

        # Extract fulfillment channels to determine curbside/delivery support
        # API returns data in storeFulfillments array with objects like {"name": "CURBSIDE_PICKUP"}
        store_fulfillments = store_data.get("storeFulfillments", None)
        if store_fulfillments is not None:
            # Build list of fulfillment channel names
            fulfillment_names = [
                f.get("name", "")
                for f in store_fulfillments
                if isinstance(f, dict)
            ]
            # Curbside = any fulfillment containing "CURBSIDE" (CURBSIDE_PICKUP, CURBSIDE_DELIVERY)
            supports_curbside = any("CURBSIDE" in name for name in fulfillment_names)
            # Delivery = ALCOHOL_DELIVERY or DELIVERY channel
            supports_delivery = any(
                "DELIVERY" in name and "CURBSIDE" not in name
                for name in fulfillment_names
            )
        else:
            # Legacy format: check fulfillmentChannels array of strings
            fulfillment_channels = store_data.get("fulfillmentChannels", None)
            if fulfillment_channels is not None:
                supports_curbside = (
                    "PICKUP" in fulfillment_channels
                    or "CURBSIDE" in fulfillment_channels
                )
                supports_delivery = "DELIVERY" in fulfillment_channels
            else:
                # No fulfillment data - default to True for curbside (most stores support it)
                supports_curbside = True
                supports_delivery = False

        return Store(
            store_id=str(store_id),
            name=name,
            address=address,
            phone=store_data.get("phone", ""),
            latitude=float(latitude) if latitude else None,
            longitude=float(longitude) if longitude else None,
            distance_miles=float(distance) if distance else None,
            supports_curbside=supports_curbside,
            supports_delivery=supports_delivery,
        )

    def _parse_store_data(self, store_data: dict[str, Any]) -> Store | None:
        """Parse store data from legacy StoreSearch response format.

        Args:
            store_data: Store dict from GraphQL response

        Returns:
            Store object or None if parsing fails
        """
        store_id = store_data.get("id") or store_data.get("storeNumber")
        if not store_id:
            return None

        name = store_data.get("name", "")

        # Build address from components
        address_obj = store_data.get("address") or {}
        address_parts = []
        address1 = store_data.get("address1") or address_obj.get("address1", "")
        if address1:
            address_parts.append(address1)

        city = store_data.get("city") or address_obj.get("city", "")
        state = store_data.get("state") or address_obj.get("state", "")
        postal_code = store_data.get("postalCode") or address_obj.get("postalCode", "")

        if city and state:
            address_parts.append(f"{city}, {state} {postal_code}".strip())

        address = ", ".join(address_parts) if address_parts else ""

        # Extract coordinates
        latitude = store_data.get("latitude") or store_data.get("location", {}).get("latitude")
        longitude = store_data.get("longitude") or store_data.get("location", {}).get("longitude")

        # Extract distance if available
        distance = store_data.get("distance") or store_data.get("distanceFromSearchLocation")

        return Store(
            store_id=str(store_id),
            name=name,
            address=address,
            phone=store_data.get("phone", ""),
            latitude=float(latitude) if latitude else None,
            longitude=float(longitude) if longitude else None,
            distance_miles=float(distance) if distance else None,
        )

    def _generate_query_variations(self, query: str) -> list[str]:
        """Generate query variations to improve search results.

        HEB's search is sensitive to exact query wording. This generates
        variations to try when the original query returns no results.

        Args:
            query: Original search query

        Returns:
            List of query variations to try (original query first)
        """
        variations = [query]  # Always try original first
        query_lower = query.lower()

        # Expand common abbreviations
        expanded = query
        abbreviations = {
            "ny ": "new york ",
            "NY ": "New York ",
            "heb ": "H-E-B ",
            "HEB ": "H-E-B ",
        }
        for abbrev, full in abbreviations.items():
            if abbrev.lower() in query_lower:
                expanded = query.replace(abbrev.strip(), full.strip())
                if expanded != query:
                    variations.append(expanded)
                break

        # Add "Meal Simple" prefix for meal-related queries
        meal_keywords = ["steak", "chicken", "salmon", "pork", "beef", "shrimp",
                         "asparagus", "potato", "meatloaf", "alfredo", "enchilada",
                         "jambalaya", "bowl", "dinner", "entree"]
        if (
            any(kw in query_lower for kw in meal_keywords)
            and "meal simple" not in query_lower
        ):
            variations.append(f"Meal Simple {query}")

        # Add "H-E-B" prefix if not present
        if "h-e-b" not in query_lower and "heb" not in query_lower:
            variations.append(f"H-E-B {query}")

        # Remove duplicates while preserving order
        seen = set()
        unique_variations = []
        for v in variations:
            v_lower = v.lower()
            if v_lower not in seen:
                seen.add(v_lower)
                unique_variations.append(v)

        return unique_variations

    def _detect_security_challenge(self, html: str) -> bool:
        """Detect if a response is a WAF/captcha security challenge page.

        HEB uses Incapsula (Imperva) WAF, which may return an interstitial
        challenge page instead of real content when bot detection is triggered.

        Naive substring matching produces false positives: HEB injects an inline
        Incapsula telemetry ``<script src="/_Incapsula_Resource?...">`` and the
        strings "incapsula"/"reese84" into EVERY normal page. So we only treat a
        response as a challenge when it (a) lacks the hallmarks of a real HEB page,
        and (b) either carries an unambiguous block phrase or is a minimal-content
        interstitial that references a challenge resource.

        Args:
            html: Response HTML content

        Returns:
            True if the response appears to be a security challenge
        """
        html_lower = html.lower()

        # (a) If the page has several hallmarks of a real HEB page, it is NOT a
        # challenge interstitial even if some indicator strings are present.
        normal_page_indicators = (
            "heb.com",
            "add to cart",
            "my cart",
            "my account",
            "curbside",
            "delivery",
            "weekly ad",
            "shop now",
            "products",
            "<nav",
            "<header",
            "data-testid",
            "__next_data__",
        )
        normal_indicator_count = sum(1 for ind in normal_page_indicators if ind in html_lower)
        if normal_indicator_count >= 3:
            return False

        # (b) Unambiguous block phrases that appear ONLY on challenge/interstitial
        # pages (never on a normal storefront page).
        strong_challenge_indicators = (
            "incapsula incident id",
            "request unsuccessful",
            "please verify you are a human",
            "enable javascript and cookies",
            "sorry, you have been blocked",
            "access denied",
            "checking your browser",
            "please wait while we verify",
            "pardon our interruption",
            "just a moment",
            "ray id:",
            "why have i been blocked",
            "this website is using a security service",
        )
        if any(indicator in html_lower for indicator in strong_challenge_indicators):
            return True

        # (c) Weak markers only count on minimal-content pages: a real HEB page is
        # tens/hundreds of KB, an interstitial is tiny and sparse.
        is_minimal_content = len(html) < 5000
        weak_challenge_indicators = (
            "_incapsula_resource",
            "challenge-platform",
            "cf-browser-verification",
        )
        return is_minimal_content and any(
            indicator in html_lower for indicator in weak_challenge_indicators
        )

    def _determine_fallback_reason(
        self,
        was_authenticated: bool,
        security_challenge: bool,
        attempts: list[ProductSearchAttempt],
    ) -> str:
        """Determine human-readable reason for fallback to typeahead.

        Args:
            was_authenticated: Whether auth cookies were available
            security_challenge: Whether a security challenge was detected
            attempts: List of search attempts made

        Returns:
            Human-readable explanation of why fallback was used
        """
        if not was_authenticated:
            return "No authentication cookies available"
        if security_challenge:
            # Only blame the browser fallback once it has actually run and come
            # back empty. Called before that, the honest answer is just "the
            # SSR route was challenged" — the browser route may still succeed,
            # and claiming otherwise triggers pointless session refreshes.
            browser_ran = any(a.method == "nodriver_browser" for a in attempts)
            if not browser_ran:
                return (
                    "Security challenge (WAF/captcha) blocked the SSR route; "
                    "retrying via the in-process browser"
                )
            return (
                "Security challenge (WAF/captcha) blocked the SSR route and the "
                "in-process browser fallback returned no results. Refresh the "
                "session if this persists."
            )
        if all(a.result == "empty" for a in attempts if a.method in ("ssr", "typeahead_as_ssr")):
            return "All SSR queries returned empty results - product may not exist"
        if all(a.result == "error" for a in attempts if a.method in ("ssr", "typeahead_as_ssr")):
            return "All SSR queries failed with errors"
        return "SSR search unsuccessful"

    async def _search_products_nodriver(
        self,
        query: str,
        store_id: str,
        limit: int = 20,
    ) -> list[Product]:
        """Search products via the in-process nodriver browser fallback.

        Used when the httpx SSR search is blocked by the WAF challenge. Drives a
        real browser (which solves the reese84 JS challenge in-container) to
        fetch the search-results page, then reuses the SSR ``__NEXT_DATA__``
        parser to extract products. Returns an empty list on any failure so the
        caller can degrade to typeahead suggestions.
        """
        from auto_grocer_mcp.clients.nodriver_search import get_nodriver_search_client

        client = get_nodriver_search_client()
        html = await client.search_html(query, store_id)
        if not html:
            return []

        match = re.search(
            r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>',
            html,
            re.DOTALL,
        )
        if not match:
            logger.warning("No __NEXT_DATA__ in nodriver search HTML", query=query)
            return []

        try:
            next_data = json.loads(match.group(1))
        except json.JSONDecodeError as exc:
            logger.warning(
                "Failed to parse nodriver search JSON", query=query, error=str(exc)
            )
            return []

        return self._parse_ssr_products(next_data, limit)

    async def search_products(
        self,
        query: str,
        store_id: str,
        limit: int = 20,
    ) -> ProductSearchResult:
        """Search for products at a store.

        Tries authenticated search first (fast, full data), falls back to
        typeahead suggestions if no auth cookies available. When authenticated
        search returns no results, tries query variations before falling back.

        Args:
            query: Search query
            store_id: Store ID for inventory/pricing
            limit: Maximum results to return

        Returns:
            ProductSearchResult with products and diagnostic metadata
        """

        attempts: list[ProductSearchAttempt] = []
        security_challenge_detected = False
        search_url = f"https://www.heb.com/search?q={query.replace(' ', '+')}"

        # Try authenticated search first
        auth_client = await self._get_authenticated_client()
        if auth_client:
            # Generate query variations to try
            query_variations = self._generate_query_variations(query)

            for variation in query_variations:
                try:
                    products, was_challenge = await self._search_products_ssr(
                        auth_client, variation, store_id, limit
                    )

                    if was_challenge:
                        security_challenge_detected = True
                        attempts.append(ProductSearchAttempt(
                            query=variation,
                            method="ssr",
                            result="security_challenge",
                        ))
                        # NOT an error: the WAF challenges the SSR *navigation*
                        # route, so we simply switch to the browser route
                        # below, which normally succeeds. Logging this at
                        # error level (and telling the caller to refresh the
                        # session) produced false alarms that pushed agents
                        # into needless session/hash refresh storms.
                        logger.info(
                            "SSR route challenged; switching to browser search route",
                            query=variation,
                        )
                        # Don't waste more httpx queries on a challenged route.
                        break

                    if products:
                        attempts.append(ProductSearchAttempt(
                            query=variation,
                            method="ssr",
                            result="success",
                        ))
                        logger.info(
                            "SSR search successful",
                            original_query=query,
                            effective_query=variation,
                            result_count=len(products),
                        )
                        return ProductSearchResult(
                            products=products,
                            count=len(products),
                            query=query,
                            store_id=store_id,
                            data_source="ssr",
                            authenticated=True,
                            attempts=attempts,
                            search_url=search_url,
                        )
                    else:
                        attempts.append(ProductSearchAttempt(
                            query=variation,
                            method="ssr",
                            result="empty",
                        ))

                except Exception as e:
                    attempts.append(ProductSearchAttempt(
                        query=variation,
                        method="ssr",
                        result="error",
                        error_detail=str(e),
                    ))
                    logger.warning(
                        "Authenticated search failed for variation",
                        query=variation,
                        error=str(e),
                    )
                    continue

            # If all variations failed, try using typeahead suggestions as queries
            # Skip this if security challenge was detected - no point in trying more SSR requests
            if not security_challenge_detected:
                try:
                    suggestions = await self.get_typeahead(query)
                    if suggestions:
                        for suggestion in suggestions[:2]:  # Try top 2 suggestions
                            try:
                                products, was_challenge = await self._search_products_ssr(
                                    auth_client, suggestion, store_id, limit
                                )

                                if was_challenge:
                                    security_challenge_detected = True
                                    attempts.append(ProductSearchAttempt(
                                        query=suggestion,
                                        method="typeahead_as_ssr",
                                        result="security_challenge",
                                    ))
                                    # Fail-fast: don't try more suggestions
                                    break

                                if products:
                                    attempts.append(ProductSearchAttempt(
                                        query=suggestion,
                                        method="typeahead_as_ssr",
                                        result="success",
                                    ))
                                    logger.info(
                                        "SSR search successful via typeahead suggestion",
                                        original_query=query,
                                        suggestion_used=suggestion,
                                        result_count=len(products),
                                    )
                                    return ProductSearchResult(
                                        products=products,
                                        count=len(products),
                                        query=query,
                                        store_id=store_id,
                                        data_source="ssr",
                                        authenticated=True,
                                        attempts=attempts,
                                        search_url=search_url,
                                    )
                                else:
                                    attempts.append(ProductSearchAttempt(
                                        query=suggestion,
                                        method="typeahead_as_ssr",
                                        result="empty",
                                    ))

                            except Exception as e:
                                attempts.append(ProductSearchAttempt(
                                    query=suggestion,
                                    method="typeahead_as_ssr",
                                    result="error",
                                    error_detail=str(e),
                                ))
                                continue
                except Exception as e:
                    logger.debug("Typeahead-guided search failed", error=str(e))

        # Browser fallback: when the WAF blocked the httpx SSR search, drive an
        # in-process nodriver browser (which solves the JS challenge) to fetch
        # the search-results page. Cart operations still use /graphql.
        #
        # This runs BEFORE any fallback verdict is computed or logged. Deciding
        # (and announcing) "the browser fallback returned no results, refresh
        # your session" up here — while the browser then went on to return 20
        # products — was a pure false alarm that drove agents into needless
        # session/hash refresh loops.
        if security_challenge_detected:
            try:
                browser_products = await self._search_products_nodriver(
                    query, store_id, limit
                )
            except Exception as e:
                logger.warning(
                    "nodriver search fallback failed", query=query, error=str(e)
                )
                browser_products = []

            if browser_products:
                attempts.append(ProductSearchAttempt(
                    query=query,
                    method="nodriver_browser",
                    result="success",
                ))
                logger.info(
                    "nodriver browser search successful",
                    query=query,
                    result_count=len(browser_products),
                )
                return ProductSearchResult(
                    products=browser_products,
                    count=len(browser_products),
                    query=query,
                    store_id=store_id,
                    data_source="ssr",
                    authenticated=auth_client is not None,
                    security_challenge_detected=True,
                    attempts=attempts,
                    search_url=search_url,
                )
            attempts.append(ProductSearchAttempt(
                query=query,
                method="nodriver_browser",
                result="empty",
            ))

        # Every real search route has now been tried and failed, so the verdict
        # below describes the actual outcome rather than a prediction.
        fallback_reason = self._determine_fallback_reason(
            was_authenticated=auth_client is not None,
            security_challenge=security_challenge_detected,
            attempts=attempts,
        )

        logger.info(
            "Product search using typeahead fallback",
            query=query,
            store_id=store_id,
            fallback_reason=fallback_reason,
            security_challenge=security_challenge_detected,
        )

        try:
            suggestions = await self.get_typeahead(query)
        except Exception as e:
            logger.error("Product search failed", query=query, error=str(e))
            return ProductSearchResult(
                products=[],
                count=0,
                query=query,
                store_id=store_id,
                data_source="typeahead_suggestions",
                authenticated=auth_client is not None,
                fallback_reason=fallback_reason,
                security_challenge_detected=security_challenge_detected,
                attempts=attempts,
                search_url=search_url,
            )

        # Return suggestions as placeholder products
        products = []
        for suggestion in suggestions[:limit]:
            product = Product(
                sku=f"suggestion-{suggestion.lower().replace(' ', '-')}",
                name=suggestion,
                price=0.0,  # Price unavailable via typeahead
                available=True,
                brand=None,
                size=None,
                price_per_unit=None,
                image_url=None,
                aisle=None,
                on_sale=False,
                original_price=None,
            )
            products.append(product)
            attempts.append(ProductSearchAttempt(
                query=suggestion,
                method="typeahead",
                result="success",
            ))

        return ProductSearchResult(
            products=products,
            count=len(products),
            query=query,
            store_id=store_id,
            data_source="typeahead_suggestions",
            authenticated=auth_client is not None,
            fallback_reason=fallback_reason,
            security_challenge_detected=security_challenge_detected,
            attempts=attempts,
            search_url=search_url,
        )

    # ========================================================================
    # Product Details
    # ========================================================================

    async def get_product_details(
        self,
        product_id: str,
        store_id: str | None = None,
    ) -> ProductDetails | None:
        """Get comprehensive details for a single product.

        Fetches the product detail page via SSR and extracts full product
        information including ingredients, nutrition, warnings, and instructions.

        Results are cached for 24 hours to reduce API calls since product
        details rarely change.

        Args:
            product_id: The product ID (e.g., '127074')
            store_id: Optional store ID (uses session's store if not provided)

        Returns:
            ProductDetails with full product information, or None if not found
        """

        # Check cache first
        cache_key = f"{product_id}:{store_id or 'default'}"
        cached = self._product_details_cache.get(cache_key)
        if cached:
            logger.info(
                "Product details cache hit",
                product_id=product_id,
                name=cached.name,
            )
            return cached

        # Pre-fetch build ID before getting auth client
        # (prevents client lifecycle issues since _get_build_id may create a client)
        await self._get_build_id()

        auth_client = await self._get_authenticated_client()
        if not auth_client:
            logger.warning("No authenticated client for product details")
            # Try with unauthenticated client as fallback
            auth_client = await self._get_client()

        try:
            details = await self._get_product_details_ssr(auth_client, product_id)
            if details:
                # Cache the result
                self._product_details_cache.set(cache_key, details)
                logger.info(
                    "Product details fetched and cached",
                    product_id=product_id,
                    name=details.name,
                )
            return details
        except Exception as e:
            logger.error(
                "Failed to get product details",
                product_id=product_id,
                error=str(e),
            )
            return None

    def get_product_details_cache_stats(self) -> dict[str, Any]:
        """Get statistics about the product details cache.

        Returns:
            Dict with cache stats (size, valid_entries, ttl_hours, etc.)
        """
        return self._product_details_cache.stats()

    def clear_product_details_cache(self) -> None:
        """Clear the product details cache."""
        self._product_details_cache.clear()

    @with_retry(config=RetryConfig(max_attempts=2, base_delay=0.5))
    async def _get_product_details_ssr(
        self,
        client: httpx.AsyncClient,
        product_id: str,
    ) -> ProductDetails | None:
        """Fetch product details via SSR data endpoint.

        Args:
            client: HTTP client (authenticated preferred)
            product_id: Product ID to fetch

        Returns:
            ProductDetails or None if not found/error
        """

        async with self._ssr_throttler:
            self.circuit_breaker.check()

            # Get build ID for SSR endpoint
            build_id = await self._get_build_id()

            url = f"https://www.heb.com/_next/data/{build_id}/en/product-detail/{product_id}.json"
            logger.debug("Fetching product details SSR", url=url, product_id=product_id)

            try:
                response = await client.get(url)

                # 404 means product doesn't exist
                if response.status_code == 404:
                    logger.info("Product not found", product_id=product_id)
                    return None

                response.raise_for_status()

                # Check for security challenge
                if response.headers.get(
                    "content-type", ""
                ).startswith("text/html") and self._detect_security_challenge(
                    response.text
                ):
                    logger.warning(
                        "Security challenge detected in product details response",
                        product_id=product_id,
                    )
                    return None

                data = response.json()

                # Try standard Next.js SSR structure first
                product_data = data.get("pageProps", {}).get("product")

                # Fallback to props wrapper if needed
                if not product_data:
                    product_data = data.get("props", {}).get("pageProps", {}).get("product")

                if not product_data:
                    page_props_keys = (
                        list(data.get("pageProps", {}).keys())
                        if "pageProps" in data
                        else None
                    )
                    logger.warning(
                        "No product data in response",
                        product_id=product_id,
                        response_keys=list(data.keys()),
                        pageProps_keys=page_props_keys,
                    )
                    return None

                self.circuit_breaker.record_success()
                return self._parse_product_details(product_data)

            except httpx.HTTPStatusError as e:
                logger.error(
                    "HTTP error fetching product details",
                    product_id=product_id,
                    status=e.response.status_code,
                )
                self.circuit_breaker.record_failure()
                return None
            except Exception as e:
                logger.error(
                    "Error fetching product details",
                    product_id=product_id,
                    error=str(e),
                )
                self.circuit_breaker.record_failure()
                raise

    def _parse_product_details(self, data: dict[str, Any]) -> ProductDetails:
        """Parse product detail JSON into ProductDetails model.

        Args:
            data: Raw product data from __NEXT_DATA__ pageProps.product

        Returns:
            Parsed ProductDetails model
        """
        from auto_grocer_mcp.models.product import (
            ExtendedNutrition,
            ProductDetails,
        )

        # Extract basic info
        product_id = str(data.get("id", ""))
        name = data.get("fullDisplayName", "")

        # Extract SKU info (use first SKU)
        skus = data.get("SKUs", [])
        sku_data = skus[0] if skus else {}
        sku = str(sku_data.get("id", ""))
        upc = sku_data.get("twelveDigitUPC")
        size = sku_data.get("customerFriendlySize")

        # Extract brand
        brand_info = data.get("brand", {})
        brand = brand_info.get("name") if brand_info else None
        is_own_brand = brand_info.get("isOwnBrand", False) if brand_info else False

        # Extract pricing from context prices
        price = 0.0
        price_online = None
        on_sale = False
        is_price_cut = False
        price_per_unit = None

        context_prices = sku_data.get("contextPrices", [])
        for cp in context_prices:
            context = cp.get("context", "")
            list_price = cp.get("listPrice", {}).get("amount", 0.0)
            sale_price = cp.get("salePrice", {}).get("amount", list_price)
            unit_price = cp.get("unitListPrice", {})

            if context == "CURBSIDE":
                price = sale_price if cp.get("isOnSale") else list_price
                on_sale = cp.get("isOnSale", False)
                is_price_cut = cp.get("isPriceCut", False)
                if unit_price:
                    formatted_amount = unit_price.get("formattedAmount", "")
                    unit = unit_price.get("unit", "")
                    price_per_unit = f"{formatted_amount} / {unit}"
            elif context == "ONLINE":
                price_online = sale_price if cp.get("isOnSale") else list_price

        # Extract availability
        inventory = data.get("inventory", {})
        available = inventory.get("inventoryState") == "IN_STOCK"

        # Extract availability channels
        availability_channels = sku_data.get("productAvailability", [])

        # Extract ingredients (string, not list)
        ingredients = data.get("ingredientStatement")

        # Extract safety warning
        safety_warning = data.get("safetyWarning")

        # Extract instructions
        instructions = data.get("preparationInstructions")

        # Extract dietary attributes from lifestyles
        lifestyles = data.get("lifestyles", [])
        dietary_attributes = [
            lifestyle.get("formattedName", "")
            for lifestyle in lifestyles
            if lifestyle.get("formattedName")
        ]

        # Extract nutrition labels
        nutrition = None
        nutrition_labels = data.get("nutritionLabels", [])
        if nutrition_labels:
            nl = nutrition_labels[0]
            nutrients = self._parse_nutrients(nl.get("nutrients", []))
            vitamins = self._parse_nutrients(nl.get("vitaminsAndMinerals", []))

            nutrition = ExtendedNutrition(
                serving_size=nl.get("servingSize"),
                servings_per_container=nl.get("servingsPerContainer"),
                calories=nl.get("calories"),
                label_modifier=nl.get("labelModifier"),
                nutrients=nutrients,
                vitamins_and_minerals=vitamins,
            )

        # Extract category path from breadcrumbs
        breadcrumbs = data.get("breadcrumbs", [])
        category_path = [b.get("title", "") for b in breadcrumbs if b.get("title")]
        # Remove "H-E-B" from path if present (it's always first)
        if category_path and category_path[0] == "H-E-B":
            category_path = category_path[1:]

        # Extract images
        image_url = None
        product_images = data.get("productImageUrls", [])
        if product_images:
            # Prefer MEDIUM size
            for img in product_images:
                if img.get("size") == "MEDIUM":
                    image_url = img.get("url")
                    break
            if not image_url and product_images:
                image_url = product_images[0].get("url")

        images = data.get("carouselImageUrls", [])

        # Extract location
        location = None
        product_location = data.get("productLocation", {})
        if product_location:
            location = product_location.get("location")

        # Extract store ID
        store_id = data.get("storeId")

        # Extract SNAP eligibility
        is_snap_eligible = data.get("isEbtSnapProduct", False)

        # Extract product URL
        product_url = data.get("productPageURL")

        # Extract description
        description = data.get("productDescription")

        return ProductDetails(
            product_id=product_id,
            sku=sku,
            upc=upc,
            name=name,
            description=description,
            brand=brand,
            is_own_brand=is_own_brand,
            price=price,
            price_online=price_online,
            on_sale=on_sale,
            is_price_cut=is_price_cut,
            available=available,
            price_per_unit=price_per_unit,
            size=size,
            ingredients=ingredients,
            safety_warning=safety_warning,
            instructions=instructions,
            dietary_attributes=dietary_attributes,
            nutrition=nutrition,
            category_path=category_path,
            image_url=image_url,
            images=images,
            location=location,
            store_id=store_id,
            availability_channels=availability_channels,
            is_snap_eligible=is_snap_eligible,
            product_url=product_url,
        )

    def _parse_nutrients(self, nutrients_data: list[dict[str, Any]]) -> list[NutrientInfo]:
        """Parse nutrients list with nested sub_items.

        Args:
            nutrients_data: List of nutrient dicts from API

        Returns:
            List of NutrientInfo models
        """
        from auto_grocer_mcp.models.product import NutrientInfo

        result = []
        for n in nutrients_data:
            sub_items = None
            if n.get("subItems"):
                sub_items = self._parse_nutrients(n["subItems"])

            result.append(NutrientInfo(
                title=n.get("title", ""),
                unit=n.get("unit", ""),
                percentage=n.get("percentage"),
                font_modifier=n.get("fontModifier"),
                sub_items=sub_items,
            ))
        return result

    @with_retry(config=RetryConfig(max_attempts=2, base_delay=0.5))
    async def _search_products_ssr(
        self,
        client: httpx.AsyncClient,
        query: str,
        store_id: str,
        limit: int = 20,
    ) -> tuple[list[Product], bool]:
        """Search products using authenticated SSR page fetch.

        Fetches the search results page HTML and extracts product data
        from the embedded __NEXT_DATA__ JSON.

        Args:
            client: Authenticated httpx client with cookies
            query: Search query
            store_id: Store ID (used for context)
            limit: Maximum results to return

        Returns:
            Tuple of (products list, security_challenge_detected)
        """
        async with self._ssr_throttler:
            self.circuit_breaker.check()

            url = f"https://www.heb.com/search?q={query.replace(' ', '+')}"
            logger.debug("Fetching SSR search results", url=url)

            try:
                response = await client.get(url)
                response.raise_for_status()

                # Check for security challenge before parsing
                if self._detect_security_challenge(response.text):
                    logger.warning(
                        "Security challenge detected in SSR response",
                        query=query,
                        response_length=len(response.text),
                    )
                    self.circuit_breaker.record_failure()
                    return [], True

                # Extract __NEXT_DATA__ JSON from HTML
                match = re.search(
                    r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>',
                    response.text,
                    re.DOTALL,
                )

                if not match:
                    logger.warning(
                        "No __NEXT_DATA__ found in response",
                        query=query,
                        response_length=len(response.text),
                    )
                    return [], False

                next_data = json.loads(match.group(1))
                products = self._parse_ssr_products(next_data, limit)

                self.circuit_breaker.record_success()
                logger.info(
                    "SSR product search successful",
                    query=query,
                    result_count=len(products),
                )

                return products, False

            except httpx.HTTPError as e:
                self.circuit_breaker.record_failure()
                logger.error("SSR search request failed", query=query, error=str(e))
                raise

    def _parse_ssr_products(self, next_data: dict[str, Any], limit: int = 20) -> list[Product]:
        """Parse products from Next.js SSR data.

        Extracts product data from the searchGridV2 component in the
        page props layout.

        Args:
            next_data: Parsed __NEXT_DATA__ JSON
            limit: Maximum products to return

        Returns:
            List of Product objects
        """
        products: list[Product] = []

        try:
            # Navigate to search grid items
            layout = next_data.get("props", {}).get("pageProps", {}).get("layout", {})
            visual_components = layout.get("visualComponents", [])

            # Find searchGridV2 component
            search_grid = None
            for component in visual_components:
                if component.get("type") == "searchGridV2":
                    search_grid = component
                    break

            if not search_grid:
                logger.debug("No searchGridV2 component found")
                return []

            items = search_grid.get("items", [])

            for item in items[:limit]:
                try:
                    product = self._parse_ssr_product_item(item)
                    if product:
                        products.append(product)
                except Exception as e:
                    logger.debug("Failed to parse product item", error=str(e))
                    continue

        except Exception as e:
            logger.error("Failed to parse SSR products", error=str(e))

        return products

    def _parse_ssr_product_item(self, item: dict[str, Any]) -> Product | None:
        """Parse a single product item from SSR data.

        Args:
            item: Product item dict from searchGridV2.items

        Returns:
            Product object or None if parsing fails
        """
        if item.get("__typename") != "Product":
            return None

        # Extract basic info
        product_id = item.get("id", "")
        display_name = item.get("fullDisplayName") or item.get("displayName", "")

        # Extract brand
        brand_info = item.get("brand", {})
        brand = brand_info.get("name") if brand_info else None

        # Extract SKU and pricing
        skus = item.get("SKUs", [])
        sku_data = skus[0] if skus else {}
        sku_id = sku_data.get("id", "")
        size = sku_data.get("customerFriendlySize", "")

        # Get pricing (prefer CURBSIDE context, fallback to ONLINE)
        price = 0.0
        price_per_unit = None
        on_sale = False
        original_price = None

        context_prices = sku_data.get("contextPrices", [])
        for ctx_price in context_prices:
            context = ctx_price.get("context", "")
            if context in ("CURBSIDE", "CURBSIDE_PICKUP", "ONLINE"):
                list_price = ctx_price.get("listPrice", {})
                sale_price = ctx_price.get("salePrice", {})
                unit_price = ctx_price.get("unitListPrice", {})

                price = sale_price.get("amount", 0.0) or list_price.get("amount", 0.0)

                if unit_price:
                    unit_amount = unit_price.get("amount", 0.0)
                    unit_type = unit_price.get("unit", "")
                    if unit_amount and unit_type:
                        price_per_unit = f"${unit_amount:.2f}/{unit_type}"

                on_sale = ctx_price.get("isOnSale", False) or ctx_price.get("isPriceCut", False)
                if on_sale:
                    original_price = list_price.get("amount")

                break  # Use first matching context

        # Extract inventory
        inventory = item.get("inventory", {})
        inventory_state = inventory.get("inventoryState", "")
        available = inventory_state == "IN_STOCK"

        # Extract image URL
        images = item.get("productImageUrls", [])
        image_url = None
        for img in images:
            if img.get("size") == "MEDIUM":
                image_url = img.get("url")
                break
        if not image_url and images:
            image_url = images[0].get("url")

        # Extract aisle/location
        location = item.get("productLocation", {})
        aisle = location.get("location") if location else None

        # Extract coupon flag
        has_coupon = item.get("showCouponFlag", False)

        return Product(
            sku=sku_id or product_id,
            product_id=product_id,  # Store product ID separately for cart operations
            name=display_name,
            price=price,
            available=available,
            brand=brand,
            size=size,
            price_per_unit=price_per_unit,
            image_url=image_url,
            aisle=aisle,
            on_sale=on_sale,
            original_price=original_price,
            has_coupon=has_coupon,
        )

    async def get_categories(self) -> list[dict[str, Any]]:
        """Get shop navigation categories.

        Returns:
            List of category dictionaries with id, name, href, and subcategories
        """
        try:
            data = await self._execute_persisted_query("ShopNavigation", {})
            categories = data.get("shopNavigation", [])
            return [
                {
                    "id": cat.get("id"),
                    "name": cat.get("displayName"),
                    "href": cat.get("href"),
                    "subcategories": [
                        {"id": sub.get("id"), "name": sub.get("displayName")}
                        for sub in cat.get("subCategories", [])
                    ],
                }
                for cat in categories
            ]
        except Exception as e:
            logger.error("Failed to get categories", error=str(e))
            return []

    async def get_typeahead(self, term: str) -> list[str]:
        """Get search suggestions for a term.

        Args:
            term: Partial search term

        Returns:
            List of suggested search terms
        """
        try:
            data = await self._execute_persisted_query(
                "typeaheadContent",
                {"term": term, "searchMode": "MAIN_SEARCH"},
            )

            suggestions = []
            content = data.get("typeaheadContent", {})
            vertical_stack = content.get("verticalStack", [])

            for section in vertical_stack:
                typename = section.get("__typename", "")
                if "SuggestedSearches" in typename:
                    suggestions.extend(section.get("terms", []))
                elif "TrendingSearches" in typename:
                    suggestions.extend(section.get("trendingSearches", []))

            return suggestions

        except Exception as e:
            logger.error("Typeahead failed", term=term, error=str(e))
            return []

    async def add_to_cart(
        self,
        product_id: str,
        sku_id: str,
        quantity: int = 1,
    ) -> dict[str, Any]:
        """Add an item to the cart using authenticated GraphQL.

        Requires authentication cookies to be available.

        Args:
            product_id: The product ID
            sku_id: The SKU ID
            quantity: Number to add

        Returns:
            Cart response data or error dict if not authenticated
        """
        auth_client = await self._get_authenticated_client()
        if not auth_client:
            return {"error": True, "code": "NOT_AUTHENTICATED", "message": "Login required"}

        return await self._execute_persisted_query_with_client(
            auth_client,
            "cartItemV2",
            {
                "userIsLoggedIn": True,
                "productId": product_id,
                "skuId": sku_id,
                "quantity": quantity,
            },
        )

    async def get_cart(self) -> dict[str, Any]:
        """Get current cart contents using authenticated GraphQL.

        Requires authentication cookies to be available.

        Returns:
            Cart data or error dict if not authenticated
        """
        auth_client = await self._get_authenticated_client()
        if not auth_client:
            return {"error": True, "code": "NOT_AUTHENTICATED", "message": "Login required"}

        return await self._execute_persisted_query_with_client(
            auth_client,
            "cartEstimated",
            {"userIsLoggedIn": True},
        )

    @with_retry(config=RetryConfig(max_attempts=3, base_delay=1.0))
    async def _execute_persisted_query_with_client(
        self,
        client: httpx.AsyncClient,
        operation_name: str,
        variables: dict[str, Any],
    ) -> dict[str, Any]:
        """Execute a persisted GraphQL query with a specific client.

        Args:
            client: httpx client to use (may have cookies)
            operation_name: The name of the persisted operation
            variables: Query variables

        Returns:
            Response data
        """
        self.circuit_breaker.check()

        if operation_name not in PERSISTED_QUERIES:
            raise ValueError(f"Unknown operation: {operation_name}")

        refreshed = False
        apq_tried = False
        while True:
            payload = {
                "operationName": operation_name,
                "variables": variables,
                "extensions": {
                    "persistedQuery": {
                        "version": 1,
                        "sha256Hash": PERSISTED_QUERIES[operation_name],
                    }
                },
            }
            # APQ registration round-trip: include the full query text so HEB
            # re-registers + executes an operation it evicted from its APQ cache.
            if apq_tried and operation_name in PERSISTED_QUERY_DOCUMENTS:
                payload["query"] = PERSISTED_QUERY_DOCUMENTS[operation_name]

            try:
                response = await client.post(
                    self.base_url,
                    json=payload,
                    headers={"Content-Type": "application/json", "Accept": "application/json"},
                )
                response.raise_for_status()

                data: Any = response.json()

                if "errors" in data:
                    for error in data["errors"]:
                        if "PersistedQueryNotFound" in str(error):
                            raise PersistedQueryNotFoundError(
                                f"Persisted query hash for '{operation_name}' is no longer valid"
                            )
                    raise GraphQLError(data["errors"])

                self.circuit_breaker.record_success()

                if isinstance(data, dict):
                    payload_data = data.get("data")
                    if isinstance(payload_data, dict):
                        return cast(dict[str, Any], payload_data)
                return {}

            except PersistedQueryNotFoundError as e:
                # 1) APQ full-query fallback (no browser needed): resend WITH the
                #    captured query document to register it, then execute.
                if not apq_tried and operation_name in PERSISTED_QUERY_DOCUMENTS:
                    apq_tried = True
                    logger.info(
                        "Retrying with full query (APQ registration)",
                        operation=operation_name,
                    )
                    continue
                # 2) Operations a browser hash-refresh cannot fix: fail fast with
                #    guidance instead of launching a doomed multi-minute capture.
                if operation_name in _APQ_ONLY_OPERATIONS:
                    raise PersistedQueryNotFoundError(
                        f"'{operation_name}' could not be resolved. Its full query "
                        "document has not been captured yet, so an automatic hash "
                        "refresh cannot help (the query is evicted from HEB's APQ "
                        "cache). Run the capture_hashes tool once - it now records "
                        "the query document - then retry."
                    ) from e
                # 3) Rotated-hash path: non-blocking background hash refresh.
                status = None if refreshed else await _attempt_hash_refresh(operation_name)
                if status == "retry":
                    refreshed = True
                    logger.info(
                        "Retrying persisted query after hash refresh",
                        operation=operation_name,
                    )
                    continue
                if status in ("started", "in_progress"):
                    raise PersistedQueryNotFoundError(
                        f"Persisted query hash for '{operation_name}' is stale; a "
                        "hash refresh has "
                        + ("just started" if status == "started" else "already been triggered")
                        + " in the background. Retry this operation in about "
                        "60-90 seconds."
                    ) from e
                raise

            except (httpx.HTTPError, GraphQLError) as e:
                self.circuit_breaker.record_failure()
                logger.error(
                    "Persisted query with client failed",
                    operation=operation_name,
                    error=str(e),
                )
                raise

    def get_status(self) -> dict[str, Any]:
        """Get client status for health checks."""
        return {
            "circuit_breaker": self.circuit_breaker.get_status(),
            "build_id": self._build_id,
            "known_stores": len(KNOWN_STORES),
        }

    # ===================
    # Coupon Methods
    # ===================

    async def get_coupons(
        self,
        category_id: int | None = None,
        search_query: str | None = None,
        limit: int = 60,
    ) -> CouponSearchResult:
        """Fetch available coupons.

        Coupons are loaded via SSR from the all-coupons page.

        Args:
            category_id: Filter by category ID (e.g., 490021 for Health & beauty)
            search_query: Search coupons by keyword
            limit: Maximum coupons to return (max 60 per page)

        Returns:
            CouponSearchResult with coupons and metadata
        """
        auth_client = await self._get_authenticated_client()
        if not auth_client:
            logger.warning("Coupon fetch requires authentication for full data")
            return CouponSearchResult(
                coupons=[],
                count=0,
                total=0,
                categories=[],
            )

        try:
            return await self._fetch_coupons_ssr(
                auth_client,
                category_id=category_id,
                search_query=search_query,
                limit=limit,
            )
        except Exception as e:
            logger.error("Failed to fetch coupons", error=str(e))
            return CouponSearchResult(
                coupons=[],
                count=0,
                total=0,
                categories=[],
            )

    @with_retry(config=RetryConfig(max_attempts=2, base_delay=0.5))
    async def _fetch_coupons_ssr(
        self,
        client: httpx.AsyncClient,
        category_id: int | None = None,
        search_query: str | None = None,
        limit: int = 60,
    ) -> CouponSearchResult:
        """Fetch coupons via SSR page.

        Args:
            client: Authenticated httpx client
            category_id: Filter by category
            search_query: Search term
            limit: Max results

        Returns:
            CouponSearchResult with parsed coupon data
        """
        self.circuit_breaker.check()

        # Build URL with query params
        url = "https://www.heb.com/digital-coupon/coupon-selection/all-coupons"
        params = {}

        if search_query:
            params["searchTerm"] = search_query
        if category_id:
            params["productCategories"] = str(category_id)

        logger.debug("Fetching coupons SSR", url=url, params=params)

        try:
            response = await client.get(url, params=params if params else None)
            response.raise_for_status()

            # Extract __NEXT_DATA__ JSON from HTML
            match = re.search(
                r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>',
                response.text,
                re.DOTALL,
            )

            if not match:
                logger.warning("No __NEXT_DATA__ found in coupon response")
                return CouponSearchResult(coupons=[], count=0, total=0, categories=[])

            next_data = json.loads(match.group(1))
            result = self._parse_coupon_ssr_data(next_data, limit)

            self.circuit_breaker.record_success()
            logger.info(
                "Coupon fetch successful",
                count=result.count,
                total=result.total,
            )

            return result

        except httpx.HTTPError as e:
            self.circuit_breaker.record_failure()
            logger.error("Coupon SSR fetch failed", error=str(e))
            raise

    def _parse_coupon_ssr_data(
        self,
        next_data: dict[str, Any],
        limit: int = 60,
    ) -> CouponSearchResult:
        """Parse coupon data from SSR __NEXT_DATA__.

        Args:
            next_data: Parsed __NEXT_DATA__ JSON
            limit: Max coupons to return

        Returns:
            CouponSearchResult with coupons and categories
        """
        page_props = next_data.get("props", {}).get("pageProps", {})

        # Parse coupon data
        coupon_data = page_props.get("couponData", [])
        coupons: list[Coupon] = []

        for item in coupon_data[:limit]:
            try:
                coupon = self._parse_coupon_item(item)
                if coupon:
                    coupons.append(coupon)
            except Exception as e:
                logger.debug("Failed to parse coupon", error=str(e))
                continue

        # Parse pagination
        pagination = page_props.get("pagination", {})
        total = pagination.get("totalCoupons", len(coupons))

        # Parse categories from filters
        categories: list[CouponCategory] = []
        filters_info = page_props.get("filtersInfo", {})
        filter_counts = filters_info.get("filterCounts", {})
        product_categories = filter_counts.get("productCategories", [])

        for cat in product_categories:
            try:
                categories.append(CouponCategory(
                    id=cat.get("option", 0),
                    name=cat.get("displayName", ""),
                    count=cat.get("count", 0),
                ))
            except Exception:
                continue

        return CouponSearchResult(
            coupons=coupons,
            count=len(coupons),
            total=total,
            categories=categories,
        )

    def _parse_coupon_item(self, item: dict[str, Any]) -> Coupon | None:
        """Parse a single coupon from SSR data.

        Args:
            item: Coupon dict from couponData array

        Returns:
            Coupon object or None if parsing fails
        """
        coupon_id = item.get("id")
        if not coupon_id:
            return None

        # Parse expiration date
        exp_date = item.get("expirationDate")
        expires_display = None
        if exp_date:
            # Convert YYYY-MM-DD to more readable format
            try:
                from datetime import datetime
                dt = datetime.strptime(exp_date, "%Y-%m-%d")
                expires_display = dt.strftime("%m/%d/%Y")
            except Exception:
                expires_display = exp_date

        # Determine if digital only
        print_statuses = item.get("printStatuses", [])
        digital_only = "PAPERLESS" in print_statuses and "PRINTED" not in print_statuses

        # Parse usage limit
        redemption_limit = item.get("redemptionLimit")
        usage_limit = f"Limit {redemption_limit}" if redemption_limit else "Unlimited use"

        return Coupon(
            coupon_id=coupon_id,
            headline=item.get("shortDescription", ""),
            description=item.get("description", ""),
            expires=exp_date,
            expires_display=expires_display,
            image_url=item.get("imageUrl"),
            coupon_type=item.get("type", "NORMAL"),
            clipped=item.get("clippedStatus") == "CLIPPED",
            redeemable=item.get("redemptionStatus") == "REDEEMABLE",
            usage_limit=usage_limit,
            digital_only=digital_only,
        )

    async def clip_coupon(self, coupon_id: int) -> dict[str, Any]:
        """Clip a coupon to the user's account.

        Args:
            coupon_id: The coupon ID to clip

        Returns:
            Result dict with success/error status
        """
        auth_client = await self._get_authenticated_client()
        if not auth_client:
            return {
                "error": True,
                "code": "NOT_AUTHENTICATED",
                "message": "Login required to clip coupons",
            }

        try:
            result = await self._execute_persisted_query_with_client(
                auth_client,
                "CouponClip",
                {
                    "userIsLoggedIn": True,
                    "id": coupon_id,
                },
            )

            # Check if the mutation succeeded
            clip_result = result.get("clipCoupon", {})
            if clip_result:
                return {
                    "success": True,
                    "coupon_id": coupon_id,
                    "message": "Coupon clipped successfully!",
                }
            else:
                return {
                    "success": True,
                    "coupon_id": coupon_id,
                    "message": "Coupon clipped.",
                }

        except GraphQLError as e:
            error_msg = str(e)
            if "already clipped" in error_msg.lower():
                return {
                    "error": True,
                    "code": "ALREADY_CLIPPED",
                    "message": "This coupon is already clipped to your account.",
                    "coupon_id": coupon_id,
                }
            logger.error("Failed to clip coupon", coupon_id=coupon_id, error=error_msg)
            return {
                "error": True,
                "code": "CLIP_FAILED",
                "message": f"Failed to clip coupon: {error_msg}",
                "coupon_id": coupon_id,
            }
        except Exception as e:
            logger.error("Failed to clip coupon", coupon_id=coupon_id, error=str(e))
            return {
                "error": True,
                "code": "CLIP_FAILED",
                "message": f"Failed to clip coupon: {e!s}",
                "coupon_id": coupon_id,
            }

    async def get_clipped_coupons(self, limit: int = 60) -> CouponSearchResult:
        """Get the user's clipped coupons.

        Fetches clipped coupons via SSR from the clipped-coupons page.

        Args:
            limit: Maximum coupons to return

        Returns:
            CouponSearchResult with clipped coupons
        """
        auth_client = await self._get_authenticated_client()
        if not auth_client:
            logger.warning("Clipped coupons require authentication")
            return CouponSearchResult(
                coupons=[],
                count=0,
                total=0,
                categories=[],
            )

        try:
            return await self._fetch_clipped_coupons_ssr(auth_client, limit)
        except Exception as e:
            logger.error("Failed to fetch clipped coupons", error=str(e))
            return CouponSearchResult(
                coupons=[],
                count=0,
                total=0,
                categories=[],
            )

    async def select_store(
        self, store_id: str, ignore_conflicts: bool = False
    ) -> dict[str, Any]:
        """Change the active store via GraphQL mutation with verification.

        This calls the SelectPickupFulfillment mutation which changes
        the user's active store on HEB's backend, then verifies the
        change actually took effect by checking the cart's store.

        Args:
            store_id: The store ID to switch to
            ignore_conflicts: If True, force store change even if cart has
                conflicts (items unavailable, price changes). Default False.

        Returns:
            Result dict with:
            - success: True only if store actually changed (verified)
            - error: True if store change failed or couldn't be verified
            - code: Error code for programmatic handling
            - verified: True if change was verified via get_cart()
        """
        auth_client = await self._get_authenticated_client()
        if not auth_client:
            return {
                "error": True,
                "code": "NOT_AUTHENTICATED",
                "message": "Login required to change stores",
            }

        try:
            # The mutation expects storeId as both string and int in different fields
            result = await self._execute_persisted_query_with_client(
                auth_client,
                "SelectPickupFulfillment",
                {
                    "fulfillmentType": "PICKUP",
                    "pickupStoreId": store_id,
                    "ignoreCartConflicts": ignore_conflicts,
                    "storeId": int(store_id),
                    "userIsLoggedIn": True,
                },
            )

            fulfillment_data = result.get("selectPickupFulfillment", {})
            logger.debug(
                "SelectPickupFulfillment response",
                store_id=store_id,
                response=fulfillment_data,
            )

            # VERIFY: Check if store actually changed by fetching cart
            # This is the key fix - don't trust the mutation response alone
            cart = await self.get_cart()
            if cart.get("error"):
                logger.warning(
                    "Could not verify store change - cart fetch failed",
                    store_id=store_id,
                    cart_error=cart,
                )
                return {
                    "error": True,
                    "code": "VERIFICATION_FAILED",
                    "message": "Store change could not be verified - cart fetch failed",
                    "store_id": store_id,
                    "mutation_response": fulfillment_data,
                }

            # Extract actual store from cart response
            # Cart structure: cartV2.fulfillment.store.id
            cart_v2 = cart.get("cartV2") or cart.get("cart") or {}
            fulfillment = cart_v2.get("fulfillment") or {}
            store_info = fulfillment.get("store") or {}
            actual_store_id = str(store_info.get("id", ""))

            # Also check pickupStore as alternative location
            if not actual_store_id:
                pickup_store = fulfillment.get("pickupStore") or {}
                actual_store_id = str(pickup_store.get("id", ""))

            # If still no store found, check top-level storeId
            if not actual_store_id:
                actual_store_id = str(cart_v2.get("storeId", ""))

            logger.debug(
                "Store verification",
                requested=store_id,
                actual=actual_store_id,
                cart_fulfillment=fulfillment,
            )

            # Compare requested vs actual
            if actual_store_id == store_id:
                logger.info(
                    "Store change verified successful",
                    store_id=store_id,
                    verified=True,
                )
                return {
                    "success": True,
                    "store_id": store_id,
                    "message": f"Store changed to {store_id}",
                    "verified": True,
                }
            else:
                # Store didn't change - likely cart conflict
                logger.warning(
                    "Store change verification failed",
                    requested=store_id,
                    actual=actual_store_id,
                    ignore_conflicts=ignore_conflicts,
                )

                # Determine likely cause
                if not ignore_conflicts:
                    return {
                        "error": True,
                        "code": "CART_CONFLICT",
                        "message": (
                            f"Store change not applied - your cart may have items "
                            "unavailable at the new store. Current store is still "
                            f"{actual_store_id}."
                        ),
                        "expected_store": store_id,
                        "actual_store": actual_store_id,
                        "suggestion": "Try with ignore_conflicts=True to force the change, "
                        "or clear your cart first.",
                    }
                else:
                    return {
                        "error": True,
                        "code": "VERIFICATION_FAILED",
                        "message": (
                            f"Store change not applied even with ignore_conflicts=True. "
                            f"Current store is still {actual_store_id}."
                        ),
                        "expected_store": store_id,
                        "actual_store": actual_store_id,
                    }

        except GraphQLError as e:
            error_msg = str(e)
            logger.error("Failed to change store", store_id=store_id, error=error_msg)
            return {
                "error": True,
                "code": "STORE_CHANGE_FAILED",
                "message": f"Failed to change store: {error_msg}",
                "store_id": store_id,
            }
        except ValueError as e:
            # Invalid store_id format (can't convert to int)
            logger.error("Invalid store ID format", store_id=store_id, error=str(e))
            return {
                "error": True,
                "code": "INVALID_STORE_ID",
                "message": f"Invalid store ID format: {store_id}",
                "store_id": store_id,
            }
        except Exception as e:
            logger.error("Failed to change store", store_id=store_id, error=str(e))
            return {
                "error": True,
                "code": "STORE_CHANGE_FAILED",
                "message": f"Failed to change store: {e!s}",
                "store_id": store_id,
            }

    @with_retry(config=RetryConfig(max_attempts=2, base_delay=0.5))
    async def _fetch_clipped_coupons_ssr(
        self,
        client: httpx.AsyncClient,
        limit: int = 60,
    ) -> CouponSearchResult:
        """Fetch clipped coupons via SSR page.

        Args:
            client: Authenticated httpx client
            limit: Max results

        Returns:
            CouponSearchResult with clipped coupon data
        """
        self.circuit_breaker.check()

        url = "https://www.heb.com/digital-coupon/clipped-coupons"
        logger.debug("Fetching clipped coupons SSR", url=url)

        try:
            response = await client.get(url)
            response.raise_for_status()

            # Extract __NEXT_DATA__ JSON from HTML
            match = re.search(
                r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>',
                response.text,
                re.DOTALL,
            )

            if not match:
                logger.warning("No __NEXT_DATA__ found in clipped coupons response")
                return CouponSearchResult(coupons=[], count=0, total=0, categories=[])

            next_data = json.loads(match.group(1))
            result = self._parse_coupon_ssr_data(next_data, limit)

            self.circuit_breaker.record_success()
            logger.info(
                "Clipped coupons fetch successful",
                count=result.count,
                total=result.total,
            )

            return result

        except httpx.HTTPError as e:
            self.circuit_breaker.record_failure()
            logger.error("Clipped coupons SSR fetch failed", error=str(e))
            raise
