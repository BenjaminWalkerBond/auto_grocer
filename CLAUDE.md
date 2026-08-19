# auto_grocier — Agent Instructions

This project automates HEB grocery ordering. The primary interface is the **MCP server**
(`auto-grocier`), which exposes grocery operations as tools over pure GraphQL.

---

## 🛒 MCP Server Usage (Primary Interface)

### Session Check (ALWAYS DO THIS FIRST)

Before using any HEB grocery tools, validate the session:

1. Call `mcp_auto-grocier_auth_status`
2. If `authenticated: false` → run the **refresh-heb-login** skill, then `refresh_session`
3. If tools return `OPERATION_NOT_CAPTURED` → run the **refresh-graphql-hashes** skill, then `refresh_session`

### Typical Workflow

```
auth_status                          # Verify session
add_groceries / add_recipe_ingredients  # Add items to cart
get_cart                             # Review cart
list_timeslots                       # See pickup times
reserve_timeslot                     # Lock a slot
checkout                             # Review order (NO CHARGE)
place_order                          # OPTIONAL: Final order (CHARGES CARD)
```

### Key Tools

| Tool | Purpose |
|------|---------|
| `auth_status` | Check session validity |
| `refresh_session` | Reload session after running refresh skills |
| `search_products(query)` | Search HEB products |
| `add_groceries(items)` | Add free-form items to cart |
| `add_recipe_ingredients(request)` | Add recipe ingredients by natural language |
| `get_cart` | View cart contents |
| `clear_cart` | Empty cart |
| `list_timeslots` | Available pickup slots |
| `reserve_timeslot(slot_id)` | Reserve a slot |
| `checkout` | Go to order review (safe, no charge) |
| `place_order` | **⚠️ CHARGES CARD** (disabled by default) |

### Error Recovery

| Error | Solution |
|-------|----------|
| `NOT_AUTHENTICATED` | Run **refresh-heb-login** skill |
| `OPERATION_NOT_CAPTURED` | Run **refresh-graphql-hashes** skill |
| WAF 401 / Email verification | Wait, then retry login manually |

### Starting the MCP Server

**Docker (recommended):**
```bash
docker compose -f docker/docker-compose.yml run --rm -T mcp
```

**Local:**
```bash
uv run python mcp_server.py
```

VS Code auto-launches via `.vscode/mcp.json`.

### Adding to Claude as a Custom Connector

Claude exposes MCP servers through **Settings → Connectors → Add custom connector**.
There are two ways to connect `auto-grocier`, depending on transport:

#### Option A — Local stdio (works today, recommended)

Claude Desktop launches the server itself over stdio. Because Claude runs from its
own working directory, the compose `-f` path **must be the absolute path to
`docker/docker-compose.yml` in your clone**.

First, from the **repo root**, print the exact path to paste into the config:

```bash
# macOS / Linux / WSL
echo "$(pwd)/docker/docker-compose.yml"
```

```powershell
# Windows PowerShell
"$($PWD.Path -replace '\\','/')/docker/docker-compose.yml"
```

Then edit `claude_desktop_config.json` (**Settings → Developer → Edit Config**) —
the key is **`mcpServers`** — and paste that path in place of `<ABSOLUTE_PATH>`:

```json
{
  "mcpServers": {
    "auto-grocier": {
      "command": "docker",
      "args": [
        "compose",
        "-f", "<ABSOLUTE_PATH>/docker/docker-compose.yml",
        "run", "--rm", "-T", "mcp"
      ]
    }
  }
}
```

> On Windows, use forward slashes in the JSON (e.g.
> `C:/Users/you/auto_grocier/docker/docker-compose.yml`) — the PowerShell command
> above already emits them.

Config file location:

| OS | Path |
|----|------|
| Windows | `%APPDATA%\Claude\claude_desktop_config.json` |
| macOS | `~/Library/Application Support/Claude/claude_desktop_config.json` |

Restart Claude, confirm `auto-grocier` shows a connected tool count, then ask it to
call `auth_status`.

#### Option B — Remote URL connector (requires HTTP transport)

The **Add custom connector** dialog that takes a **URL** needs the server running over
the optional streamable-HTTP transport (see
[docs/adr/0002-self-hosted-remote-mcp.md](docs/adr/0002-self-hosted-remote-mcp.md)).
This transport is **not enabled by default** — stdio is. Once enabled:

1. Start the server in HTTP mode (bound to loopback):
   ```bash
   AUTO_GROCIER_TRANSPORT=http uv run python mcp_server.py
   ```
2. Default endpoint URL: **`http://127.0.0.1:8000/mcp`**
   (override host/port via `AUTO_GROCIER_HTTP_HOST` / `AUTO_GROCIER_HTTP_PORT`).
3. In Claude: **Settings → Connectors → Add custom connector** → paste the URL and the
   bearer token (`AUTO_GROCIER_HTTP_TOKEN`, required in HTTP mode).
4. For access outside localhost, front the loopback port with an HTTPS tunnel
   (Cloudflare Tunnel / Tailscale Funnel) and use the `https://<name>/mcp` URL — never
   a raw port-forward.

