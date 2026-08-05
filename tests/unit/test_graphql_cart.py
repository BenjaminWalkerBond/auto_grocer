"""Unit tests for auto_grocier's own cart-scaling and ingredient logic.

These cover the project-specific code in utility/graphql_cart.py and
recipe_grabber.clean_ingredient — the package-size-aware quantity scaling and
the free-form ingredient parser. The vendored auto_grocier_mcp library has its
own tests elsewhere in tests/unit.
"""

import math

import pytest

from utility.graphql_cart import (
    _build_search_term,
    _choose_best_product,
    _coerce_scalar,
    _normalize_unit,
    _parse_size,
    _safe_float,
    _to_base,
)


class _FakeProduct:
    """Minimal stand-in for a search-result product."""

    def __init__(self, name, size, available=True):
        self.name = name
        self.size = size
        self.available = available
        self.product_id = "pid"
        self.sku = "sku"


class _FakeIngredient:
    def __init__(self, name, tag):
        self._name = name
        self._tag = tag

    def get_name(self):
        return self._name

    def get_tag(self):
        return self._tag


# --- _safe_float / _coerce_scalar -----------------------------------------

@pytest.mark.parametrize(
    "value,expected",
    [(1, 1.0), ("2.5", 2.5), (None, 0.0), ("abc", 0.0), (["3"], 0.0)],
)
def test_safe_float(value, expected):
    assert _safe_float(value) == expected


def test_coerce_scalar_unwraps_lists():
    # clean_ingredient returns amount/unit as lists; recipes store scalars.
    assert _coerce_scalar(["16"], 0) == "16"
    assert _coerce_scalar(["oz"], "") == "oz"
    assert _coerce_scalar([], "") == ""
    assert _coerce_scalar(None, "none") == "none"
    assert _coerce_scalar(2.0, 0) == 2.0


# --- _normalize_unit -------------------------------------------------------

def test_normalize_unit_handles_none_and_lists_safely():
    assert _normalize_unit("") == ""
    assert _normalize_unit(None) == ""
    assert _normalize_unit("  OZ ") == "oz"
    assert _normalize_unit("fl oz") == "floz"
    # Defensive: non-string should not raise.
    assert _normalize_unit(5) == "5"


# --- _to_base --------------------------------------------------------------

def test_to_base_families():
    val, fam = _to_base(16, "oz")
    assert fam == "weight"
    assert val == pytest.approx(453.59237, rel=1e-6)

    val, fam = _to_base(1, "cup")
    assert fam == "volume"
    assert val == pytest.approx(236.588237, rel=1e-6)

    val, fam = _to_base(2, "ct")
    assert fam == "count"
    assert val == 2.0


def test_to_base_unconvertible_returns_none():
    # Bare counts / non-measure units are intentionally not convertible.
    assert _to_base(2, "none") is None
    assert _to_base(5, "clove") is None
    assert _to_base(1, "inch") is None
    assert _to_base(1, "") is None


# --- _parse_size -----------------------------------------------------------

@pytest.mark.parametrize(
    "text,family",
    [
        ("5 oz", "weight"),
        ("Avg. 0.63 lb", "weight"),
        ("1 lb bag", "weight"),
        ("13.66 oz", "weight"),
        ("1 gal", "volume"),
        ("2 ct", "count"),
    ],
)
def test_parse_size_recognizes_common_labels(text, family):
    parsed = _parse_size(text)
    assert parsed is not None
    assert parsed[1] == family


@pytest.mark.parametrize("text", [None, "", "4-7 Bananas", "each"])
def test_parse_size_rejects_unparseable(text):
    assert _parse_size(text) is None


# --- _choose_best_product --------------------------------------------------

def test_choose_best_product_zero_waste_wins():
    target_base, family = _to_base(16, "oz")
    products = [
        _FakeProduct("Baby Spinach", "5 oz"),
        _FakeProduct("Spinach", "10 oz"),
        _FakeProduct("Spinach", "1 lb"),  # exactly 16 oz
    ]
    product, packages = _choose_best_product(products, target_base, family)
    assert product.size == "1 lb"
    assert packages == 1


