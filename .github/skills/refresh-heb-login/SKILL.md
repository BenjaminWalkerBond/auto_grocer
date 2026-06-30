---
name: refresh-heb-login
description: 'Refresh the HEB login session for the auto-grocier MCP server. Use when MCP tools return NOT_AUTHENTICATED, auth_status reports authenticated:false, or any cart/timeslot/checkout/search tool fails to start because there is no valid session. Logs in via a real browser, exports a fresh auth.json, syncs it into the Docker session volume, then calls refresh_session.'
argument-hint: 'Run when HEB tools say NOT_AUTHENTICATED'
---

# Refresh HEB Login Session

The MCP server (`auto-grocier`) reuses an exported HEB session. The container reads
it from the Docker named volume `auto_grocier_session` (mounted at
`/root/.texas-grocery-mcp`). A real browser login is required to mint cookies
(HEB's Incapsula WAF blocks headless/Xvfb-only logins). Auto-login inside the
container is unreliable, so refresh on the host and sync into the volume.

## When to Use
- `auth_status` returns `{"authenticated": false}`.
- Any MCP tool returns `NOT_AUTHENTICATED`.
- `refresh_session` alone does not flip authenticated to true.

## Procedure
1. Confirm the session is stale: call `mcp_auto-grocier_auth_status`. If already
   `authenticated:true`, stop.
2. Log in on the host with a real display (writes `~/.texas-grocery-mcp/auth.json`).
   May prompt for email verification:
   ```bash
   source venv/bin/activate
   MODE=login_export DISPLAY=:0 python -m grocery_browser.run
   ```
3. Sync the fresh session into the Docker volume the container reads:
   ```bash
   docker run --rm -v auto_grocier_session:/v -v ~/.texas-grocery-mcp:/src:ro alpine \
     sh -c 'cp /src/auth.json /v/auth.json; cp /src/persisted_queries.json /v/ 2>/dev/null; cp /src/captured_operations.json /v/ 2>/dev/null'
   ```
4. Reload the session in the server: call `mcp_auto-grocier_refresh_session`.
5. Verify with `mcp_auto-grocier_auth_status` → expect `{"authenticated": true}`.

## Notes
- Session file: `~/.texas-grocery-mcp/auth.json` (host) → `auto_grocier_session` volume (container).
- Do NOT hammer heb.com; repeated automated hits trigger WAF 401s and email verification.
- If tools still fail with `OPERATION_NOT_CAPTURED`, run the **refresh-graphql-hashes** skill.
