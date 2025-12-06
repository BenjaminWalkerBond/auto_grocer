# Time Slot Reservation Fix

## Date: December 5, 2025

## Problem
The `reserve_time_slot()` function was failing because it was looking for a "Save" button, but the actual HTML contains a button with the text "Select this time".

## Root Cause Analysis

Based on the actual HEB HTML structure provided, the issues were:

1. **Wrong button text**: Function searched for "Save" but button says "Select this time"
2. **Wrong selector**: Used generic XPath text search instead of the stable `data-qe-id="fulfillmentSchedule"` attribute
3. **Button state**: The button is initially disabled and only becomes enabled after a timeslot radio button is selected
4. **No wait condition**: Function didn't wait for the button to become clickable

## HTML Structure (Key Elements)

```html
<!-- Timeslot radio button (example from Morning section) -->
<label class="Timeslot_label__DGNpk Timeslot_free__7Anzs focusWithinOutline" 
       data-qe-id="timeslotButton-false" 
       for="AevuM1yUZ4CBgUp4zzP5EwAAAAC0T4QZAAABmvO_bIA">
    <input class="Timeslot_radioInput__CLPyS" 
           aria-label="Time slot available from 7:00am to 7:30am for Free. Click to select this timeslot." 
           type="radio" 
           id="AevuM1yUZ4CBgUp4zzP5EwAAAAC0T4QZAAABmvO_bIA" 
           name="timeslot-Morning">
    <div class="Timeslot_timePriceContainer__Ouv5l">
        <div class="Timeslot_time__qygZ1">7:00am - 7:30am</div>
        <div class="Timeslot_price__nvTcI">Free</div>
    </div>
</label>

<!-- Submit button (initially disabled) -->
<button type="button" 
        data-qe-id="fulfillmentSchedule" 
        disabled="" 
        class="focusVisibleOutline Button_button__ytBI_ Button_default__a3TQR Button_base__gqVu1 Button_primaryDefault__0_x_e ReservationFooter_saveButton__R_k_z">
    <span class="ButtonLabel_buttonText__1w7YM">Select this time</span>
</button>
```

## Solution Implemented

### 1. Updated Button Selector
**Before:**
```python
search_word = "Save"
xpath = f"//*[contains(text(), '{search_word}')]"
confirm_reserve = driver.find_element(By.XPATH, xpath)
```

**After:**
```python
wait = WebDriverWait(driver, 10)
confirm_reserve = wait.until(EC.element_to_be_clickable(
    (By.CSS_SELECTOR, '[data-qe-id="fulfillmentSchedule"]')
))
```

### 2. Added Wait Condition
The new implementation:
- Waits for the button to become clickable (not disabled)
- Uses `WebDriverWait` with `EC.element_to_be_clickable()`
- Automatically waits up to 10 seconds for the button state to change

### 3. Enhanced Error Handling
```python
try:
    confirm_reserve.click()
except:
    print("  ℹ️  Normal click failed, using JavaScript click...")
    driver.execute_script("arguments[0].click();", confirm_reserve)
```

### 4. Improved Modal Closing
```python
try:
    close_modal_button = driver.find_element(By.CSS_SELECTOR, '[aria-label="Close Modal"]')
    try:
        close_modal_button.click()
        print("  ✓ Closed reservation modal")
    except:
        print("  ℹ️  Normal click failed on modal, using JavaScript click...")
        driver.execute_script("arguments[0].click();", close_modal_button)
        print("  ✓ Closed reservation modal")
except:
    print("  ℹ️  Modal already closed or not found")
```

## Code Changes

### File: `main.py`

#### Added Imports (lines 7-8):
```python
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
```

#### Updated `reserve_time_slot()` function (lines ~386-407):
```python
for time in evening_slots_container:
    if "Free" in time.get_attribute("aria-label"):
        print("found a free time!")
        # Click the label to select the radio button
        time.click()
        random_time()
        break
    print(time.accessible_name)

# Wait for the "Select this time" button to become enabled
print("  ⏳ Waiting for 'Select this time' button to be enabled...")
wait = WebDriverWait(driver, 10)
confirm_reserve = wait.until(EC.element_to_be_clickable(
    (By.CSS_SELECTOR, '[data-qe-id="fulfillmentSchedule"]')
))

print("  ✓ Clicking 'Select this time' button...")
try:
    confirm_reserve.click()
except:
    print("  ℹ️  Normal click failed, using JavaScript click...")
    driver.execute_script("arguments[0].click();", confirm_reserve)

random_time()

# Close the modal with fallback to JavaScript click
try:
    close_modal_button = driver.find_element(By.CSS_SELECTOR, '[aria-label="Close Modal"]')
    try:
        close_modal_button.click()
        print("  ✓ Closed reservation modal")
    except:
        print("  ℹ️  Normal click failed on modal, using JavaScript click...")
        driver.execute_script("arguments[0].click();", close_modal_button)
        print("  ✓ Closed reservation modal")
except:
    print("  ℹ️  Modal already closed or not found")
```

## Benefits

1. **More Reliable**: Uses stable `data-qe-id` test attribute instead of fragile text matching
2. **Proper Timing**: Waits for button to become enabled instead of immediate click attempt
3. **Better UX**: Informative console messages show progress through reservation flow
4. **Robust**: Multiple fallback strategies (Selenium click → JavaScript click)
5. **Defensive**: Handles case where modal is already closed

## Testing Recommendations

1. Run in test mode to verify timeslot reservation
2. Check console output for:
   - "found a free time!" message
   - "⏳ Waiting for 'Select this time' button to be enabled..."
   - "✓ Clicking 'Select this time' button..."
   - "✓ Closed reservation modal"
3. Verify the selected timeslot appears in the cart header
4. Confirm no errors are logged to `debug_logs/`

## Related Files
- `main.py` - Contains the fixed `reserve_time_slot()` function
- `CLAUDE_SETUP.md` - Test execution guide
- `SOFT_STOP_GUIDE.md` - Debugging guide for pausing execution

## Key Selector Reference

| Element | Selector | Type |
|---------|----------|------|
| Reservation Modal | `[data-qe-id="chooseReservationTime"]` | CSS (button) |
| Timeslot (Free) | `[aria-label*="Free"]` | Attribute contains |
| Submit Button | `[data-qe-id="fulfillmentSchedule"]` | CSS (data-qe-id) |
| Close Modal | `[aria-label="Close Modal"]` | CSS (aria-label) |

## Notes
- The button is disabled (`disabled=""`) until a timeslot is selected
- Timeslots are grouped by time of day: Morning, Afternoon, Evening
- Free timeslots show "Free" in the price area
- The function currently selects from Evening slots only
