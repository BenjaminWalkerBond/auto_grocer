"""
Example: Integrate database with existing ingredient extraction workflow.
This shows how to save extracted ingredients to the database.
"""
import sys
import os

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from recipe_grabber import populate_ingredient_list
from database.db_connection import get_db_session
from database.ingredient_repository import IngredientRepository
from database.recipe_repository import RecipeRepository


def extract_and_save_ingredients(url_list):
    """
    Extract ingredients from URLs and save them to the database.
    
    Args:
        url_list: List of recipe URLs to process
    """
    print("=" * 80)
    print("EXTRACTING AND SAVING INGREDIENTS TO DATABASE")
    print("=" * 80)
    print()
    
    # Get database session
    db = get_db_session()
    ingredient_repo = IngredientRepository(db)
    recipe_repo = RecipeRepository(db)
    
    total_ingredients_saved = 0
    
    for url in url_list:
        print(f"Processing: {url}")
        print("-" * 80)
        
        try:
            # Create or get recipe
            recipe = recipe_repo.get_or_create(url=url)
            print(f"✓ Recipe ID: {recipe.id}")
            
            # Extract ingredients using existing function
            ingredient_list = populate_ingredient_list([url])
            
            # Save each ingredient to database
            for ingredient_obj in ingredient_list.get_ingredients():
                db_ingredient = ingredient_repo.create(
                    name=ingredient_obj.get_name(),
                    amount=ingredient_obj.get_amount(),
                    unit=ingredient_obj.get_unit(),
                    tag_names=[ingredient_obj.get_tag()] if ingredient_obj.get_tag() else [],
                    recipe_id=recipe.id
                )
                print(f"  ✓ Saved: {db_ingredient}")
                total_ingredients_saved += 1
            
            print()
            
        except Exception as e:
            print(f"  ✗ Error processing {url}: {e}")
            print()
    
    # Close database session
    db.close()
    
    print("=" * 80)
    print(f"COMPLETE! Saved {total_ingredients_saved} ingredients to database")
    print("=" * 80)
    print()
    
    # Show what's in the database
    print("Current database contents:")
    db = get_db_session()
    ingredient_repo = IngredientRepository(db)
    recipe_repo = RecipeRepository(db)
    
    total_recipes = recipe_repo.count()
    total_ingredients = ingredient_repo.count()
    
    print(f"  Total recipes: {total_recipes}")
    print(f"  Total ingredients: {total_ingredients}")
    print()
    
    print("Recent ingredients:")
    recent = ingredient_repo.get_all(limit=10)
    for ing in recent:
        print(f"  - {ing}")
    
    db.close()


if __name__ == '__main__':
    # Example URLs (modify as needed)
    url_list = [
        "https://skinnyspatula.com/salmon-gnocchi/",
    ]
    
    extract_and_save_ingredients(url_list)
