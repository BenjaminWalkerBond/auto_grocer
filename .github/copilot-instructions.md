# auto_grocier — agent instructions

This repo automates HEB grocery ordering through the `auto-grocier` MCP server,
which reuses an exported HEB session and persisted GraphQL hashes.

## Startup check (do this first, every session)
Before using any HEB cart / timeslot / checkout / search tool, verify the session
and recover automatically:

1. Call `mcp_auto-grocier_auth_status`. If `authenticated:false` (or any tool
   returns `NOT_AUTHENTICATED`), run the **refresh-heb-login** skill.
2. If any tool returns `OPERATION_NOT_CAPTURED` or a persisted-query/hash error,
   run the **refresh-graphql-hashes** skill.
3. Re-run `mcp_auto-grocier_auth_status` and proceed once it returns
   `authenticated:true`.

Both skills require running login flows on the host with `source venv/bin/activate`,
then syncing files into the `auto_grocier_session` Docker volume and calling
`mcp_auto-grocier_refresh_session`. Never hammer heb.com — repeated hits trigger
WAF 401s and email verification.
