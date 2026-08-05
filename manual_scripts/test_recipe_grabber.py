import os
import sys

# Add the parent directory to the Python path to import modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from classes.IngredientList import IngredientList
from recipe_grabber import populate_ingredient_list


def process_urls_and_display(url_list):
    """
    Process a list of recipe URLs and display ingredients for each webpage.

    Args:
        url_list: List of recipe webpage URLs to process
    """
    results = {}

    print("=" * 80)
    print("RECIPE INGREDIENT EXTRACTOR")
    print("=" * 80)
    print()

    for url in url_list:
        print(f"Processing: {url}")
        print("-" * 80)

        try:
            # Create a new ingredient list for this URL
            IL = IngredientList()

            # Use populate_ingredient_list to get ingredients from the webpage
            # Note: populate_ingredient_list processes all URLs in the list,
            # so we pass a single-item list
            IL = populate_ingredient_list([url])

            # Store the ingredient list for this URL
            results[url] = IL

            print(f"Successfully extracted {len(IL.get_ingredients())} ingredients")
            print()

        except Exception as e:
            print(f"Error processing {url}: {str(e)}")
            print()
            results[url] = None

    # Display all results
    print("\n")
    print("=" * 80)
    print("FINAL RESULTS")
    print("=" * 80)
    print()

    for url, ingredient_list in results.items():
        print(f"WEBPAGE URL: {url}")
        print("-" * 80)

        if ingredient_list and ingredient_list.get_ingredients():
            print("INGREDIENT LIST:")
            for ingredient in ingredient_list.get_ingredients():
                print(f"  - {ingredient}")
        else:
            print("  No ingredients found or error occurred")

        print()
        print()


if __name__ == '__main__':
    # Test URL list - you can modify this list
    url_list = [
        "https://www.cookingclassy.com/skillet-seared-salmon-with-garlic-lemon-butter-sauce/",
        "https://www.recipetineats.com/spaghetti-bolognese/",
        "https://skinnyspatula.com/salmon-gnocchi/"
    ]

    # Uncomment below to test with a single URL
    # url_list = [
    #     "https://skinnyspatula.com/salmon-gnocchi/",
    # ]

    process_urls_and_display(url_list)
