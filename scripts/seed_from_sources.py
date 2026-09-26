"""One-off seeder for a batch of recipe sources (YouTube + web pages).

Runs in a FRESH process so it picks up the latest utility/youtube.py code
(the long-lived MCP server caches modules and won't see edits until restarted).
It calls the real seed_recipes logic (mcp_server.seed_recipes.fn), writing to the
same database the MCP server reads.

  * YouTube URLs  -> seed_recipes auto-parses the description (new code).
  * Web pages     -> we fetch the page, parse ingredients with the structured
                     Claude extractor, then seed with explicit ingredients.

Usage:
    python scripts/seed_from_sources.py
"""
import requests
from bs4 import BeautifulSoup

from auto_grocer import mcp_server as M
from auto_grocer.recipe_grabber import extract_recipe_metadata
from auto_grocer.utility.youtube import is_youtube_url, parse_ingredients_from_text

_seed = getattr(M.seed_recipes, "fn", M.seed_recipes)

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}


# (title, url) — title is a hint; web/YouTube metadata may refine it.
RECIPES = [
    ("Carrot Refried Bean Chicken Enchiladas",
     "https://www.ambitiouskitchen.com/skinny-refried-bean-chicken-enchiladas-with-homemade-enchilada-sauce/"),
    ("Creamy Spinach Chicken Soup", "https://youtube.com/shorts/Ef7L11tUDeo"),
    ("Italian Meatloaf", "https://youtube.com/shorts/ToYtBZAsBlk"),
    ("Hotpot", "https://youtube.com/shorts/wWhWExhds-4"),
    ("Chili Peanut Noodles", "https://youtube.com/shorts/zt0ugxA3Alw"),
    ("One Pan Breakfast Casserole", "https://youtube.com/shorts/9t_7HHHM4S8"),
    ("Penne alla Vodka", "https://nofrillskitchen.com/penne-alla-vodka-without-vodka-recipe/"),
    ("Palak Paneer", "https://www.teaforturmeric.com/palak-paneer/"),
    ("White Chicken Chili", "https://tastesbetterfromscratch.com/creamy-white-chicken-chili/"),
    ("Sheet Pan Kofta", "https://www.foodnetwork.com/recipes/food-network-kitchen/sheet-pan-kofta-and-tomatoes-11542995"),
    ("Folded Crispy Buffalo Chicken Wraps", "https://www.halfbakedharvest.com/buffalo-chicken-wraps/"),
]


def _fetch_page_text(url):
    resp = requests.get(url, headers=_HEADERS, timeout=30)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.content, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    return " ".join(soup.get_text().split())


def seed_one(title, url):
    if is_youtube_url(url):
        result = _seed(title=title, url=url, ingredients=[])
        return result

    # Web page: fetch + parse ingredients, then seed explicitly.
    try:
        text = _fetch_page_text(url)
    except Exception as e:  # noqa: BLE001
        return {"error": True, "code": "PAGE_FETCH_FAILED", "message": str(e)}

    ingredients = parse_ingredients_from_text(text)
    meta = extract_recipe_metadata(url)
    return _seed(
        title=title or meta.get("title", ""),
        url=url,
        ingredients=ingredients,
        description=meta.get("description", ""),
    )


def main():
    print("=" * 70)
    for title, url in RECIPES:
        print(f"\n>>> {title}\n    {url}")
        try:
            res = seed_one(title, url)
        except Exception as e:  # noqa: BLE001
            print(f"    EXCEPTION: {type(e).__name__}: {e}")
            continue
        if res.get("error"):
            print(f"    FAILED [{res.get('code')}]: {res.get('message')}")
        else:
            recipe = res.get("recipe", {})
            print(f"    OK id={recipe.get('id')} source={res.get('source')} "
                  f"ingredients={res.get('ingredients_added')} "
                  f"title={recipe.get('title')!r}")
    print("\n" + "=" * 70)


if __name__ == "__main__":
    main()
