# Ingredient Source Configuration

## Overview

Auto Grocier now supports two methods for providing ingredients:

1. **Recipe URLs** - Automatically parse ingredients from recipe websites using Claude AI
2. **Hardcoded List** - Manually specify ingredients in the script

## Configuration

Edit `main.py` and set the `USE_URLS` variable:

```python
# ============================================================
# INGREDIENT SOURCE SELECTION
# ============================================================

USE_URLS = False  # Set to True to use url_list, False to use ingredient_list_array
```

---

## Option 1: Recipe URLs (`USE_URLS = True`)

### When to Use:
- You have recipe URLs from supported websites
- You want automatic ingredient extraction
- You're cooking from online recipes
- You want to combine multiple recipes

### Setup:

```python
USE_URLS = True

url_list = [
    "https://www.cookingclassy.com/skillet-seared-salmon/",
    "https://www.recipetineats.com/spaghetti-bolognese/",
    "https://skinnyspatula.com/salmon-gnocchi/",
]
```

### How It Works:

1. Script fetches HTML from each URL
2. Claude AI extracts ingredient list
3. Ingredients are parsed and cleaned
4. All recipes are combined into one ingredient list
5. Browser automation adds items to HEB cart

### Requirements:

- ✅ `CLAUDE_API_KEY` in `config.txt`
- ✅ Internet connection
- ✅ Supported recipe website format

### Pros:
- ✅ Fully automatic ingredient extraction
- ✅ Supports multiple recipes
- ✅ No manual typing needed
- ✅ AI handles format variations

### Cons:
- ⚠️ Requires Claude API calls (costs money)
- ⚠️ Slower than hardcoded list
- ⚠️ Dependent on recipe website format
- ⚠️ May occasionally misparse unusual formats

### Example Output:

```
📡 Fetching ingredients from recipe URLs...
   Processing 3 recipe(s)...

✓ Successfully parsed recipes

📋 Loaded 28 ingredients:
  • 1 tablespoon olive oil
  • 2 cloves garlic
  • 1 pound salmon
  ...
```

---

## Option 2: Hardcoded List (`USE_URLS = False`)

### When to Use:
- You already know exactly what you need
- Testing specific ingredients
- Debugging automation
- Weekly staple groceries
- No API calls desired
- Maximum control over ingredients

### Setup:

```python
USE_URLS = False

ingredient_list_array = [
    '1 tablespoon: olive oil',
    '1 medium: shallot',
    '2 large: garlic cloves',
    '¼ teaspoon: red chilli flakes',
    '75 ml (⅓ cup): dry white wine',
    '2 tablespoons: tomato paste',
    '1 teaspoon: Italian seasoning mix',
    '200 ml (1 cup): water',
    '100 g (3.5 oz): fresh spinach',
    '180 g (6.5 oz): cream cheese',
    '500 g (1 lb): gnocchi',
    '225 g (½ lb): hot smoked salmon'
]
```

### Ingredient Format:

```
'<quantity> [unit]: <ingredient name>'
```

Examples:
- `'1 tablespoon: olive oil'`
- `'2 large: garlic cloves'`
- `'500 g (1 lb): gnocchi'`
- `'1 cup: water'`

### How It Works:

1. Each string is parsed by `clean_ingredient()`
2. Extracts quantity, unit, and name
3. Creates Ingredient objects
4. Adds to IngredientList
5. Browser automation adds items to HEB cart

### Requirements:

- ✅ Properly formatted ingredient strings
- ✅ No special dependencies

### Pros:
- ✅ Fast - no API calls
- ✅ Free - no API costs
- ✅ Full control over exact ingredients
- ✅ Great for testing
- ✅ Predictable results

### Cons:
- ⚠️ Manual entry required
- ⚠️ Must follow format exactly
- ⚠️ More work for multiple recipes

### Example Output:

```
📝 Using hardcoded ingredient list...

📋 Loaded 12 ingredients:
  • 1 tablespoon olive oil
  • 1 medium shallot
  • 2 large garlic cloves
  ...
```

---

## Comparison

