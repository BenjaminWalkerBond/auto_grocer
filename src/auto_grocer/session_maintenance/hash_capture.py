"""Capture HEB GraphQL persisted-query hashes via live CDP Network events.

The Selenium version (utility/graphql_hash_capture.py) periodically drained the
destructive Chrome performance log. nodriver lets us subscribe to the CDP
``Network.requestWillBeSent`` event directly and accumulate operations live, so
nothing rolls off a bounded buffer.

Output format and file paths are identical to the Selenium version: this reuses
that module's pure parser + savers (``_parse_operation_samples``,
``save_hashes``, ``save_operation_samples``) and the ``TARGET_OPERATIONS`` set.
"""
from __future__ import annotations

from nodriver import cdp

from auto_grocer.utility.graphql_hash_capture import (
    _parse_operation_samples,
    save_hashes,
    save_operation_samples,
)


class GraphQLHashCapturer:
    """Subscribe to CDP network requests and collect GraphQL persisted queries.

    Usage:
        cap = GraphQLHashCapturer(tab)
        await cap.start()
        ... drive the site ...
        cap.save()
    """

    def __init__(self, tab):
        self.tab = tab
        # {operationName: {"hash": str, "variables": dict}}
        self.operations: dict = {}
        self._started = False

    async def start(self):
        """Enable the Network domain and register the request handler."""
        if self._started:
            return
        await self.tab.send(cdp.network.enable())
        self.tab.add_handler(cdp.network.RequestWillBeSent, self._on_request)
        self._started = True

    async def _on_request(self, event):
        """Handle a requestWillBeSent event; record any GraphQL operations."""
        try:
            request = event.request
            url = getattr(request, "url", "") or ""
            method = getattr(request, "method", "") or ""
            if "/graphql" not in url or method != "POST":
                return

            post_data = getattr(request, "post_data", None)
            if not post_data and getattr(request, "has_post_data", False):
                post_data = await self._fetch_post_data(event)
            if not post_data:
                return

            for name, sha, variables, query in _parse_operation_samples(post_data):
                existing = self.operations.get(name) or {}
                # Preserve a previously-captured full query if this request is a
                # hash-only re-send (APQ cache hit): HEB only includes the query
                # text on the registration MISS, so never overwrite it with None.
                if query is None:
                    query = existing.get("query")
                self.operations[name] = {
                    "hash": sha,
                    "variables": variables,
                    "query": query,
                }
        except Exception:  # noqa: BLE001 - never let a handler crash the flow
            return

    async def _fetch_post_data(self, event):
        """Fetch a request body not inlined in the event (best-effort)."""
        try:
            request_id = event.request_id
            result = await self.tab.send(
                cdp.network.get_request_post_data(request_id)
            )
            # nodriver may return the string directly or a (data, ...) tuple.
            if isinstance(result, tuple):
                return result[0]
            return result
        except Exception:  # noqa: BLE001
            return None

    @property
    def hashes(self) -> dict:
        """Return {operationName: sha256Hash} for everything captured so far."""
        return {
            name: op["hash"]
            for name, op in self.operations.items()
            if op.get("hash")
        }

    def save(self):
        """Persist captured hashes + operation samples. Returns (hashes_path, samples_path)."""
        hashes = self.hashes
        if not hashes:
            return None, None
        path = save_hashes(hashes)
        samples_path = save_operation_samples(self.operations) if self.operations else None
        return path, samples_path
