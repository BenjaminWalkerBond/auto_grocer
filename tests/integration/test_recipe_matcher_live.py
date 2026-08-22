"""Integration tests for the natural-language recipe matcher.

Seeds a couple of recipes directly into the database (no scraping), then
verifies that:
  1. RecipeRepository.search_recipes matches on title AND description.
  2. recipe_matcher.parse_and_match maps a natural-language request to the
     right recipes (using the ILIKE fallback so the test runs offline
     without Claude).
  3. recipe_matcher.build_ingredient_list builds an IngredientList from the
     matched recipes' ingredients.

Requires a live Postgres database (the compose ``postgres`` service or a
local instance configured via .env). Skipped unless ``--run-integration``
is passed; also skipped automatically if the database is unreachable.

Run with: pytest tests/integration/ --run-integration
"""
import pytest

# Sentinel URLs so the test can clean up after itself.
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


@pytest.fixture
def db_session():
    """Yield a database session, skipping if the database is unreachable."""
    try:
        from sqlalchemy import text

        from auto_grocer.database.db_connection import get_db_session

        db = get_db_session()
        # Force a real connection so unreachable DBs skip rather than error later.
        db.execute(text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"database unavailable: {exc}")
    try:
        yield db
    finally:
        db.close()


@pytest.mark.integration
def test_recipe_matcher_end_to_end(db_session):
    """Seed recipes, match a natural-language request, build an ingredient list."""
    from auto_grocer.database.ingredient_repository import IngredientRepository
    from auto_grocer.database.recipe_repository import RecipeRepository
    from auto_grocer.utility import recipe_matcher

    recipe_repo = RecipeRepository(db_session)
    ingredient_repo = IngredientRepository(db_session)

    _cleanup(recipe_repo)
    _seed(recipe_repo, ingredient_repo)
    try:
        # 1. search_recipes matches on description.
        results = recipe_repo.search_recipes("spinach")
        assert any(r.url == TEST_RECIPES[1]["url"] for r in results), \
            "search_recipes should match Palak Paneer via its description"

        # 2. parse_and_match (force the ILIKE fallback by hiding Claude).
        from auto_grocer import claude

        saved_client = claude.client
        claude.client = None  # force offline fallback
        try:
            matched, unmatched = recipe_matcher.parse_and_match(
                "I want penne alla vodka and palak paneer this week", recipe_repo
            )
        finally:
            claude.client = saved_client

        matched_urls = {r.url for r in matched}
        assert TEST_RECIPES[0]["url"] in matched_urls, "Should match Penne alla Vodka"
        assert TEST_RECIPES[1]["url"] in matched_urls, "Should match Palak Paneer"

        # 3. build_ingredient_list.
        ingredient_list = recipe_matcher.build_ingredient_list(matched, ingredient_repo)
        names = {i.get_name() for i in ingredient_list.get_ingredients()}
        assert "penne" in names, "Ingredient list should include penne"
        assert "spinach" in names, "Ingredient list should include spinach"
    finally:
        _cleanup(recipe_repo)
