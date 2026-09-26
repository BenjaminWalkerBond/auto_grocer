import io
import json
import os
import sys
from typing import cast

import anthropic
from anthropic.types import TextBlock
from dotenv import load_dotenv

# Ensure stdout/stderr use UTF-8 so the project's Unicode status symbols (✓, 🥗,
# emoji) don't crash on Windows, whose console defaults to a legacy code page
# (cp1252). claude.py is imported first by every entry point, so reconfiguring
# here covers the whole app. No-op on Linux/macOS (already UTF-8).
for _stream in (sys.stdout, sys.stderr):
    try:
        if isinstance(_stream, io.TextIOWrapper):
            _stream.reconfigure(encoding="utf-8")
    except Exception:
        pass

# Load configuration from the .env file (the single source of config for this
# Docker-first project). Pointing at an explicit path makes it work regardless
# of the current working directory. Real environment variables take precedence
# over .env values (load_dotenv does not override), so Docker Compose / the
# shell can override individual settings.
_ENV_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
load_dotenv(_ENV_PATH)

# Claude model used across the project. Update here if the model is retired.
MODEL = "claude-sonnet-5"


def get_setting(key, default=""):
    """Return a configuration value from the environment (.env or real env).

    This is the project's single config accessor now that config.txt has been
    retired in favor of .env. Returns ``default`` only when the key is absent.
    """
    return os.environ.get(key, default)


# Get Claude API key from the environment (.env CLAUDE_API_KEY, or the standard
# ANTHROPIC_API_KEY).
claude_api_key = get_setting("CLAUDE_API_KEY") or get_setting("ANTHROPIC_API_KEY")

if not claude_api_key:
    print("ERROR: No Claude API key found.", file=sys.stderr)
    print("Add CLAUDE_API_KEY=your-key-here to your .env file", file=sys.stderr)
    print("or set the ANTHROPIC_API_KEY environment variable.", file=sys.stderr)
    print("See docs/CLAUDE_SETUP.md for instructions.", file=sys.stderr)
else:
    # Never print the key itself — just confirm it loaded. Route to stderr so it
    # doesn't corrupt the MCP JSON-RPC stream on stdout.
    print("✓ Claude API key loaded", file=sys.stderr)

# Initialize the Anthropic client
client = anthropic.Anthropic(api_key=claude_api_key) if claude_api_key else None


def extract_ingredients(txt):
    """
    Extract ingredients from text using Claude Sonnet.

    Args:
        txt: The text content from a recipe webpage

    Returns:
        A list containing comma-separated ingredients with their measurements
    """
    if client is None:
        raise Exception("Claude API client not initialized. Add CLAUDE_API_KEY to your .env file or set the ANTHROPIC_API_KEY environment variable. See docs/CLAUDE_SETUP.md for instructions.")

    ingredient_list = []

    # get the amount of characters in the text
    char_count = len(txt)

    # Truncate text if too long (Claude has context limits)
    # Claude Sonnet supports up to 200k tokens, but we'll be conservative
    max_chars = 100000
    if char_count > max_chars:
        txt = txt[:max_chars]
        print(f"Warning: Text truncated from {char_count} to {max_chars} characters", file=sys.stderr)

    message = client.messages.create(
        model=MODEL,
        max_tokens=2048,
        messages=[
            {
                "role": "user",
                "content": f"Please grab the ingredients and their measurements from the following text and return them in a comma seperated list in this format: AMOUNT UNIT: INGREDIENT. Make sure to only grab the ingredients from the ingredient section, and do not count ingredients twice. {txt}\n"
            }
        ]
    )

    verified = client.messages.create(
        model=MODEL,
        max_tokens=2048,
        messages=[
            {
                "role": "user",
                "content": f"Please verify that the following text separates each distinct ingredient by a comma, and that the format of AMOUNT UNIT: INGREDIENT, AMOUNT UNIT: INGREDIENT , etc. was followed: {message.content[0].text}\n. If it does not, please insert commas where appropriate and return ONLY the list of comma separated ingredients. DO NOT include any other text."
            }
        ]
    )

    ingredient_list.append(verified.content[0].text)
    return ingredient_list


