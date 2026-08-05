"""
Natural-language recipe matching.

Turns a user request like
    "I want palak paneer, chicken buffalo wraps, and penne alla vodka this week"
into a set of recipes from the database, then builds an IngredientList from the
ingredients of those recipes for the existing cart pipeline.

Matching strategy:
  1. Primary: ask Claude (claude.match_recipes_txt) to map the request to recipe
     ids from the catalog (handles synonyms, typos, loose wording).
  2. Fallback: if Claude is unavailable or returns nothing, split the request on
     commas/"and" and ILIKE-search each phrase via RecipeRepository.search_recipes.
"""
import re

from classes.Ingredient import Ingredient
from classes.IngredientList import IngredientList


def _split_request(user_text: str):
    """Split a free-form request into candidate dish phrases."""
    # Remove common lead-ins
    text = re.sub(
        r"\b(i\s+want|i\s+would\s+like|i'd\s+like|can\s+i\s+get|please|this\s+week|for\s+dinner)\b",
        "",
        user_text,
        flags=re.IGNORECASE,
    )
    # Split on commas and the word "and"
    parts = re.split(r",|\band\b", text, flags=re.IGNORECASE)
    return [p.strip() for p in parts if p.strip()]


def _fallback_match(user_text: str, recipe_repo):
    """ILIKE-based matching when Claude is unavailable."""
    matched = {}
    unmatched = []
    for phrase in _split_request(user_text):
        results = recipe_repo.search_recipes(phrase)
        if results:
            best = results[0]
            matched[best.id] = best
        else:
            unmatched.append(phrase)
    return list(matched.values()), unmatched


def parse_and_match(user_text: str, recipe_repo):
    """
    Match a natural-language request to recipes in the database.

    Args:
        user_text: The user's free-form meal request.
        recipe_repo: A RecipeRepository instance.

    Returns:
        (matched_recipes, unmatched_phrases)
        matched_recipes: list of Recipe ORM objects
        unmatched_phrases: list of strings the user asked for but we couldn't match
    """
    all_recipes = recipe_repo.get_all()
    if not all_recipes:
        return [], _split_request(user_text)

    catalog = [
        {"id": r.id, "title": r.title or "", "description": r.description or ""}
        for r in all_recipes
    ]
    by_id = {r.id: r for r in all_recipes}

    # Primary: Claude-based matching
    try:
        from claude import match_recipes_txt

        result = match_recipes_txt(user_text, catalog)
        matched_ids = [i for i in result.get("matched_ids", []) if i in by_id]
        unmatched = result.get("unmatched", [])
        if matched_ids:
            matched = [by_id[i] for i in matched_ids]
            return matched, unmatched
    except Exception as e:
        print(f"Warning: Claude matching failed, using fallback: {e}")

    # Fallback: ILIKE search
    return _fallback_match(user_text, recipe_repo)


def _to_amount(amount):
    """Convert a DB amount (Decimal) to the list form Ingredient expects."""
    try:
        return [str(amount)]
    except Exception:
        return [str(1)]


def build_ingredient_list(recipes, ingredient_repo):
    """
    Build an IngredientList from the ingredients of the given recipes.

    Args:
        recipes: list of Recipe ORM objects.
        ingredient_repo: An IngredientRepository instance.

    Returns:
        An IngredientList populated with classes.Ingredient objects.
    """
    IL = IngredientList()
    for recipe in recipes:
        for db_ing in ingredient_repo.get_by_recipe(recipe.id):
            unit = db_ing.unit or "none"
            ingredient = Ingredient(db_ing.name, _to_amount(db_ing.amount), [unit])
            IL.add_ingredient(ingredient)
    return IL
