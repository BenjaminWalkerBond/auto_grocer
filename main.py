
import selenium
import undetected_chromedriver as uc
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.common.exceptions import NoSuchElementException
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC    

from classes.IngredientList import IngredientList
from classes.Ingredient import Ingredient
from utility.read_email import fetch_verification_code
from utility.driver_logger import DriverLogger, logged_driver_function

import os
import time
import random
import signal
import sys
from recipe_grabber import populate_ingredient_list
from recipe_grabber import clean_ingredient
from utility.self_healing import self_healing_call, dismiss_modals
from utility.graphql_auth import export_selenium_session_to_authjson
from utility.graphql_cart import graphql_cart_sync
from utility.graphql_store import select_store_interactive, update_config_value

# Initialize the logger globally
logger = DriverLogger(log_dir="debug_logs")

# Global variable to hold the driver for signal handling
_global_driver = None
_global_mode = None
_interrupted = False
# Default location used to prefill the store-search prompt (set from config).
_STORE_SEARCH_ADDRESS = ""


def signal_handler(signum, frame):
    """
    Handle Ctrl+C (SIGINT) by capturing browser state and stopping the main loop.
    Chrome runs in its own process group, so it stays alive.
    """
    global _global_driver, _global_mode, _interrupted
    _interrupted = True
    
    print("\n\n⚠️  Interrupt signal received (Ctrl+C)")
    print("📸 Attempting to capture browser state immediately...")
    
    if _global_driver:
        try:
            logger.save_screenshot(_global_driver, "interrupted", _global_mode or "unknown")
            print(f"✓ Screenshot saved to: {logger.session_dir}")
        except Exception as e:
            print(f"⚠️  Could not capture screenshot in signal handler: {e}")
        
        try:
            logger.save_html_snapshot(_global_driver, "interrupted", _global_mode or "unknown")
            print(f"✓ HTML snapshot saved to: {logger.session_dir}")
        except Exception as e:
            print(f"⚠️  Could not capture HTML in signal handler: {e}")
    
    print("\n⏸️  Browser will remain open for inspection.")
    print("Press Ctrl+C again to force quit, or close the terminal to exit.\n")
    
    signal.signal(signal.SIGINT, signal.SIG_DFL)  # Reset to default handler for second Ctrl+C


def check_exists_by_xpath(xpath,driver):
    try:
        driver.find_element(By.XPATH, xpath)
    except NoSuchElementException:
        return False
    return True
def random_time():
    """Sleep for a random amount of time to simulate human behavior"""
    time.sleep(random.uniform(2.0, 3.5))

def human_like_delay():
    """Very short random delay to simulate human reaction time"""
    time.sleep(random.uniform(0.3, 0.8))

def scroll_to_element(driver, element):
    """Scroll to an element in a human-like way"""
    try:
        # Scroll element into view
        driver.execute_script("arguments[0].scrollIntoView({behavior: 'smooth', block: 'center'});", element)
        human_like_delay()
    except Exception as e:
        print(f"    ⚠️  Could not scroll to element: {e}")

def move_mouse_to_element(driver, element):
    """Simulate moving mouse to an element"""
    try:
        from selenium.webdriver.common.action_chains import ActionChains
        actions = ActionChains(driver)
        actions.move_to_element(element).perform()
        human_like_delay()
    except Exception as e:
        print(f"    ⚠️  Could not move mouse: {e}")

def human_like_typing(element, text):
    """Type text with random delays between keystrokes"""
    for char in text:
        element.send_keys(char)
        time.sleep(random.uniform(0.05, 0.15))
    human_like_delay()
def add_ingredient(ingredient, driver):
    """Add an ingredient to the HEB cart with human-like behavior"""
    max_retries = 3
    retry_count = 0
    
    while retry_count < max_retries:
        try:
            # Make sure we're on a page where the search bar is interactable
            # (not blocked by a modal or stuck on cart page)
            if "/cart" in driver.current_url:
                print("    📍 On cart page, navigating to homepage for search...")
                driver.get("https://www.heb.com/")
                time.sleep(random.uniform(2.0, 3.0))
            
            # Close any open modals that might be blocking
            try:
                modal_close = driver.find_element(By.CSS_SELECTOR, '[data-qe-id="modalClose"]')
                driver.execute_script("arguments[0].click();", modal_close)
                time.sleep(1)
                print("    ℹ️  Closed a blocking modal")
            except:
                pass
            
            # Find search bar and wait for it to be interactable
            wait = WebDriverWait(driver, 10)
            search_bar = wait.until(EC.element_to_be_clickable((By.ID, "search-input")))
            
            # Human-like behavior: scroll to search bar first
            scroll_to_element(driver, search_bar)
            
            # Clear the search bar properly - use multiple methods to ensure it's cleared
            search_bar.clear()
            human_like_delay()
            
            # Also select all and delete as backup
            search_bar.send_keys(Keys.CONTROL + "a")
            human_like_delay()
            search_bar.send_keys(Keys.DELETE)
            human_like_delay()
            
            # Enter the search term with human-like typing
            search_term = ""
            if ingredient.get_tag() == "vegetable" or ingredient.get_tag() == "fruit":
                search_term = f"organic {ingredient.get_name()}"
            else:
                search_term = ingredient.get_name()
            
            print(f"    🔍 Searching for: {search_term}")
            human_like_typing(search_bar, search_term)
            
            # Random delay before submitting
            time.sleep(random.uniform(0.5, 1.0))
            
            # Submit search
            search_bar.send_keys(Keys.ENTER)
            
            # Wait for results to load with random human-like delay
            time.sleep(random.uniform(2.5, 4.0))
            
            # Try multiple selectors for the add to cart button
            # Based on actual HEB button structure: data-qe-id="addToCart"
            button_selectors = [
                '//button[@data-qe-id="addToCart"]',  # Most reliable - data attribute
                '//button[contains(@class, "AddByQuantityButton")]',  # Specific button class
                '//button[contains(., "Add to cart")]',  # Contains text "Add to cart"
                '//button[@type="button" and contains(@class, "Button_button")]//div[contains(text(), "Add to cart")]/..',  # Full path to button
                '//*[@id="search_product_grid"]//button[@data-qe-id="addToCart"]',  # Within search results
                '//button[@data-component="button" and contains(., "Add to cart")]'  # Data component attribute
            ]
            
            add_to_cart_button = None
            for i, selector in enumerate(button_selectors):
                try:
                    if check_exists_by_xpath(selector, driver):
                        add_to_cart_button = driver.find_element(By.XPATH, selector)
                        print(f"    ✓ Found button using selector #{i+1}")
                        break
                except Exception as e:
                    continue
            
            if add_to_cart_button:
                print(f"    ✓ Found add to cart button (attempt {retry_count + 1}/{max_retries})")
                
                # Human-like behavior: scroll to button and move mouse
                scroll_to_element(driver, add_to_cart_button)
                move_mouse_to_element(driver, add_to_cart_button)
                
                # Random small delay before clicking
                time.sleep(random.uniform(0.3, 0.7))
                
                # Try multiple click methods in order
                click_successful = False
                
                # Method 1: Regular Selenium click
                try:
                    add_to_cart_button.click()
                    click_successful = True
                    print(f"    ✓ Clicked with Selenium")
                except Exception as e:
                    print(f"    ⚠️  Selenium click failed: {e}")
                
                # Method 2: ActionChains click (more human-like)
                if not click_successful:
                    try:
                        from selenium.webdriver.common.action_chains import ActionChains
                        actions = ActionChains(driver)
                        actions.move_to_element(add_to_cart_button).pause(random.uniform(0.2, 0.5)).click().perform()
                        click_successful = True
                        print(f"    ✓ Clicked with ActionChains")
                    except Exception as e:
                        print(f"    ⚠️  ActionChains click failed: {e}")
                
                # Method 3: JavaScript click (last resort)
                if not click_successful:
                    try:
                        driver.execute_script("arguments[0].click();", add_to_cart_button)
                        click_successful = True
                        print(f"    ✓ Clicked with JavaScript")
                    except Exception as e:
                        print(f"    ⚠️  JavaScript click failed: {e}")
                
                if click_successful:
                    # Wait to see if item was added
                    time.sleep(random.uniform(1.5, 2.5))
                    print(f"    ✅ Added {ingredient.get_name()} to cart")
                    return 1
                else:
                    print(f"    ⚠️  All click methods failed")
                    retry_count += 1
                    if retry_count < max_retries:
                        wait_time = random.uniform(3, 5)
                        print(f"    ⏳ Waiting {wait_time:.1f}s before retry {retry_count + 1}/{max_retries}")
                        time.sleep(wait_time)
                        continue
            else:
                print(f"    ⚠️  Add to cart button not found for: {ingredient.get_name()} (attempt {retry_count + 1}/{max_retries})")
                retry_count += 1
                
                if retry_count < max_retries:
                    wait_time = random.uniform(2, 4)
                    print(f"    ⏳ Waiting {wait_time:.1f}s before retry {retry_count + 1}/{max_retries}")
                    time.sleep(wait_time)
                    # Try scrolling down to see if more results load
                    driver.execute_script("window.scrollBy(0, 300);")
                    time.sleep(random.uniform(1, 2))
                    continue
        
        except Exception as e:
            print(f"    ❌ Error on attempt {retry_count + 1}/{max_retries}: {e}")
            retry_count += 1
            if retry_count < max_retries:
                time.sleep(random.uniform(2, 4))
                continue
    
    # All retries exhausted - capture debug info and pause
    print(f"\n    ❌ Failed to add {ingredient.get_name()} after {max_retries} attempts")
    
    # Capture screenshot and HTML for debugging
    try:
        logger.save_screenshot(driver, f"button_not_found_{ingredient.get_name()}", _global_mode or "unknown")
        logger.save_html_snapshot(driver, f"button_not_found_{ingredient.get_name()}", _global_mode or "unknown")
        print(f"    📸 Debug screenshot saved to: {logger.session_dir}")
    except Exception as e:
        print(f"    ⚠️  Could not save debug info: {e}")
    
    # Pause and ask user what to do
    print(f"\n    ⏸️  PAUSED - Browser is still open for inspection")
    print(f"    Options:")
    print(f"      [Enter] - Skip this ingredient and continue")
    print(f"      [r] - Retry this ingredient")
    print(f"      [q] - Quit the program")
    choice = input(f"    Your choice: ").strip().lower()
    
    if choice == 'q':
        print("\n    🛑 User requested quit")
        driver.quit()
        exit(0)
    elif choice == 'r':
        print(f"    🔄 Retrying {ingredient.get_name()}...")
        return add_ingredient(ingredient, driver)  # Recursive retry
    else:
        print(f"    ⏭️  Skipping {ingredient.get_name()}")
        return 0