| Feature | Recipe URLs (`True`) | Hardcoded (`False`) |
|---------|---------------------|---------------------|
| **Setup Time** | Fast (paste URLs) | Slow (type each) |
| **API Calls** | Yes (Claude AI) | No |
| **Cost** | $$ (API usage) | Free |
| **Speed** | Slower | Faster |
| **Accuracy** | ~95% (AI-based) | 100% (you control) |
| **Multiple Recipes** | Easy | Manual work |
| **Control** | Less | Full |
| **Best For** | New recipes | Testing/staples |

---

## Switching Between Options

### From Hardcoded to URLs:

```python
# Before
USE_URLS = False
ingredient_list_array = [...]

# After
USE_URLS = True
url_list = [
    "https://example.com/recipe1/",
    "https://example.com/recipe2/",
]
```

### From URLs to Hardcoded:

```python
# Before
USE_URLS = True
url_list = [...]

# After
USE_URLS = False
ingredient_list_array = [
    '1 cup: flour',
    '2 large: eggs',
    # ... etc
]
```

---

## Best Practices

### For Recipe URLs:
1. Test with `MODE = 'test'` first
2. Review parsed ingredients in console output
3. Check cart before checkout
4. Use reputable recipe sites
5. Keep API key secure in `config.txt`

### For Hardcoded List:
1. Follow the format exactly: `'quantity unit: name'`
2. Use consistent units (cups, tablespoons, etc.)
3. Include size modifiers when relevant (large, medium, small)
4. Test with a small list first
5. Keep common ingredients saved for reuse

---

## Troubleshooting

### Recipe URLs Not Working:

**Problem**: Ingredients not parsed correctly
- Check if recipe website is supported
- View the HTML to see ingredient format
- Try a different recipe URL
- Use hardcoded list as fallback

**Problem**: Claude API error
- Verify `CLAUDE_API_KEY` in `config.txt`
- Check API quota/billing
- Ensure internet connection

### Hardcoded List Issues:

**Problem**: Ingredients not found on HEB
- Check spelling
- Try simpler ingredient names
- HEB may not carry specialty items
- Review console output for errors

**Problem**: Format errors
- Ensure format is: `'quantity unit: name'`
- Include quotes around each ingredient
- Comma after each entry (except last)
- Check for typos

---

## Examples

### Example 1: Weekly Meal Plan from Recipes

```python
MODE = 'checkout_with_prompt'
USE_URLS = True

url_list = [
    "https://www.recipetineats.com/honey-garlic-chicken/",
    "https://www.cookingclassy.com/salmon-recipe/",
    "https://www.budgetbytes.com/pasta-dish/",
    "https://skinnyspatula.com/stir-fry/",
]

# Automatically combines all 4 recipes
# Prompts before checkout
```

### Example 2: Staple Groceries (Weekly Run)

```python
MODE = 'checkout_with_prompt'
USE_URLS = False

ingredient_list_array = [
    '1 gallon: milk',
    '2 dozen: eggs',
    '1 loaf: bread',
    '1 pound: butter',
    '1 block: cheddar cheese',
    '5 pounds: chicken breast',
    '2 pounds: ground beef',
    '1 bag: spinach',
    '1 head: lettuce',
    '1 pound: carrots',
]
```

### Example 3: Testing Single Recipe

```python
MODE = 'test'
USE_URLS = True

url_list = [
    "https://www.cookingclassy.com/new-recipe/",
]

# Parse ingredients from recipe
# Add to cart
# DON'T checkout (test mode)
# Review cart manually
```

### Example 4: Quick Test Ingredients

```python
MODE = 'test'
USE_URLS = False

ingredient_list_array = [
    '1 pound: salmon',
    '1 lemon: fresh',
    '2 tablespoons: olive oil',
]

# Quick test with 3 items
# Verify automation works
```

---

## Summary

- **Use `USE_URLS = True`** for automatic recipe parsing
- **Use `USE_URLS = False`** for manual control and testing
- **Change easily** by toggling one variable
- **Both methods** work with all three modes (test, checkout_with_prompt, auto_checkout)
- **Choose based on** your needs: convenience vs. control

See **[MODES_GUIDE.md](MODES_GUIDE.md)** for more information about the three operating modes.
