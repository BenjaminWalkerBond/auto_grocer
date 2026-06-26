# Auto Grocier

An automated grocery shopping assistant that parses recipes and manages ingredients.

## 🔒 Security Notice

**NEVER commit `.env` to version control!** It contains sensitive credentials.

1. Copy `.env.example` to `.env`
2. Fill in your actual credentials in `.env`
3. The `.gitignore` file ensures `.env` stays local only

## Quick Start

1. **Activate virtual environment** (ALWAYS do this first!)
   ```bash
   source venv/bin/activate
   ```

2. **Configure your credentials** - Copy and edit the env file:
   ```bash
   cp .env.example .env
   # Then edit .env with your actual credentials
   ```
   
   Example `.env`:
   ```
   EMAIL=your-heb-email@example.com
   PASSWORD=your-heb-password
   CLAUDE_API_KEY=your-claude-api-key
   DATABASE_PASSWORD=your_secure_password
   ```

3. **Choose a mode** (set `MODE` in `.env`):
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

4. **Run the automation**
   ```bash
   python main.py
   # or, equivalently:
   python -m grocery_browser.run
   # override the mode without editing .env:
   MODE=test python -m grocery_browser.run
   ```

5. **Run database tests** (optional)
   ```bash
   python testing/test_connection.py
   python testing/test_database.py
   ```

## MCP Server Operations

The project ships an [MCP](https://modelcontextprotocol.io/) server (`mcp_server.py`)
that exposes HEB grocery automation as tools over **pure GraphQL** (no browser at
runtime). It reuses an exported HEB session — run the maintenance workflow
(`MODE=update_graphql_hashes python -m grocery_browser.run`) to log in and capture
the GraphQL hashes, then call `refresh_session`.

**Automatic login:** if no valid session is available when an authenticated tool
is called, the server automatically runs a one-off nodriver browser login
(`MODE=login_export python -m grocery_browser.run`) to refresh the session, then
continues. This can take up to a minute on the first call. Disable it with
`AUTO_GROCIER_AUTO_LOGIN=0` (tune the cap with `AUTO_GROCIER_AUTO_LOGIN_TIMEOUT`),
in which case tools return `NOT_AUTHENTICATED` and you refresh the session
manually.

Start the server:
```bash
source venv/bin/activate
python mcp_server.py
```

### Running it fully in Docker (recommended, portable)

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
  driving Chromium headfully under Xvfb — validated against HEB's Imperva WAF.
  The exported session persists in the `auto_grocier_session` volume.
- **Mounts:** `.env` (all credentials — HEB login, Gmail IMAP for email
  verification, Claude key, store) is mounted read-only — never baked into the
  image. The MCP service also loads it via `env_file`.

> The image is ~1 GB because it bundles Chromium. If you'd rather keep the server
> slim and refresh the session on the host instead, set
> `AUTO_GROCIER_LOGIN_MODE=selenium` (or `AUTO_GROCIER_AUTO_LOGIN=0`) and produce
> `auth.json` on the host, then mount the session volume.

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

## Documentation

All documentation is located in the `docs/` directory:

- **[Browser automation (nodriver)](grocery_browser/README.md)** - The async browser layer and its run modes
- **[Claude Setup Guide](docs/CLAUDE_SETUP.md)** - API configuration and usage instructions
- **[PostgreSQL Installation](docs/POSTGRES_INSTALL.md)** - Database setup guide
- **[Database Plan](docs/DATABASE_PLAN.md)** - Database architecture and design
- **[Database Implementation](docs/DATABASE_IMPLEMENTATION.md)** - Implementation details
- **[Full Documentation](docs/README.md)** - Complete project documentation

## Project Structure

```
auto_grocier/
├── docs/                    # All documentation
├── classes/                 # Core ingredient classes
├── database/                # Database models and repositories
├── grocery_browser/         # Async nodriver browser automation (login, reserve, checkout)
├── docker/                  # Dockerized Postgres + MCP server
├── testing/                 # All test scripts
├── utility/                 # Utility scripts (GraphQL, recipe parsing, email)
├── word_dictionaries/       # Ingredient classification data
├── mcp_server.py            # MCP server (pure GraphQL)
└── main.py                  # Entrypoint shim -> grocery_browser.run
```

## Important Notes

- **Always activate the virtual environment before running any commands!**
- **All test scripts are located in the `testing/` directory**
- Database credentials are stored in `.env` (not tracked in git)

## Configuration

Create a `.env` file in the root directory (copy `.env.example`) with:
```
DATABASE_HOST=localhost
DATABASE_PORT=5432
DATABASE_NAME=auto_grocier
DATABASE_USER=grocier_user
DATABASE_PASSWORD=your_password
CLAUDE_API_KEY=your_api_key
```

See `docs/CLAUDE_SETUP.md` and `docs/POSTGRES_INSTALL.md` for detailed setup instructions.
