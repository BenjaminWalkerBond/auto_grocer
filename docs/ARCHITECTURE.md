# Architecture

The browser automation that used to live in a monolithic Selenium `main.py` has
been replaced by the async, nodriver-based **`session_maintenance`** package. There
is no Selenium or undetected-chromedriver in the project anymore.

- **Entrypoint:** `main.py` is a thin shim that delegates to
  `session_maintenance.run`. You can also run `python -m session_maintenance.run`.
- **Modes** (set `MODE` in `.env`, or via the `MODE` env var): two core modes.
  `graphql` shops via the HEB GraphQL API (`CHECKOUT=none|prompt|auto`).
  `nodriver` drives the browser, selected by `OPERATION=shop|login_export|
  capture_hashes` (for `OPERATION=shop`, `CHECKOUT=none|prompt|auto`).
- **Flows** (login, clear_cart, reserve_time_slot, change_store_via_ui,
  add_ingredient, checkout) live in `session_maintenance/flows.py`.
- **Self-healing** (Claude rewrites a broken flow from a screenshot + page HTML)
  lives in `session_maintenance/self_healing.py`; rewrites are saved to
  `session_maintenance/updated_functions/`.
- **Debug capture** (screenshots / HTML / error JSON on failure) lives in
  `session_maintenance/logger.py`, written to `debug_logs/session_*/`.

See **[session_maintenance/README.md](../session_maintenance/README.md)** for the full
module layout and run instructions.

The MCP server (`mcp_server.py`) is pure GraphQL at runtime and reuses the
session exported by the browser flow; see the main
[README](../README.md#mcp-server-operations).
