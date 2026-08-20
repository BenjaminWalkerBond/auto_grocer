---
name: refresh-graphql-hashes
description: 'Refresh HEB GraphQL persisted-query hashes for the auto-grocier MCP server. Use when MCP tools return OPERATION_NOT_CAPTURED, persisted-query/hash mismatch errors, or product search / add-to-cart / checkout calls fail after an HEB site update. Captures fresh hashes INSIDE the Docker container (Xvfb, no host browser), which writes persisted_queries.json directly into the session volume, then calls refresh_session.'
argument-hint: 'Run when tools return OPERATION_NOT_CAPTURED'
---

# Refresh HEB GraphQL Hashes

HEB uses persisted GraphQL queries keyed by hashes. When HEB updates its site the
hashes change and pure-GraphQL MCP tools fail with `OPERATION_NOT_CAPTURED` or
persisted-query errors. The capture flow drives a real browser, sniffs the hashes
via CDP, and writes `persisted_queries.json` (and a fresh `auth.json`).

**Run the capture INSIDE the Docker container.** The container drives Chromium
headfully under Xvfb (`DISPLAY=:99`) and writes directly to the
`auto_grocier_session` volume that the MCP server reads. This means **no browser
window opens on your host** and **no manual volume sync is needed**. Never run the
host flow with `DISPLAY=:0` — that pops a browser on the user's desktop.

## When to Use
- Any MCP tool returns `OPERATION_NOT_CAPTURED`.
- Persisted-query / hash-mismatch errors after an HEB site change.
- Search/add/checkout fail while `auth_status` is `authenticated:true`.

## Procedure
Run every command yourself — never ask the user to run them.

1. Capture fresh hashes in-container (also re-exports `auth.json`). Watch the
   output for an email-verification prompt:
   ```bash
   docker compose --env-file .env -f docker/docker-compose.yml run --rm -T \
     -e MODE=nodriver -e OPERATION=capture_hashes mcp python -m auto_grocier.session_maintenance.run
   ```
   **Do NOT pipe this through `tail`, `head`, or `grep`.** If the hashes are
   stale, session maintenance itself is the thing under suspicion — you need the
   full, unfiltered output to see where the capture actually broke. Truncating it
   hides the real failure.
2. Reload the hashes/session in the server: call `mcp_auto-grocier_refresh_session`.
3. Verify: call `mcp_auto-grocier_search_products` (e.g. "milk") — expect results
   with real `product_id`s, not `OPERATION_NOT_CAPTURED` or suggestion-only rows.

## Notes
- The capture runs the `auto_grocier.session_maintenance.run` module (MODE=nodriver
  OPERATION=capture_hashes). The old `grocery_browser.run` module no longer exists.
- The container writes `auth.json`, `persisted_queries.json`, and
  `captured_operations.json` straight into the `auto_grocier_session` volume — no
  `docker run ... cp` sync step is required anymore.
- If the capture fails to log in first, run the **refresh-heb-login** skill, then retry.
- Avoid repeated automated hits to heb.com (WAF 401 + email verification triggers).
