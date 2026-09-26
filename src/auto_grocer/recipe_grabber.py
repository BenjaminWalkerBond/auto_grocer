import re
import sys
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

# import classes.Ingredient as Ingredient
from auto_grocer.classes.Ingredient import Ingredient

# import classes.IngredientList as IngredientList
from auto_grocer.classes.IngredientList import IngredientList
from auto_grocer.claude import extract_ingredients, get_recipe_metadata_txt


def extract_recipe_metadata(url):
    """
    Extract title, description, and source domain for a recipe URL.

    Strategy:
      1. Fast path: read Open Graph / standard <meta> tags and <title> via
         BeautifulSoup (no API cost).
      2. Fallback: if title or description is missing, ask Claude to derive a
         canonical dish name + short description from the page text.

    Args:
        url: Recipe URL

    Returns:
        dict with keys 'title', 'description', 'source_domain'.
    """
    source_domain = urlparse(url).netloc

    title = ""
    description = ""

    try:
        response = requests.get(url, timeout=30)
        soup = BeautifulSoup(response.content, "html.parser")

        def meta(attr, value):
            tag = soup.find("meta", attrs={attr: value})
            if tag and tag.get("content"):
                return tag["content"].strip()
            return ""

        title = meta("property", "og:title") or meta("name", "twitter:title")
        if not title and soup.title and soup.title.string:
            title = soup.title.string.strip()

        description = (
            meta("property", "og:description")
            or meta("name", "description")
            or meta("name", "twitter:description")
        )

        # Fallback to Claude if either field is missing
        if not title or not description:
            text = " ".join(soup.get_text().split())
            meta_from_ai = get_recipe_metadata_txt(text)
            if not title:
                title = meta_from_ai.get("title", "")
            if not description:
                description = meta_from_ai.get("description", "")
    except Exception as e:
        print(f"Warning: extract_recipe_metadata failed for {url}: {e}", file=sys.stderr)

    return {
        "title": title,
        "description": description,
        "source_domain": source_domain,
    }



def _format_amount(value):
    """Render a numeric amount without a trailing '.0' (so '16' stays '16')."""
    return "%g" % value


# Unicode vulgar fractions that show up in recipe ingredient lines.
_UNICODE_FRACTIONS = {
    "¼": 0.25, "½": 0.5, "¾": 0.75,
    "⅐": 1 / 7, "⅑": 1 / 9, "⅒": 0.1,
    "⅓": 1 / 3, "⅔": 2 / 3,
    "⅕": 0.2, "⅖": 0.4, "⅗": 0.6, "⅘": 0.8,
    "⅙": 1 / 6, "⅚": 5 / 6,
    "⅛": 0.125, "⅜": 0.375, "⅝": 0.625, "⅞": 0.875,
}
_UNICODE_FRACTION_CHARS = "".join(_UNICODE_FRACTIONS)


def _extract_amounts(text):
    """Extract the leading quantity from an ingredient string.

    Preserves decimals and fractions so "0.5 cup" is 0.5 (not 5) and "1/2" is
    0.5. Returns a list with a single formatted numeric string to match
    clean_ingredient's list contract, or [] when no quantity is present.
    """
    if not text:
        return []

    # Mixed number: "1 1/2"
    m = re.search(r"(\d+)\s+(\d+)\s*/\s*(\d+)", text)
    if m:
        whole, num, den = int(m.group(1)), int(m.group(2)), int(m.group(3))
        return [_format_amount(whole + num / den)] if den else []

    # Simple fraction: "3/4"
    m = re.search(r"(\d+)\s*/\s*(\d+)", text)
    if m:
        num, den = int(m.group(1)), int(m.group(2))
        return [_format_amount(num / den)] if den else []

    # Decimal/integer, optionally followed by a unicode fraction ("1½", "0.5", "16")
    m = re.search(rf"(\d+(?:\.\d+)?)\s*([{_UNICODE_FRACTION_CHARS}])?", text)
    if m:
        value = float(m.group(1))
        if m.group(2):
            value += _UNICODE_FRACTIONS[m.group(2)]
        return [_format_amount(value)]

    # Standalone unicode fraction: "½ cup"
    m = re.search(rf"([{_UNICODE_FRACTION_CHARS}])", text)
    if m:
        return [_format_amount(_UNICODE_FRACTIONS[m.group(1)])]

    return []