def clear_cart(driver):
    """Clear all items from the HEB shopping cart"""
    try:
        # First, close any modal that might be intercepting clicks
        try:
            close_button = driver.find_element(By.CSS_SELECTOR, "button[aria-label='close']")
            if close_button.is_displayed():
                close_button.click()
                random_time()
        except:
            pass
        
        # Look for the "Empty cart" button directly on the cart page
        from selenium.webdriver.support.wait import WebDriverWait
        from selenium.webdriver.support import expected_conditions as EC
        wait = WebDriverWait(driver, 10)
        
        try:
            # Wait for and click the empty cart button using the visible text
            empty_cart_button = wait.until(EC.element_to_be_clickable((By.XPATH, "//button[contains(text(), 'Empty cart')]")))
            empty_cart_button.click()
            random_time()
            
            # Confirm the empty cart action
            confirm_empty = wait.until(EC.element_to_be_clickable((By.XPATH, "//button[contains(text(), 'Empty')]")))
            confirm_empty.click()
            random_time()
            
            # Navigate back to home
            home_link = driver.find_element(By.CSS_SELECTOR, "a[href='/']")
            home_link.click()
            random_time()
            
        except Exception as e:
            # If we can't find empty cart button, the cart might already be empty
            return 0
            
    except Exception as e:
        logger.log_failure(
            driver=driver,
            function_name="clear_cart",
            error=e,
            additional_info={"step": "clearing cart"}
        )
        raise

def change_store_via_ui(driver, search_text):
    """Drive HEB's store-change UI to trigger StoreSearch + SelectPickupFulfillment.

    This is used by the ``update_graphql_hashes`` capture mode so the GraphQL
    requests for store search and store change appear in the browser's network
    log (and their persisted-query hashes can be captured). It does NOT need to
    permanently change the store — it only needs to exercise those two requests.

    Args:
        driver: Selenium WebDriver instance.
        search_text: A zip code or city/state to search stores by.

    Returns:
        True if the store search/selection UI was exercised.
    """
    wait = WebDriverWait(driver, 15)

    # STEP 1: Open the fulfillment / store selector from the header.
    print("  Step 1: Opening the store/fulfillment selector...")
    driver.get("https://www.heb.com/")
    random_time()

    opener_selectors = [
        (By.CSS_SELECTOR, '[data-qe-id="headerFulfillmentButton"]'),
        (By.CSS_SELECTOR, '[data-qe-id="fulfillmentSelector"]'),
        (By.XPATH, '//button[contains(., "Curbside") or contains(., "Pickup") or contains(., "store")]'),
        (By.XPATH, '//button[contains(@aria-label, "store") or contains(@aria-label, "fulfillment")]'),
    ]
    opened = False
    for by, sel in opener_selectors:
        try:
            btn = wait.until(EC.element_to_be_clickable((by, sel)))
            driver.execute_script("arguments[0].click();", btn)
            opened = True
            print(f"    ✓ Opened selector via {sel}")
            break
        except Exception:
            continue
    if not opened:
        raise Exception(
            "Could not find the store/fulfillment selector button. "
            "The header layout may have changed."
        )
    random_time()

    # STEP 2: Find a "change store" affordance if present.
    change_selectors = [
        (By.XPATH, '//button[contains(., "Change store") or contains(., "Change my store")]'),
        (By.XPATH, '//a[contains(., "Change store")]'),
        (By.XPATH, '//button[contains(., "Find a store") or contains(., "store near")]'),
    ]
    for by, sel in change_selectors:
        try:
            el = driver.find_element(by, sel)
            driver.execute_script("arguments[0].click();", el)
            print(f"    ✓ Clicked change-store via {sel}")
            random_time()
            break
        except Exception:
            continue

    # STEP 3: Type the search text into the store search input (fires StoreSearch).
    print("  Step 3: Searching stores by location...")
    
    # The modal is open with a visible search input
    # Based on the HTML, look for input fields within the dialog
    search_input = None
    
    # Try to find the search input within the modal dialog
    try:
        # Wait for the modal to be present
        time.sleep(1)
        
        # Try various selectors for the store search input
        input_selectors = [
            '//div[@role="dialog"]//input[@type="text"]',
            '//div[@role="dialog"]//input[@placeholder]',
            '//input[contains(@placeholder, "address")]',
            '//input[contains(@placeholder, "zip")]',
            '//input[contains(@placeholder, "city")]',
        ]
        
        for sel in input_selectors:
            try:
                search_input = wait.until(EC.presence_of_element_located((By.XPATH, sel)))
                if search_input.is_displayed():
                    print(f"    ✓ Found store search input via {sel}")
                    break
                else:
                    search_input = None
            except Exception:
                continue
                
    except Exception:
        pass

    if search_input is None:
        raise Exception(
            "Could not find a dedicated store-search input. The store/"
            "fulfillment modal may not have opened (refusing to type into the "
            "global product-search box)."
        )

    search_input.clear()
    human_like_typing(search_input, str(search_text))
    time.sleep(random.uniform(0.5, 1.0))
    search_input.send_keys(Keys.ENTER)
    random_time()
    random_time()

    # STEP 4: Select the first store result (fires SelectPickupFulfillment).
    print("  Step 4: Selecting the first store result...")
    select_selectors = [
        (By.XPATH, '//button[contains(., "Selected Store")]'),
        (By.XPATH, '//button[contains(., "Select Store")]'),
        (By.XPATH, '//button[contains(., "Make my store") or contains(., "Select") or contains(., "Shop this store")]'),
        (By.CSS_SELECTOR, '[data-qe-id="selectStoreButton"]'),
        (By.XPATH, '//button[contains(@aria-label, "Select") and contains(@aria-label, "store")]'),
    ]
    for by, sel in select_selectors:
        try:
            el = wait.until(EC.element_to_be_clickable((by, sel)))
            driver.execute_script("arguments[0].click();", el)
            print(f"    ✓ Selected a store via {sel}")
            random_time()
            return True
        except Exception:
            continue

    # Even if final selection failed, StoreSearch likely fired.
    print("    ⚠️  Could not click a store-select button; StoreSearch may still be captured.")
    return True

