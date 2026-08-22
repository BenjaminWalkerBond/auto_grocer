# Auto Grocer

Talk to your **H-E-B** cart from an AI assistant. `auto_grocer` is an
[MCP](https://modelcontextprotocol.io/) server that lets GitHub Copilot or Claude
search products, build a cart from recipes or free-form lists, reserve a curbside
pickup slot, and review checkout — all against **your own** H-E-B account.

Everything runs in Docker: the image bundles PostgreSQL, Chromium, and Xvfb and
refreshes its own H-E-B session, so there is **no host Python, database, or browser
to install**. All you need is Docker Desktop and a filled-in `.env`.

> **Not affiliated with H-E-B.** For personal, educational use with your own
> account only. See [Disclaimer](#disclaimer).

---

## Table of contents

- [What you can do](#what-you-can-do)
- [Prerequisites](#prerequisites)
- [Quick start](#quick-start)
- [Add the server to your AI client](#add-the-server-to-your-ai-client)
- [Verify it works](#verify-it-works)
- [MCP tools reference](#mcp-tools-reference)
- [Typical workflow](#typical-workflow)
- [Troubleshooting](#troubleshooting)
- [Development](#development)
- [Documentation](#documentation)
- [Disclaimer](#disclaimer)
- [Credits](#credits)

---

## What you can do

Once connected, ask your assistant to:

- **Search products** — "find organic chicken breast at my store"
- **Build a cart** — "add 2 lb ground beef, a dozen eggs, and tortillas"
- **Cook from recipes** — "add everything for taco night" (matches your recipe DB)
- **Add a recipe from a URL** — including YouTube videos/Shorts
- **Reserve pickup** — list and lock a curbside timeslot
- **Review checkout** — advance to order review **without charging your card**

Placing a **paid** order is possible but **disabled by default** and must be
explicitly enabled (see [`place_order`](#mcp-tools-reference)).

---

## Prerequisites

| Requirement | Why |
|-------------|-----|
| **[Docker Desktop](https://www.docker.com/products/docker-desktop/)** | Runs the entire stack (Postgres + MCP server + Chromium). |
| **An active H-E-B account** | The automation shops with *your* credentials. |
| **A Gmail account + [app password](https://myaccount.google.com/apppasswords)** | H-E-B emails verification codes; the app reads them over IMAP. |
| **An [Anthropic / Claude API key](https://console.anthropic.com/)** (`sk-ant-…`) | Parses recipes and ingredient lists. |

That's it. No host Python, PostgreSQL, or Chrome install is required for normal use.

---

## Quick start

Four steps: clone → configure → build → connect.

### 1. Clone the repo

```bash
git clone https://github.com/BenjaminWalkerBond/auto_grocer.git
cd auto_grocer
```

### 2. Configure your credentials

Copy the template and fill in your values:

```bash
cp .env.example .env
```

Open `.env` and set at least these keys:

```dotenv
# H-E-B account
EMAIL=your-heb-email@example.com
PASSWORD=your-heb-password

# Gmail IMAP (for H-E-B verification codes) — must be a Gmail APP PASSWORD
EMAIL_USER=your-gmail@gmail.com
EMAIL_PASS=your-gmail-app-password

# Claude / Anthropic
CLAUDE_API_KEY=sk-ant-your-key-here

# Database (any value is fine — it is only used inside Docker)
DATABASE_PASSWORD=pick-a-strong-password

# Your H-E-B store id (find it on heb.com; 737 = The Heights, Houston)
STORE_ID=737
```

> 🔒 **`.env` holds secrets and is gitignored — never commit it.**

### 3. Build the Docker image

Build the MCP image once before connecting a client (Python 3.12 + Chromium + Xvfb,
~1 GB). This also makes the first client launch fast:

```bash
docker compose -f docker/docker-compose.yml build mcp
```

The database image is pulled automatically the first time the server starts.

### 4. Connect your AI client

Use a helper script (recommended) or configure manually — see the next section.

---

## Add the server to your AI client

The server id is **`auto-grocer`** and it runs over **stdio** — your client launches
it on demand with:

```
docker compose -f docker/docker-compose.yml run --rm -T mcp
```

### Claude Desktop — one-command setup (recommended)

The helper scripts compute the absolute path to `docker/docker-compose.yml`, back up
your existing config, and merge in the `auto-grocer` entry **without touching your
other MCP servers**. Run the one for your shell **from the repo root**:

**Windows (PowerShell):**

```powershell
./scripts/add-to-claude.ps1
```

**macOS / Linux (bash, requires [`jq`](https://jqlang.github.io/jq/)):**

```bash
./scripts/add-to-claude.sh
```

Then **restart Claude Desktop**. Done.

<details>
<summary><strong>Claude Desktop — manual setup</strong></summary>

Open **Settings → Developer → Edit Config** and add the block below. The key is
**`mcpServers`**, and because Claude Desktop runs from its own working directory the
compose `-f` path **must be absolute** (use forward slashes on Windows):

```json
{
  "mcpServers": {
    "auto-grocer": {
      "command": "docker",
      "args": [
        "compose",
        "-f", "C:/Users/you/auto_grocer/docker/docker-compose.yml",
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
| Linux | `~/.config/Claude/claude_desktop_config.json` |

Replace the path with your real clone location, then restart Claude Desktop.

</details>

<details>
<summary><strong>GitHub Copilot (VS Code)</strong></summary>

**Workspace (easiest).** The repo ships [.vscode/mcp.json](.vscode/mcp.json). Open the
`auto_grocer` folder in VS Code and Copilot auto-detects the server — no config to
write:

```json
{
  "servers": {
    "auto-grocer": {
      "type": "stdio",
      "command": "docker",
      "args": ["compose", "-f", "docker/docker-compose.yml", "run", "--rm", "-T", "mcp"]
    }
  }
}
```

The compose `-f` path here is **relative to the repo root**, so the workspace must be
the `auto_grocer` folder for it to resolve.

**User-level (every workspace).** Add the same `auto-grocer` block to your user
`mcp.json` (Command Palette → **MCP: Open User Configuration**), but change
`-f docker/docker-compose.yml` to an **absolute** path, e.g.
`-f /absolute/path/to/auto_grocer/docker/docker-compose.yml`.

</details>

---

## Verify it works

Open your assistant (Copilot **Agent mode**, or Claude Desktop after restarting) and
ask it to call **`auth_status`**. It should report whether a valid H-E-B session is
available.

**First authenticated call takes up to a minute.** When no session exists yet, the
container logs itself into H-E-B by driving Chromium under Xvfb (completing H-E-B's
normal sign-in, including its verification-code step via your Gmail app password).
After that the session is cached in a Docker volume and subsequent calls are fast.

---

## MCP tools reference

| Tool | Auth | Description |
|------|:---:|-------------|
| `auth_status()` | No | Report whether a valid H-E-B session exists, the active store, and whether `place_order` is enabled. Does not open a browser. |
| `refresh_session()` | No | Reload the exported session and latest GraphQL hashes. Call this if tools start reporting `NOT_AUTHENTICATED` or `OPERATION_NOT_CAPTURED`. |
| `search_products(query, limit=10, store_id="")` | Yes | Search H-E-B products via GraphQL without adding anything. |
| `add_groceries(items, clear_first=False)` | Yes | Add free-form items (e.g. `"2 lb chicken breast"`) to the cart. Produce is searched as organic automatically. |
| `add_recipe_ingredients(request, clear_first=False)` | Yes | Match a natural-language meal request against your recipe DB and add all matched ingredients. |
| `find_recipes(request)` | No | Preview which recipes match a request **without** adding to the cart. |
| `query_recipes(search="", recipe_id=0, domain="", include_ingredients=False, limit=50)` | No | Browse/search/inspect the recipe DB directly. |
| `list_all_recipes(page=1)` | No | List every recipe, paginated 10 per page. |
| `seed_recipes(title, url, ingredients, description="")` | No | Insert a recipe (auto-tagged). Re-seeding the same URL updates it. **YouTube URLs** auto-parse ingredients from the video description. |
| `get_cart()` | Yes | Return current cart contents. |
| `clear_cart()` | Yes | Empty the cart. |
| `remove_from_cart(items)` | Yes | Remove specific items by id, sku, or name fragment. |
| `set_store(store_id)` | Yes | Set the active pickup store. |
| `list_timeslots(store_id="")` | Yes | List available curbside pickup slots. |
| `reserve_timeslot(slot_id, store_id="")` | Yes | Reserve a pickup slot (use `list_timeslots` first). |
| `checkout()` | Yes | Advance to order review. **Never charges.** Reserve a timeslot first. |
| `place_order()` | Yes | Submit the final **paid** order. ⚠️ **Charges your card.** Disabled unless `AUTO_GROCER_ALLOW_PLACE_ORDER=1`. |

> **Safety:** `place_order` is the only tool that spends money and is disabled by
> default. `checkout` only advances to order review and never charges.

---

## Typical workflow

```
auth_status                             # confirm you're logged in
add_groceries / add_recipe_ingredients  # build the cart
get_cart                                # review what was added
list_timeslots
reserve_timeslot
checkout                                # review only — no charge
place_order                             # optional, guarded — CHARGES your card
```

---

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| Client shows **0 tools** / server won't start | Make sure Docker Desktop is running and you built the image: `docker compose -f docker/docker-compose.yml build mcp`. |
| **Claude Desktop can't find the server** | The compose `-f` path must be **absolute** with forward slashes. Re-run `scripts/add-to-claude.ps1` / `.sh`, then restart Claude. |
| `NOT_AUTHENTICATED` | Session expired. Call `refresh_session`, or let auto-login run on the next authenticated call. |
| `OPERATION_NOT_CAPTURED` / hash errors | H-E-B changed its API. Refresh the GraphQL hashes (see [Development](#development)), then call `refresh_session`. |
| First call **hangs ~1 min** | Expected — the container is logging into H-E-B under Xvfb. Subsequent calls are fast. |
| **WAF 401 / email-verification loop** | You've hit H-E-B's bot protection. Wait a few minutes and retry; avoid rapid repeated logins. |
| `DATABASE_PASSWORD must be set` | `DATABASE_PASSWORD` is missing from `.env`, or you ran compose without the repo-root `.env` as the interpolation source. Pass `--env-file .env`. |

---

## Development

This section covers running the automation and MCP server from a **host checkout**
(outside Docker), plus tests and project layout. For normal use, the Docker
[Quick start](#quick-start) is all you need.

### Host prerequisites

- **Python 3.12** — for the host `main.py` / MCP server path.
- **PostgreSQL** — only if running against a host DB instead of the compose one.
- **Chromium / Chrome** — only for the host login path (Docker bundles it).

### Local setup (uv)

[uv](https://docs.astral.sh/uv/) manages the virtualenv and dependencies:

```bash
uv python install 3.12   # if the interpreter is missing
uv sync                  # create .venv and install all deps (incl. dev tools)
```

Prefix commands with `uv run` to run inside the environment.

### Run the automation on the host

```bash
uv run python main.py
# or run the package directly:
uv run python -m auto_grocer.session_maintenance.run
# override the mode without editing .env:
MODE=nodriver OPERATION=shop uv run python -m auto_grocer.session_maintenance.run
```

**Modes** (set `MODE` in `.env`):

- `graphql` (default) — shop via the H-E-B GraphQL API. `CHECKOUT=none|prompt|auto`.
- `nodriver` — drive the browser, selected by `OPERATION`:
  - `shop` (default) — login, reserve a slot, add ingredients.
  - `login_export` — log in and export the session (refresh MCP auth).
  - `capture_hashes` — refresh H-E-B's GraphQL persisted-query hashes.

`CHECKOUT` never places a paid order; it only advances to H-E-B's checkout page.

### Run the MCP server on the host

```bash
uv run python -m auto_grocer.mcp_server
```

### Run everything in Docker

```bash
# Build the MCP image (Python 3.12 + Chromium + Xvfb)
docker compose -f docker/docker-compose.yml build mcp

# Start just the database (optional; the MCP server starts it automatically)
docker compose --env-file .env -f docker/docker-compose.yml up -d postgres

# Run the MCP server over stdio (Postgres comes up first)
docker compose --env-file .env -f docker/docker-compose.yml run --rm -T mcp

# Stop (keeps data) / stop + wipe the DB volume
docker compose -f docker/docker-compose.yml down
docker compose -f docker/docker-compose.yml down -v
```

**How it works:**

- **Database** — the `postgres` service auto-creates the schema from
  `src/auto_grocer/database/migrations/` on first boot. Data lives in the
  `auto_grocer_pgdata` volume (only `down -v` wipes it). The MCP container reaches
  it over the compose network via a `DATABASE_URL` override.
- **In-container login** — when no valid session exists, the container refreshes it
  itself using the async nodriver flow, driving Chromium under Xvfb to complete
  H-E-B's normal sign-in. The session persists in the `auto_grocer_session` volume.
- **Mounts** — `.env` is mounted read-only (never baked into the image); debug
  snapshots and self-healing rewrites are bind-mounted back to the working tree.

### Refresh the H-E-B session / GraphQL hashes

Run inside the container so results land in the session volume (do **not** truncate
the output):

```bash
docker compose --env-file .env -f docker/docker-compose.yml run --rm -T \
  -e MODE=nodriver -e OPERATION=capture_hashes mcp \
  python -m auto_grocer.session_maintenance.run
```

Then call `refresh_session` from your client.

### Tests

```bash
uv run pytest tests/unit            # fast, offline
uv run pytest --run-integration     # live H-E-B API / Postgres
```

### Project structure

```
auto_grocer/
├── docker/                          # Dockerized Postgres + MCP server
├── docs/                            # Architecture, database, ADRs
├── scripts/                         # Setup helpers (add-to-claude.{ps1,sh}, seeding)
├── tests/                           # unit/ (offline) + integration/ (live)
└── src/
    ├── auto_grocer/
    │   ├── classes/                 # Ingredient / IngredientList
    │   ├── database/                # Models, repositories, migrations
    │   ├── session_maintenance/     # Async nodriver automation (login, capture)
    │   ├── utility/                 # GraphQL, recipe parsing, email helpers
    │   ├── mcp_server.py            # MCP server entrypoint (pure GraphQL)
    │   └── recipe_grabber.py
    └── auto_grocer_mcp/            # Vendored texas-grocery-mcp (modified)
```

---

## Documentation

- **[Architecture](docs/ARCHITECTURE.md)** — system overview
- **[Browser automation (nodriver)](src/auto_grocer/session_maintenance/README.md)** — the async browser layer
- **[Claude setup guide](CLAUDE.md)** — API configuration and MCP usage
- **[PostgreSQL install](docs/POSTGRES_INSTALL.md)** — host database setup
- **[Database plan](docs/DATABASE_PLAN.md)** / **[implementation](docs/DATABASE_IMPLEMENTATION.md)**

---

## Disclaimer

This project is **not affiliated with or endorsed by H-E-B** (and is not sponsored by
H-E-B). "H-E-B" and all related names, logos, and marks are trademarks of their
respective owners and are used here only for descriptive, identifying purposes.

`auto_grocer` is provided for **personal and educational use only**. You are
responsible for using it in accordance with H-E-B's terms of service and all
applicable laws. It automates actions against your own account with your own
credentials and does not attempt to gain unauthorized access to anything.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED.
See [LICENSE](LICENSE) for the full terms.

---

## Credits

`auto_grocer` vendors and builds on **texas-grocery-mcp** by Michael Walker, used
under the MIT License:

- Upstream project: https://github.com/mgwalkerjr95/texas-grocery-mcp

The vendored code lives in `src/auto_grocer_mcp/` (formerly imported as
`texas_grocery_mcp`) and has been modified from the original — see [NOTICE](NOTICE)
and `src/auto_grocer_mcp/LICENSE` for attribution and a summary of the changes.
Thanks to Michael Walker for the original work.
