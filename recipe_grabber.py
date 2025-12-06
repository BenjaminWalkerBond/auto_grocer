import re
import requests
from bs4 import BeautifulSoup

# import classes.IngredientList as IngredientList
from classes.IngredientList import IngredientList
# import classes.Ingredient as Ingredient
from classes.Ingredient import Ingredient

from claude import get_ingredients_gpt_txt


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


