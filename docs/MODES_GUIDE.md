# Auto Grocier - Modes Guide

## Overview

Auto Grocier now supports three different operating modes for flexibility and safety:

1. **`test`** - Testing and debugging (safest)
2. **`checkout_with_prompt`** - Semi-automated with confirmation
3. **`auto_checkout`** - Fully automated (⚠️ use with caution)

## Mode Selection

Edit `main.py` and change the `MODE` variable:

```python
# MODE SELECTION: Choose one of: 'test', 'checkout_with_prompt', 'auto_checkout'
MODE = 'test'  # Change this to switch modes
```

---

## Mode 1: `test` 🧪

**Purpose:** Testing and debugging without placing an order.

**What it does:**
- ✅ Logs in to HEB
- ✅ Clears the cart
- ✅ Reserves a delivery time slot
- ✅ Adds all ingredients to cart
- ❌ Does NOT checkout
- ✅ Keeps browser open for manual inspection

**Use when:**
- Testing new ingredients
- Debugging website changes
- Verifying the automation works correctly
- Checking prices and availability
- Making manual adjustments before ordering

**Safety:** ⭐⭐⭐⭐⭐ (Very Safe)
- No risk of accidental orders
- Full control over checkout

**Example output:**
```
🧪 RUNNING IN TEST MODE
============================================================
This will add ingredients to cart but NOT checkout.
Browser will remain open for inspection.

✓ Time slot reserved
✓ All ingredients added to cart!

🧪 TEST MODE COMPLETE
Browser left open for manual inspection.
Press Enter to close the browser and exit...
```

---

## Mode 2: `checkout_with_prompt` 🤔

**Purpose:** Add items to cart, then prompt before final checkout.

**What it does:**
- ✅ Logs in to HEB
- ✅ Clears the cart
- ✅ Reserves a delivery time slot
- ✅ Adds all ingredients to cart
- ⏸️ **PAUSES** and asks for confirmation
- ✅ Checks out only if you confirm

**Use when:**
- You want automation but with final control
- You want to review the cart before ordering
- You're semi-confident in the automation
- You want to make last-minute changes

**Safety:** ⭐⭐⭐⭐ (Safe)
- You control the final checkout step
- Can cancel if something looks wrong

**Example output:**
```
🤔 RUNNING IN CHECKOUT WITH PROMPT MODE
============================================================
✓ Time slot reserved
✓ All ingredients added to cart!

============================================================
🛒 Ready to checkout!
============================================================

Proceed with checkout? (yes/no): yes

💳 Proceeding with checkout...
✓ Order placed successfully!
```

**Canceling:**
```
Proceed with checkout? (yes/no): no

❌ Checkout cancelled by user.
Browser will remain open. Close manually when done.
```

---

## Mode 3: `auto_checkout` 🤖

**Purpose:** Fully automated ordering with NO user interaction.

**⚠️ WARNING:** This mode will automatically place and pay for the order!

**What it does:**
- ✅ Logs in to HEB
- ✅ Clears the cart
- ✅ Reserves a delivery time slot
- ✅ Adds all ingredients to cart
- ✅ **AUTOMATICALLY checks out**
- ✅ **CHARGES your payment method**

**Safety confirmation required:**
- You must type `CONFIRM` to proceed
- This is your last chance to cancel

**Use when:**
- You have thoroughly tested the automation
- You trust the ingredient list completely
- You want fully hands-off operation
- You're scheduling this to run automatically

**Safety:** ⭐⭐ (Use with Caution)
- ⚠️ Will charge your payment method
- ⚠️ No manual review step
- ⚠️ Make sure ingredient list is correct!

**Example output:**
```
🤖 RUNNING IN AUTO CHECKOUT MODE
============================================================
⚠️  WARNING: This will AUTOMATICALLY COMPLETE the order!
⚠️  Your payment method will be charged!
============================================================

This is your last chance to cancel.
Type 'CONFIRM' to proceed with automatic checkout: CONFIRM

✓ Time slot reserved
✓ All ingredients added to cart!
💳 Automatically processing checkout...

============================================================
✅ ORDER PLACED SUCCESSFULLY!
============================================================
Check your email for order confirmation.
```

**Canceling:**
```
Type 'CONFIRM' to proceed with automatic checkout: cancel

❌ Auto checkout cancelled. Exiting...
```

---

## Quick Reference

| Mode | Login | Add Items | Reserve Slot | Checkout | Browser | Safety |
|------|-------|-----------|--------------|----------|---------|--------|
| `test` | ✅ | ✅ | ✅ | ❌ | Stays Open | ⭐⭐⭐⭐⭐ |
| `checkout_with_prompt` | ✅ | ✅ | ✅ | With Prompt | Closes | ⭐⭐⭐⭐ |
| `auto_checkout` | ✅ | ✅ | ✅ | Automatic | Closes | ⭐⭐ |

---

## Recommended Workflow

### First Time Setup:
1. **Use `test` mode** to verify everything works
2. Check the cart manually in the browser
3. Close the browser without ordering

### Regular Usage (Cautious):
1. **Use `checkout_with_prompt` mode**
2. Review the cart when prompted
3. Confirm or cancel as needed

