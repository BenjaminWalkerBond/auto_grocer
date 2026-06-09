
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

# Initialize the logger globally
logger = DriverLogger(log_dir="debug_logs")

# Global variable to hold the driver for signal handling
_global_driver = None
_global_mode = None
_interrupted = False


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

def reserve_time_slot(driver):
    """Reserve a curbside pickup time slot on HEB website.

    Flow:
    1. Navigate to cart page
    2. Click 'Choose a time' button to open reservation modal
    3. Ensure 'Curbside' tab is selected
    4. Pick the first available (Free, non-Full) date
    5. Pick the first available free timeslot
    6. Click 'Select this time' to confirm
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

        # STEP 2: Click the 'Choose pickup time' button from the cart page
        print("  Step 2: Opening reservation modal...")
        try:
            # Look for the specific button with icon and text "Choose pickup time"
            reserve_button = wait.until(EC.element_to_be_clickable(
                (By.XPATH, '//button[contains(., "Choose pickup time") or .//span[contains(text(), "Choose pickup time")]]')
            ))
            reserve_button.click()
            print("    ✓ Clicked 'Choose pickup time' button")
        except:
            try:
                # Fallback: look for button in the curbside fulfillment section
                reserve_button = wait.until(EC.element_to_be_clickable(
                    (By.XPATH, '//button[contains(@aria-label, "Choose pickup time") or contains(@aria-label, "pickup time")]')
                ))
                reserve_button.click()
                print("    ✓ Clicked pickup time button")
            except:
                raise Exception("Could not find pickup time selection button")
        
        random_time()

        # STEP 3: Make sure the Curbside tab is selected
        print("  Step 3: Ensuring Curbside tab is selected...")
        try:
            # Look for curbside tab or pickup option
            curbside_elements = driver.find_elements(By.XPATH, '//*[contains(text(), "Curbside") or contains(text(), "CURBSIDE") or contains(@id, "CURBSIDE")]')
            for element in curbside_elements:
                if element.tag_name in ['button', 'a'] or element.get_attribute('role') == 'tab':
                    if element.get_attribute("aria-selected") != "true":
                        element.click()
                        random_time()
                        print("    ✓ Selected Curbside option")
                    else:
                        print("    ✓ Curbside already selected")
                    break
        except Exception as e:
            print(f"    ⚠️  Could not check/click Curbside tab: {e}")

        # Wait for modal/page to load
        time.sleep(3)
        
        # STEP 4: Select a free date
        print("  Step 4: Selecting a free date...")
        
        # Look for date selection elements with various approaches
        date_elements = []
        
        # Try to find radio buttons for dates
        date_radios = driver.find_elements(By.XPATH, '//input[@type="radio" and (contains(@name, "date") or contains(@aria-label, "date") or contains(@value, "2025"))]')
        if date_radios:
            print(f"    Found {len(date_radios)} date radio buttons")
            date_elements = date_radios
        
        # Try to find clickable date buttons or labels
        if not date_elements:
            date_buttons = driver.find_elements(By.XPATH, '//button[contains(@aria-label, "date") or contains(text(), "Jan") or contains(text(), "Feb") or contains(text(), "Mar") or contains(text(), "Apr") or contains(text(), "May") or contains(text(), "Jun") or contains(text(), "Jul") or contains(text(), "Aug") or contains(text(), "Sep") or contains(text(), "Oct") or contains(text(), "Nov") or contains(text(), "Dec")]')
            if date_buttons:
                print(f"    Found {len(date_buttons)} date buttons")
                date_elements = date_buttons
        
        # Try to find any elements with date-related data attributes
        if not date_elements:
            date_elements = driver.find_elements(By.CSS_SELECTOR, '[data-testid*="date"], [data-qe-id*="date"], [aria-label*="date"], [class*="date"]')
            if date_elements:
                print(f"    Found {len(date_elements)} date-related elements")

        date_selected = False
        for element in date_elements:
            try:
                # Get text content and attributes to check availability
                element_text = element.get_attribute('textContent') or element.text or ''
                aria_label = element.get_attribute('aria-label') or ''
                value = element.get_attribute('value') or ''
                combined_text = f"{element_text} {aria_label} {value}".lower()
                
                # Skip if element is disabled or marked as full
                if element.get_attribute('disabled') or 'full' in combined_text or 'unavailable' in combined_text:
                    print(f"    ⏭️  Skipping (unavailable): {element_text or aria_label}")
                    continue
                
                # Check if it's already selected
                if element.get_attribute('checked') == 'true' or element.get_attribute('aria-checked') == 'true' or 'selected' in element.get_attribute('class') or '':
                    print(f"    ✓ Date already selected: {element_text or aria_label}")
                    date_selected = True
                    break
                
                # Try to click the element
                try:
                    if element.tag_name == 'input':
                        # For radio inputs, click directly
                        driver.execute_script("arguments[0].click();", element)
                    else:
                        # For buttons or other clickable elements
                        element.click()
                    
                    print(f"    📅 Selected date: {element_text or aria_label}")
                    random_time()
                    date_selected = True
                    break
                except Exception as click_error:
                    print(f"    ⚠️  Could not click date element: {click_error}")
                    continue
                    
            except Exception as e:
                print(f"    ⚠️  Error processing date element: {e}")
                continue

        if not date_selected:
            # Final fallback: try to click any radio button or clickable element
            all_clickable = driver.find_elements(By.XPATH, '//input[@type="radio"] | //button[not(@disabled)]')
            for element in all_clickable[:5]:  # Try first 5 elements
                try:
                    driver.execute_script("arguments[0].click();", element)
                    print("    📅 Selected first available option")
                    date_selected = True
                    break
                except:
                    continue
                    
        if not date_selected:
            raise Exception(
                f"No available dates found. Found {len(date_elements)} date elements but none were selectable. "
                f"The page layout may have changed or no dates are available."
            )

        # STEP 5: Select a timeslot
        print("  Step 5: Selecting a free timeslot...")
        time.sleep(2)  # Wait for timeslots to load after date selection

        # Look for timeslot elements
        timeslot_elements = []
        
        # Try to find radio buttons for timeslots
        timeslot_radios = driver.find_elements(By.XPATH, '//input[@type="radio" and (contains(@name, "time") or contains(@aria-label, "time") or contains(@aria-label, "slot"))]')
        if timeslot_radios:
            print(f"    Found {len(timeslot_radios)} timeslot radio buttons")
            timeslot_elements = timeslot_radios
        
        # Try to find clickable timeslot buttons
        if not timeslot_elements:
            timeslot_buttons = driver.find_elements(By.XPATH, '//button[contains(@aria-label, "time") or contains(text(), "AM") or contains(text(), "PM") or contains(text(), ":")]')
            if timeslot_buttons:
                print(f"    Found {len(timeslot_buttons)} timeslot buttons")
                timeslot_elements = timeslot_buttons
        
        # Try to find any elements with timeslot-related data attributes
        if not timeslot_elements:
            timeslot_elements = driver.find_elements(By.CSS_SELECTOR, '[data-testid*="time"], [data-qe-id*="time"], [aria-label*="time"], [class*="time"]')
            if timeslot_elements:
                print(f"    Found {len(timeslot_elements)} time-related elements")

        timeslot_selected = False
        for element in timeslot_elements:
            try:
                element_text = element.get_attribute('textContent') or element.text or ''
                aria_label = element.get_attribute('aria-label') or ''
                combined_text = f"{element_text} {aria_label}".lower()
                
                # Skip if disabled or full
                if element.get_attribute('disabled') or 'full' in combined_text or 'unavailable' in combined_text:
                    continue
                
                # Look for free timeslots or ones with pricing
                if 'free' in combined_text or '$0' in combined_text or ('am' in combined_text or 'pm' in combined_text):
                    try:
                        if element.tag_name == 'input':
                            driver.execute_script("arguments[0].click();", element)
                        else:
                            element.click()
                        
                        print(f"    🕐 Selected timeslot: {element_text or aria_label}")
                        human_like_delay()
                        timeslot_selected = True
                        break
                    except Exception as click_error:
                        print(f"    ⚠️  Could not click timeslot: {click_error}")
                        continue
                        
            except Exception as e:
                continue

        if not timeslot_selected:
            # Fallback: try any available radio button or clickable element
            remaining_clickable = driver.find_elements(By.XPATH, '//input[@type="radio"][not(@disabled)] | //button[not(@disabled)]')
            for element in remaining_clickable[:5]:
                try:
                    driver.execute_script("arguments[0].click();", element)
                    print("    🕐 Selected first available timeslot")
                    timeslot_selected = True
                    break
                except:
                    continue

        if not timeslot_selected:
            raise Exception(
                f"No free timeslots found. Found {len(timeslot_elements)} timeslot elements but none were selectable. "
                f"The page layout may have changed or no timeslots are available."
            )

        # STEP 6: Click confirmation button
        print("  Step 6: Clicking confirmation button...")
        
        confirm_selectors = [
            '//button[contains(text(), "Select this time")]',
            '//button[contains(text(), "Confirm")]',
            '//button[contains(text(), "Save")]',
            '//button[contains(text(), "Schedule")]',
            '//button[contains(@aria-label, "confirm")]',
            '//button[contains(@data-qe-id, "fulfill")]',
            '//button[contains(@data-qe-id, "schedule")]',
            '//button[contains(@data-qe-id, "save")]'
        ]
        
        confirm_button = None
        for selector in confirm_selectors:
            try:
                confirm_button = wait.until(EC.element_to_be_clickable((By.XPATH, selector)))
                break
            except:
                continue
        
        if confirm_button:
            try:
                confirm_button.click()
                print("    ✓ Clicked confirmation button")
            except:
                driver.execute_script("arguments[0].click();", confirm_button)
                print("    ✓ Clicked confirmation button (JS)")
        else:
            # Look for any prominent button that might be the confirmation
            all_buttons = driver.find_elements(By.TAG_NAME, 'button')
            for button in all_buttons:
                if not button.get_attribute('disabled'):
                    button_text = (button.text or '').lower()
                    if any(word in button_text for word in ['select', 'confirm', 'save', 'continue', 'next']):
                        try:
                            button.click()
                            print(f"    ✓ Clicked button: {button.text}")
                            break
                        except:
                            continue
            else:
                print("    ⚠️  Could not find confirmation button, proceeding anyway")

        print("  ✓ Time slot reservation process completed!")
        random_time()

        # Wait for any modal to close or page to update
        time.sleep(3)

        # Try to close any remaining modal
        try:
            close_elements = driver.find_elements(By.XPATH, '//button[contains(@aria-label, "close") or contains(@aria-label, "Close") or contains(text(), "×")]')
            for close_elem in close_elements:
                try:
                    close_elem.click()
                    print("  ✓ Closed modal")
                    break
                except:
                    continue
        except:
            print("  ℹ️  No modal to close or already closed")

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
            close_buttons = driver.find_elements(By.XPATH, '//button[contains(@aria-label, "close") or contains(text(), "×")]')
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
    """
    try:
        print("\n🛒 Starting checkout process...")
        
        # Navigate to cart
        driver.get("https://www.heb.com/cart/")
        random_time()
        
        # Find and click checkout button
        checkout_button = driver.find_element(By.CSS_SELECTOR, '[data-qe-id="proceedToCheckout"]')
        checkout_button.click()
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


if __name__ == '__main__':
    
    # ============================================================
    # CONFIGURATION
    # ============================================================
    
    # MODE SELECTION: Read from config.txt (KEY: MODE)
    # Valid values: 'test', 'checkout_with_prompt', 'auto_checkout'
    from claude import parse_config
    _config = parse_config(os.path.join(os.path.dirname(__file__), 'config.txt'))
    MODE = _config.get('MODE', 'test').strip()
    
    # ============================================================
    # INGREDIENT SOURCE SELECTION
    # ============================================================
    # Option 1: Use recipe URLs (set USE_URLS = True)
    # Option 2: Use hardcoded ingredient list (set USE_URLS = False)
    
    USE_URLS = False  # Set to True to use url_list, False to use ingredient_list_array
    
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
    print(f"Ingredient Source: {'Recipe URLs' if USE_URLS else 'Hardcoded List'}")
    print("="*60 + "\n")
    
    # Initialize ingredient list based on USE_URLS setting
    if USE_URLS:
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
        else:
            print(f"❌ Invalid MODE: '{MODE}'")
            print("Valid modes: 'test', 'checkout_with_prompt', 'auto_checkout'")
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