# Status: Intelligent Out-of-Stock Substitution

<!--
Shared status file for the auto_grocer multi-agent workflow. This is the single
source of truth passed between the Orchestrator and the Product Designer /
Developer / Tester subagents. Subagents run in isolated contexts and cannot see
each other, so ALL shared state lives here.

Rules:
- Every agent MUST read this file at the start of its turn.
- Every agent MUST update this file (including on failure) BEFORE returning.
- The Orchestrator owns creating this file (copy of this template) and updating
  routing fields (status, next_agent, attempt counters) between subagent calls.
-->

topic: oos-substitution
chosen_idea: When a requested product is unavailable, use Claude to find and suggest a sensible substitute based on the ingredient's role in the recipe, ensuring the replacement is actually similar (not just category-matched).
status: PASSED
next_agent: orchestrator

## Attempt counters
design_attempts: 1
dev_attempts: 1
test_attempts: 1

## User constraints
- Substitution logic MUST use Claude (chat agent) to evaluate whether a substitute is truly appropriate
- Rule-based category matching alone is NOT sufficient
- The substitute should make sense in context (e.g., don't substitute butter with margarine if the recipe is for croissants)

## Design (Product Designer, Mode C)

### goal
Build an intelligent substitution system that, when a requested product is unavailable at the user's HEB store, uses Claude to evaluate alternative products and suggest contextually-appropriate substitutes. The substitute must make sense for the ingredient's role in the recipe (e.g., for laminated dough, suggest another butter brand rather than margarine; for a salad, kale could substitute for spinach).

### non_goals
- **Auto-add substitutes without user confirmation** — substitutes are suggestions; user approves before cart_add
- **Multi-store fallback** — we don't search other HEB locations for the original product
- **Price-based optimization** — we don't guarantee cheaper or comparable pricing
- **Brand loyalty/preferences** — no user preference storage in this iteration
- **Partial quantity matching** — if the substitute has a different size, we don't auto-adjust quantity

### scope_and_approach

#### Overview
Add a new `find_substitute` tool to the MCP server that:
1. Detects when a requested product is unavailable (`available: false`)
2. Searches for alternative products in the same category/type
3. Sends the original request, recipe context, and candidate substitutes to Claude
4. Returns Claude's recommendation with a justification

#### Technical flow

1. **Detection trigger**: When `product_search` returns products where the best match has `available: false`, or when `cart_add` fails with an out-of-stock indication.

2. **Context gathering**:
   - Original ingredient name, amount, unit, and tags (from `Ingredient` class)
   - Recipe context (title, description, cook_time from `Recipe` model if available)
   - The unavailable product's details (name, brand, category_path, size)

3. **Candidate search**: Query HEB for related products:
   - Search by ingredient category (e.g., "butter" if tag is "none" but name contains butter)
   - Search by broader category (e.g., "cooking fat" for butter)
   - Filter to `available: true` products only
   - Limit to 5-10 candidates to keep prompt size reasonable

4. **Claude evaluation**: New function in `claude.py`:
   ```python
   def evaluate_substitutes(
       original_ingredient: dict,      # name, amount, unit, tags
       recipe_context: dict | None,    # title, description, cook_time
       unavailable_product: dict,      # name, brand, category_path, size
       candidates: list[dict],         # list of available products with details
   ) -> dict:
       """
       Returns {
           "recommended": {product_id, sku, name, reason},
           "alternatives": [{product_id, sku, name, reason}, ...],
           "no_good_substitute": bool,
           "warning": str | None  # e.g., "This may affect texture"
       }
       """
   ```

5. **Tool response**: The `find_substitute` tool returns Claude's recommendation with enough detail for the user (or calling agent) to decide whether to accept.

#### Files to add/modify

| File | Change |
|------|--------|
| `claude.py` | Add `evaluate_substitutes()` function |
| `auto_grocer_mcp/tools/substitution.py` | New file with `find_substitute` tool |
| `auto_grocer_mcp/server.py` | Register the new tool |
| `tests/unit/test_substitution.py` | Unit tests for Claude prompt and parsing |
| `tests/integration/test_substitution_live.py` | Integration test with real HEB search |

#### Claude prompt strategy

The prompt must:
- Explain the ingredient's culinary role (based on tags and recipe context)
- List candidate products with their attributes
- Ask Claude to pick the BEST substitute OR declare no good substitute exists
- Require a `reason` explaining why the substitute works (or doesn't)
- Handle edge cases: organic preference if original was organic, dietary restrictions from recipe context

### acceptance_criteria

1. **AC1 — Substitution tool exists**: A new `find_substitute` MCP tool is registered and callable, accepting `ingredient_name`, `store_id`, and optional `recipe_context` parameters.

2. **AC2 — Claude evaluates candidates**: The tool calls `claude.evaluate_substitutes()` with the unavailable product, recipe context, and at least 3 candidate products; the response includes a `reason` field explaining the recommendation.

3. **AC3 — Only available products suggested**: All products in `recommended` and `alternatives` fields have `available: true` at the specified store.

4. **AC4 — Context-aware rejection**: Given a croissant recipe requiring butter, if only margarine is available, Claude returns `no_good_substitute: true` with a warning about lamination requirements.

5. **AC5 — Graceful fallback**: If Claude API is unavailable, the tool returns the top available category match with `"reason": "Claude unavailable — category match only"` and `"warning": "Review suggested substitute"`.

6. **AC6 — Unit tests pass**: `tests/unit/test_substitution.py` covers prompt construction, response parsing, and fallback behavior with mocked Claude responses.

7. **AC7 — MODE=test verification**: Running `python main.py` with a recipe containing an out-of-stock ingredient triggers the substitution flow and prints Claude's recommendation (no cart modification unless user confirms).

### risks_and_dependencies

| Risk | Mitigation |
|------|------------|
| **HEB WAF/auth constraints** | Batch searches, reuse existing `product_search_batch`, respect session limits |
| **Claude API cost** | Cache substitution results by (ingredient, store_id) for the session; limit candidates to 10 |
| **Claude latency** | Acceptable for user-facing flow (1-3s); consider parallel calls for batch ingredients |
| **Prompt injection via product names** | Sanitize product data before prompt construction |
| **No good substitute exists** | Design explicitly handles this case with `no_good_substitute: true` |
| **Recipe context unavailable** | Tool works without context but warns that substitution quality may be lower |

**External dependencies**:
- Claude API (anthropic SDK, already in requirements.txt)
- HEB GraphQL API via existing `HEBGraphQLClient`
- Valid HEB session (auth.json) for product availability data

## dev_plan (Developer — write BEFORE any code)
files_to_change:
  - claude.py                               # Add evaluate_substitutes() function
  - auto_grocer_mcp/tools/substitution.py # New file - find_substitute tool
  - auto_grocer_mcp/server.py             # Register find_substitute tool
  - tests/unit/test_substitution.py         # Unit tests with mocked Claude
  - tests/integration/test_substitution_live.py # Live integration tests

approach:
  1. **claude.py - evaluate_substitutes()**: Create a new function that takes original
     ingredient, recipe context, unavailable product info, and candidate products. Build
     a structured prompt asking Claude to pick the best substitute or declare none suitable.
     Parse JSON response with recommended/alternatives/no_good_substitute/warning fields.
     Handle API errors gracefully by returning a fallback response.

  2. **substitution.py - find_substitute tool**: Create async tool function with parameters
     (ingredient_name, store_id, recipe_context). Flow:
     a) Search for products matching ingredient_name via product_search
     b) If best match is unavailable, search for broader category terms
     c) Filter candidates to available=true only
     d) Call evaluate_substitutes() with context
     e) Return Claude's recommendation with reason
     f) On Claude failure, return top category match with warning

  3. **server.py**: Import find_substitute and register with mcp.tool() alongside
     existing product tools (readOnlyHint annotation).

  4. **Unit tests**: Test prompt construction, response parsing, JSON edge cases,
     fallback behavior when Claude unavailable, filtering of unavailable products.
     Use unittest.mock to patch Claude client.

  5. **Integration tests**: Test with real HEB API (requires authenticated session).
     Use known products that may be OOS. Mark with @pytest.mark.integration.

