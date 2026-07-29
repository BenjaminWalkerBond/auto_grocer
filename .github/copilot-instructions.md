# auto_grocier — Agent Instructions

This repo automates HEB grocery ordering through the `auto-grocier` MCP server,
which reuses an exported HEB session and persisted GraphQL hashes.

## Custom Agent

For **grocery ordering tasks** (adding items, managing cart, checking out), use the
**Grocery Ordering** agent (`.github/agents/grocery-ordering.agent.md`). It has:
- Full access to all `auto-grocier` MCP tools
- Session validation via a `SessionStart` hook
- Detailed knowledge of the ordering workflow
- Safety constraints around payment

## Startup Check (ALWAYS DO THIS FIRST — ALL AGENTS)

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

## MCP Tool Quick Reference

### Session
- `auth_status` — Check session validity
- `refresh_session` — Reload session after refresh skills

### Products & Cart
- `search_products(query)` — Search HEB products
- `add_groceries(items)` — Add items to cart
- `get_cart` / `clear_cart` / `remove_from_cart(items)`

### Recipes
- `add_recipe_ingredients(request)` — Add recipe ingredients
- `find_recipes(request)` — Preview recipe matches
- `query_recipes(...)` / `list_all_recipes(page)` / `seed_recipes(...)`

> **Adding a recipe from a URL:** ALWAYS use the **seed-recipe-from-url** skill.
> Fetch the actual page and extract EVERY ingredient — never author the list from
> memory. For YouTube URLs, pass the URL with empty `ingredients` (auto-parsed).

### Checkout
- `list_timeslots` / `reserve_timeslot(slot_id)`
- `checkout` — Review only (NO CHARGE)
- `place_order` — **⚠️ CHARGES CARD** (disabled by default)

### Store & Coupons
- `search_stores(query)` / `set_store(store_id)`
- `list_coupons` / `clip_coupon(coupon_id)`

## Error Recovery

| Error | Skill to Run |
|-------|--------------|
| `NOT_AUTHENTICATED` | **refresh-heb-login** |
| `OPERATION_NOT_CAPTURED` | **refresh-graphql-hashes** |
| WAF 401 / Email verification | Wait, retry manually |

## Development Reference

- **README.md** — Quick start, Docker setup, tool reference
- **CLAUDE.md** — MCP usage guide + browser automation (maintenance)
- **docs/** — Architecture, database, debugging guides