def get_recipe_metadata_txt(txt):
    """
    Extract a recipe's canonical dish name and a short description from page text
    using Claude Sonnet.

    Args:
        txt: The text content from a recipe webpage

    Returns:
        dict with keys 'title' (str) and 'description' (str). On any failure,
        returns {'title': '', 'description': ''} so callers can fall back to
        scraped <meta> tags.
    """
    if client is None:
        raise Exception("Claude API client not initialized. Add CLAUDE_API_KEY to your .env file or set the ANTHROPIC_API_KEY environment variable.")

    # Truncate to stay within a reasonable prompt size
    max_chars = 100000
    if len(txt) > max_chars:
        txt = txt[:max_chars]

    try:
        message = client.messages.create(
            model=MODEL,
            max_tokens=512,
            messages=[
                {
                    "role": "user",
                    "content": (
                        "From the following recipe webpage text, identify the dish. "
                        "Respond with ONLY a JSON object (no markdown, no extra text) "
                        "with exactly two keys: \"title\" (the canonical dish name, e.g. "
                        "\"Penne alla Vodka\") and \"description\" (1-2 sentences describing "
                        "the dish, its main ingredients, and cuisine so it can be matched "
                        f"against a natural-language request). Text:\n{txt}\n"
                    ),
                }
            ],
        )
        raw = message.content[0].text.strip()
        # Strip code fences if present
        if raw.startswith("```"):
            raw = raw.strip("`")
            raw = raw[raw.find("{"):]
        data = json.loads(raw)
        return {
            "title": (data.get("title") or "").strip(),
            "description": (data.get("description") or "").strip(),
        }
    except Exception as e:
        print(f"Warning: get_recipe_metadata_txt failed: {e}", file=sys.stderr)
        return {"title": "", "description": ""}


def match_recipes_txt(user_text, recipes):
    """
    Given a user's natural-language request and a list of known recipes, decide
    which recipes the user is asking for.

    Args:
        user_text: e.g. "I want palak paneer, chicken buffalo wraps, and penne alla vodka"
        recipes: list of dicts with keys 'id', 'title', 'description'

    Returns:
        dict with keys 'matched_ids' (list[int]) and 'unmatched' (list[str]).
        On failure returns {'matched_ids': [], 'unmatched': []}.
    """
    if client is None:
        raise Exception("Claude API client not initialized. Add CLAUDE_API_KEY to your .env file or set the ANTHROPIC_API_KEY environment variable.")

    catalog = json.dumps(recipes, ensure_ascii=False)
    try:
        message = client.messages.create(
            model=MODEL,
            max_tokens=1024,
            messages=[
                {
                    "role": "user",
                    "content": (
                        "You are matching a user's meal request to a catalog of recipes. "
                        "The user request is:\n"
                        f"\"{user_text}\"\n\n"
                        "The recipe catalog (JSON array of {id, title, description}) is:\n"
                        f"{catalog}\n\n"
                        "For each distinct dish the user asks for, find the single best "
                        "matching recipe id from the catalog (allow for synonyms, typos and "
                        "loose wording). Respond with ONLY a JSON object (no markdown) with "
                        "two keys: \"matched_ids\" (array of integer recipe ids that match) "
                        "and \"unmatched\" (array of strings for requested dishes with no "
                        "good match). Do not invent ids that are not in the catalog."
                    ),
                }
            ],
        )
        raw = message.content[0].text.strip()
        if raw.startswith("```"):
            raw = raw.strip("`")
            raw = raw[raw.find("{"):]
        data = json.loads(raw)
        matched_ids = [int(i) for i in data.get("matched_ids", [])]
        unmatched = [str(u) for u in data.get("unmatched", [])]
        return {"matched_ids": matched_ids, "unmatched": unmatched}
    except Exception as e:
        print(f"Warning: match_recipes_txt failed: {e}", file=sys.stderr)
        return {"matched_ids": [], "unmatched": []}

