# Claude API Setup Instructions

## Overview
The project has been migrated from OpenAI's GPT to Anthropic's Claude Sonnet API.

## ⚠️ IMPORTANT: Virtual Environment
**ALWAYS activate the virtual environment before running any commands, scripts, or tests!**

```bash
# In WSL/Linux/Mac:
source venv/bin/activate

# In Windows PowerShell:
.\venv\Scripts\Activate.ps1

# In Windows Command Prompt:
.\venv\Scripts\activate.bat
```

You should see `(venv)` in your terminal prompt when the virtual environment is active.

## Configuration

### Option 1: Add to config.txt (Recommended)
The `config.txt` file now uses a labeled KEY=VALUE format. Add your Claude API key:

```
# Configuration File
# Lines starting with # are comments and will be ignored
# Format: KEY=VALUE

EMAIL=your-email@example.com
PASSWORD=your-password
OPENAI_ORG=your-openai-org-id
OPENAI_API_KEY=your-openai-key
CLAUDE_API_KEY=your-claude-api-key-here
MODE=test
```

The config file supports:
- Comments (lines starting with #)
- KEY=VALUE format
- Empty lines are ignored

### Program Mode (in config.txt)

The `MODE` key in `config.txt` controls how the program runs:

| Mode | Description |
|------|-------------|
| `test` | Adds ingredients to cart but does NOT checkout. Browser stays open for inspection. |
| `checkout_with_prompt` | Adds ingredients, reserves time slot, then prompts you before final checkout. |
| `auto_checkout` | Fully automated — adds ingredients, reserves slot, and completes checkout. **Will charge your payment method!** |

Example:
```
MODE=checkout_with_prompt
```

### Option 2: Environment Variable
Set the `ANTHROPIC_API_KEY` environment variable:

**Linux/Mac/WSL:**
```bash
export ANTHROPIC_API_KEY="your-api-key-here"
```

**Windows PowerShell:**
```powershell
$env:ANTHROPIC_API_KEY="your-api-key-here"
```

**Windows Command Prompt:**
```cmd
set ANTHROPIC_API_KEY=your-api-key-here
```

## Getting a Claude API Key

1. Go to [https://console.anthropic.com/](https://console.anthropic.com/)
2. Sign up or log in to your account
3. Navigate to API Keys section
4. Create a new API key
5. Copy the key and add it to your config.txt or environment variables

## Model Used

The code uses **Claude Sonnet 4** (`claude-sonnet-4-20250514`), which is:
- Fast and efficient
- Great for structured data extraction
- Cost-effective for ingredient parsing tasks

## Changes Made

1. **chatgpt3.py** - Replaced OpenAI implementation with Anthropic Claude
2. **requirements.txt** - Added `anthropic>=0.75.0` package
3. Function signatures remain the same, so no changes needed in `recipe_grabber.py`

## Testing

**All testing scripts are located in the `testing/` directory.**

To run tests:

```bash
# First, activate virtual environment (REQUIRED!)
source venv/bin/activate

# Then run any test script from the testing directory
python testing/test_recipe_grabber.py
python testing/test_connection.py
python testing/test_database.py
python main.py 
```

**Note:** All test scripts should be placed in the `testing/` directory for consistency and organization.

## Testing Cycle for Main Program

**💡 NEW:** The program now has improved error handling with automatic pause and debug capture when errors occur. See [docs/SOFT_STOP_GUIDE.md](docs/SOFT_STOP_GUIDE.md) for details.

### Test Mode Overview

Test mode (`MODE=test` in `config.txt`) runs the full automation pipeline **without completing checkout**. It is the safest way to verify the program works end-to-end. The flow is:

1. **Login** — Authenticates with HEB using credentials from `config.txt`, handling email verification and passkey prompts automatically.
2. **Clear cart** — Navigates to the cart and removes any existing items.
3. **Reserve time slot** — Opens the reservation modal, selects a free curbside pickup date and timeslot.
4. **Add ingredients** — Searches for each ingredient on heb.com and clicks "Add to cart". Ingredients tagged as `vegetable` or `fruit` are prefixed with "organic".
5. **Stop** — Prints a completion message and **keeps the browser open** so you can manually inspect the cart contents. Press Enter in the terminal to close the browser.

All steps are wrapped with `self_healing_call`, which uses the Claude API to automatically rewrite broken Selenium functions on failure (up to 3 retries per function). Screenshots and page HTML are sent to Claude for context. Rewritten functions are saved to `updated_functions/` for later review.

No payment is processed. No order is placed.

When testing the main program with web scraping functionality, follow this systematic debugging cycle:

### 1. Run the Program in Test Mode

```bash
# Activate virtual environment first (REQUIRED!)
source venv/bin/activate

# Ensure MODE is set to 'test' in config.txt:
# MODE=test

# Run main program
python main.py
```

### 2. Watch Terminal Output Closely

Monitor the terminal for:
- Selenium/WebDriver initialization messages
- Login attempts and status
- Page navigation events
- Element detection messages
- Error messages or exceptions
- Stack traces

**Pay special attention to:**
- NoSuchElementException errors (element not found)
- TimeoutException errors (page load or element wait timeout)
- WebDriverException errors (browser/driver issues)
- Any logged warnings or error messages

### 3. Check the Debug Logs

**Note:** Debug logs are only created when running `python main.py`. They are NOT created when running other test scripts like `test_recipe_grabber.py` or `test_database.py`.

Navigate to the `debug_logs/` directory:

```bash
cd debug_logs/
ls -lt  # List sessions sorted by time (newest first)
```

Find the latest session directory (format: `session_YYYYMMDD_HHMMSS/`):

```bash
# Example: session_20251205_172111/
cd session_20251205_172111/
ls -la
```

### 4. Review Debug Artifacts

Each session directory contains timestamped debug files:

**Screenshot Files (.png):**
```bash
# View screenshot to see what the browser actually saw
# Format: YYYYMMDD_HHMMSS_MICROSECONDS_<context>_<error_type>.png
# Example: 20251205_163148_880746_login_NoSuchElementException.png
```

**HTML Source Files (.html):**
```bash
# Open HTML file to inspect the page structure
# This shows the actual HTML elements available at time of error
# Format: YYYYMMDD_HHMMSS_MICROSECONDS_<context>_<error_type>.html
```

**Error Information:**
- Error type is embedded in the filename (e.g., `NoSuchElementException`)
- Context label indicates which operation was being performed (e.g., `login`, `navigation`, `scraping`)
- Timestamp helps correlate with terminal output

### 5. Analyze and Make Changes

Based on the debug artifacts:

1. **Compare Screenshot vs. Expected Page:**
   - Is the page loaded correctly?
   - Are expected elements visible?
   - Did the page navigate to the right location?

2. **Inspect HTML Source:**
   - Are the selectors correct?
   - Have element IDs or classes changed?
   - Are elements present but hidden/disabled?
   - Check for dynamic content loading

3. **Common Issues and Fixes:**

   **NoSuchElementException:**
   - Element selector is wrong → Update selector in code
   - Element not loaded yet → Increase wait time
   - Page structure changed → Inspect HTML and update selectors

   **TimeoutException:**
   - Slow page load → Increase timeout value
   - Wrong page loaded → Check navigation logic
   - Element never appears → Verify page flow

   **Login/Authentication Issues:**
   - Check credentials in config.txt
   - Look for CAPTCHA or bot detection in screenshot
   - Verify login form selectors in HTML

4. **Make Code Changes:**
   - Update selectors in `recipe_grabber.py` or relevant module
   - Adjust wait times in WebDriver configuration
   - Add additional error handling
   - Update login flow if needed

### 6. Iterate

Repeat the testing cycle:
1. Make changes based on analysis
2. Run program with test flag again
3. Monitor terminal output
4. Check new debug logs
5. Verify the issue is resolved

### Example Complete Cycle

```bash
# 1. Set MODE to 'test' in main.py, then run
python main.py

# 2. (Watch terminal output for errors)

# 3. Navigate to latest debug logs
cd debug_logs/
cd $(ls -t | head -1)  # Go to most recent session

# 4. Review files
ls -la
# View screenshot (use your preferred image viewer)
# Open HTML in browser or text editor

# 5. Analyze and identify issue
# Example: Found that button ID changed from "submit-btn" to "submit-button"

# 6. Make changes in code
# Update the selector in recipe_grabber.py

# 7. Test again
cd ../..  # Back to project root
python main.py
```

### Pro Tips

- **Keep multiple terminal windows open:** One for running the program, one for navigating debug logs
- **Use a diff tool:** Compare HTML files between working and broken sessions
- **Check browser version:** Ensure Chrome/ChromeDriver versions are compatible
- **Enable verbose logging:** Set logging level to DEBUG for more detailed output
- **Save working sessions:** Keep debug logs from successful runs for comparison

