"""Unit tests for recipe_matcher ingredient-list building and exclusions."""
from types import SimpleNamespace

from auto_grocer.utility.recipe_matcher import build_ingredient_list


class _FakeIngredientRepo:
    def __init__(self, by_recipe):
        self._by_recipe = by_recipe

    def get_by_recipe(self, recipe_id):
        return self._by_recipe.get(recipe_id, [])


def _ing(name, amount=1, unit="none"):
    return SimpleNamespace(name=name, amount=amount, unit=unit)


def _repo():
    return _FakeIngredientRepo(
        {
            1: [
                _ing("spinach", 16, "oz"),
                _ing("olive oil", 2, "tbsp"),
                _ing("ghee", 1, "tbsp"),
                _ing("ground cumin", 1, "tsp"),
                _ing("paneer", 8, "oz"),
            ],
            2: [
                _ing("black lentils", 1, "cup"),
                _ing("salted butter", 4, "tbsp"),
            ],
        }
    )


def _names(ingredient_list):
    return [i.get_name() for i in ingredient_list.get_ingredients()]


def test_build_ingredient_list_without_exclusions():
    recipes = [SimpleNamespace(id=1), SimpleNamespace(id=2)]
    IL, excluded = build_ingredient_list(recipes, _repo())
    assert excluded == []
    assert "olive oil" in _names(IL)
    assert "black lentils" in _names(IL)


def test_exclusions_drop_named_ingredients():
    recipes = [SimpleNamespace(id=1), SimpleNamespace(id=2)]
    IL, excluded = build_ingredient_list(
        recipes, _repo(), exclude=["olive oil", "Ghee", "  ground cumin "]
    )
    names = _names(IL)
    assert "olive oil" not in names
    assert "ghee" not in names
    assert "ground cumin" not in names
    assert "spinach" in names
    assert "paneer" in names
    assert sorted(excluded) == ["ghee", "ground cumin", "olive oil"]


def test_exclusions_are_exact_names_not_substrings():
    # The caller decides what to drop; "oil" alone must not knock out "olive oil",
    # and "salt" must not knock out "salted butter".
    recipes = [SimpleNamespace(id=1), SimpleNamespace(id=2)]
    IL, excluded = build_ingredient_list(recipes, _repo(), exclude=["oil", "salt"])
    names = _names(IL)
    assert "olive oil" in names
    assert "salted butter" in names
    assert excluded == []
