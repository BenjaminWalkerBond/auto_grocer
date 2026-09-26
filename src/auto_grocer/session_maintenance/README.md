# session_maintenance — async browser automation (nodriver)

The browser-automation layer for auto_grocer, built on
[`nodriver`](https://github.com/ultrafunkamsterdam/nodriver) — the maintained,
CDP-native successor to undetected-chromedriver. It drives HEB's site (no
Selenium, no chromedriver) to log in, reserve pickup slots, add items, capture
GraphQL persisted-query hashes, and export the authenticated session the
GraphQL/MCP path reuses.

Selenium and undetected-chromedriver have been **removed** from the project;
this package is the sole browser implementation.

## Why nodriver

- Maintained, with strong anti-bot evasion (Imperva/Incapsula `reese84`,
  Cloudflare) — validated logging into HEB both on the host and **inside Docker**
  (Chromium under Xvfb).
- No chromedriver binary, no Chrome version pin (auto-detects the browser).
- CDP-native network capture for GraphQL hash sniffing.

Trade-off: nodriver is fully async, so the entrypoint runs on an event loop.

## Layout

| Module | Purpose |
|--------|---------|
| `browser.py` | start/stop a Browser (auto-detect Chrome; env overrides for Docker/Xvfb) |
| `primitives.py` | async helpers + select-with-fallbacks (replaces WebDriverWait/EC) |
| `logger.py` | async screenshot / HTML / error capture into `debug_logs/` |
| `auth_export.py` | export cookies + localStorage → `auth.json` |
| `self_healing.py` | async Claude-powered function repair (saves to `updated_functions/`) |
| `flows.py` | login, clear_cart, reserve_time_slot, change_store_via_ui, add_ingredient, checkout |
| `hash_capture.py` | capture GraphQL hashes via CDP `Network` events |
| `run.py` | async mode dispatcher (the program entrypoint; `main.py` delegates here) |

## Running

From the repo root, after `uv sync`, with `config.txt` present (prefix commands
with `uv run`):

```bash
# MODE is read from .env; the MODE env var overrides it.
uv run python -m session_maintenance.run

# --- Two core modes ---

# graphql (default): shop via the HEB GraphQL API (fast).
#   CHECKOUT = none (default) | prompt | auto   (never places a paid order)
MODE=graphql uv run python -m session_maintenance.run
MODE=graphql CHECKOUT=prompt uv run python -m session_maintenance.run

# nodriver: drive the HEB website with the browser. Selected by OPERATION:
#   OPERATION = shop (default) | login_export | capture_hashes
#   For OPERATION=shop, CHECKOUT = none (default) | prompt | auto.
MODE=nodriver OPERATION=shop CHECKOUT=none uv run python -m session_maintenance.run

# Refresh the MCP session (login + export auth.json):
MODE=nodriver OPERATION=login_export uv run python -m session_maintenance.run

# Capture fresh GraphQL hashes (also exports auth.json):
MODE=nodriver OPERATION=capture_hashes uv run python -m session_maintenance.run

# WAF baseline probe (fingerprint + single heb.com hit; diagnostic only):
uv run python -m session_maintenance.waf_probe
```

`uv run python main.py` is a thin shim that calls `session_maintenance.run` with the same
modes.

## Notes

- **Headless host:** set `DISPLAY` to an X server (WSLg on Windows, or Xvfb). The
  Docker image runs Chromium under Xvfb automatically.
- **Docker / root:** set `AUTO_GROCER_NO_SANDBOX=1` (Chrome's sandbox refuses to
  run as root) and `NODRIVER_BROWSER_PATH` to the Chromium binary.
- Self-healing rewrites are saved to `session_maintenance/updated_functions/`
  (gitignored, regenerated at runtime).
- The checkout flow stops at HEB's checkout page; placing a paid order is the MCP
  server's guarded `place_order` tool.