feasibility: feasible
  - anthropic SDK already in requirements.txt and working in claude.py
  - product_search API available and returns availability info
  - StateManager pattern provides store_id access
  - Test patterns established in existing test suite

risks:
  - Claude API rate limits during heavy substitution batches (mitigated: batch search first, single Claude call per substitution)
  - Product search may not return category info for all products (mitigated: fall back to name-based search)
  - HEB session constraints (mitigated: reuse existing ensure_session decorator)

verification:
  - AC1: Unit test verifies find_substitute tool callable with correct signature
  - AC2: Unit test mocks Claude response and verifies evaluate_substitutes() called correctly
  - AC3: Unit test verifies only available=true products passed to Claude
  - AC4: Unit test with mocked croissant/butter scenario returns no_good_substitute
  - AC5: Unit test with mocked Claude exception returns fallback response
  - AC6: pytest tests/unit/test_substitution.py passes
  - AC7: Requires manual test or MODE=test run (Tester's responsibility)

## Implementation notes (Developer)
summary: |
  Implemented intelligent out-of-stock substitution feature with Claude AI evaluation.
  
  Key components:
  1. **claude.py - evaluate_substitutes()**: Added function that builds a culinary-context
     prompt and sends it to Claude for substitution evaluation. Returns structured response
     with recommended substitute, alternatives, no_good_substitute flag, and warnings.
     Includes graceful fallback when Claude API is unavailable.
  
  2. **substitution.py - find_substitute tool**: New MCP tool that:
     - Searches for products matching ingredient_name
     - Detects when best match is unavailable
     - Gathers available candidates via broader category searches
     - Calls evaluate_substitutes() with full context
     - Returns recommendation with cart_usage instructions
  
  3. **server.py**: Registered find_substitute tool with readOnlyHint annotation
  
  4. **Unit tests (18 tests)**: Cover all acceptance criteria including:
     - Store ID validation (AC1)
     - Claude evaluation flow (AC2)
     - Available-only filtering (AC3)
     - Croissant/butter rejection scenario (AC4)
     - Fallback when Claude unavailable (AC5)
     - JSON parsing with code fences
     - Category term extraction
  
  5. **Integration tests (8 tests)**: Ready for live testing with HEB API

changed_files:
  - claude.py (added evaluate_substitutes function ~150 LOC)
  - auto_grocer_mcp/tools/substitution.py (new file ~280 LOC)
  - auto_grocer_mcp/server.py (import + registration)
  - tests/unit/test_substitution.py (new file, 18 tests)
  - tests/integration/test_substitution_live.py (new file, 8 integration tests)
  - auto_grocer_mcp/tools/cart.py (fixed pre-existing leading whitespace)

## Test results
- **ruff check** (new files): All checks passed. Pre-existing W293 whitespace warnings in `claude.py` lines 58/61 — not introduced by this PR.
- **pytest tests/unit/test_substitution.py**: 18/18 passed (5.77s)
  - AC1: `test_requires_store_id` ✓
  - AC2: `test_calls_claude_for_substitution`, `test_includes_recipe_context` ✓
  - AC3: `test_only_passes_available_products_to_claude`, `test_filters_unavailable_from_candidates` ✓
  - AC4: `test_croissant_margarine_rejection` ✓
  - AC5: `test_fallback_when_claude_unavailable`, `test_returns_fallback_when_no_client` ✓
  - AC6: All 18 unit tests pass ✓
- **pytest tests/unit/ (regression)**: 338 passed, 2 skipped (pre-existing redis skips), 0 failures (24.79s)

AC7 (MODE=test manual run) not executed — requires valid HEB session and live browser; deferred to integration testing phase.
commands:
  1. source venv/bin/activate
  2. ruff check claude.py auto_grocer_mcp/tools/substitution.py auto_grocer_mcp/server.py tests/unit/test_substitution.py
  3. pytest tests/unit/test_substitution.py -v
  4. pytest tests/unit/ -v
criteria_mapping:
  - ruff check: code quality for all changed files (prerequisite for all ACs)
  - test_substitution.py: AC1 (tool exists/signature), AC2 (Claude evaluation), AC3 (available-only), AC4 (croissant/butter rejection), AC5 (fallback), AC6 (unit tests pass)
  - pytest tests/unit/ -v: regression check — existing tests must still pass alongside new tests
expected_outcomes:
  - ruff: no errors in changed files
  - test_substitution.py: all 18 tests pass
  - tests/unit/ full suite: no regressions (all previously passing tests continue to pass)
  - find_substitute tool importable and registered in server.py
prerequisites:
  - venv active (source venv/bin/activate)
  - No HEB session needed for unit tests (Claude + HEB calls are mocked)
  - Integration tests (tests/integration/) are NOT run — they require a live HEB session
