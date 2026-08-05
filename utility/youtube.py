"""YouTube recipe support for seed_recipes.

We assume a cooking video's full recipe + ingredient list lives in its
description. This module:
  * detects YouTube video / Shorts URLs,
  * fetches the video description (no API key — scrapes the watch page and reads
    ``videoDetails.shortDescription`` from the embedded ytInitialPlayerResponse
    JSON, with an og:description fallback),
  * parses that description into structured ingredient dicts via the project's
    existing Claude extractor + cleaner, so it plugs straight into seed_recipes.
"""
import json
import re
from typing import Optional

import requests

from claude import MODEL, client, get_recipe_metadata_txt

# Match an 11-char YouTube video id from the common URL shapes.
_VIDEO_ID_PATTERNS = [
    r"youtube\.com/watch\?[^ ]*\bv=([\w-]{11})",
    r"youtu\.be/([\w-]{11})",
    r"youtube\.com/shorts/([\w-]{11})",
    r"youtube\.com/embed/([\w-]{11})",
    r"youtube\.com/live/([\w-]{11})",
]

_BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}


def is_youtube_url(url) -> bool:
    """Return True if the URL points to a YouTube video or Short."""
    if not url:
        return False
    u = str(url).lower()
    return (
        "youtube.com/watch" in u
        or "youtu.be/" in u
        or "youtube.com/shorts/" in u
        or "youtube.com/embed/" in u
        or "youtube.com/live/" in u
        or "m.youtube.com/watch" in u
    )


def extract_video_id(url) -> Optional[str]:
    """Return the 11-character YouTube video id, or None if not found."""
    if not url:
        return None
    for pattern in _VIDEO_ID_PATTERNS:
        match = re.search(pattern, str(url))
        if match:
            return match.group(1)
    return None


def fetch_youtube_description(url) -> str:
    """Fetch a YouTube video's full description text.

    Shorts and youtu.be links are normalized to the canonical /watch URL. Reads
    ``videoDetails.shortDescription`` from the embedded player JSON (the complete
    description, including line breaks), falling back to the og:description meta
    tag (truncated by YouTube) if the JSON isn't present.

    Returns the description string (empty string if nothing could be read).

    Raises:
        ValueError: if the page could not be fetched.
    """
    video_id = extract_video_id(url)
    target = (
        f"https://www.youtube.com/watch?v={video_id}" if video_id else str(url)
    )

    try:
        resp = requests.get(target, headers=_BROWSER_HEADERS, timeout=30)
        resp.raise_for_status()
    except requests.RequestException as e:
        raise ValueError(f"Could not fetch YouTube page: {e}") from e

    html = resp.text

    # Primary: the complete description from the player response JSON.
    match = re.search(r'"shortDescription":"((?:\\.|[^"\\])*)"', html)
    if match:
        try:
            return json.loads('"' + match.group(1) + '"')
        except (ValueError, json.JSONDecodeError):
            pass

    # Fallback: og:description / meta description (often truncated by YouTube).
    for pattern in (
        r'<meta property="og:description" content="([^"]*)"',
        r'<meta name="description" content="([^"]*)"',
    ):
        meta = re.search(pattern, html)
        if meta and meta.group(1).strip():
            # Unescape basic HTML entities for the common cases.
            text = (
                meta.group(1)
                .replace("&quot;", '"')
                .replace("&#39;", "'")
                .replace("&amp;", "&")
                .replace("&gt;", ">")
                .replace("&lt;", "<")
            )
            return text

    return ""


def parse_ingredients_from_text(text):
    """Parse free-form recipe text (e.g. a video description) into structured
    ingredient dicts.

    Uses a single direct Claude call that returns a JSON array of
    ``{"name", "amount", "unit"}`` objects. This is more robust for prose-style
    YouTube descriptions than the project's two-step text extractor, and the
    output matches what seed_recipes expects.

    Returns an empty list if nothing usable was found.
    """
    if not text or not text.strip():
        return []
    if client is None:
        raise Exception(
            "Claude API client not initialized. Add CLAUDE_API_KEY to your .env "
            "file or set ANTHROPIC_API_KEY."
        )

    max_chars = 100000
    snippet = text[:max_chars]

    prompt = (
        "Extract the recipe ingredients from the following video description. "
        "Return ONLY a JSON array (no markdown, no commentary). Each element is an "
        "object with exactly these keys: \"name\" (the ingredient, lowercase, no "
        "amounts or prep words, e.g. \"peanut butter\"), \"amount\" (a number; use "
        "1 if unspecified), and \"unit\" (e.g. \"cup\", \"tbsp\", \"oz\", \"clove\"; "
        "use \"none\" if unspecified). Only include actual food ingredients from the "
        "ingredient list. Ignore garnishes-only lines, instructions, hashtags, links, "
        "and commentary. If there are no ingredients, return [].\n\n"
        f"Description:\n{snippet}\n"
    )

    try:
        message = client.messages.create(
            model=MODEL,
            max_tokens=2048,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = message.content[0].text.strip()
    except Exception as e:  # noqa: BLE001
        print(f"Warning: ingredient extraction call failed: {e}")
        return []

    # Strip code fences and isolate the JSON array.
    if raw.startswith("```"):
        raw = raw.strip("`")
        raw = raw[raw.find("["):]
    start = raw.find("[")
    end = raw.rfind("]")
    if start != -1 and end != -1 and end > start:
        raw = raw[start : end + 1]

    try:
        data = json.loads(raw)
    except (ValueError, json.JSONDecodeError):
        print("Warning: could not parse ingredient JSON from Claude response.")
        return []

    if not isinstance(data, list):
        return []

    items = []
    for entry in data:
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("name", "")).strip()
        if not name:
            continue
        try:
            amount_val = float(entry.get("amount", 1) or 1)
        except (TypeError, ValueError):
            amount_val = 1.0
        unit_val = str(entry.get("unit", "none") or "none").strip() or "none"
        items.append({"name": name, "amount": amount_val, "unit": unit_val})
    return items


def youtube_recipe_from_url(url):
    """Build a recipe payload from a YouTube URL's description.

    Returns a dict with:
        ingredients     -> list of {"name", "amount", "unit"} dicts
        title           -> derived dish title (may be "")
        description     -> derived short description (may be "")
        raw_description -> the full fetched video description

    Raises:
        ValueError: if the description could not be fetched or was empty.
    """
    description_text = fetch_youtube_description(url)
    if not description_text or not description_text.strip():
        raise ValueError(
            "The YouTube description was empty or could not be read; "
            "no ingredients to parse."
        )

    ingredients = parse_ingredients_from_text(description_text)

    title = ""
    short_description = ""
    try:
        meta = get_recipe_metadata_txt(description_text)
        title = (meta.get("title") or "").strip()
        short_description = (meta.get("description") or "").strip()
    except Exception as e:  # noqa: BLE001 - metadata is best-effort
        print(f"Warning: could not derive YouTube recipe metadata: {e}")

    return {
        "ingredients": ingredients,
        "title": title,
        "description": short_description,
        "raw_description": description_text,
    }
