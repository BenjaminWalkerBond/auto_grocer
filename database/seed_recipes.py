"""
Seed recipes into the database from a list of URLs.

For each URL this script:
  1. Extracts title + description (via recipe_grabber.extract_recipe_metadata).
  2. Creates/gets the recipe row (RecipeRepository.get_or_create).
  3. If the recipe has no ingredients yet, scrapes ingredients
     (recipe_grabber.populate_ingredient_list) and saves them with recipe_id.

The script is idempotent: re-running it will not duplicate recipes or
re-scrape recipes that already have ingredients.

URLs are read from pre_process/recipe_urls.txt (one per line) unless a list is
passed to seed_recipes() directly.

Usage:
    python database/seed_recipes.py
"""
import sys
import os

# Allow running directly: add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from recipe_grabber import populate_ingredient_list, extract_recipe_metadata
from database.db_connection import get_db_session
from database.ingredient_repository import IngredientRepository
from database.recipe_repository import RecipeRepository

DEFAULT_URLS_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "pre_process",
    "recipe_urls.txt",
)


def load_urls_from_file(path: str) -> list:
    """Read recipe URLs from a file (one per line, ignoring # comments/blanks)."""
    urls = []
    if not os.path.exists(path):
        return urls
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            urls.append(line)
    return urls


def _to_decimal(amount):
    """Normalize a scraped amount (which may be a list of digit strings) to float."""
    if isinstance(amount, (list, tuple)):
        amount = amount[0] if amount else 1
    try:
        return float(amount)
    except (TypeError, ValueError):
        return 1.0


def _to_unit(unit):
    """Normalize a scraped unit (which may be a list) to a single string."""
    if isinstance(unit, (list, tuple)):
        unit = unit[0] if unit else "none"
    if not unit:
        return "none"
    return str(unit)


def seed_recipes(url_list=None):
    """
    Seed the database with recipes and their ingredients.

    Args:
        url_list: Optional list of URLs. If None, reads from
                  pre_process/recipe_urls.txt.

    Returns:
        dict summary: {'recipes_added', 'recipes_skipped', 'ingredients_added'}
    """
    if url_list is None:
        url_list = load_urls_from_file(DEFAULT_URLS_FILE)

    summary = {"recipes_added": 0, "recipes_skipped": 0, "ingredients_added": 0}

    if not url_list:
        print(f"No URLs found. Add recipe URLs to {DEFAULT_URLS_FILE}")
        return summary

    db = get_db_session()
    recipe_repo = RecipeRepository(db)
    ingredient_repo = IngredientRepository(db)

    try:
        for url in url_list:
            print("=" * 80)
            print(f"Seeding: {url}")
            print("-" * 80)

            try:
                existing = recipe_repo.get_by_url(url)

                if existing and ingredient_repo.get_by_recipe(existing.id):
                    print(f"  ↪ Already seeded (recipe id {existing.id}), skipping.")
                    summary["recipes_skipped"] += 1
                    continue

                # Extract title + description
                meta = extract_recipe_metadata(url)
                print(f"  Title:       {meta['title']}")
                print(f"  Description: {meta['description']}")

                recipe = recipe_repo.get_or_create(
                    url=url,
                    title=meta["title"] or None,
                    source_domain=meta["source_domain"] or None,
                    description=meta["description"] or None,
                )

                # Backfill metadata if the recipe pre-existed without it
                if existing and (not existing.title or not existing.description):
                    recipe_repo.update(
                        recipe.id,
                        title=meta["title"] or None,
                        description=meta["description"] or None,
                    )

                print(f"  ✓ Recipe id: {recipe.id}")

                if not existing:
                    summary["recipes_added"] += 1

                # Scrape and save ingredients
                ingredient_list = populate_ingredient_list([url])
                for ing in ingredient_list.get_ingredients():
                    ingredient_repo.create(
                        name=ing.get_name(),
                        amount=_to_decimal(ing.get_amount()),
                        unit=_to_unit(ing.get_unit()),
                        tag_names=[ing.get_tag()] if ing.get_tag() else [],
                        recipe_id=recipe.id,
                    )
                    summary["ingredients_added"] += 1
                print(f"  ✓ Saved {len(ingredient_list.get_ingredients())} ingredients")

            except Exception as e:
                print(f"  ✗ Error seeding {url}: {e}")
    finally:
        db.close()

    print("=" * 80)
    print(
        f"DONE. Recipes added: {summary['recipes_added']}, "
        f"skipped: {summary['recipes_skipped']}, "
        f"ingredients added: {summary['ingredients_added']}"
    )
    print("=" * 80)
    return summary


if __name__ == "__main__":
    seed_recipes()
