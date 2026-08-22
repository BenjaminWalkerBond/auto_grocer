---
name: seed-recipe-from-url
description: 'Add one or more recipes to the auto_grocer recipe database from a URL. Use whenever the user asks to "add this recipe", "add these recipes", "seed a recipe", "save this recipe to the database", or pastes a recipe link (a recipe web page OR a YouTube video/Short). ALWAYS fetch the real page and extract EVERY ingredient from it — never invent, guess, or recall ingredients from memory. Persists via the seed_recipes MCP tool.'
argument-hint: 'Paste a recipe URL to add it to the database'
---

# Seed a Recipe From a URL

Add a recipe to the auto_grocer database from its URL by reading the **actual
page** and persisting its real ingredients with the `seed_recipes` MCP tool.

## THE IRON RULE — never invent ingredients

> When adding a recipe from a URL, you MUST fetch the page and read its real
> ingredient list. NEVER author the ingredient list from memory, training
> knowledge, or what a dish "usually" contains. Hand-authoring silently drops
> and mangles ingredients (e.g. missing fried onions / birista in a korma).

If you cannot fetch the page, STOP and tell the user — do not guess.

## When to Use
- "Add this recipe to my database: <url>"
- "Add these recipes: <url1> <url2> ..."
- "Seed / save this recipe" with a link
- Any recipe web page or YouTube video/Short URL.

## Procedure

### 1. Fetch the real page (mandatory)
- **Recipe web page (non-YouTube):** fetch the page content with your web-fetch
  capability and locate the recipe's ingredients section. Extract EVERY
  ingredient exactly as listed — including easy-to-miss ones (fried onions,
  garnishes, chilies, water/stock, "for the sauce/marinade" sub-sections).
- **YouTube video/Short:** do NOT hand-author. Call `seed_recipes` with the
  YouTube URL and an EMPTY `ingredients` list — the tool fetches the video
  description and parses ingredients with Claude automatically, and derives the
  title/description when blank.

### 2. Parse each ingredient into structured fields
For every ingredient capture:
- `name` (required) — e.g. "fried onions", "lamb", "green cardamom"
- `amount` (number, default 1) — e.g. 2, 0.5
- `unit` (string, default "none") — e.g. "cup", "tablespoon", "lb", "cloves"

### 3. Show the FULL list and confirm before persisting
Print the complete extracted ingredient list (with amounts/units) in chat and
state the count. This lets the user catch omissions before it is saved. Apply
any user modifications they request (e.g. "remove the almonds", "no cilantro")
to the list AFTER extracting the full set — never as a reason to skip fetching.

### 4. Persist with the MCP tool (once per recipe)
Call `mcp_auto-grocer_seed_recipes` ONCE per recipe:
- `title` — the recipe name from the page
- `url` — the source URL (unique key; re-seeding the same URL UPDATES it and
  replaces its ingredients, so it is safe to correct/re-run)
- `ingredients` — the full list of dicts (`name`, `amount`, `unit`)
- `description` — a short description for natural-language matching (optional)
- `cook_time` — minutes, if the page lists it (optional)

For multiple recipes, repeat steps 1–4 for each URL — one `seed_recipes` call each.

### 5. Verify
Report the saved recipe's `ingredient_count` from the tool result and confirm it
matches the number of ingredients you extracted. If they differ, investigate
before telling the user it is done.

## Failure Handling
- Page fetch fails / is paywalled / blocked → tell the user; ask them to paste
  the ingredient list or a different URL. Do NOT fabricate ingredients.
- `seed_recipes` returns `YOUTUBE_FETCH_FAILED` → the video description had no
  parseable ingredients; ask the user to paste them.
- `seed_recipes` returns `DATABASE_UNAVAILABLE` → the recipe DB/Postgres isn't
  up; surface the error rather than retrying blindly.

## Anti-patterns (do NOT do these)
- ❌ Building the ingredient list from what you know about the dish.
- ❌ Passing a partial list "to save time".
- ❌ Skipping the fetch for a page you think you recognize.
- ❌ Silently applying dietary substitutions without first extracting the real list.