def reserve_time_slot(driver):
    """Reserve a curbside pickup time slot on HEB website.
    
    Updated to handle the modal-based date/time selection interface.
    The modal appears when clicking "Choose pickup time" button.
    """
    try:
        wait = WebDriverWait(driver, 15)

        # STEP 1: Navigate to cart if not already there
        print("  Step 1: Navigating to cart...")
        if "/cart" not in driver.current_url:
            driver.get("https://www.heb.com/cart/")
            random_time()

        # Check if time is already reserved
        if check_exists_by_xpath("//*[contains(text(), 'Change time')]", driver):
            print("  ✓ Time slot already reserved")
            return True

        # STEP 2: Wait for modal to be gone if it's blocking
        print("  Step 2: Waiting for any blocking modals to clear...")
        try:
            # Wait for modal cover to disappear if present
            WebDriverWait(driver, 10).until(
                EC.invisibility_of_element_located((By.CSS_SELECTOR, '.ModalContainers_modalCover__1tKfw, [data-component="modal-cover-container"]'))
            )
            time.sleep(1)
        except:
            # Modal cover not present or already gone
            pass

        # STEP 3: Click the 'Choose pickup time' button from the cart page
        print("  Step 3: Opening reservation modal...")
        try:
            # Wait for button to be clickable and not obscured
            reserve_button = wait.until(EC.element_to_be_clickable(
                (By.CSS_SELECTOR, 'button[data-qe-id="chooseReservationTime"], button[aria-label*="Choose reservation time"]')
            ))
            
            # Scroll button into view
            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", reserve_button)
            time.sleep(1)
            
            # Try to click
            try:
                reserve_button.click()
            except:
                # Use JavaScript click if regular click fails
                driver.execute_script("arguments[0].click();", reserve_button)
            
            print("    ✓ Clicked 'Choose pickup time' button")
        except:
            # Try alternative selectors
            try:
                reserve_button = wait.until(EC.element_to_be_clickable(
                    (By.XPATH, '//button[contains(., "Choose pickup time") or contains(., "Choose a time") or contains(@aria-label, "Choose")]')
                ))
                driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", reserve_button)
                time.sleep(1)
                driver.execute_script("arguments[0].click();", reserve_button)
                print("    ✓ Clicked 'Choose pickup time' button (fallback)")
            except:
                raise Exception("Could not find 'Choose pickup time' button")

        random_time()
        time.sleep(3)  # Wait for modal to fully load

        # STEP 4: Ensure Curbside tab is selected
        print("  Step 4: Ensuring Curbside tab is selected...")
        try:
            curbside_tabs = driver.find_elements(By.XPATH, '//button[contains(text(), "Curbside")] | //*[@role="tab" and contains(text(), "Curbside")]')
            for tab in curbside_tabs:
                if tab.get_attribute("aria-selected") != "true":
                    tab.click()
                    random_time()
                    print("    ✓ Selected Curbside tab")
                else:
                    print("    ✓ Curbside tab already selected")
                break
        except Exception as e:
            print(f"    ⚠️  Could not check Curbside tab: {e}")

        time.sleep(2)

        # STEP 4.5: Select a delivery tier (new tiered timeslot UI).
        # HEB's refreshed reservation modal (variant
        # 'dsweb-3931-timeslot-refresh-sidebar-layout') first shows summary
        # buttons for each fee tier ("Under 2 hours", "2-4 hours", "Scheduled")
        # instead of a date grid. The date/time options only appear AFTER a tier
        # is clicked. Prefer the free "Scheduled" tier, then fall back to the
        # cheapest available tier. If no tier buttons exist, the account is
        # already on the old grid layout and we skip straight to date selection.
        print("  Step 4.5: Selecting a delivery tier...")
        try:
            tier_buttons = driver.find_elements(
                By.CSS_SELECTOR, 'button[class*="TimeslotSummary_button"]'
            )
            # Fallback: match by the aria-label pattern HEB uses on tier buttons.
            if not tier_buttons:
                tier_buttons = driver.find_elements(
                    By.XPATH, '//button[contains(@aria-label, "time slots for")]'
                )

            visible_tiers = [b for b in tier_buttons if b.is_displayed()]
            if not visible_tiers:
                print("    ℹ️  No tier buttons found; assuming legacy date-grid layout.")
            else:
                # Prefer the free "Scheduled" tier.
                preferred = None
                for b in visible_tiers:
                    label = (b.get_attribute("aria-label") or "")
                    if "Scheduled" in label or "for Free" in label:
                        preferred = b
                        break
                target = preferred or visible_tiers[-1]
                label = (target.get_attribute("aria-label") or "tier").strip()
                driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", target)
                time.sleep(1)
                try:
                    target.click()
                except Exception:
                    driver.execute_script("arguments[0].click();", target)
                print(f"    ✓ Selected delivery tier: {label[:60]}")
                random_time()
                time.sleep(2)
        except Exception as e:
            print(f"    ⚠️  Could not select a delivery tier: {e}")

        # STEP 5: Select a date
        print("  Step 5: Selecting a date...")
        date_buttons = []
        
        # Try different possible selectors
        selectors = [
            'button[id^="date-button-"]',
            'input[type="radio"][name*="date"]',
            'button[aria-label*="date"]',
            'label[for^="date-button-"]',
            '[role="button"][id*="date"]',
        ]
        
        for selector in selectors:
            date_buttons = driver.find_elements(By.CSS_SELECTOR, selector)
            if date_buttons:
                print(f"    Found {len(date_buttons)} date options using selector: {selector}")
                break
        
        if not date_buttons:
            # Fallback: look for any clickable elements in the modal that might be dates
            date_buttons = driver.find_elements(By.XPATH, 
                '//button[contains(@class, "date") or contains(@class, "Date")] | '
                '//div[contains(@class, "date") or contains(@class, "Date")]//button'
            )
            if date_buttons:
                print(f"    Found {len(date_buttons)} date options using fallback xpath")

        date_selected = False
        for btn in date_buttons:
            try:
                if not btn.is_displayed() or not btn.is_enabled():
                    continue
                
                text_content = btn.get_attribute('textContent') or btn.get_attribute('innerText') or ''
                aria_label = btn.get_attribute('aria-label') or ''
                
                if 'Free' in text_content or 'Free' in aria_label or btn.get_attribute('aria-disabled') != 'true':
                    try:
                        btn.click()
                    except:
                        driver.execute_script("arguments[0].click();", btn)
                    
                    print(f"    📅 Selected date: {text_content.strip()[:50] if text_content else aria_label[:50]}")
                    date_selected = True
                    random_time()
                    break
            except Exception as e:
                continue

        if not date_selected and date_buttons:
            try:
                date_buttons[0].click()
                print("    📅 Selected first available date")
                date_selected = True
                random_time()
            except:
                try:
                    driver.execute_script("arguments[0].click();", date_buttons[0])
                    print("    📅 Selected first available date (via JS)")
                    date_selected = True
                    random_time()
                except:
                    pass

        if not date_selected:
            raise Exception(
                f"No dates found or could not select date. Tried multiple selectors, found {len(date_buttons)} elements."
            )

        time.sleep(2)

        # STEP 6: Select a timeslot
        print("  Step 6: Selecting a timeslot...")
        timeslot_elements = []
        
        timeslot_selectors = [
            'input[type="radio"][data-qe-id="timeslotRadioButton"]',
            'input[type="radio"][name*="timeslot"]',
            'input[type="radio"][name*="time"]',
            'button[data-qe-id*="timeslot"]',
            '[role="radio"][aria-label*="time"]',
        ]
        
        for selector in timeslot_selectors:
            timeslot_elements = driver.find_elements(By.CSS_SELECTOR, selector)
            if timeslot_elements:
                print(f"    Found {len(timeslot_elements)} timeslot options using selector: {selector}")
                break
        
        if not timeslot_elements:
            timeslot_elements = driver.find_elements(By.XPATH,
                '//input[@type="radio"] | '
                '//button[contains(@class, "time") or contains(@class, "Time")] | '
                '//div[contains(@class, "timeslot")]//input[@type="radio"]'
            )
            if timeslot_elements:
                print(f"    Found {len(timeslot_elements)} timeslot options using fallback xpath")

        timeslot_selected = False
        for slot in timeslot_elements:
            try:
                disabled = slot.get_attribute('disabled') or slot.get_attribute('aria-disabled') == 'true'
                if disabled:
                    continue

                try:
                    driver.execute_script("arguments[0].click();", slot)
                except:
                    slot.click()
                
                aria_label = slot.get_attribute('aria-label') or ''
                slot_desc = aria_label[:60] if aria_label else "timeslot"
                print(f"    🕐 Selected timeslot: {slot_desc}")
                timeslot_selected = True
                break
            except Exception as e:
                continue

        if not timeslot_selected:
            raise Exception(
                f"No timeslots found or could not select. Found {len(timeslot_elements)} elements."
            )

        # STEP 7: Wait for selection to register
        print("  Step 7: Waiting for timeslot selection to register...")
        time.sleep(3)

        # Try to close the modal if it's still open
        try:
            close_btns = driver.find_elements(By.CSS_SELECTOR, 
                '[aria-label="close"], [aria-label="Close"], button[class*="close"], button[class*="Close"]'
            )
            for btn in close_btns:
                try:
                    if btn.is_displayed():
                        btn.click()
                        print("    ✓ Closed modal")
                        break
                except:
                    continue
        except:
            pass

        time.sleep(2)

        # Verify reservation
        if check_exists_by_xpath("//*[contains(text(), 'Change time')]", driver):
            print("  ✓ Time slot successfully reserved!")
        else:
            print("  ✓ Time slot reservation process completed (could not verify)")

        return True

    except Exception as e:
        logger.log_failure(
            driver=driver,
            function_name="reserve_time_slot",
            error=e,
            additional_info={
                "step": "reserving time slot",
                "url": driver.current_url
            }
        )
        # Try to close modal on failure
        try:
            close_buttons = driver.find_elements(By.CSS_SELECTOR, '[aria-label="close"], [aria-label="Close"]')
            for btn in close_buttons:
                try:
                    btn.click()
                    break
                except:
                    continue
        except:
            pass
        raise

