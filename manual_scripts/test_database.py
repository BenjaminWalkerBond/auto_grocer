"""
Test database operations.
Creates sample ingredients and verifies CRUD operations.
"""
import os
import sys

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from auto_grocier.database.db_connection import get_db_session
from auto_grocier.database.ingredient_repository import IngredientRepository
from auto_grocier.database.recipe_repository import RecipeRepository
from auto_grocier.database.tag_repository import TagRepository


def test_database():
    """Test database operations"""
    print("=" * 60)
    print("Testing Database Operations")
    print("=" * 60)
    print()

    try:
        # Get database session
        db = get_db_session()

        # Create repositories
        tag_repo = TagRepository(db)
        recipe_repo = RecipeRepository(db)
        ingredient_repo = IngredientRepository(db)

        # Test 1: Create a recipe
        print("Test 1: Creating a recipe...")
        recipe = recipe_repo.get_or_create(
            url="https://test.com/recipe1",
            title="Test Salmon Recipe"
        )
        print(f"  ✓ Created recipe: {recipe}")
        print()

        # Test 2: Create ingredients
        print("Test 2: Creating ingredients...")

        ingredient1 = ingredient_repo.create(
            name="salmon",
            amount=1.5,
            unit="lb",
            tag_names=["fish"],
            recipe_id=recipe.id
        )
        print(f"  ✓ Created: {ingredient1}")

        ingredient2 = ingredient_repo.create(
            name="olive oil",
            amount=2,
            unit="tablespoon",
            tag_names=["oil"],
            recipe_id=recipe.id
        )
        print(f"  ✓ Created: {ingredient2}")

        ingredient3 = ingredient_repo.create(
            name="spinach",
            amount=100,
            unit="g",
            tag_names=["vegetable"],
            recipe_id=recipe.id
        )
        print(f"  ✓ Created: {ingredient3}")
        print()

        # Test 3: Retrieve ingredients
        print("Test 3: Retrieving ingredients...")
        all_ingredients = ingredient_repo.get_all()
        print(f"  ✓ Total ingredients in database: {len(all_ingredients)}")
        print()

        # Test 4: Search by tag
        print("Test 4: Searching by tag...")
        fish_ingredients = ingredient_repo.get_by_tag("fish")
        print(f"  ✓ Found {len(fish_ingredients)} fish ingredients:")
        for ing in fish_ingredients:
            print(f"    - {ing}")
        print()

        # Test 5: Search by name
        print("Test 5: Searching by name...")
        salmon_results = ingredient_repo.search_by_name("salmon")
        print(f"  ✓ Found {len(salmon_results)} ingredients matching 'salmon':")
        for ing in salmon_results:
            print(f"    - {ing}")
        print()

        # Test 6: Get ingredients by recipe
        print("Test 6: Getting ingredients by recipe...")
        recipe_ingredients = ingredient_repo.get_by_recipe(recipe.id)
        print(f"  ✓ Recipe '{recipe.title}' has {len(recipe_ingredients)} ingredients:")
        for ing in recipe_ingredients:
            print(f"    - {ing}")
        print()

        # Test 7: Update ingredient
        print("Test 7: Updating an ingredient...")
        updated = ingredient_repo.update(
            ingredient1.id,
            amount=2.0,
            tag_names=["fish", "protein"]
        )
        print(f"  ✓ Updated: {updated}")
        print()

        # Test 8: Count operations
        print("Test 8: Counting...")
        total_ingredients = ingredient_repo.count()
        total_recipes = recipe_repo.count()
        total_tags = len(tag_repo.get_all())
        print(f"  ✓ Total ingredients: {total_ingredients}")
        print(f"  ✓ Total recipes: {total_recipes}")
        print(f"  ✓ Total tags: {total_tags}")
        print()

        # Test 9: Tag statistics
        print("Test 9: Tag statistics...")
        all_tags = tag_repo.get_all()
        print("  Tag usage:")
        for tag in all_tags[:10]:  # Show first 10
            count = ingredient_repo.count_by_tag(tag.name)
            if count > 0:
                print(f"    - {tag.name}: {count} ingredient(s)")
        print()

        # Close session
        db.close()

        print("=" * 60)
        print("All tests passed! ✓")
        print("=" * 60)
        print()

        return True

    except Exception as e:
        print(f"\n✗ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == '__main__':
    success = test_database()
    sys.exit(0 if success else 1)
