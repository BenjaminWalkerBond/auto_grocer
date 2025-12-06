# Driver Logger - Debugging HEB Website Changes

## Overview

The Driver Logger automatically captures HTML snapshots, screenshots, and error logs whenever the automation script fails. This is essential for debugging when HEB updates their website structure.

## How It Works

When any function fails (like `reserve_time_slot`, `add_ingredient`, `clear_cart`, or `login`), the logger automatically:

1. **Saves the full HTML** of the page where the error occurred
2. **Takes a screenshot** of the page
3. **Logs detailed error information** including:
   - Error type and message
   - Full stack trace
   - Current URL and page title
   - Function-specific context (e.g., which ingredient failed)
   - Timestamp

## Usage

The logger is automatically initialized in `main.py`:

```python
from utility.driver_logger import DriverLogger

# Initialize the logger
logger = DriverLogger(log_dir="debug_logs")
```

All critical functions (`reserve_time_slot`, `add_ingredient`, `clear_cart`, `login`) are wrapped with try-except blocks that automatically call the logger on failure.

## Output Structure

Debug logs are saved in timestamped session directories:

```
debug_logs/
└── session_20251205_143022/
    ├── 20251205_143045_123456_reserve_time_slot_NoSuchElementException.html
    ├── 20251205_143045_123456_reserve_time_slot_NoSuchElementException.png
    ├── 20251205_143045_123456_reserve_time_slot_error.json
    ├── 20251205_143102_789012_add_ingredient_NoSuchElementException.html
    ├── 20251205_143102_789012_add_ingredient_NoSuchElementException.png
    └── 20251205_143102_789012_add_ingredient_error.json
```

## Debugging Workflow

### When a Function Fails:

1. **Check the console output** - It will show you where the debug files are saved
2. **Open the HTML file** - This shows exactly what the page looked like when it failed
3. **Review the screenshot** - Visual confirmation of the page state
4. **Read the error JSON** - Detailed context about what went wrong

### Updating Functions for Website Changes:

1. Open the HTML file in a browser or text editor
2. Search for the element you're trying to find
3. Copy the new XPath, ID, or CSS selector
4. Update the function in `main.py`
5. Test again

## Example: Fixing `reserve_time_slot`

If `reserve_time_slot` fails:

```bash
# 1. Check the console output:
📄 HTML snapshot saved: debug_logs/session_20251205_143022/20251205_143045_reserve_time_slot_NoSuchElementException.html
📸 Screenshot saved: debug_logs/session_20251205_143022/20251205_143045_reserve_time_slot_NoSuchElementException.png
📝 Error log saved: debug_logs/session_20251205_143022/20251205_143045_reserve_time_slot_error.json

# 2. Open the HTML file
# 3. Search for the button text (e.g., "Evening", "Reserve", "Save")
# 4. Find the new selector
# 5. Update main.py with the new selector
```

## Adding Logging to New Functions

If you create new functions that interact with the driver, wrap them with try-except:

```python
def my_new_function(driver):
    """My new HEB automation function"""
    try:
        # Your code here
        element = driver.find_element(By.ID, "some-id")
        element.click()
    
    except Exception as e:
        logger.log_failure(
            driver=driver,
            function_name="my_new_function",
            error=e,
            additional_info={
                "step": "description of what failed",
                "custom_context": "any relevant info"
            }
        )
        raise
```

## Using the Decorator (Alternative)

You can also use the `@logged_driver_function` decorator:

```python
from utility.driver_logger import logged_driver_function

@logged_driver_function(logger)
def my_function(driver, some_arg):
    # Your code here
    # Automatically logs failures
    pass
```

## Manual Logging

You can also manually trigger logging at any point:

```python
# Just save HTML snapshot
logger.save_html_snapshot(driver, "function_name", "checkpoint")

# Just save screenshot
logger.save_screenshot(driver, "function_name", "checkpoint")

# Full failure logging
logger.log_failure(driver, "function_name", exception, {"context": "info"})
```

## Benefits

- **Faster Debugging**: No need to re-run the script and wait for it to fail again
- **Complete Context**: You see exactly what the page looked like
- **Historical Record**: Compare how the website has changed over time
- **Claude-Friendly**: HTML files are perfect for feeding to Claude for analysis and fixes
- **Automatic**: No need to remember to add logging - it's built into all functions

## Tips for Claude Debugging

When asking Claude to fix a broken function:

1. Attach the HTML file from `debug_logs/`
2. Attach the error JSON file
3. Specify which function failed
4. Ask Claude to find the new selectors and update the code

Example prompt:
> "The reserve_time_slot function failed. I've attached the HTML snapshot and error log. Can you find the new selectors for the 'Evening' time slots button and the 'Save' button, and update the function?"

## Configuration

### Change Log Directory

```python
logger = DriverLogger(log_dir="my_custom_logs")
```

### Disable Auto-Logging

Remove the try-except blocks from functions (not recommended).

### Keep Browser Open on Failure

The `main.py` already keeps the browser open if an error occurs (see the `finally` block), so you can manually inspect the page.

## .gitignore

Make sure `debug_logs/` is in your `.gitignore` to avoid committing large HTML files to git.

## Troubleshooting

**Problem**: Logger not saving files
- Check that the `debug_logs/` directory has write permissions
- Verify the logger is initialized before functions are called

**Problem**: HTML file is empty
- The page might not have loaded yet
- Add `random_time()` or `time.sleep()` before the operation

**Problem**: Too many log files
- Manually delete old session directories
- Or add a cleanup script to remove sessions older than X days