def login(driver):
    """Login to HEB website using credentials from config.txt"""
    try:
        print("🔐 Starting login process...")
        
        # Get config
        current_directory = os.getcwd()
        filename = 'config.txt'
        config_file_path = os.path.join(current_directory, filename)
        
        if not os.path.exists(config_file_path):
            print(f"❌ {filename} not found in the current directory.")
            raise FileNotFoundError(f"{filename} not found")
        
        # Parse config file
        config_dict = {}
        with open(config_file_path, 'r') as file:
            for line in file:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                if '=' in line:
                    key, value = line.split('=', 1)
                    config_dict[key.strip()] = value.strip()
        
        email_address = config_dict.get('EMAIL', '')
        password = config_dict.get('PASSWORD', '')
        
        # STEP 1: Navigate to home page
        print("  Step 1: Navigating to HEB home page...")
        driver.get("https://www.heb.com/")
        random_time()
        
        # STEP 2: Click the cart icon (this triggers login for non-logged-in users)
        print("  Step 2: Clicking cart icon to trigger login...")
        wait = WebDriverWait(driver, 10)
        cart_button = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, 'a[data-qe-id="headerCartButtonDesktop"]')))
        cart_button.click()
        random_time()
        
        # STEP 3: Enter email on first login page
        print(f"  Step 3: Entering email...")
        email_input = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, 'input[type="email"]')))
        email_input.clear()
        email_input.send_keys(email_address)
        random_time()
        
        # Click Continue button
        print("  Step 4: Clicking 'Continue' button...")
        continue_button = wait.until(EC.element_to_be_clickable((By.XPATH, "//button[contains(text(), 'Continue')]")))
        continue_button.click()
        random_time()
        
        # STEP 4: Select "Enter password" option (radio button)
        print("  Step 5: Selecting 'Enter password' option...")
        # Click the "Enter password" radio button
        try:
            # Try clicking the radio button with id "credentials"
            password_radio = wait.until(EC.element_to_be_clickable((By.ID, "credentials")))
            password_radio.click()
        except:
            # Fallback: try clicking the label
            try:
                password_label = wait.until(EC.element_to_be_clickable((By.XPATH, "//label[@for='credentials']")))
                password_label.click()
            except:
                # Last resort: find all radio buttons and click the one with value="password"
                radio_buttons = driver.find_elements(By.CSS_SELECTOR, 'input[type="radio"][name="authType"]')
                for radio in radio_buttons:
                    if radio.get_attribute('value') == 'password':
                        driver.execute_script("arguments[0].click();", radio)
                        break
        random_time()
        
        # STEP 5: Enter password (field is already visible on the same page)
        print("  Step 6: Entering password...")
        # The password field might be type="text" or type="password", and has id="password-input"
        try:
            password_input = wait.until(EC.presence_of_element_located((By.ID, 'password-input')))
        except:
            # Fallback to CSS selector
            password_input = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, 'input[type="password"], input[name="password"]')))
        password_input.clear()
        password_input.send_keys(password)
        random_time()
        
        # STEP 6: Click Submit button
        print("  Step 7: Clicking 'Submit' button...")
        submit_button = wait.until(EC.element_to_be_clickable((By.XPATH, '//button[@type="submit"]')))
        submit_button.click()
        random_time()
        
        # STEP 7: Handle verification page if it appears
        print("  Step 8: Checking for verification requirement...")
        # Check if we're on the "Choose a way to verify" page
        if "Choose a way to verify" in driver.page_source or check_exists_by_xpath("//input[@name='channel']", driver):
            print("  ⚠️  Verification required - selecting email option...")
            
            # Ensure email radio button is selected (should be by default, but let's make sure)
            try:
                email_radio = wait.until(EC.presence_of_element_located((By.XPATH, "//input[@name='channel'][@value='email']")))
                if not email_radio.is_selected():
                    email_radio.click()
                    print("  ✓ Email option selected")
                else:
                    print("  ✓ Email option already selected")
            except:
                print("  ℹ️  Email option already selected (default)")
            random_time()
            
            # Click "Send code" button
            print("  📧 Clicking 'Send code' button...")
            send_code_button = wait.until(EC.element_to_be_clickable((By.XPATH, "//button[@type='submit' and contains(text(), 'Send code')]")))
            send_code_button.click()
            random_time()
            
            # Now wait for verification code input fields to appear
            print("  ⏳ Waiting for verification code input fields...")
            # Wait for the first input field to appear (they use separate fields for each digit)
            wait.until(EC.presence_of_element_located((By.NAME, "code_input_1")))
            
            # Fetch verification code from email
            print("  📨 Fetching verification code from email...")
            verification_code = fetch_verification_code()
            print(f"  ✓ Got verification code: {verification_code}")
            
            # Enter each digit of the verification code into separate input fields
            # The page has 6 separate input fields: code_input_1 through code_input_6
            if verification_code and len(verification_code) >= 6:
                print("  ⌨️  Entering verification code digits...")
                for i, digit in enumerate(verification_code[:6], start=1):
                    input_field = driver.find_element(By.NAME, f"code_input_{i}")
                    input_field.send_keys(digit)
                random_time()
            else:
                print(f"  ⚠️  Warning: Verification code has unexpected length: {len(verification_code) if verification_code else 0}")
            
            # Click submit/verify button
            print("  ✅ Submitting verification code...")
            verify_button = wait.until(EC.element_to_be_clickable((By.XPATH, "//button[@type='submit' and contains(text(), 'Verify')]")))
            verify_button.click()
            random_time()
        
        # STEP 8: Handle passkey registration prompt if it appears
        # After login/verification, HEB may prompt to set up a passkey
        # We skip this for now and continue with email verification
        print("  Step 9: Checking for passkey registration prompt...")
        try:
            # Check if we landed on the passkey registration page
            if "passkey_registration" in driver.current_url:
                print("  ⚠️  Passkey registration prompt detected - clicking 'Not now'...")
                not_now_button = wait.until(EC.element_to_be_clickable(
                    (By.XPATH, "//button[contains(text(), 'Not now')]")
                ))
                not_now_button.click()
                random_time()
                print("  ✓ Skipped passkey registration")
            else:
                print("  ✓ No passkey prompt detected")
        except Exception as e:
            print(f"  ℹ️  Passkey check: {e}")
        
        print("✓ Login successful!\n")
        return True
    
    except Exception as e:
        logger.log_failure(
            driver=driver,
            function_name="login",
            error=e,
            additional_info={
                "step": "HEB multi-step login process",
                "url": driver.current_url
            }
        )
        raise

