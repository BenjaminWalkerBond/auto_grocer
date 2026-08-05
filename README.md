# Auto Grocier

An automated grocery shopping assistant that parses recipes and manages ingredients.

## 🔒 Security Notice

**NEVER commit `.env` to version control!** It contains sensitive credentials.

1. Copy `.env.example` to `.env`
2. Fill in your actual credentials in `.env`
3. The `.gitignore` file ensures `.env` stays local only

## Prerequisites

The **recommended** way to run auto_grocier is the source-only Docker path: clone
the repo and start everything with `docker compose`. The Docker image bundles
**PostgreSQL, Chromium, and Xvfb**, so it can refresh its own HEB session with no
host Python, Postgres, or browser install.

```bash
git clone <your-auto_grocier-repo-url>
cd auto_grocier
cp .env.example .env          # then fill in your credentials (see below)
docker compose -f docker/docker-compose.yml build mcp
docker compose -f docker/docker-compose.yml run --rm -T mcp
```

The host `python main.py` path (see [Quick Start](#quick-start-usage)) is the
**alternative** for local development.

### What you need

Regardless of path, you need the following to get from a fresh clone to a running
MCP server:

- **Docker Desktop** — for the recommended route (bundles Postgres + Chromium + Xvfb).
- **PostgreSQL** (Postgres) — only if you run on the host *without* the
  compose-provided database; the Docker route provides one for you.
- **Chromium / Chrome** — only for the host login path; the Docker image bundles it.
- **A Gmail account + app password** — HEB sends email-verification codes, which
  are read over IMAP. Set `EMAIL` and the Gmail IMAP **app password** in `.env`.
- **An Anthropic / Claude API key** — `CLAUDE_API_KEY` (`sk-ant-...`) for ingredient
  parsing and self-healing.
- **An active H-E-B account** — `EMAIL` / `PASSWORD` in `.env`.
- **Store selection** — set your active pickup store (via the `set_store` tool or
  the store setting in `.env`) so orders route to the right location.

## Quick Start (Usage)

Talk to your HEB cart from an MCP client (GitHub Copilot or Claude Desktop). This
section assumes you already have **Docker Desktop** installed and a filled-in
repo-root **`.env`** (HEB credentials, Gmail IMAP app password, `CLAUDE_API_KEY`,
`DATABASE_PASSWORD`). If you still need to build the image, set up `.env`, or seed
the HEB session, see [Development](#development).

The MCP server id is **`auto-grocier`** and launches over stdio via Docker Compose:
`docker compose -f docker/docker-compose.yml run --rm -T mcp`.

Pick your client below.

<details>
<summary><strong>GitHub Copilot (VS Code)</strong></summary>

**Workspace (recommended).** The repo already ships
[.vscode/mcp.json](.vscode/mcp.json). Just open the `auto_grocier` folder in VS Code
and Copilot auto-detects the server — no config to write:

```json
{
  "servers": {
    "auto-grocier": {
      "type": "stdio",
      "command": "docker",
      "args": ["compose", "-f", "docker/docker-compose.yml", "run", "--rm", "-T", "mcp"]
    }
  }
}
```

Because the compose `-f` path is **relative to the repo root**, the workspace must be
the `auto_grocier` folder for this to resolve.

**User-level (optional).** To make the server available in every workspace, add the
same `auto-grocier` block to your user `mcp.json` (Command Palette →
**MCP: Open User Configuration**). In that case change `-f docker/docker-compose.yml`
to an **absolute** path, e.g. `-f /absolute/path/to/auto_grocier/docker/docker-compose.yml`.

**Verify:** open Copilot Chat (Agent mode) and ask it to call `auth_status` — it
should report whether a valid HEB session is available.

</details>

<details>
<summary><strong>Claude Desktop</strong></summary>

Edit `claude_desktop_config.json` (Claude Desktop → **Settings → Developer → Edit
Config**). Note the key is **`mcpServers`** (not `servers`), and because Claude
Desktop runs from its own working directory the compose `-f` path **must be
absolute**:

```json
{
  "mcpServers": {
    "auto-grocier": {
      "command": "docker",
      "args": [
        "compose",
        "-f", "/absolute/path/to/auto_grocier/docker/docker-compose.yml",
        "run", "--rm", "-T", "mcp"
      ]
    }
  }
}
```

Config file location:

| OS | Path |
|----|------|
| Windows | `%APPDATA%\Claude\claude_desktop_config.json` |
| macOS | `~/Library/Application Support/Claude/claude_desktop_config.json` |

Replace `/absolute/path/to/auto_grocier` with your real clone path (on Windows use
your actual path, e.g. `C:/Users/you/auto_grocier/docker/docker-compose.yml`).

**Verify:** restart Claude Desktop, confirm `auto-grocier` shows a connected tool
count, then ask Claude to call `auth_status`.

</details>

**First run.** The container needs a valid HEB session. With
`AUTO_GROCIER_AUTO_LOGIN` on (the default), the server logs itself in on the first
authenticated tool call (e.g. `search_products` or `get_cart`) — this can take
**up to a minute** while it drives Chromium under Xvfb and completes HEB's normal
sign-in. To pre-seed the session instead of waiting, run
`MODE=update_graphql_hashes python -m session_maintenance.run` (see
[Development](#development)) and then call `refresh_session`.

## MCP Server Operations

The project ships an [MCP](https://modelcontextprotocol.io/) server (`mcp_server.py`)
that exposes HEB grocery automation as tools over **pure GraphQL** (no browser at
runtime). It reuses an exported HEB session — run the maintenance workflow
(`MODE=update_graphql_hashes python -m session_maintenance.run`) to log in and capture
the GraphQL hashes, then call `refresh_session`.

**Automatic login:** if no valid session is available when an authenticated tool
is called, the server automatically runs a one-off nodriver browser login
(`MODE=login_export python -m session_maintenance.run`) to refresh the session, then
continues. This can take up to a minute on the first call. Disable it with
`AUTO_GROCIER_AUTO_LOGIN=0` (tune the cap with `AUTO_GROCIER_AUTO_LOGIN_TIMEOUT`),
in which case tools return `NOT_AUTHENTICATED` and you refresh the session
manually.

### Available Tools

| Tool | Auth required | Description |
|------|:---:|-------------|
| `auth_status()` | No | Report whether a valid HEB session is available, the active store, and whether `place_order` is enabled. Reads the exported session; does not open a browser. |
| `refresh_session()` | No | Reload the exported session and the latest persisted-query hashes after running the maintenance workflow. Call this if tools start reporting `NOT_AUTHENTICATED` or `OPERATION_NOT_CAPTURED`. |
| `search_products(query, limit=10, store_id="")` | Yes | Search HEB products via GraphQL without adding anything to the cart. |
| `add_groceries(items, clear_first=False)` | Yes | Search for and add a list of free-form grocery items (e.g. `"2 lb chicken breast"`) to the cart. Produce is searched as organic automatically. |
| `add_recipe_ingredients(request, clear_first=False)` | Yes | Match a natural-language meal request against database recipes and add all matched recipes' ingredients to the cart. Requires seeded recipes. |
| `find_recipes(request)` | No | Preview which database recipes match a natural-language request **without** adding anything to the cart. |
| `query_recipes(search="", recipe_id=0, domain="", include_ingredients=False, limit=50)` | No | Browse/search/inspect the recipe database directly (no AI matching, no HEB login). |
| `list_all_recipes(page=1)` | No | List every recipe, paginated 10 per page. Returns each recipe's name, url, ingredient count, and cook time (minutes). Call `page=1`, then `page=2`, etc. until `has_next` is false. |
| `seed_recipes(title, url, ingredients, description="")` | No | Insert one recipe (with auto-tagged ingredients) into the recipe database. Re-seeding the same URL updates it instead of duplicating. **YouTube URLs** (videos/Shorts) are auto-detected: pass the URL with empty `ingredients` and it fetches the video description, parses the ingredients with Claude, and derives the title/description. |
| `get_cart()` | Yes | Return the current cart contents (items, quantities, totals). |
| `clear_cart()` | Yes | Empty all items from the cart. |
| `remove_from_cart(items)` | Yes | Remove specific items from the cart by product id, sku, or name fragment (sets their quantity to 0). |
| `set_store(store_id)` | Yes | Set the active pickup store for GraphQL operations. |
| `list_timeslots(store_id="")` | Yes | List available curbside pickup time slots. |
| `reserve_timeslot(slot_id, store_id="")` | Yes | Reserve a curbside pickup time slot (use `list_timeslots` first to get a slot id). |
| `checkout()` | Yes | Advance to the order-review stage. **Does NOT place the order and never charges.** Reserve a timeslot first. |
| `place_order()` | Yes | Submit the final **paid** order. ⚠️ **This charges your payment method.** Disabled by default — enable with `AUTO_GROCIER_ALLOW_PLACE_ORDER=1` in the server environment. |

### Typical Order of Operations

```
auth_status                          # confirm you're logged in
add_groceries / add_recipe_ingredients
get_cart                             # review what was added
list_timeslots
reserve_timeslot
checkout                             # review only — no charge
place_order                          # optional, guarded — CHARGES your card
```

> **Safety:** `place_order` is the only tool that spends money and is disabled
> unless `AUTO_GROCIER_ALLOW_PLACE_ORDER=1` is set. `checkout` only advances to
> order review and never charges.

## Development

This section covers running the automation and the MCP server from a host checkout,
plus the database tests and project layout. For usage from an MCP client, see
[Quick Start (Usage)](#quick-start-usage).

### Local setup (virtual environment)

Python 3.12 required.

PowerShell (Windows):
```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
```

bash / WSL / macOS:
```bash
python3 -m venv .venv
source .venv/bin/activate
```

### Configuration

Copy and edit the env file:
```bash
cp .env.example .env
# Then edit .env with your actual credentials
```

Example `.env`:
```
EMAIL=your-heb-email@example.com
PASSWORD=your-heb-password
CLAUDE_API_KEY=your-claude-api-key
DATABASE_HOST=localhost
DATABASE_PORT=5432
DATABASE_NAME=auto_grocier
DATABASE_USER=grocier_user
DATABASE_PASSWORD=your_secure_password
```

**Choose a mode** (set `MODE` in `.env`):
- `MODE=login_export` - log in and export the session (refresh MCP auth)
- `MODE=test` - login, reserve a slot, add ingredients (no checkout)
- `MODE=checkout_with_prompt` - prompts before advancing to checkout
- `MODE=auto_checkout` - advances to checkout automatically
- `MODE=graphql` / `graphql_checkout_with_prompt` / `graphql_auto_checkout` - add via the GraphQL API
- `MODE=update_graphql_hashes` - refresh HEB's GraphQL persisted-query hashes

**Ingredient source** (set `INGREDIENT_SOURCE` in `.env`): `hardcoded`
(default), `urls`, or `database`.

> The browser automation runs on **nodriver** (async, CDP-native). Selenium /
> undetected-chromedriver have been removed. The checkout flow stops at HEB's
> checkout page and never places a paid order.

See `CLAUDE.md` and `docs/POSTGRES_INSTALL.md` for detailed setup instructions.

### Running the automation

```bash
python main.py
# or, equivalently:
python -m session_maintenance.run
# override the mode without editing .env:
MODE=test python -m session_maintenance.run
```

### Running the MCP server on the host

```bash
source .venv/bin/activate
python mcp_server.py
```

### Running it fully in Docker

The whole stack — **PostgreSQL + the MCP server (with Chromium + Xvfb so it can
refresh its own HEB session)** — runs in containers, so no host Python/Postgres
install is required. Starting the MCP server auto-starts the database first
(`depends_on` + healthcheck).

```bash
# Build the MCP image (Python 3.12 + Chromium + Xvfb)
docker compose -f docker/docker-compose.yml build mcp

# Start just the database (optional; the MCP server starts it automatically)
docker compose -f docker/docker-compose.yml up -d postgres

# Run the MCP server over stdio (Postgres comes up first)
docker compose -f docker/docker-compose.yml run --rm -T mcp
```

VS Code launches it automatically via [.vscode/mcp.json](.vscode/mcp.json), which
uses `docker compose run --rm -T mcp`.

How it works:
- **Database:** the `postgres` service auto-creates the schema from
  `database/migrations/` on first boot. Data lives in the `auto_grocier_pgdata`
  named volume (survives restarts; only `down -v` wipes it). The MCP container
  reaches it over the compose network via a `DATABASE_URL` override (no
  `.env` change needed).
- **In-container login:** when no valid session exists, the container refreshes
  it itself using the async **nodriver** flow (`AUTO_GROCIER_LOGIN_MODE=nodriver`)
  driving Chromium headfully under Xvfb, completing HEB's normal browser-based
  sign-in (including its standard bot-protection challenge) the same way a real
  browser session does. The exported session persists in the
  `auto_grocier_session` volume.
- **Mounts:** `.env` (all credentials — HEB login, Gmail IMAP for email
  verification, Claude key, store) is mounted read-only — never baked into the
  image. The MCP service also loads it via `env_file`.

> The image is ~1 GB because it bundles Chromium. If you'd rather keep the server
> slim and refresh the session on the host instead, set
> `AUTO_GROCIER_LOGIN_MODE=selenium` (or `AUTO_GROCIER_AUTO_LOGIN=0`) and produce
> `auth.json` on the host, then mount the session volume.

### Database tests

```bash
python manual_scripts/test_connection.py
python manual_scripts/test_database.py
```

### Project Structure

```
auto_grocier/
├── docs/                    # All documentation
├── classes/                 # Core ingredient classes
├── database/                # Database models and repositories
├── session_maintenance/     # Async nodriver browser automation (login, reserve, checkout)
├── docker/                  # Dockerized Postgres + MCP server
├── manual_scripts/          # Ad-hoc/manual test scripts (run by hand; not pytest)
├── utility/                 # Utility scripts (GraphQL, recipe parsing, email)
├── word_dictionaries/       # Ingredient classification data
├── mcp_server.py            # MCP server (pure GraphQL)
└── main.py                  # Entrypoint shim -> session_maintenance.run
```

### Important Notes

- **Always activate the virtual environment before running any commands!**
- **Manual/ad-hoc scripts live in `manual_scripts/`; the pytest suite is in `tests/`**
- Database credentials are stored in `.env` (not tracked in git)

## Documentation

All documentation is located in the `docs/` directory:

- **[Browser automation (nodriver)](session_maintenance/README.md)** - The async browser layer and its run modes
- **[Claude Setup Guide](CLAUDE.md)** - API configuration and usage instructions
- **[PostgreSQL Installation](docs/POSTGRES_INSTALL.md)** - Database setup guide
- **[Database Plan](docs/DATABASE_PLAN.md)** - Database architecture and design
- **[Database Implementation](docs/DATABASE_IMPLEMENTATION.md)** - Implementation details

## Disclaimer

This project is **not affiliated with or endorsed by H-E-B** (and is not
sponsored by H-E-B). "H-E-B" and all related names, logos, and marks are
trademarks of their respective owners and are used here only for descriptive,
identifying purposes.

auto_grocier is provided for **personal and educational use only**. You are
responsible for using it in accordance with H-E-B's terms of service and all
applicable laws. It automates actions against your own account with your own
credentials and does not attempt to gain unauthorized access to anything.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED. See [LICENSE](LICENSE) for the full terms.

## Credits

auto_grocier vendors and builds on **texas-grocery-mcp** by Michael Walker,
used under the MIT License:

- Upstream project: https://github.com/mgwalkerjr95/texas-grocery-mcp

The vendored code lives in `auto_grocier_mcp/` (formerly imported as
`texas_grocery_mcp`) and has been modified from the original — see
[NOTICE](NOTICE) and `auto_grocier_mcp/LICENSE` for the
attribution and a summary of the changes. Thanks to Michael Walker for the
original work.