def evaluate_substitutes(
    original_ingredient: dict,
    recipe_context: dict | None,
    unavailable_product: dict,
    candidates: list[dict],
) -> dict:
    """Evaluate substitute products using Claude to find contextually-appropriate alternatives.

    Args:
        original_ingredient: dict with keys 'name', 'amount', 'unit', 'tags' (e.g., 'vegetable')
        recipe_context: dict with keys 'title', 'description', 'cook_time' or None
        unavailable_product: dict with keys 'name', 'brand', 'category_path', 'size', 'product_id', 'sku'
        candidates: list of dicts with keys 'product_id', 'sku', 'name', 'brand', 'size', 'price', 'available'

    Returns:
        dict with keys:
            'recommended': dict with 'product_id', 'sku', 'name', 'reason' or None
            'alternatives': list of dicts with 'product_id', 'sku', 'name', 'reason'
            'no_good_substitute': bool
            'warning': str or None
            'fallback_used': bool (True if Claude was unavailable)
    """
    # Filter to only available candidates
    available_candidates = [c for c in candidates if c.get("available", False)]

    if not available_candidates:
        return {
            "recommended": None,
            "alternatives": [],
            "no_good_substitute": True,
            "warning": "No available products found in this category",
            "fallback_used": False,
        }

    # If Claude client is not available, use fallback
    if client is None:
        # Fallback: return first available candidate with warning
        fallback = available_candidates[0]
        return {
            "recommended": {
                "product_id": fallback.get("product_id"),
                "sku": fallback.get("sku"),
                "name": fallback.get("name"),
                "reason": "Claude unavailable — category match only",
            },
            "alternatives": [],
            "no_good_substitute": False,
            "warning": "Review suggested substitute — AI evaluation unavailable",
            "fallback_used": True,
        }

    # Build context string for recipe
    recipe_str = ""
    if recipe_context:
        recipe_str = f"""
Recipe context:
- Title: {recipe_context.get('title', 'Unknown')}
- Description: {recipe_context.get('description', 'Not provided')}
- Cook time: {recipe_context.get('cook_time', 'Not specified')}
"""

    # Build ingredient context
    ingredient_str = f"""
Original ingredient requested:
- Name: {original_ingredient.get('name', 'Unknown')}
- Amount: {original_ingredient.get('amount', '')} {original_ingredient.get('unit', '')}
- Tags: {', '.join(original_ingredient.get('tags', [])) or 'none'}
"""

    # Build unavailable product info
    unavailable_str = f"""
Product that is unavailable:
- Name: {unavailable_product.get('name', 'Unknown')}
- Brand: {unavailable_product.get('brand', 'Unknown')}
- Size: {unavailable_product.get('size', 'Unknown')}
- Category: {unavailable_product.get('category_path', 'Unknown')}
"""

    # Build candidates list
    candidates_str = "Available substitute candidates:\n"
    for i, c in enumerate(available_candidates[:10], 1):  # Limit to 10 candidates
        candidates_str += f"{i}. {c.get('name', 'Unknown')} - {c.get('brand', 'Unknown brand')}, {c.get('size', 'Unknown size')}, ${c.get('price', 0):.2f} (ID: {c.get('product_id')})\n"

    prompt = f"""You are a culinary expert helping find appropriate ingredient substitutes.

{recipe_str}
{ingredient_str}
{unavailable_str}
{candidates_str}

Evaluate the candidates and determine the best substitute considering:
1. Culinary similarity (will it work the same way in this recipe?)
2. Flavor/texture compatibility
3. Dietary considerations (organic if original was organic, etc.)
4. Practical size/quantity match

IMPORTANT RULES:
- For laminated dough recipes (croissants, puff pastry, danish), margarine or vegetable shortening is NOT a suitable substitute for butter
- For baking, consider fat content and behavior under heat
- If no candidate is truly appropriate, say so

Respond with ONLY a JSON object (no markdown, no extra text) with these exact keys:
{{
    "recommended": {{"product_id": "...", "sku": "...", "name": "...", "reason": "1-2 sentence explanation"}} or null if none suitable,
    "alternatives": [{{"product_id": "...", "sku": "...", "name": "...", "reason": "..."}}] (up to 2 other options),
    "no_good_substitute": true/false,
    "warning": "optional warning about the substitution" or null
}}
"""

    try:
        message = client.messages.create(
            model=MODEL,
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = cast(TextBlock, message.content[0]).text.strip()

        # Strip code fences if present
        if raw.startswith("```"):
            raw = raw.strip("`")
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw[raw.find("{"):]

        data = json.loads(raw)

        # Validate and normalize response
        recommended = data.get("recommended")
        if recommended and isinstance(recommended, dict):
            recommended = {
                "product_id": str(recommended.get("product_id", "")),
                "sku": str(recommended.get("sku", "")),
                "name": str(recommended.get("name", "")),
                "reason": str(recommended.get("reason", "")),
            }
        else:
            recommended = None

        alternatives = []
        for alt in data.get("alternatives", [])[:2]:
            if isinstance(alt, dict):
                alternatives.append({
                    "product_id": str(alt.get("product_id", "")),
                    "sku": str(alt.get("sku", "")),
                    "name": str(alt.get("name", "")),
                    "reason": str(alt.get("reason", "")),
                })

        return {
            "recommended": recommended,
            "alternatives": alternatives,
            "no_good_substitute": bool(data.get("no_good_substitute", False)),
            "warning": data.get("warning") if data.get("warning") else None,
            "fallback_used": False,
        }

    except Exception as e:
        print(f"Warning: evaluate_substitutes failed: {e}", file=sys.stderr)
        # Fallback: return first available candidate
        fallback = available_candidates[0]
        return {
            "recommended": {
                "product_id": fallback.get("product_id"),
                "sku": fallback.get("sku"),
                "name": fallback.get("name"),
                "reason": "Claude unavailable — category match only",
            },
            "alternatives": [],
            "no_good_substitute": False,
            "warning": "Review suggested substitute — AI evaluation unavailable",
            "fallback_used": True,
        }

# text = "...recipe page text..."

# test the function
# print(extract_ingredients(text))