def checkout(driver):
    """
    Complete the checkout process on HEB.
    This function should be called after cart is filled and time slot is reserved.

    Navigates to the cart and clicks the "Start checkout" button to reach the
    checkout screen. It does NOT place the order (no payment/confirmation step).
    """
    try:
        print("\n🛒 Starting checkout process...")

        # Navigate to cart
        driver.get("https://www.heb.com/cart/")
        random_time()

        wait = WebDriverWait(driver, 15)

        # The checkout button's identifier has changed over time. Try the known
        # selectors in order of likelihood.
        checkout_selectors = [
            (By.CSS_SELECTOR, '[data-qe-id="footerStartCheckout"]'),
            (By.CSS_SELECTOR, '[data-qe-id="proceedToCheckout"]'),
            (By.XPATH, '//button[contains(., "Start checkout") or contains(., "Proceed to checkout") or contains(., "Checkout")]'),
        ]

        checkout_button = None
        used = None
        for by, sel in checkout_selectors:
            try:
                checkout_button = wait.until(EC.element_to_be_clickable((by, sel)))
                used = sel
                break
            except Exception:
                continue

        if checkout_button is None:
            raise NoSuchElementException(
                "Could not find the checkout button on the cart page "
                "(tried footerStartCheckout, proceedToCheckout, and text match)."
            )

        scroll_to_element(driver, checkout_button)
        try:
            checkout_button.click()
        except Exception:
            driver.execute_script("arguments[0].click();", checkout_button)
        print(f"    ✓ Clicked checkout button ({used})")
        random_time()

        # TODO: Add payment and final confirmation steps here
        # For now, just confirm we're on the checkout page
        print("✓ Reached checkout page")

        return True

    except Exception as e:
        logger.log_failure(
            driver=driver,
            function_name="checkout",
            error=e,
            additional_info={"step": "checkout process"}
        )
        raise


def test_mode(driver, ingredient_list):
    """
    Test mode: Adds ingredients to cart but does NOT checkout.
    Keeps browser open for manual inspection.
    
    Args:
        driver: Selenium WebDriver instance
        ingredient_list: IngredientList object with ingredients to add
    """
    print("\n" + "="*60)
    print("🧪 RUNNING IN TEST MODE")
    print("="*60)
    print("This will add ingredients to cart but NOT checkout.")
    print("Browser will remain open for inspection.\n")
    
    try:
        # Login
        self_healing_call(login, driver, driver=driver)
        random_time()
        driver.maximize_window()
        
        # Dismiss any post-login modals (delivery fee promos, etc.)
        dismiss_modals(driver)
        
        # Clear cart
        self_healing_call(clear_cart, driver, driver=driver)
        random_time()

        # Reserve time slot
        print("\n📅 Attempting to reserve time slot...")
        try:
            slot_reserved = self_healing_call(reserve_time_slot, driver, driver=driver)
            if slot_reserved:
                print("✓ Time slot reserved")
        except Exception as e:
            print(f"⚠️  Could not reserve time slot - continuing anyway ({type(e).__name__})")
        random_time()

        # Navigate to homepage before searching for ingredients
        print("\n🏠 Navigating to homepage for ingredient search...")
        driver.get("https://www.heb.com/")
        random_time()

        # Add all ingredients to cart
        print(f"\n🛒 Adding {len(ingredient_list.get_ingredients())} ingredients to cart...")
        while ingredient_list.get_ingredients() and not _interrupted:
            ingredient = ingredient_list.remove_last_ingredient()
            print(f"  Adding: {ingredient.get_name()}")
            self_healing_call(add_ingredient, ingredient, driver, driver=driver)
            random_time()
        
        if _interrupted:
            remaining = len(ingredient_list.get_ingredients())
            print(f"\n⚠️  Interrupted! {remaining} ingredient(s) not added.")
        else:
            print("\n✓ All ingredients added to cart!")
        
        print("\n" + "="*60)
        print("🧪 TEST MODE COMPLETE" if not _interrupted else "🧪 TEST MODE INTERRUPTED")
        print("="*60)
        print("Browser left open for manual inspection.")
        print("Review the cart and close the browser when done.\n")
        
        # Keep browser open indefinitely in test mode
        input("Press Enter to close the browser and exit...")
        
    except Exception as e:
        logger.log_failure(
            driver=driver,
            function_name="test_mode",
            error=e,
            additional_info={
                "remaining_ingredients": len(ingredient_list.get_ingredients()),
                "mode": "test"
            }
        )
        print(f"\n❌ Test mode failed with error: {e}")
        print("Check the debug_logs directory for HTML snapshots and details.\n")
        raise


def checkout_with_prompt(driver, ingredient_list):
    """
    Checkout with prompt mode: Adds ingredients, reserves slot, then prompts before checkout.
    
    Args:
        driver: Selenium WebDriver instance
        ingredient_list: IngredientList object with ingredients to add
    """
    print("\n" + "="*60)
    print("🤔 RUNNING IN CHECKOUT WITH PROMPT MODE")
    print("="*60)
    print("This will add ingredients and reserve a slot.")
    print("You'll be prompted before final checkout.\n")
    
    try:
        # Login
        self_healing_call(login, driver, driver=driver)
        random_time()
        driver.maximize_window()
        
        # Dismiss any post-login modals (delivery fee promos, etc.)
        dismiss_modals(driver)
        
        # Clear cart
        self_healing_call(clear_cart, driver, driver=driver)
        random_time()

        # Reserve time slot
        print("\n📅 Attempting to reserve time slot...")
        try:
            slot_reserved = self_healing_call(reserve_time_slot, driver, driver=driver)
            if slot_reserved:
                print("✓ Time slot reserved")
        except Exception as e:
            print(f"⚠️  Could not reserve time slot - continuing anyway ({type(e).__name__})")
        random_time()

        # Navigate to homepage before searching for ingredients
        print("\n🏠 Navigating to homepage for ingredient search...")
        driver.get("https://www.heb.com/")
        random_time()

        # Add all ingredients to cart
        print(f"\n🛒 Adding {len(ingredient_list.get_ingredients())} ingredients to cart...")
        while ingredient_list.get_ingredients() and not _interrupted:
            ingredient = ingredient_list.remove_last_ingredient()
            print(f"  Adding: {ingredient.get_name()}")
            self_healing_call(add_ingredient, ingredient, driver, driver=driver)
            random_time()
        
        if _interrupted:
            remaining = len(ingredient_list.get_ingredients())
            print(f"\n⚠️  Interrupted! {remaining} ingredient(s) not added.")
            print("Browser left open for inspection.")
            input("Press Enter to close the browser and exit...")
            return
        
        print("\n✓ All ingredients added to cart!")
        
        # Prompt user before checkout
        print("\n" + "="*60)
        print("🛒 Ready to checkout!")
        print("="*60)
        response = input("\nProceed with checkout? (yes/no): ").strip().lower()
        
        if response in ['yes', 'y']:
            print("\n💳 Proceeding with checkout...")
            self_healing_call(checkout, driver, driver=driver)
            print("\n✓ Order placed successfully!")
        else:
            print("\n❌ Checkout cancelled by user.")
            print("Browser will remain open. Close manually when done.")
            input("Press Enter to exit...")
        
    except Exception as e:
        logger.log_failure(
            driver=driver,
            function_name="checkout_with_prompt",
            error=e,
            additional_info={
                "remaining_ingredients": len(ingredient_list.get_ingredients()),
                "mode": "checkout_with_prompt"
            }
        )
        print(f"\n❌ Checkout with prompt failed with error: {e}")
        print("Check the debug_logs directory for HTML snapshots and details.\n")
        raise


