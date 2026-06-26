# Architecture

The browser automation that used to live in a monolithic Selenium `main.py` has
been replaced by the async, nodriver-based **`grocery_browser`** package. There
is no Selenium or undetected-chromedriver in the project anymore.

- **Entrypoint:** `main.py` is a thin shim that delegates to
  `grocery_browser.run`. You can also run `python -m grocery_browser.run`.
- **Modes** (set `MODE` in `.env`, or via the `MODE` env var):
  `login_export`, `test`, `checkout_with_prompt`, `auto_checkout`, `graphql`,
  `graphql_checkout_with_prompt`, `graphql_auto_checkout`, `update_graphql_hashes`.
- **Flows** (login, clear_cart, reserve_time_slot, change_store_via_ui,
  add_ingredient, checkout) live in `grocery_browser/flows.py`.
- **Self-healing** (Claude rewrites a broken flow from a screenshot + page HTML)
  lives in `grocery_browser/self_healing.py`; rewrites are saved to
  `grocery_browser/updated_functions/`.
- **Debug capture** (screenshots / HTML / error JSON on failure) lives in
  `grocery_browser/logger.py`, written to `debug_logs/session_*/`.

See **[grocery_browser/README.md](../grocery_browser/README.md)** for the full
module layout and run instructions.

The MCP server (`mcp_server.py`) is pure GraphQL at runtime and reuses the
session exported by the browser flow; see the main
[README](../README.md#mcp-server-operations).