def test_choose_best_product_multiple_packages_when_needed():
    target_base, family = _to_base(16, "oz")
    products = [
        _FakeProduct("Spinach", "5 oz"),
        _FakeProduct("Spinach", "10 oz"),
    ]
    product, packages = _choose_best_product(products, target_base, family)
    # 10 oz x2 = 20 (waste 4) beats 5 oz x4 = 20 (waste 4) on fewer packages.
    assert product.size == "10 oz"
    assert packages == 2
    assert packages == math.ceil(16 / 10)


def test_choose_best_product_prefers_available():
    target_base, family = _to_base(16, "oz")
    products = [
        _FakeProduct("Spinach OOS", "1 lb", available=False),
        _FakeProduct("Spinach", "1 lb", available=True),
    ]
    product, _ = _choose_best_product(products, target_base, family)
    assert product.available is True


def test_choose_best_product_none_when_no_compatible_size():
    target_base, family = _to_base(16, "oz")  # weight
    products = [_FakeProduct("Milk", "1 gal")]  # volume -> incompatible
    assert _choose_best_product(products, target_base, family) is None


# --- _build_search_term ----------------------------------------------------

def test_build_search_term_prefixes_organic_for_produce():
    assert _build_search_term(_FakeIngredient("spinach", "vegetable")) == "organic spinach"
    assert _build_search_term(_FakeIngredient("apple", "fruit")) == "organic apple"
    assert _build_search_term(_FakeIngredient("chicken breast", "meat")) == "chicken breast"


# --- clean_ingredient (recipe_grabber) ------------------------------------

def test_clean_ingredient_measured_amount():
    from recipe_grabber import clean_ingredient

    name, amount, unit = clean_ingredient("16 oz spinach")
    assert "spinach" in name
    assert "16" in amount
    assert "oz" in unit


def test_clean_ingredient_bare_count_has_no_unit():
    from recipe_grabber import clean_ingredient

    name, amount, unit = clean_ingredient("2 onions")
    assert "onions" in name
    assert "2" in amount
    # No measurement unit for a bare count.
    assert unit == []


def test_clean_ingredient_decimal_amount_preserved():
    from recipe_grabber import clean_ingredient

    name, amount, unit = clean_ingredient("0.5 cup heavy cream")
    assert "heavy" in name and "cream" in name
    # Regression: the '.' used to be stripped, turning 0.5 into 5.
    assert amount == ["0.5"]
    assert "cup" in unit


def test_clean_ingredient_quarter_decimal_amount():
    from recipe_grabber import clean_ingredient

    _name, amount, _unit = clean_ingredient("0.25 cup vegetable oil")
    # Regression: 0.25 used to parse as 25.
    assert amount == ["0.25"]


def test_clean_ingredient_ascii_fraction():
    from recipe_grabber import clean_ingredient

    _name, amount, _unit = clean_ingredient("1/2 cup water")
    assert amount == ["0.5"]


def test_clean_ingredient_mixed_number():
    from recipe_grabber import clean_ingredient

    _name, amount, _unit = clean_ingredient("1 1/2 cups flour")
    assert amount == ["1.5"]


def test_clean_ingredient_unicode_fraction():
    from recipe_grabber import clean_ingredient

    _name, amount, _unit = clean_ingredient("½ cup milk")
    assert amount == ["0.5"]


def test_decimal_amount_does_not_overorder():
    """End-to-end regression: a 0.5 cup need must not order 3 pints."""
    from recipe_grabber import clean_ingredient

    _name, amount, unit = clean_ingredient("0.5 cup heavy cream")
    target_base, family = _to_base(
        _safe_float(_coerce_scalar(amount, 0)),
        _normalize_unit(_coerce_scalar(unit, "")),
    )
    products = [_FakeProduct("Heavy Cream", "1 pt")]  # 1 pint ~ 473 ml
    product, packages = _choose_best_product(products, target_base, family)
    assert packages == 1