def auto_checkout(driver, ingredient_list):
    """
    Auto checkout mode: Fully automated - adds ingredients, reserves slot, and checks out.
    ⚠️ WARNING: This will complete the order and charge your payment method!
    
    Args:
        driver: Selenium WebDriver instance
        ingredient_list: IngredientList object with ingredients to add
    """
    print("\n" + "="*60)
    print("🤖 RUNNING IN AUTO CHECKOUT MODE")
    print("="*60)
    print("⚠️  WARNING: This will AUTOMATICALLY COMPLETE the order!")
    print("⚠️  Your payment method will be charged!")
    print("="*60 + "\n")
    
    # Final safety confirmation
    print("This is your last chance to cancel.")
    response = input("Type 'CONFIRM' to proceed with automatic checkout: ").strip()
    
    if response != 'CONFIRM':
        print("\n❌ Auto checkout cancelled. Exiting...")
        return
    
    try:
        # Login
        self_healing_call(login, driver, driver=driver)
        random_time()
        driver.maximize_window()
        
        # Dismiss any post-login modals (delivery fee promos, etc.)
        dismiss_modals(driver)
        
        # Clear cart
        self_healing_call(clear_cart, driver, driver=driver)
        random_time()

        # Reserve time slot
        print("\n📅 Attempting to reserve time slot...")
        try:
            slot_reserved = self_healing_call(reserve_time_slot, driver, driver=driver)
            if slot_reserved:
                print("✓ Time slot reserved")
        except Exception as e:
            print(f"⚠️  Could not reserve time slot - continuing anyway ({type(e).__name__})")
        random_time()

        # Navigate to homepage before searching for ingredients
        print("\n🏠 Navigating to homepage for ingredient search...")
        driver.get("https://www.heb.com/")
        random_time()

        # Add all ingredients to cart
        print(f"\n🛒 Adding {len(ingredient_list.get_ingredients())} ingredients to cart...")
        while ingredient_list.get_ingredients() and not _interrupted:
            ingredient = ingredient_list.remove_last_ingredient()
            print(f"  Adding: {ingredient.get_name()}")
            self_healing_call(add_ingredient, ingredient, driver, driver=driver)
            random_time()
        
        if _interrupted:
            remaining = len(ingredient_list.get_ingredients())
            print(f"\n⚠️  Interrupted! {remaining} ingredient(s) not added.")
            print("Browser left open for inspection.")
            input("Press Enter to close the browser and exit...")
            return
        
        print("\n✓ All ingredients added to cart!")
        
        # Automatically checkout
        print("\n💳 Automatically processing checkout...")
        self_healing_call(checkout, driver, driver=driver)
        
        print("\n" + "="*60)
        print("✅ ORDER PLACED SUCCESSFULLY!")
        print("="*60)
        print("Check your email for order confirmation.\n")
        
    except Exception as e:
        logger.log_failure(
            driver=driver,
            function_name="auto_checkout",
            error=e,
            additional_info={
                "remaining_ingredients": len(ingredient_list.get_ingredients()),
                "mode": "auto_checkout"
            }
        )
        print(f"\n❌ Auto checkout failed with error: {e}")
        print("Check the debug_logs directory for HTML snapshots and details.\n")
        raise


def _graphql_login_and_export(driver, store_id):
    """Shared setup for GraphQL modes: Selenium login then export session.

    Returns nothing; raises on login failure.
    """
    # Reuse the existing self-healing Selenium login.
    self_healing_call(login, driver, driver=driver)
    random_time()
    driver.maximize_window()
    dismiss_modals(driver)

    # Export the authenticated browser session for the GraphQL client.
    print("\n🔐 Exporting browser session for GraphQL client...")
    export_selenium_session_to_authjson(driver, store_id=store_id)


def _graphql_choose_store(store_id):
    """Offer interactive store selection; persist + return the chosen store id.

    Falls back to the provided ``store_id`` on any issue.
    """
    try:
        chosen = select_store_interactive(
            default_store_id=store_id,
            default_address=_STORE_SEARCH_ADDRESS,
        )
    except Exception as e:  # noqa: BLE001
        print(f"⚠️  Store selection skipped ({e}). Using store #{store_id}.")
        return store_id

    if chosen and str(chosen) != str(store_id):
        config_path = os.path.join(os.path.dirname(__file__), 'config.txt')
        if update_config_value("STORE_ID", chosen, config_path):
            print(f"💾 Saved STORE_ID={chosen} to config.txt")
    return chosen


def _print_graphql_report(report):
    """Print a concise summary of a graphql_cart_sync report."""
    added = report.get("added", [])
    failed = report.get("failed", [])
    print("\n" + "-"*60)
    print(f"🛒 GraphQL cart summary: {len(added)} added, {len(failed)} failed")
    if failed:
        print("Failed items:")
        for f in failed:
            detail = f.get("detail")
            detail_str = f" - {detail}" if detail else ""
            print(f"  • {f['ingredient']} [{f['status']}]{detail_str}")
    print("-"*60)


def graphql_mode(driver, ingredient_list, store_id):
    """GraphQL test mode: add ingredients to cart via the API, no checkout.

    Args:
        driver: Selenium WebDriver instance (used for login + auth export).
        ingredient_list: IngredientList object with ingredients to add.
        store_id: HEB store id to operate against.
    """
    print("\n" + "="*60)
    print("⚡ RUNNING IN GRAPHQL MODE")
    print("="*60)
    print("This will add ingredients to the cart via HEB's GraphQL API.")
    print("No checkout is performed. Browser stays open for inspection.\n")

    try:
        _graphql_login_and_export(driver, store_id)

        # Let the user pick the closest store.
        store_id = _graphql_choose_store(store_id)

        print(f"\n⚡ Adding {len(ingredient_list.get_ingredients())} ingredients via GraphQL...")
        report = graphql_cart_sync(ingredient_list, store_id, do_clear=True)
        _print_graphql_report(report)

        print("\n" + "="*60)
        print("⚡ GRAPHQL MODE COMPLETE")
        print("="*60)
        print("Browser left open for manual inspection of the cart.")
        input("Press Enter to close the browser and exit...")

    except Exception as e:
        logger.log_failure(
            driver=driver,
            function_name="graphql_mode",
            error=e,
            additional_info={
                "remaining_ingredients": len(ingredient_list.get_ingredients()),
                "mode": "graphql",
            },
        )
        print(f"\n❌ GraphQL mode failed with error: {e}")
        print("Check the debug_logs directory for details.\n")
        raise


def graphql_checkout_with_prompt(driver, ingredient_list, store_id):
    """GraphQL add + Selenium timeslot + prompted Selenium checkout.

    Args:
        driver: Selenium WebDriver instance.
        ingredient_list: IngredientList object with ingredients to add.
        store_id: HEB store id to operate against.
    """
    print("\n" + "="*60)
    print("⚡🤔 RUNNING IN GRAPHQL CHECKOUT WITH PROMPT MODE")
    print("="*60)
    print("Adds ingredients via GraphQL, reserves a slot, prompts before checkout.\n")

    try:
        _graphql_login_and_export(driver, store_id)

        # Let the user pick the closest store.
        store_id = _graphql_choose_store(store_id)

        print(f"\n⚡ Adding {len(ingredient_list.get_ingredients())} ingredients via GraphQL...")
        report = graphql_cart_sync(ingredient_list, store_id, do_clear=True)
        _print_graphql_report(report)

        # Timeslot reservation still uses the Selenium flow.
        print("\n📅 Attempting to reserve time slot...")
        try:
            slot_reserved = self_healing_call(reserve_time_slot, driver, driver=driver)
            if slot_reserved:
                print("✓ Time slot reserved")
        except Exception as e:
            print(f"⚠️  Could not reserve time slot - continuing anyway ({type(e).__name__})")

        print("\n" + "="*60)
        print("🛒 Ready to checkout!")
        print("="*60)
        response = input("\nProceed with checkout? (yes/no): ").strip().lower()

        if response in ['yes', 'y']:
            print("\n💳 Proceeding with checkout...")
            self_healing_call(checkout, driver, driver=driver)
            print("\n✓ Order placed successfully!")
        else:
            print("\n❌ Checkout cancelled by user.")
            print("Browser will remain open. Close manually when done.")
            input("Press Enter to exit...")

    except Exception as e:
        logger.log_failure(
            driver=driver,
            function_name="graphql_checkout_with_prompt",
            error=e,
            additional_info={
                "remaining_ingredients": len(ingredient_list.get_ingredients()),
                "mode": "graphql_checkout_with_prompt",
            },
        )
        print(f"\n❌ GraphQL checkout with prompt failed with error: {e}")
        print("Check the debug_logs directory for details.\n")
        raise


