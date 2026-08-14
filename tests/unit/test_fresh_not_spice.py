"""Fresh ingredients must not be tagged as pantry spices.

"fresh cilantro" is produce bought by the bunch, not a jar of dried spice, so
the organic/produce handling downstream should treat it as such.
"""

from classes.IngredientList import IngredientList


def test_fresh_herb_is_not_tagged_spice():
    tagger = IngredientList()
    assert tagger.get_tag("cilantro") == "spice"
    assert tagger.get_tag("fresh cilantro") != "spice"


def test_fresh_does_not_suppress_other_tags():
    tagger = IngredientList()
    assert tagger.get_tag("fresh salmon") == "fish"
    assert tagger.get_tag("fresh ginger") == "vegetable"


def test_non_fresh_spices_still_tagged():
    tagger = IngredientList()
    assert tagger.get_tag("ground cumin") == "spice"
    assert tagger.get_tag("chili powder") == "spice"
