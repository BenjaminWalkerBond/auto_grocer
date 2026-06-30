---
name: refresh-graphql-hashes
description: 'Refresh HEB GraphQL persisted-query hashes for the auto-grocier MCP server. Use when MCP tools return OPERATION_NOT_CAPTURED, persisted-query/hash mismatch errors, or product search / add-to-cart / checkout calls fail after an HEB site update. Captures fresh hashes via a real browser, syncs persisted_queries.json into the Docker session volume, then calls refresh_session.'
argument-hint: 'Run when tools return OPERATION_NOT_CAPTURED'
---

# Refresh HEB GraphQL Hashes

HEB uses persisted GraphQL queries keyed by hashes. When HEB updates its site the
hashes change and pure-GraphQL MCP tools fail with `OPERATION_NOT_CAPTURED` or
persisted-query errors. The capture flow drives a real browser, sniffs the hashes
via CDP, and writes `persisted_queries.json` (and a fresh `auth.json`). The
container reads these from the `auto_grocier_session` volume.

## When to Use
- Any MCP tool returns `OPERATION_NOT_CAPTURED`.
- Persisted-query / hash-mismatch errors after an HEB site change.
- Search/add/checkout fail while `auth_status` is `authenticated:true`.

## Procedure
1. Capture fresh hashes on the host (also re-exports `auth.json`). May prompt for
   email verification:
   ```bash
   source venv/bin/activate
   MODE=update_graphql_hashes DISPLAY=:0 python -m grocery_browser.run
   ```
2. Sync hashes + session into the Docker volume the container reads:
   ```bash
   docker run --rm -v auto_grocier_session:/v -v ~/.texas-grocery-mcp:/src:ro alpine \
     sh -c 'cp /src/persisted_queries.json /v/; cp /src/captured_operations.json /v/ 2>/dev/null; cp /src/auth.json /v/auth.json 2>/dev/null'
   ```
3. Reload the hashes/session in the server: call `mcp_auto-grocier_refresh_session`.
4. Verify: call `mcp_auto-grocier_search_products` (e.g. "milk") — expect results,
   not `OPERATION_NOT_CAPTURED`.

## Notes
- Hash file: `~/.texas-grocery-mcp/persisted_queries.json` (host) → `auto_grocier_session` volume.
- If the capture run fails to log in first, run the **refresh-heb-login** skill, then retry.
- Avoid repeated automated hits to heb.com (WAF 401 + email verification triggers).
