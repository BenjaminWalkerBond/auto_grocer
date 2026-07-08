"""
Test the natural-language recipe matcher and ingredient-list builder.

This test seeds a couple of recipes directly into the database (no scraping),
then verifies that:
  1. RecipeRepository.search_recipes matches on title AND description.
  2. recipe_matcher.parse_and_match maps a natural-language request to the right
     recipes (using the ILIKE fallback so the test runs offline without Claude).
  3. recipe_matcher.build_ingredient_list builds an IngredientList from the
     matched recipes' ingredients.

Run:
    python manual_scripts/test_recipe_matcher.py
"""
import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database.db_connection import get_db_session
from database.recipe_repository import RecipeRepository
from database.ingredient_repository import IngredientRepository
from utility import recipe_matcher


# Sentinel URLs so we can clean up after ourselves
TEST_RECIPES = [
    {
        "url": "https://example.com/test/penne-alla-vodka",
        "title": "Penne alla Vodka",
        "description": "A creamy Italian pasta dish with penne, tomato, vodka and cream.",
        "ingredients": [
            {"name": "penne", "amount": 1.0, "unit": "lb", "tags": ["pasta"]},
            {"name": "tomato paste", "amount": 2.0, "unit": "tablespoon", "tags": ["vegetable"]},
        ],
    },
    {
        "url": "https://example.com/test/palak-paneer",
        "title": "Palak Paneer",
        "description": "Indian spinach curry with paneer cheese and spices.",
        "ingredients": [
            {"name": "spinach", "amount": 1.0, "unit": "lb", "tags": ["vegetable"]},
            {"name": "paneer", "amount": 8.0, "unit": "oz", "tags": ["cheese"]},
        ],
    },
]


def _cleanup(recipe_repo):
    for spec in TEST_RECIPES:
        existing = recipe_repo.get_by_url(spec["url"])
        if existing:
            recipe_repo.delete(existing.id)  # cascade deletes ingredients


def _seed(recipe_repo, ingredient_repo):
    for spec in TEST_RECIPES:
        recipe = recipe_repo.create(
            url=spec["url"],
            title=spec["title"],
            description=spec["description"],
        )
        for ing in spec["ingredients"]:
            ingredient_repo.create(
                name=ing["name"],
                amount=ing["amount"],
                unit=ing["unit"],
                tag_names=ing["tags"],
                recipe_id=recipe.id,
            )


def run():
    db = get_db_session()
    recipe_repo = RecipeRepository(db)
    ingredient_repo = IngredientRepository(db)

    passed = True
    try:
        _cleanup(recipe_repo)
        _seed(recipe_repo, ingredient_repo)

        # 1. search_recipes matches on description
        results = recipe_repo.search_recipes("spinach")
        assert any(r.url == TEST_RECIPES[1]["url"] for r in results), \
            "search_recipes should match Palak Paneer via its description"
        print("✓ search_recipes matches on description")

        # 2. parse_and_match (force ILIKE fallback by hiding Claude)
        import claude
        saved_client = claude.client
        claude.client = None  # force fallback
        try:
            matched, unmatched = recipe_matcher.parse_and_match(
                "I want penne alla vodka and palak paneer this week", recipe_repo
            )
        finally:
            claude.client = saved_client

        matched_urls = {r.url for r in matched}
        assert TEST_RECIPES[0]["url"] in matched_urls, "Should match Penne alla Vodka"
        assert TEST_RECIPES[1]["url"] in matched_urls, "Should match Palak Paneer"
        print(f"✓ parse_and_match matched {len(matched)} recipes (unmatched: {unmatched})")

        # 3. build_ingredient_list
        IL = recipe_matcher.build_ingredient_list(matched, ingredient_repo)
        names = {i.get_name() for i in IL.get_ingredients()}
        assert "penne" in names, "Ingredient list should include penne"
        assert "spinach" in names, "Ingredient list should include spinach"
        print(f"✓ build_ingredient_list built {len(IL.get_ingredients())} ingredients: {sorted(names)}")

        print("\nALL TESTS PASSED")
    except AssertionError as e:
        passed = False
        print(f"\n✗ TEST FAILED: {e}")
    finally:
        _cleanup(recipe_repo)
        db.close()

    return passed


if __name__ == "__main__":
    ok = run()
    sys.exit(0 if ok else 1)
