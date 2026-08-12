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

import base64
import json

from nodriver import cdp

from utility.graphql_hash_capture import (
    _parse_operation_samples,
    save_documents,
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
        # {operationName: {"hash": str, "variables": dict, "query": str | None}}
        self.operations: dict = {}
        # {operationName: query document text} - only for operations where
        # Apollo sent the full document (i.e. on an APQ cache miss).
        self.documents: dict = {}
        self._started = False
        # Operations we still want a full query document for, and the ones we
        # have already forced a cache miss on (force each at most once).
        self._wanted_documents: set = set()
        self._forced_documents: set = set()
        self._paused_seen = 0
        self._paused_with_body = 0

    async def start(self):
        """Enable the Network domain and register the request handler."""
        if self._started:
            return
        await self.tab.send(cdp.network.enable())
        self.tab.add_handler(cdp.network.RequestWillBeSent, self._on_request)
        self._started = True

    async def force_document_capture(self, operation_names):
        """Make Apollo reveal the full query document for ``operation_names``.

        HEB's persisted-query hashes rotate on every deploy, and an operation
        that has fallen out of their APQ cache answers PersistedQueryNotFound
        forever. Holding the query document lets the GraphQL client register it
        under a hash it computes itself, which survives rotation.

        Apollo only puts the document on the wire when the server reports a
        cache miss, so we intercept the outgoing request and corrupt its
        sha256Hash exactly once per operation. HEB then answers
        PersistedQueryNotFound and Apollo automatically retries with the full
        document, which :meth:`_on_request` records.
        """
        self._wanted_documents = {str(n) for n in operation_names or ()}
        if not self._wanted_documents:
            return
        await self.tab.send(
            cdp.fetch.enable(
                patterns=[
                    cdp.fetch.RequestPattern(
                        url_pattern="*graphql*",
                        request_stage=cdp.fetch.RequestStage.REQUEST,
                    )
                ]
            )
        )
        self.tab.add_handler(cdp.fetch.RequestPaused, self._on_paused)
        print(f"    🕸  Document capture armed for: {', '.join(sorted(self._wanted_documents))}")

    def report_forcing(self):
        """Print what the request interceptor actually saw (diagnostics)."""
        print(
            f"    🕸  Fetch interception: {self._paused_seen} GraphQL request(s) paused, "
            f"{self._paused_with_body} with a readable body, "
            f"forced={sorted(self._forced_documents) or 'none'}, "
            f"documents={sorted(self.documents) or 'none'}"
        )

    async def _on_paused(self, event):
        """Corrupt one persisted hash per wanted operation, then let it through.

        Every paused request MUST be resumed or the page hangs, so the whole
        body is defensive and always falls through to continue_request.
        """
        request_id = event.request_id
        patched_post_data = None
        try:
            self._paused_seen += 1
            request = event.request
            post_data = getattr(request, "post_data", None)
            if isinstance(post_data, bytes):
                post_data = post_data.decode("utf-8", "replace")
            if post_data:
                self._paused_with_body += 1
                patched_post_data = self._corrupt_hash(post_data)
        except Exception:  # noqa: BLE001 - never strand a paused request
            patched_post_data = None

        try:
            if patched_post_data is not None:
                await self.tab.send(
                    cdp.fetch.continue_request(
                        request_id=request_id,
                        post_data=base64.b64encode(
                            patched_post_data.encode("utf-8")
                        ).decode("ascii"),
                    )
                )
            else:
                await self.tab.send(cdp.fetch.continue_request(request_id=request_id))
        except Exception:  # noqa: BLE001
            return

    def _corrupt_hash(self, post_data):
        """Return post_data with a bogus hash, or None to send it unchanged.

        Only rewrites a request that (a) names an operation we still need a
        document for and (b) does not already carry the document itself, so the
        automatic Apollo retry is never tampered with.
        """
        try:
            payload = json.loads(post_data)
        except (TypeError, ValueError):
            return None
        if not isinstance(payload, dict):
            return None

        name = payload.get("operationName")
        if not name or name not in self._wanted_documents:
            return None
        if name in self._forced_documents or name in self.documents:
            return None
        if payload.get("query"):
            return None

        persisted = (payload.get("extensions") or {}).get("persistedQuery") or {}
        if not persisted.get("sha256Hash"):
            return None

        self._forced_documents.add(name)
        persisted["sha256Hash"] = "0" * 64
        print(f"    🕸  Forcing APQ miss for '{name}' to reveal its query document...")
        return json.dumps(payload)

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
                previous = self.operations.get(name) or {}
                # Never let a later hash-only request erase a document we
                # already captured for this operation.
                document = query or previous.get("query")
                self.operations[name] = {
                    "hash": sha,
                    "variables": variables,
                    "query": document,
                }
                if query:
                    self.documents[name] = query
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
        save_documents(self.documents)
        return path, samples_path