def graphql_auto_checkout(driver, ingredient_list, store_id):
    """GraphQL add + Selenium timeslot + automatic Selenium checkout.

    ⚠️ WARNING: This will complete the order and charge your payment method!

    Args:
        driver: Selenium WebDriver instance.
        ingredient_list: IngredientList object with ingredients to add.
        store_id: HEB store id to operate against.
    """
    print("\n" + "="*60)
    print("⚡🤖 RUNNING IN GRAPHQL AUTO CHECKOUT MODE")
    print("="*60)
    print("⚠️  WARNING: This will AUTOMATICALLY COMPLETE the order!")
    print("⚠️  Your payment method will be charged!")
    print("="*60 + "\n")

    print("This is your last chance to cancel.")
    response = input("Type 'CONFIRM' to proceed with automatic checkout: ").strip()
    if response != 'CONFIRM':
        print("\n❌ Auto checkout cancelled. Exiting...")
        return

    try:
        _graphql_login_and_export(driver, store_id)

        # Let the user pick the closest store.
        store_id = _graphql_choose_store(store_id)

        print(f"\n⚡ Adding {len(ingredient_list.get_ingredients())} ingredients via GraphQL...")
        report = graphql_cart_sync(ingredient_list, store_id, do_clear=True)
        _print_graphql_report(report)

        # Timeslot reservation still uses the Selenium flow.
        print("\n📅 Attempting to reserve time slot...")
        try:
            slot_reserved = self_healing_call(reserve_time_slot, driver, driver=driver)
            if slot_reserved:
                print("✓ Time slot reserved")
        except Exception as e:
            print(f"⚠️  Could not reserve time slot - continuing anyway ({type(e).__name__})")

        print("\n💳 Automatically processing checkout...")
        self_healing_call(checkout, driver, driver=driver)

        print("\n" + "="*60)
        print("✅ ORDER PLACED SUCCESSFULLY!")
        print("="*60)
        print("Check your email for order confirmation.\n")

    except Exception as e:
        logger.log_failure(
            driver=driver,
            function_name="graphql_auto_checkout",
            error=e,
            additional_info={
                "remaining_ingredients": len(ingredient_list.get_ingredients()),
                "mode": "graphql_auto_checkout",
            },
        )
        print(f"\n❌ GraphQL auto checkout failed with error: {e}")
        print("Check the debug_logs directory for details.\n")
        raise


def update_graphql_hashes(driver, store_id):
    """Capture current HEB GraphQL persisted-query hashes from a live session.

    HEB rotates its Apollo persisted-query sha256 hashes on every front-end
    deploy, which breaks the GraphQL modes. This mode logs in, exercises the
    cart/store flows in a real browser, sniffs the GraphQL requests out of the
    Chrome performance log, and writes the captured hashes to the override file
    that the GraphQL client reads at runtime.

    The browser must have been started with performance logging enabled
    (handled in the main block when MODE == 'update_graphql_hashes').

    Args:
        driver: Selenium WebDriver instance (with performance logging).
        store_id: HEB store id used when exercising the store-change flow.
    """
    from utility.graphql_hash_capture import (
        TARGET_OPERATIONS,
        capture_graphql_operations,
        save_hashes,
        save_operation_samples,
    )

    print("\n" + "="*60)
    print("🔄 RUNNING IN UPDATE GRAPHQL HASHES MODE")
    print("="*60)
    print("This logs in and exercises the site to capture fresh GraphQL")
    print("persisted-query hashes for the GraphQL cart modes.\n")

    # Accumulator for every GraphQL operation seen across the whole flow.
    # driver.get_log("performance") is destructive and the buffer is bounded,
    # so we drain it after EACH step and merge, instead of once at the end.
    captured_ops = {}

    def _run_step(label, fn, *args):
        """Run one capture step, log failures with artifacts, then drain the log.

        Each step is best-effort: a failure in one flow must not abort the
        capture run, but it MUST be recorded (screenshot + HTML + context) so
        broken selectors can be diagnosed. The performance log is drained after
        the step regardless of success so its GraphQL traffic is retained.
        """
        print(f"\n{label}")
        try:
            self_healing_call(fn, *args, driver=driver)
        except Exception as e:  # noqa: BLE001
            print(f"⚠️  {label} incomplete ({type(e).__name__}: {e}) - continuing")
            try:
                logger.log_failure(
                    driver=driver,
                    function_name=getattr(fn, "__name__", str(fn)),
                    error=e,
                    additional_info={
                        "mode": "update_graphql_hashes",
                        "step": label,
                        "args": [str(a) for a in args],
                    },
                )
            except Exception as log_err:  # noqa: BLE001
                print(f"    ⚠️  Could not write debug log for this step: {log_err}")
        finally:
            random_time()
            before = len(captured_ops)
            capture_graphql_operations(driver, into=captured_ops)
            gained = len(captured_ops) - before
            print(f"    📡 Captured {len(captured_ops)} GraphQL op(s) so far (+{gained} this step).")

    try:
        # Login (reuse the self-healing Selenium login).
        self_healing_call(login, driver, driver=driver)
        random_time()
        driver.maximize_window()
        dismiss_modals(driver)
        # Drain any GraphQL traffic that fired during/after login.
        capture_graphql_operations(driver, into=captured_ops)

        # 1. Homepage browsing -> ShopNavigation / alertEntryPoint / cartEstimated.
        print("\n🏠 Loading homepage to trigger navigation queries...")
        driver.get("https://www.heb.com/")
        random_time()
        capture_graphql_operations(driver, into=captured_ops)

        # 2. Reserve a time slot -> timeslot list/reserve GraphQL ops.
        _run_step("📅 Exercising time slot reservation...", reserve_time_slot, driver)

        # 3. Visit the cart -> cartEstimated.
        _run_step("🛒 Visiting cart to trigger cart estimate query...", clear_cart, driver)

        # 4. Add a simple item -> cartItemV2.
        print("\n➕ Adding a sample item to trigger cart mutation...")
        driver.get("https://www.heb.com/")
        random_time()
        _run_step("➕ Adding sample item 'milk'...", add_ingredient, Ingredient("milk", ["1"], []), driver)

        # 5. Change store via the UI -> StoreSearch + SelectPickupFulfillment.
        search_text = _STORE_SEARCH_ADDRESS or "78701"
        _run_step(
            f"🏪 Exercising store search/change (near '{search_text}')...",
            change_store_via_ui, driver, search_text,
        )

        # 6. Walk into checkout -> timeslot + checkout/order-review GraphQL ops.
        #    The Selenium checkout stops before payment; we only need it to
        #    advance far enough for HEB to fire the timeslot/checkout queries so
        #    their operation names, hashes, and variable shapes get captured.
        _run_step(
            "🧾 Walking into checkout to trigger timeslot/checkout queries...",
            checkout, driver,
        )

        # 7. Final drain + save. Hashes are derived from the accumulated samples
        #    so we never call the destructive get_log twice for the same data.
        print("\n🔎 Finalizing GraphQL capture...")
        capture_graphql_operations(driver, into=captured_ops)
        operations = captured_ops
        hashes = {name: op["hash"] for name, op in operations.items() if op.get("hash")}

        if not hashes:
            print("\n❌ No GraphQL hashes captured.")
            print("Ensure performance logging is enabled and the flows ran.")
            print("Check the debug_logs directory for per-step failure artifacts.")
            input("Press Enter to close the browser and exit...")
            return

        path = save_hashes(hashes)
        samples_path = save_operation_samples(operations) if operations else None

        print("\n" + "="*60)
        print(f"✅ Captured {len(hashes)} GraphQL operation hash(es)")
        print("="*60)
        for name in sorted(hashes):
            marker = "🎯" if name in TARGET_OPERATIONS else "  "
            print(f"  {marker} {name}: {hashes[name][:16]}...")

        missing = sorted(TARGET_OPERATIONS - set(hashes))
        if missing:
            print("\n⚠️  Target operations NOT captured this run:")
            for name in missing:
                print(f"    • {name}")
            print("These weren't triggered; re-run after exercising those flows.")

        print(f"\n💾 Saved to: {path}")
        if samples_path:
            print(f"💾 Operation samples (hash + variables) saved to: {samples_path}")
            print(f"   ({len(operations)} operation(s) recorded for timeslot/checkout discovery)")
        print("GraphQL modes will use these hashes on the next run.")
        input("\nPress Enter to close the browser and exit...")

    except Exception as e:
        logger.log_failure(
            driver=driver,
            function_name="update_graphql_hashes",
            error=e,
            additional_info={"mode": "update_graphql_hashes"},
        )
        print(f"\n❌ Update GraphQL hashes failed with error: {e}")
        print("Check the debug_logs directory for details.\n")
        raise


