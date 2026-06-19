import re
import requests
from bs4 import BeautifulSoup

# import classes.IngredientList as IngredientList
from classes.IngredientList import IngredientList
# import classes.Ingredient as Ingredient
from classes.Ingredient import Ingredient

from claude import get_ingredients_gpt_txt
from claude import get_recipe_metadata_txt
from urllib.parse import urlparse


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
        print(f"Warning: extract_recipe_metadata failed for {url}: {e}")

    return {
        "title": title,
        "description": description,
        "source_domain": source_domain,
    }



def clean_ingredient(ingredient):
    # filter out everything that is not a character, a space, or a number
    # print("ingredient before char, space, and num only: ", ingredient)
    cleaned_ingredient = re.sub(r'[^a-zA-Z0-9\s$]', '', ingredient)
    # print("cleaned_ingredient after char, space, and num only: ", cleaned_ingredient)

    # remove all conjunctions from the line
    cleaned_ingredient = re.sub(r'\b(?:to|of|cause|after|agin|albeit|also|altho|although|an|and|and/or|as|assuming|because|before|being|both|but|conjunction|directly|either|ere|ergo|except|excepting|for|how|howbeit|however|if|immediately|instantly|lest|like|neither|nor|notwithstanding|now|once|only|or|ossia|plus|provided|providing|save|saving|seeing|since|sith|slash|so|supposing|syne|than|that|tho|though|til|till|unless|until|what|when|whenas|whence|whencesoever|whenever|whensoever|where|whereas|whereat|whereby|wherefrom|wherein|whereinto|whereof|wheresoever|wherethrough|whereto|whereupon|wherever|wherewith|wherewithal|whether|while|whiles|whilst|whither|why|without|yet)\b', '', cleaned_ingredient)
    # print("cleaned_ingredient after conjunction: ", cleaned_ingredient)
    
    # Normalize spacing - collapse multiple spaces into single spaces
    cleaned_ingredient = ' '.join(cleaned_ingredient.split())
    
    # create a variable called pre_amount that removes everything in the word in parenthesis
    pre_amount = re.sub(r'\([^)]*\)', '', cleaned_ingredient)
    amount = re.findall(r'\d+', pre_amount)
    
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

    debug = True
    IL = IngredientList()

    filter_list=["optional", "tsp", "tbsp", "cup", "oz", "lb", "g", "kg", "ml", "l", "pinch", "dash", "can", "jar", "bottle", "slice", "slices","sliced", "piece", "pieces", "stalk", "stalks", "head", "heads", "leaf", "leaves", "bunch", "bunches", "bag", "bags", "box", "boxes", "package", "packages", "container", "containers", "bowl", "bowls", "pint", "pints", "quart", "quarts", "gallon", "gallons", "stick", "sticks", "sprig", "sprigs", "sprinkle", "sprinkles", "handful", "handfuls", "pinch", "pinches", "dash", "dashes", "teaspoon", "teaspoons", "tablespoon", "tablespoons", "clove", "cloves", "head", "heads", "inch", "inches", "ounce", "ounces", "pound", "pounds", "gram", "grams", "kilogram", "kilograms", "milliliter", "milliliters", "liter", "liters", "milligram", "milligrams", "gallon", "gallons", "quart", "quarts", "pint", "pints", "cup", "cups", "tablespoon", "tablespoons", "teaspoon", "teaspoons", "pinch", "pinches", "dash", "dashes", "sprinkle", "sprinkles", "handful", "handfuls", "slice", "slices", "piece", "pieces", "stalk", "stalks", "head", "heads", "leaf", "leaves", "bunch", "bunches", "bag", "bags", "box", "boxes", "package", "packages", "container", "containers", "bowl", "bowls", "stick", "sticks", "sprig", "sprigs", "sprinkle", "sprinkles", "handful", "handfuls", "pinch", "pinches", "dash", "dashes", "teaspoon", "teaspoons", "tablespoon"]
    conjunctions = 'cause|after|agin|albeit|also|altho|although|an|and|and/or|as|assuming|because|before|being|both|but|conjunction|directly|either|ere|ergo|except|excepting|for|how|howbeit|however|if|immediately|instantly|lest|like|neither|nor|notwithstanding|now|once|only|or|ossia|plus|provided|providing|save|saving|seeing|since|sith|slash|so|supposing|syne|than|that|tho|though|til|till|unless|until|what|when|whenas|whence|whencesoever|whenever|whensoever|where|whereas|whereat|whereby|wherefrom|wherein|whereinto|whereof|wheresoever|wherethrough|whereto|whereupon|wherever|wherewith|wherewithal|whether|while|whiles|whilst|whither|why|without|yet'
    
    for url in url_list:
        print("url: ", url)

    for url in url_list:

        # Send a GET request to the webpage
        response = requests.get(url)
        # print the response 
        print(response)
        # Create a BeautifulSoup object to parse the HTML content
        soup = BeautifulSoup(response.content, "html.parser")

        # Find all the text on the webpage
        text = soup.get_text()
        # Remove newlines and extra spaces in the text
        text = " ".join(text.split())
        text = text.lower()

        ingredient_list_array = get_ingredients_gpt_txt(text)
        print("ingredient_list_array: ", ingredient_list_array)
        for ingredient in ingredient_list_array:
            print("Ingredient: ", ingredient)
            print(f"Cleaning the ingredient: {ingredient}\n")
            cleaned_ingredient_tuple = clean_ingredient(ingredient)
            print(cleaned_ingredient_tuple)

            # Unpack the tuple into name, amount, and unit variables
            name, amount, unit = cleaned_ingredient_tuple

            # add to ingredient list
            IL.add_ingredient(Ingredient(name, amount, unit))
            print("ADDING INGREDIENT", name)
            print("AMOUNT", amount)
            print("UNIT", unit)
    return IL