def clean_ingredient(ingredient):
    # Parse the amount from the ORIGINAL text (with parentheticals removed) so
    # decimals and fraction slashes survive. The character filter below strips
    # '.' and '/', which would otherwise turn "0.5" into "05" (-> 5) or "1/2"
    # into "12".
    amount = _extract_amounts(re.sub(r'\([^)]*\)', '', ingredient))

    # filter out everything that is not a character, a space, or a number
    # print("ingredient before char, space, and num only: ", ingredient)
    cleaned_ingredient = re.sub(r'[^a-zA-Z0-9\s$]', '', ingredient)
    # print("cleaned_ingredient after char, space, and num only: ", cleaned_ingredient)

    # remove all conjunctions from the line
    cleaned_ingredient = re.sub(r'\b(?:to|of|cause|after|agin|albeit|also|altho|although|an|and|and/or|as|assuming|because|before|being|both|but|conjunction|directly|either|ere|ergo|except|excepting|for|how|howbeit|however|if|immediately|instantly|lest|like|neither|nor|notwithstanding|now|once|only|or|ossia|plus|provided|providing|save|saving|seeing|since|sith|slash|so|supposing|syne|than|that|tho|though|til|till|unless|until|what|when|whenas|whence|whencesoever|whenever|whensoever|where|whereas|whereat|whereby|wherefrom|wherein|whereinto|whereof|wheresoever|wherethrough|whereto|whereupon|wherever|wherewith|wherewithal|whether|while|whiles|whilst|whither|why|without|yet)\b', '', cleaned_ingredient)
    # print("cleaned_ingredient after conjunction: ", cleaned_ingredient)

    # Normalize spacing - collapse multiple spaces into single spaces
    cleaned_ingredient = ' '.join(cleaned_ingredient.split())

    # get unit from line
    unit = re.findall(r'\b(?:optional|tsp|tbsp|cup|oz|lb|g|kg|ml|l|pinch|dash|can|jar|bottle|slice|slices|sliced|piece|pieces|stalk|stalks|head|heads|leaf|leaves|bunch|bunches|bag|bags|box|boxes|package|packages|container|containers|bowl|bowls|pint|pints|quart|quarts|gallon|gallons|stick|sticks|sprig|sprigs|sprinkle|sprinkles|handful|handfuls|pinch|pinches|dash|dashes|teaspoon|teaspoons|tablespoon|tablespoons|clove|cloves|head|heads|inch|inches|ounce|ounces|pound|pounds|gram|grams|kilogram|kilograms|milliliter|milliliters|liter|liters|milligram|milligrams|gallon|gallons|quart|quarts|pint|pints|cup|cups|tablespoon|tablespoons|teaspoon|teaspoons|pinch|pinches|dash|dashes|sprinkle|sprinkles|handful|handfuls|slice|slices|piece|pieces|stalk|stalks|head|heads|leaf|leaves|bunch|bunches|bag|bags|box|boxes|package|packages|container|containers|bowl|bowls|stick|sticks|sprig|sprigs|sprinkle|sprinkles|handful|handfuls|pinch|pinches|dash|dashes|teaspoon|teaspoons|tablespoon)\b', cleaned_ingredient)

    # get name from line
    name = re.findall(r'[a-zA-Z]+', cleaned_ingredient)

    # remove unit from name
    for u in unit:
        try:
            name.remove(u)
        except ValueError:
            pass

    # rejoin name
    name = " ".join(name)

    return name, amount, unit

def populate_ingredient_list(url_list):

    IL = IngredientList()

    for url in url_list:
        print("url: ", url, file=sys.stderr)

    for url in url_list:

        # Send a GET request to the webpage
        response = requests.get(url)
        # print the response
        print(response, file=sys.stderr)
        # Create a BeautifulSoup object to parse the HTML content
        soup = BeautifulSoup(response.content, "html.parser")

        # Find all the text on the webpage
        text = soup.get_text()
        # Remove newlines and extra spaces in the text
        text = " ".join(text.split())
        text = text.lower()

        ingredient_list_array = extract_ingredients(text)
        print("ingredient_list_array: ", ingredient_list_array, file=sys.stderr)
        for ingredient in ingredient_list_array:
            print("Ingredient: ", ingredient, file=sys.stderr)
            print(f"Cleaning the ingredient: {ingredient}\n", file=sys.stderr)
            cleaned_ingredient_tuple = clean_ingredient(ingredient)
            print(cleaned_ingredient_tuple, file=sys.stderr)

            # Unpack the tuple into name, amount, and unit variables
            name, amount, unit = cleaned_ingredient_tuple

            # add to ingredient list
            IL.add_ingredient(Ingredient(name, amount, unit))
            print("ADDING INGREDIENT", name, file=sys.stderr)
            print("AMOUNT", amount, file=sys.stderr)
            print("UNIT", unit, file=sys.stderr)
    return IL