if __name__ == '__main__':
    
    # ============================================================
    # CONFIGURATION
    # ============================================================
    
    # MODE SELECTION: Read from config.txt (KEY: MODE)
    # Valid values: 'test', 'checkout_with_prompt', 'auto_checkout'
    from claude import parse_config
    _config = parse_config(os.path.join(os.path.dirname(__file__), 'config.txt'))
    MODE = _config.get('MODE', 'test').strip()
    STORE_ID = _config.get('STORE_ID', '737').strip()
    _STORE_SEARCH_ADDRESS = _config.get('STORE_SEARCH_ADDRESS', '').strip()
    
    # ============================================================
    # INGREDIENT SOURCE SELECTION
    # ============================================================
    # Controlled by INGREDIENT_SOURCE in config.txt:
    #   'hardcoded' - use the ingredient_list_array below (default)
    #   'urls'      - scrape ingredients from url_list
    #   'database'  - ask the user which recipes they want this week and load
    #                 the matching recipes' ingredients from the database
    # (Legacy USE_URLS = True is still honored as 'urls'.)

    USE_URLS = False  # Legacy toggle; INGREDIENT_SOURCE takes precedence if set
    INGREDIENT_SOURCE = _config.get('INGREDIENT_SOURCE', '').strip().lower()
    if not INGREDIENT_SOURCE:
        INGREDIENT_SOURCE = 'urls' if USE_URLS else 'hardcoded'
    
    # Recipe URLs - Used when USE_URLS = True
    url_list = [
        "https://skinnyspatula.com/salmon-gnocchi/",
        # Add more recipe URLs here
    ]
    
    # Hardcoded ingredient list - Used when USE_URLS = False
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
    
    # ============================================================
    # SETUP
    # ============================================================
    
    print("\n" + "="*60)
    print("🥗 AUTO GROCIER - HEB AUTOMATION")
    print("="*60)
    print(f"Mode: {MODE.upper()}")
    print(f"Ingredient Source: {INGREDIENT_SOURCE}")
    print("="*60 + "\n")
    
    # Initialize ingredient list based on INGREDIENT_SOURCE setting
    if INGREDIENT_SOURCE == 'database':
        print("🗄️  Loading recipes from the database...\n")
        from database.db_connection import get_db_session
        from database.recipe_repository import RecipeRepository
        from database.ingredient_repository import IngredientRepository
        from utility.recipe_matcher import parse_and_match, build_ingredient_list

        user_request = input("What recipes do you want this week? ").strip()
        _db = get_db_session()
        try:
            _recipe_repo = RecipeRepository(_db)
            _ingredient_repo = IngredientRepository(_db)
            matched, unmatched = parse_and_match(user_request, _recipe_repo)

            if matched:
                print("\n✓ Matched recipes:")
                for r in matched:
                    print(f"   - {r.title or r.url}")
            if unmatched:
                print("\n⚠️  Could not match the following requests:")
                for u in unmatched:
                    print(f"   - {u}")

            IL = build_ingredient_list(matched, _ingredient_repo)
        finally:
            _db.close()
    elif INGREDIENT_SOURCE == 'urls':
        print("📡 Fetching ingredients from recipe URLs...")
        print(f"   Processing {len(url_list)} recipe(s)...\n")
        IL = populate_ingredient_list(url_list)
        print(f"✓ Successfully parsed recipes\n")
    else:
        print("📝 Using hardcoded ingredient list...\n")
        IL = IngredientList()
        for ingredient in ingredient_list_array:
            cleaned_ingredient_tuple = clean_ingredient(ingredient)
            name, amount, unit = cleaned_ingredient_tuple
            ingredient_obj = Ingredient(name, amount, unit)
            IL.add_ingredient(ingredient_obj)
    
    print(f"📋 Loaded {len(IL.get_ingredients())} ingredients:")
    IL.show_list()
    print()
    
    # Initialize Chrome driver with options to disable password save prompts
    print("🌐 Starting browser...")
    # Configure Chrome options to disable password manager and notifications
    options = uc.ChromeOptions()
    
    # Disable password manager prompts and update notifications
    prefs = {
        "credentials_enable_service": False,
        "profile.password_manager_enabled": False,
    }
    options.add_experimental_option("prefs", prefs)
    
    # Additional arguments to reduce popups and notifications
    options.add_argument("--disable-notifications")
    options.add_argument("--disable-popup-blocking")
    options.add_argument("--no-first-run")
    options.add_argument("--no-service-autorun")
    options.add_argument("--password-store=basic")

    # Stop the "Can't update Chrome" / "Update" banner. Chrome 116 is pinned, so
    # we disable the background update checks that trigger the upgrade bubble.
    options.add_argument("--disable-component-update")
    options.add_argument("--disable-background-networking")
    options.add_argument("--disable-features=ChromeWhatsNewUI,UpgradeDetector")

    # For the hash-capture mode, enable Chrome performance logging so we can
    # read GraphQL network requests (and their persisted-query hashes).
    if MODE == 'update_graphql_hashes':
        options.set_capability("goog:loggingPrefs", {"performance": "ALL"})

    # Match Chrome version 116 that's installed
    # Temporarily ignore SIGINT so chromedriver inherits SIG_IGN and won't die on Ctrl+C.
    # This keeps the browser + driver connection alive when the user interrupts.
    original_sigint = signal.getsignal(signal.SIGINT)
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    driver = uc.Chrome(version_main=116, options=options, use_subprocess=False)
    signal.signal(signal.SIGINT, original_sigint)  # restore default before registering ours
    
    # Set global variables for signal handler
    _global_driver = driver
    _global_mode = MODE
    
    # Register signal handler for Ctrl+C
    signal.signal(signal.SIGINT, signal_handler)
    
    # DON'T navigate to sign-in page - let login() handle navigation
    # driver.get("https://www.heb.com/sign-in")  # <- REMOVE THIS LINE
    # random_time()  # <- REMOVE THIS LINE
    
    print("✓ Browser started\n")
    
    # ============================================================
    # RUN SELECTED MODE
    # ============================================================
    
    try:
        if MODE == 'test':
            test_mode(driver, IL)
        elif MODE == 'checkout_with_prompt':
            checkout_with_prompt(driver, IL)
        elif MODE == 'auto_checkout':
            auto_checkout(driver, IL)
        elif MODE == 'graphql':
            graphql_mode(driver, IL, STORE_ID)
        elif MODE == 'graphql_checkout_with_prompt':
            graphql_checkout_with_prompt(driver, IL, STORE_ID)
        elif MODE == 'graphql_auto_checkout':
            graphql_auto_checkout(driver, IL, STORE_ID)
        elif MODE == 'update_graphql_hashes':
            update_graphql_hashes(driver, STORE_ID)
        else:
            print(f"❌ Invalid MODE: '{MODE}'")
            print("Valid modes: 'test', 'checkout_with_prompt', 'auto_checkout', "
                  "'graphql', 'graphql_checkout_with_prompt', 'graphql_auto_checkout', "
                  "'update_graphql_hashes'")
            driver.quit()
            exit(1)
    
    except KeyboardInterrupt:
        print("\n\n⚠️  Interrupted by user (Ctrl+C)")
        # Log the interrupt with current browser state
        try:
            logger.log_interrupt(driver, context=f"{MODE}_mode")
            print(f"📝 Session state saved to: {logger.session_dir}")
        except:
            pass
        print("Browser will remain open. Close manually if needed.\n")
    
    except Exception as e:
        print(f"\n❌ Unexpected error: {e}")
        print("Check debug_logs for details.\n")
    
    finally:
        # In test mode, browser stays open. Otherwise, clean exit.
        if MODE != 'test':
            print("\nClosing browser...")
            driver.quit()
            print("✓ Browser closed\n")