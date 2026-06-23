# nodriver migration prototype (Step 1)

A parallel, async reimplementation of the auto_grocier browser layer using
[`nodriver`](https://github.com/ultrafunkamsterdam/nodriver) — the maintained,
CDP-native successor to the (now abandoned) `undetected_chromedriver`.

**This is Step 1 of a two-step migration.** Nothing here modifies or imports the
existing Selenium code in `main.py` / `utility/`. The goal is to validate that
the async nodriver stack works end-to-end before doing the full in-place swap
(Step 2).

## Why nodriver

- Maintained successor to `undetected_chromedriver` (same author).
- Stronger anti-bot evasion (Imperva/Incapsula `reese84`, Cloudflare) — directly
  helps keep the MCP session alive.
- No chromedriver binary, no Chrome version pin (auto-detects the browser).
- CDP-native network capture (cleaner GraphQL hash sniffing).

Trade-off: nodriver is **fully async**, so every browser call is `await`ed and
the entry point runs on an event loop.

## Layout

| Module | Replaces (Selenium) | Purpose |
|--------|---------------------|---------|
| `browser.py` | `uc.Chrome(...)` in `main.py` | start/stop a Browser, no version pin |
| `primitives.py` | `random_time`, `human_like_*`, `check_exists_by_xpath`, `dismiss_modals`, `WebDriverWait` loops | async helpers + select-with-fallbacks |
| `logger.py` | `utility/driver_logger.py` | async screenshot / HTML / error capture |
| `auth_export.py` | `utility/graphql_auth.py` | export cookies + localStorage → `auth.json` |
| `self_healing.py` | `utility/self_healing.py` | async-aware Claude function repair |
| `flows.py` | the `driver`-taking flows in `main.py` | login, clear_cart, reserve_time_slot, change_store_via_ui, add_ingredient, checkout |
| `hash_capture.py` | `utility/graphql_hash_capture.py` | capture GraphQL hashes via CDP Network events |
| `run.py` | the `__main__` block + mode functions in `main.py` | async mode dispatcher |

Reused unchanged (not Selenium-bound): `claude.py`, `classes/`,
`utility/read_email.py`, `utility/graphql_cart.py`,
`utility/graphql_hash_capture.py` (pure parsers/savers), `texas_grocery_mcp/`.

## Running

From the project root, with the venv active and `config.txt` present:

```bash
source venv/bin/activate
export DISPLAY=${DISPLAY:-:0}      # WSLg / Xvfb for the visible browser

# Refresh the MCP session (login + export auth.json only):
MODE=login_export python -m migration.nodriver.run

# Capture fresh GraphQL hashes (also exports auth.json):
MODE=update_graphql_hashes python -m migration.nodriver.run

# Full legacy test flow (login, clear cart, reserve slot, add ingredients):
MODE=test python -m migration.nodriver.run

# Add ingredients via the GraphQL API after login/export:
MODE=graphql python -m migration.nodriver.run
```

> `MODE` is read from `config.txt`; the env-var examples above assume you export
> `MODE` before running (or just set it in `config.txt`).

Self-healing rewrites are saved to `migration/nodriver/updated_functions/`
(async nodriver functions — separate from the Selenium ones in the repo-root
`updated_functions/`).

## Step 1 validation checklist

1. `MODE=update_graphql_hashes` logs in (email verification handled), exercises
   the flows, writes `~/.texas-grocery-mcp/persisted_queries.json` and
   `auth.json` (look for "Exported N cookies" + a found `reese84`).
2. MCP `refresh_session` / `auth_status` report `authenticated: true`.
3. An MCP cart op (`add_groceries` / `get_cart`) works on the exported session.
4. `reserve_time_slot` completes tier + date + timeslot selection.
5. Forcing a selector failure triggers async self-healing (valid async rewrite,
   saved + retried).
6. Captured hashes match the current `persisted_queries.json`.

Once these pass, proceed to **Step 2** (the full in-place migration).