### Fully Automated (Advanced):
1. **Test thoroughly with `test` mode first**
2. **Verify with `checkout_with_prompt` several times**
3. **Only then use `auto_checkout` for hands-free operation**

---

## Configuration

### Changing Modes

Edit `main.py`:

```python
# For testing (safest)
MODE = 'test'

# For prompted checkout
MODE = 'checkout_with_prompt'

# For automatic checkout (least safe)
MODE = 'auto_checkout'
```

### Ingredient Source Selection

You can choose to use either **recipe URLs** or a **hardcoded ingredient list**:

```python
# Set to True to parse ingredients from recipe URLs
USE_URLS = False  # Change to True to use url_list

# Option 1: Recipe URLs (when USE_URLS = True)
url_list = [
    "https://www.cookingclassy.com/recipe1/",
    "https://www.recipetineats.com/recipe2/",
]

# Option 2: Hardcoded ingredients (when USE_URLS = False)
ingredient_list_array = [
    '1 tablespoon: olive oil',
    '1 medium: shallot',
    # ... more ingredients
]
```

**Using Recipe URLs** (`USE_URLS = True`):
- ✅ Automatically parses ingredients from recipe websites
- ✅ Supports multiple recipes
- ✅ Uses Claude AI to extract and clean ingredients
- ⚠️ Requires API calls (uses Claude API key)
- ⚠️ May take longer to process

**Using Hardcoded List** (`USE_URLS = False`):
- ✅ Faster - no API calls needed
- ✅ Full control over exact ingredients
- ✅ Good for testing and debugging
- ✅ No API costs
- ⚠️ Must manually format ingredients

---

## Error Handling

All modes include automatic error logging:

- HTML snapshots saved to `debug_logs/`
- Screenshots captured on failure
- Detailed error information logged

See `docs/DRIVER_LOGGER_GUIDE.md` for debugging details.

---

## Safety Tips

### Always Test First
- Run `test` mode before using other modes
- Verify ingredients are correct
- Check prices and availability

### Review Your Config
- Ensure `config.txt` has correct credentials
- Verify payment method is set up correctly in HEB

### Monitor Your Orders
- Check your email for order confirmations
- Review your HEB order history
- Set up budget alerts if using `auto_checkout` regularly

### Use `checkout_with_prompt` for New Recipes
- New recipes might have unusual ingredients
- Prices can vary significantly
- Manual review prevents surprises

---

## Troubleshooting

**Browser closes immediately:**
- Check for errors in the console
- Look in `debug_logs/` for HTML snapshots
- Make sure virtual environment is activated

**Stuck on "Press Enter":**
- This is expected in `test` mode
- Review the cart in the browser
- Press Enter when done

**Mode not recognized:**
- Check spelling: `'test'`, `'checkout_with_prompt'`, or `'auto_checkout'`
- Make sure MODE is a string (in quotes)
- Case-sensitive!

**Order placed accidentally:**
- Contact HEB customer service immediately
- Provide order number from confirmation email
- They can often cancel orders before fulfillment

---

## Examples

### Example 1: Testing New Recipe from URL

```python
MODE = 'test'
USE_URLS = True

url_list = [
    "https://example.com/new-recipe/",
]

# Run the script, ingredients auto-parsed from recipe
# Review cart, don't checkout
```

### Example 2: Testing with Hardcoded Ingredients

```python
MODE = 'test'
USE_URLS = False

ingredient_list_array = [
    '1 tablespoon: olive oil',
    '2 cloves: garlic',
    '1 pound: salmon',
]

# Run the script, review cart, don't checkout
```

### Example 3: Weekly Groceries with Review

```python
MODE = 'checkout_with_prompt'
USE_URLS = False

ingredient_list_array = [
    '1 gallon: milk',
    '2 dozen: eggs',
    '1 loaf: bread',
    # ... weekly items
]

# Run, review when prompted, confirm to order
```

### Example 4: Multiple Recipes Automated

```python
MODE = 'checkout_with_prompt'
USE_URLS = True

url_list = [
    "https://www.cookingclassy.com/recipe1/",
    "https://www.recipetineats.com/recipe2/",
    "https://skinnyspatula.com/recipe3/",
]

# Automatically combines ingredients from all recipes
# Prompts before checkout
```

### Example 3: Scheduled Automated Order

```python
MODE = 'auto_checkout'

# Set up in cron or Task Scheduler
# Only after thorough testing!
# Consider adding email notification after completion
```

---

## Future Enhancements

Potential improvements:
- **Budget mode**: Skip checkout if total exceeds threshold
- **Dry run mode**: Calculate total without adding to cart
- **Email confirmation**: Send summary after order placed
- **Scheduling**: Integrate with cron/Task Scheduler
- **Multi-recipe mode**: Combine multiple recipes automatically

---

## Summary

- **Start with `test` mode** - Always test first!
- **Use `checkout_with_prompt` for regular use** - Safe and convenient
- **Use `auto_checkout` with caution** - Only after thorough testing
- **Check debug logs** if anything goes wrong
- **Keep browser open in test mode** for manual inspection

Happy automated grocery shopping! 🛒