> ⚠️ Do not point a connector at a tokenless HTTP server, and keep `place_order`
> disabled on any remotely reachable instance.

---

## 🔧 Development & Maintenance

The sections below cover the Claude API, browser automation, and debugging — used for
developing/maintaining the automation, not for routine grocery ordering.

### Claude API Setup

The project uses Anthropic's Claude Sonnet API for ingredient parsing and self-healing.

### ⚠️ IMPORTANT: Environment (uv)
**Run project commands through `uv run` so they use the project environment.**
Run `uv sync` once to create/update the local `.venv` (uv manages it on all
platforms — no manual activation needed):

```bash
# One-time (or after deps change):
uv sync

# Then run anything inside the project env:
uv run python main.py
uv run pytest tests/unit
```

If the 3.12 interpreter is missing, run `uv python install 3.12` first.

## Configuration

### Option 1: Add to .env (Recommended)
The `.env` file uses a labeled KEY=VALUE format. Copy `.env.example` to `.env` and add your Claude API key:

```
# .env
# Lines starting with # are comments and will be ignored
# Format: KEY=VALUE

EMAIL=your-email@example.com
PASSWORD=your-password
CLAUDE_API_KEY=your-claude-api-key-here
MODE=graphql
```

The `.env` file supports:
- Comments (lines starting with #)
- KEY=VALUE format
- Empty lines are ignored

### Program Mode (in .env)

The `MODE` key in `.env` controls how the program runs. There are two core modes:

| Mode | Description |
|------|-------------|
| `graphql` (default) | Shop via the HEB GraphQL API (fast). `CHECKOUT=none` adds only; `prompt`/`auto` advance to checkout. |
| `nodriver` | Drive the HEB website with the browser. Selected by `OPERATION` (below). |

For `MODE=nodriver`, `OPERATION` selects the task:

| OPERATION | Description |
|-----------|-------------|
| `shop` (default) | Adds ingredients via the browser UI. `CHECKOUT=none` (no checkout), `prompt` (confirm first), or `auto` (**can advance to checkout**). |
| `login_export` | Log in and export `auth.json` (refresh the MCP session). |
| `capture_hashes` | Log in, exercise flows, capture GraphQL persisted-query hashes. |

`CHECKOUT` never places a paid order; it only advances to HEB's checkout page.

Example:
```
MODE=nodriver
OPERATION=shop
CHECKOUT=prompt
```

### Option 2: Environment Variable
Set the `ANTHROPIC_API_KEY` environment variable:

**Linux/Mac/WSL:**
```bash
export ANTHROPIC_API_KEY="your-api-key-here"
```

**Windows PowerShell:**
```powershell
$env:ANTHROPIC_API_KEY="your-api-key-here"
```

**Windows Command Prompt:**
```cmd
set ANTHROPIC_API_KEY=your-api-key-here
```

## Getting a Claude API Key

1. Go to [https://console.anthropic.com/](https://console.anthropic.com/)
2. Sign up or log in to your account
3. Navigate to API Keys section
4. Create a new API key
5. Copy the key and add it to your `.env` file or environment variables

## Model Used

The code uses **Claude Sonnet 4** (`claude-sonnet-4-20250514`), which is:
- Fast and efficient
- Great for structured data extraction
- Cost-effective for ingredient parsing tasks

## Changes Made

1. **chatgpt3.py** - Replaced OpenAI implementation with Anthropic Claude
2. **requirements.txt** - Added `anthropic>=0.75.0` package
3. Function signatures remain the same, so no changes needed in `recipe_grabber.py`

## Testing

**The automated test suite lives in `tests/`** — `tests/unit/` (fast, no external
services; run by default) and `tests/integration/` (live HEB API or Postgres,
skipped unless `--run-integration` is passed).

To run tests:

```bash
# Unit suite (fast, offline)
uv run pytest tests/unit

# Include integration tests (needs an authenticated session and/or a live DB)
uv run pytest --run-integration

# Full browser automation run (adds to cart, no checkout/charge)
MODE=nodriver OPERATION=shop CHECKOUT=none uv run python main.py
```

**Note:** ad-hoc demo scripts that used to live in `manual_scripts/` have been
removed — the useful ones were promoted to `tests/` (e.g.
`tests/unit/test_auth_export.py`, `tests/integration/test_recipe_matcher_live.py`).
New tests belong in `tests/`, one-off maintenance utilities in `scripts/`.

## Testing Cycle for Main Program

**💡 NEW:** The program now has improved error handling with automatic pause and debug capture when errors occur. See [docs/SOFT_STOP_GUIDE.md](docs/SOFT_STOP_GUIDE.md) for details.

### Test Mode Overview

A browser test run (`MODE=nodriver OPERATION=shop CHECKOUT=none` in `.env`) runs the full automation pipeline **without completing checkout**. It is the safest way to verify the program works end-to-end. The flow is:

1. **Login** — Authenticates with HEB using credentials from `.env`, handling email verification and passkey prompts automatically.
2. **Clear cart** — Navigates to the cart and removes any existing items.
3. **Reserve time slot** — Opens the reservation modal, selects a free curbside pickup date and timeslot.
4. **Add ingredients** — Searches for each ingredient on heb.com and clicks "Add to cart". Ingredients tagged as `vegetable` or `fruit` are prefixed with "organic".
5. **Stop** — Prints a completion message and **keeps the browser open** so you can manually inspect the cart contents. Press Enter in the terminal to close the browser.

All steps are wrapped with `self_healing_call`, which uses the Claude API to automatically rewrite broken **nodriver** flow functions on failure (up to 3 retries per function). Screenshots and page HTML are sent to Claude for context. Rewritten functions are saved to `session_maintenance/updated_functions/` for later review.

No payment is processed. No order is placed.

When testing the main program with web scraping functionality, follow this systematic debugging cycle:

### 1. Run the Program in Test Mode

```bash
# Ensure a browser test run is configured in .env:
# MODE=nodriver
# OPERATION=shop
# CHECKOUT=none

# Run main program via uv
uv run python main.py
```

### 2. Watch Terminal Output Closely

Monitor the terminal for:
- nodriver / Chrome (CDP) initialization messages
- Login attempts and status
- Page navigation events
- Element detection messages
- Error messages or exceptions
- Stack traces

**Pay special attention to:**
- NoSuchElementException errors (element not found)
- TimeoutException errors (page load or element wait timeout)
- WebDriverException errors (browser/driver issues)
- Any logged warnings or error messages

### 3. Check the Debug Logs

**Note:** Debug logs are only created when running `python main.py`. They are NOT created when running the pytest suite (`uv run pytest`).

Navigate to the `debug_logs/` directory:

```bash
cd debug_logs/
ls -lt  # List sessions sorted by time (newest first)
```

Find the latest session directory (format: `session_YYYYMMDD_HHMMSS/`):

```bash
# Example: session_20251205_172111/
cd session_20251205_172111/
ls -la
```

### 4. Review Debug Artifacts

Each session directory contains timestamped debug files:

**Screenshot Files (.png):**
```bash
# View screenshot to see what the browser actually saw
# Format: YYYYMMDD_HHMMSS_MICROSECONDS_<context>_<error_type>.png
# Example: 20251205_163148_880746_login_NoSuchElementException.png
```

**HTML Source Files (.html):**
```bash
# Open HTML file to inspect the page structure
# This shows the actual HTML elements available at time of error
# Format: YYYYMMDD_HHMMSS_MICROSECONDS_<context>_<error_type>.html
```

**Error Information:**
- Error type is embedded in the filename (e.g., `NoSuchElementException`)
- Context label indicates which operation was being performed (e.g., `login`, `navigation`, `scraping`)
- Timestamp helps correlate with terminal output

### 5. Analyze and Make Changes

Based on the debug artifacts:

1. **Compare Screenshot vs. Expected Page:**
   - Is the page loaded correctly?
   - Are expected elements visible?
   - Did the page navigate to the right location?

2. **Inspect HTML Source:**
   - Are the selectors correct?
   - Have element IDs or classes changed?
   - Are elements present but hidden/disabled?
   - Check for dynamic content loading

3. **Common Issues and Fixes:**

   **NoSuchElementException:**
   - Element selector is wrong → Update selector in code
   - Element not loaded yet → Increase wait time
   - Page structure changed → Inspect HTML and update selectors

   **TimeoutException:**
   - Slow page load → Increase timeout value
   - Wrong page loaded → Check navigation logic
   - Element never appears → Verify page flow

   **Login/Authentication Issues:**
   - Check credentials in .env
   - Look for CAPTCHA or bot detection in screenshot
   - Verify login form selectors in HTML

4. **Make Code Changes:**
   - Update selectors in `recipe_grabber.py` or relevant module
   - Adjust wait times in WebDriver configuration
   - Add additional error handling
   - Update login flow if needed

### 6. Iterate

Repeat the testing cycle:
1. Make changes based on analysis
2. Run program with test flag again
3. Monitor terminal output
4. Check new debug logs
5. Verify the issue is resolved

### Example Complete Cycle

```bash
# 1. Set MODE to 'test' in main.py, then run
python main.py

# 2. (Watch terminal output for errors)

# 3. Navigate to latest debug logs
cd debug_logs/
cd $(ls -t | head -1)  # Go to most recent session

# 4. Review files
ls -la
# View screenshot (use your preferred image viewer)
# Open HTML in browser or text editor

# 5. Analyze and identify issue
# Example: Found that button ID changed from "submit-btn" to "submit-button"

# 6. Make changes in code
# Update the selector in recipe_grabber.py

# 7. Test again
cd ../..  # Back to project root
python main.py
```

### Pro Tips

- **Keep multiple terminal windows open:** One for running the program, one for navigating debug logs
- **Use a diff tool:** Compare HTML files between working and broken sessions
- **Check browser:** nodriver auto-detects the installed Chrome/Chromium (no chromedriver to version-match)
- **Enable verbose logging:** Set logging level to DEBUG for more detailed output
- **Save working sessions:** Keep debug logs from successful runs for comparison

