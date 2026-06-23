# Auto Grocier

An automated grocery shopping assistant that parses recipes and manages ingredients.

## 🔒 Security Notice

**NEVER commit `config.txt` to version control!** It contains sensitive credentials.

1. Copy `config.txt.example` to `config.txt`
2. Fill in your actual credentials in `config.txt`
3. The `.gitignore` file ensures `config.txt` stays local only

## Quick Start

1. **Activate virtual environment** (ALWAYS do this first!)
   ```bash
   source venv/bin/activate
   ```

2. **Configure your credentials** - Copy and edit the config file:
   ```bash
   cp config.txt.example config.txt
   # Then edit config.txt with your actual credentials
   ```
   
   Example `config.txt`:
   ```
   EMAIL=your-heb-email@example.com
   PASSWORD=your-heb-password
   CLAUDE_API_KEY=your-claude-api-key
   DATABASE_PASSWORD=your_secure_password
   ```

3. **Choose a mode and ingredient source** (edit `main.py`):
   
   **Mode:**
   - `MODE = 'test'` - Testing (safest, no checkout)
   - `MODE = 'checkout_with_prompt'` - Prompts before checkout
   - `MODE = 'auto_checkout'` - Fully automated (⚠️ careful!)
   
   **Ingredient Source:**
   - `USE_URLS = True` - Parse ingredients from recipe URLs
   - `USE_URLS = False` - Use hardcoded ingredient list

4. **Run the automation**
   ```bash
   python main.py
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
(`MODE=update_graphql_hashes python main.py`) to log in and capture the GraphQL
hashes, then call `refresh_session`.

**Automatic login:** if no valid session is available when an authenticated tool
is called, the server automatically runs a one-off browser login
(`scripts/refresh_authjson.py`) to refresh the session, then continues. This can
take up to a minute on the first call. Disable it with
`AUTO_GROCIER_AUTO_LOGIN=0` (tune the cap with `AUTO_GROCIER_AUTO_LOGIN_TIMEOUT`),
in which case tools return `NOT_AUTHENTICATED` and you refresh the session
manually.

Start the server:
```bash
source venv/bin/activate
python mcp_server.py
```

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
| `seed_recipes(title, url, ingredients, description="")` | No | Insert one recipe (with auto-tagged ingredients) into the recipe database. Re-seeding the same URL updates it instead of duplicating. |
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

- **[Modes Guide](docs/MODES_GUIDE.md)** - Three operating modes: test, checkout_with_prompt, auto_checkout
- **[Ingredient Source Guide](docs/INGREDIENT_SOURCE_GUIDE.md)** - Recipe URLs vs. hardcoded ingredients
- **[Driver Logger Guide](docs/DRIVER_LOGGER_GUIDE.md)** - Debugging HEB website changes with HTML snapshots
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
├── testing/                 # All test scripts
├── utility/                 # Utility scripts
├── word_dictionaries/       # Ingredient classification data
└── main.py                  # Main application entry point
```

## Important Notes

- **Always activate the virtual environment before running any commands!**
- **All test scripts are located in the `testing/` directory**
- Database credentials are stored in `config.txt` (not tracked in git)

## Configuration

Create a `config.txt` file in the root directory with:
```
DATABASE_HOST=localhost
DATABASE_PORT=5432
DATABASE_NAME=auto_grocier
DATABASE_USER=grocier_user
DATABASE_PASSWORD=your_password
CLAUDE_API_KEY=your_api_key
```

See `docs/CLAUDE_SETUP.md` and `docs/POSTGRES_INSTALL.md` for detailed setup instructions.
