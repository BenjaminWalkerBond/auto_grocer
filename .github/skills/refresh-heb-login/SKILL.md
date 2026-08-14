---
name: refresh-heb-login
description: 'Refresh the HEB login session for the auto-grocier MCP server. Use when MCP tools return NOT_AUTHENTICATED, auth_status reports authenticated:false, or any cart/timeslot/checkout/search tool fails to start because there is no valid session. Logs in INSIDE the Docker container (Xvfb, no host browser), which writes a fresh auth.json directly into the session volume, then calls refresh_session.'
argument-hint: 'Run when HEB tools say NOT_AUTHENTICATED'
---

# Refresh HEB Login Session

The MCP server (`auto-grocier`) reuses an exported HEB session. The container reads
it from the Docker named volume `auto_grocier_session` (mounted at
`/root/.texas-grocery-mcp`).

**Run the login INSIDE the Docker container.** The container drives Chromium
headfully under Xvfb (`DISPLAY=:99`) and writes the fresh `auth.json` directly to
the `auto_grocier_session` volume. This means **no browser window opens on your
host** and **no manual volume sync is needed**. Never run the host flow with
`DISPLAY=:0` — that pops a browser on the user's desktop.

## When to Use
- `auth_status` returns `{"authenticated": false}`.
- Any MCP tool returns `NOT_AUTHENTICATED`.
- `refresh_session` alone does not flip authenticated to true.

## Procedure
Run every command yourself — never ask the user to run them.

1. Confirm the session is stale: call `mcp_auto-grocier_auth_status`. If already
   `authenticated:true`, stop.
2. Log in in-container (writes `auth.json` into the session volume). Watch the
   output for an email-verification prompt:
   ```bash
   docker compose --env-file .env -f docker/docker-compose.yml run --rm -T \
     -e MODE=nodriver -e OPERATION=login_export mcp python -m session_maintenance.run
   ```
   **Do NOT pipe this through `tail`, `head`, or `grep`.** When the session is
   broken, session maintenance is the thing under suspicion — read its full,
   unfiltered output so the real failure point is visible.
3. Reload the session in the server: call `mcp_auto-grocier_refresh_session`.
4. Verify with `mcp_auto-grocier_auth_status` → expect `{"authenticated": true}`.

## Notes
- The login runs the `session_maintenance.run` module (MODE=nodriver
  OPERATION=login_export). The old `grocery_browser.run` module no longer exists.
- Session file lands in the `auto_grocier_session` volume
  (`/root/.texas-grocery-mcp/auth.json`) — no `docker run ... cp` sync step needed.
- Do NOT hammer heb.com; repeated automated hits trigger WAF 401s and email verification.
- If tools still fail with `OPERATION_NOT_CAPTURED`, run the **refresh-graphql-hashes** skill.
