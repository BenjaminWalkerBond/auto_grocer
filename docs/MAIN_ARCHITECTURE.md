# Main.py - Three Mode Implementation

## Summary

`main.py` now has three distinct operating modes for HEB automation:

```python
MODE = 'test'                    # Safe testing mode
MODE = 'checkout_with_prompt'    # Semi-automated with confirmation  
MODE = 'auto_checkout'           # Fully automated (⚠️ use with caution)
```

## Architecture

```
main.py
├── Helper Functions (unchanged)
│   ├── check_exists_by_xpath()
│   ├── random_time()
│   ├── add_ingredient()      [with error logging]
│   ├── clear_cart()          [with error logging]
│   ├── reserve_time_slot()   [with error logging]
│   └── login()               [with error logging]
│
├── New: checkout()
│   └── Handles final checkout process
│
├── Mode Functions (NEW)
│   ├── test_mode(driver, ingredient_list)
│   │   ├── Login → Clear Cart → Reserve Slot → Add Items
│   │   ├── NO checkout
│   │   └── Browser stays open for inspection
│   │
│   ├── checkout_with_prompt(driver, ingredient_list)
│   │   ├── Login → Clear Cart → Reserve Slot → Add Items
│   │   ├── PROMPT: "Proceed with checkout? (yes/no)"
│   │   └── Checkout only if confirmed
│   │
│   └── auto_checkout(driver, ingredient_list)
│       ├── SAFETY PROMPT: Type 'CONFIRM' to proceed
│       ├── Login → Clear Cart → Reserve Slot → Add Items
│       └── AUTOMATIC checkout (⚠️ charges payment!)
│
└── Main Execution (if __name__ == '__main__')
    ├── 1. Configuration
    │   ├── MODE selection
    │   ├── Recipe URLs
    │   └── Ingredient list
    │
    ├── 2. Setup
    │   ├── Initialize IngredientList
    │   ├── Parse ingredients
    │   └── Start Chrome driver
    │
    ├── 3. Run Selected Mode
    │   └── Calls appropriate mode function
    │
    └── 4. Error Handling
        ├── Automatic HTML snapshots
        ├── Screenshots on failure
        └── Graceful exit
```

## Mode Comparison

| Feature | `test` | `checkout_with_prompt` | `auto_checkout` |
|---------|--------|------------------------|-----------------|
| Login | ✅ | ✅ | ✅ |
| Clear Cart | ✅ | ✅ | ✅ |
| Reserve Slot | ✅ | ✅ | ✅ |
| Add Items | ✅ | ✅ | ✅ |
| User Prompt | ❌ | ✅ ("yes/no") | ✅ (Type "CONFIRM") |
| Checkout | ❌ | Only if confirmed | ✅ Automatic |
| Browser | Stays open | Closes after | Closes after |
| Safety | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐ |
| Use Case | Testing/Debug | Regular use | Scheduled automation |

## Error Handling

All modes include comprehensive error logging:

```python
try:
    # Mode-specific operations
    login(driver)
    clear_cart(driver)
    reserve_time_slot(driver)
    # ... add ingredients ...
    
except Exception as e:
    logger.log_failure(
        driver=driver,
        function_name=mode_name,
        error=e,
        additional_info={
            "remaining_ingredients": len(ingredient_list.get_ingredients()),
            "mode": MODE
        }
    )
    # HTML snapshot, screenshot, and error log saved
    raise
```

## Configuration Location

All configuration is at the top of the `if __name__ == '__main__'` block:

```python
# ============================================================
# CONFIGURATION
# ============================================================

# MODE SELECTION
MODE = 'test'  # ← Change this line

# Recipe URLs
url_list = [
    "https://skinnyspatula.com/salmon-gnocchi/",
]

# Ingredient list
ingredient_list_array = [
    '1 tablespoon: olive oil',
    # ... more ingredients
]
```

## Key Changes from Original

### Before (Original):
```python
if __name__ == '__main__':
    # Setup code
    driver = uc.Chrome()
    
    # Single linear workflow
    login(driver)
    clear_cart(driver)
    reserve_time_slot(driver)
    while IL.get_ingredients():
        add_ingredient(IL.remove_last_ingredient(), driver)
    
    # No checkout function
    # No mode selection
    # Browser handling unclear
```

### After (New):
```python
if __name__ == '__main__':
    # Clear configuration section
    MODE = 'test'  # Easy to change
    
    # Setup code with better output
    print("🥗 AUTO GROCIER - HEB AUTOMATION")
    driver = uc.Chrome()
    
    # Mode-based execution
    if MODE == 'test':
        test_mode(driver, IL)
    elif MODE == 'checkout_with_prompt':
        checkout_with_prompt(driver, IL)
    elif MODE == 'auto_checkout':
        auto_checkout(driver, IL)
    
    # Clean error handling
    # Proper browser cleanup
    # Debug logs on failure
```

## Benefits

1. **Safety**: Test mode prevents accidental orders
2. **Flexibility**: Three modes for different use cases
3. **Clarity**: Clear separation of concerns
4. **User-friendly**: Helpful output messages and prompts
5. **Debuggable**: All modes use error logging
6. **Maintainable**: Easy to understand and modify

## Usage Examples

### Example 1: First Time Testing
```python
MODE = 'test'
# Run script, browser stays open
# Manually inspect cart
# Press Enter to close
```

### Example 2: Regular Weekly Order
```python
MODE = 'checkout_with_prompt'
# Script adds items
# Prompts: "Proceed with checkout? (yes/no)"
# Type 'yes' to confirm
# Order placed!
```

### Example 3: Scheduled Automation
```python
MODE = 'auto_checkout'
# Safety prompt: Type 'CONFIRM'
# Fully automated
# Email notification recommended
```

## Next Steps

1. ✅ Three modes implemented
2. ✅ Error logging in all modes
3. ✅ Safety prompts added
4. ✅ Documentation created
5. 🔄 Test `checkout()` function
6. 🔄 Implement payment confirmation
7. 🔄 Add email notifications
8. 🔄 Create scheduled task examples

## See Also

- **[MODES_GUIDE.md](MODES_GUIDE.md)** - Complete mode documentation
- **[DRIVER_LOGGER_GUIDE.md](DRIVER_LOGGER_GUIDE.md)** - Error logging details
- **[DEBUGGING_PROCESS.md](DEBUGGING_PROCESS.md)** - How to debug failures
