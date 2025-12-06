# Debugging Process Summary

## Problem Statement
HEB frequently updates their website, causing automation functions to break. Previously, there was no efficient way to debug these issues without re-running the entire script and manually inspecting the page.

## Solution: Driver Logger

A comprehensive logging system that automatically captures:
- Full HTML page source
- Screenshots
- Detailed error information with stack traces
- Function-specific context

## Implementation

### Files Created/Modified:

1. **`utility/driver_logger.py`** - Core logger module
   - `DriverLogger` class for HTML/screenshot/error logging
   - `@logged_driver_function` decorator for automatic logging
   - Session-based directory organization

2. **`main.py`** - Updated all critical functions:
   - `reserve_time_slot()` - Wrapped with try-except + logging
   - `add_ingredient()` - Wrapped with try-except + logging
   - `clear_cart()` - Wrapped with try-except + logging
   - `login()` - Wrapped with try-except + logging
   - Main execution block - Wrapped with try-except + logging

3. **`docs/DRIVER_LOGGER_GUIDE.md`** - Complete documentation
   - How it works
   - Usage examples
   - Debugging workflow
   - Tips for Claude-assisted debugging

4. **`.gitignore`** - Added `debug_logs/` to prevent committing snapshots

5. **`README.md`** - Added reference to the Driver Logger Guide

## How It Works

### When a Function Fails:

```python
def reserve_time_slot(driver):
    try:
        # ... your automation code ...
        button = driver.find_element(By.XPATH, "...")
        button.click()
    except Exception as e:
        logger.log_failure(
            driver=driver,
            function_name="reserve_time_slot",
            error=e,
            additional_info={"step": "reserving time slot"}
        )
        raise
```

### Output:

```
debug_logs/
└── session_20251205_143022/
    ├── 20251205_143045_reserve_time_slot_NoSuchElementException.html
    ├── 20251205_143045_reserve_time_slot_NoSuchElementException.png
    └── 20251205_143045_reserve_time_slot_error.json
```

## Debugging Workflow

1. **Run the script** → It fails and automatically saves debug files
2. **Open HTML file** → See exactly what the page looked like
3. **Find new selectors** → Search for element IDs, classes, or text
4. **Update function** → Replace old XPath/CSS selectors with new ones
5. **Test again** → Repeat if needed

## Claude Integration

The HTML snapshots are perfect for Claude debugging:

**Example Prompt:**
> "The `reserve_time_slot` function is failing to find the 'Evening' time slots. I've attached the HTML snapshot. Can you:
> 1. Find where the 'Evening' text appears in the HTML
> 2. Determine the correct XPath or CSS selector
> 3. Update the function to use the new selector
> 
> Attached: `20251205_143045_reserve_time_slot_NoSuchElementException.html`"

## Benefits

✅ **No re-running needed** - HTML is captured the first time it fails
✅ **Complete context** - See the exact page state when it failed
✅ **Automatic** - All functions are already instrumented
✅ **Timestamped** - Track when HEB made changes
✅ **Claude-friendly** - HTML files are perfect LLM input
✅ **Function-specific context** - Know which ingredient failed, which step, etc.

## Future Enhancements

### Potential Improvements:
- Add automatic cleanup of logs older than 30 days
- Create a viewer script to browse debug sessions
- Add comparison tool to show HTML diffs between sessions
- Integrate with automated testing to detect HEB changes early
- Add success logging (optional) to track working selectors

### For `reserve_time_slot` Specifically:
Once working, consider:
- Adding a `checkout()` function with similar error logging
- Creating a `verify_reservation()` function to confirm the slot was saved
- Adding retry logic with different selectors if the first attempt fails

## Next Steps

1. **Test the logger** - Run `main.py` and intentionally cause a failure
2. **Review debug output** - Examine the HTML/screenshot/error files
3. **Fix `reserve_time_slot`** - Use the HTML to find current selectors
4. **Implement `checkout()`** - Add the automated checkout function with logging

## Usage Example

```python
# The logger is already initialized in main.py
logger = DriverLogger(log_dir="debug_logs")

# All functions are already wrapped with logging
# Just run your script normally:
python main.py

# If it fails, check the console output for file paths:
# 📄 HTML snapshot saved: debug_logs/session_XXXXX/...
# 📸 Screenshot saved: debug_logs/session_XXXXX/...
# 📝 Error log saved: debug_logs/session_XXXXX/...
```

## Configuration

The logger is configured in `main.py`:

```python
# Change log directory:
logger = DriverLogger(log_dir="my_custom_logs")

# The logger is automatically used by all functions
# No additional configuration needed
```

## Maintenance

### Cleaning Old Logs:

```bash
# Delete logs older than 30 days (manual)
find debug_logs -type d -mtime +30 -exec rm -rf {} +

# Or create a cleanup script:
python utility/cleanup_logs.py --days 30
```

### Reviewing Logs:

```bash
# List all session directories
ls -lt debug_logs/

# Open the most recent HTML file
open debug_logs/session_*/**.html

# View error details
cat debug_logs/session_*/*_error.json | jq .
```

## Success Criteria

✅ Created comprehensive logging system  
✅ Wrapped all critical HEB automation functions  
✅ HTML snapshots capture full page on failure  
✅ Screenshots provide visual confirmation  
✅ Error logs include full context and stack traces  
✅ Documentation explains usage and debugging workflow  
✅ `.gitignore` prevents committing debug files  
✅ Ready for Claude-assisted debugging  

## Questions or Issues?

See `docs/DRIVER_LOGGER_GUIDE.md` for complete documentation.
