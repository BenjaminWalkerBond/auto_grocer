import os
import sys
import json
import anthropic

# Ensure stdout/stderr use UTF-8 so the project's Unicode status symbols (✓, 🥗,
# emoji) don't crash on Windows, whose console defaults to a legacy code page
# (cp1252). claude.py is imported first by every entry point, so reconfiguring
# here covers the whole app. No-op on Linux/macOS (already UTF-8).
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except Exception:
        pass

# Claude model used across the project. Update here if the model is retired.
MODEL = "claude-sonnet-4-5-20250929"


def parse_config(config_path):
    """
    Parse the config.txt file and return a dictionary of key-value pairs.
    Supports KEY=VALUE format and ignores comments (lines starting with #).
    """
    config_dict = {}
    
    if not os.path.exists(config_path):
        return config_dict
    
    with open(config_path, 'r') as file:
        for line in file:
            line = line.strip()
            
            # Skip empty lines and comments
            if not line or line.startswith('#'):
                continue
            
            # Parse KEY=VALUE format
            if '=' in line:
                key, value = line.split('=', 1)  # Split only on first =
                config_dict[key.strip()] = value.strip()
    
    return config_dict


# Find the absolute path of the file called config.txt in the current directory
file_path = os.path.join(os.path.dirname(__file__), 'config.txt')

# Parse the config file
config = parse_config(file_path)

# Get Claude API key from config or environment variable
claude_api_key = config.get('CLAUDE_API_KEY') or os.environ.get("ANTHROPIC_API_KEY")

if not claude_api_key:
    print("ERROR: No Claude API key found.")
    print("Please add CLAUDE_API_KEY=your-key-here to config.txt")
    print("or set the ANTHROPIC_API_KEY environment variable")
    print("See CLAUDE_SETUP.md for instructions.")
else:
    print(f"✓ Claude API key loaded successfully: {claude_api_key[:20]}...")

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
        raise Exception("Claude API client not initialized. Please add your Claude API key to config.txt (line 5) or set the ANTHROPIC_API_KEY environment variable. See CLAUDE_SETUP.md for instructions.")
    
    ingredient_list = []

    # get the amount of characters in the text
    char_count = len(txt)
    
    # Truncate text if too long (Claude has context limits)
    # Claude Sonnet supports up to 200k tokens, but we'll be conservative
    max_chars = 100000
    if char_count > max_chars:
        txt = txt[:max_chars]
        print(f"Warning: Text truncated from {char_count} to {max_chars} characters")

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
        raise Exception("Claude API client not initialized. Please add your Claude API key to config.txt or set the ANTHROPIC_API_KEY environment variable.")

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
        print(f"Warning: get_recipe_metadata_txt failed: {e}")
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
        raise Exception("Claude API client not initialized. Please add your Claude API key to config.txt or set the ANTHROPIC_API_KEY environment variable.")

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
        print(f"Warning: match_recipes_txt failed: {e}")
        return {"matched_ids": [], "unmatched": []}


# text = "...recipe page text..."

# test the function
# print(extract_ingredients(text))