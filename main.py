import selenium
import undetected_chromedriver as uc
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.common.exceptions import NoSuchElementException    

from classes.IngredientList import IngredientList
from classes.Ingredient import Ingredient
from utility.read_email import fetch_verification_code
from utility.driver_logger import DriverLogger, logged_driver_function

import os
import time
import random
from recipe_grabber import populate_ingredient_list
from recipe_grabber import clean_ingredient

# Initialize the logger globally
logger = DriverLogger(log_dir="debug_logs")

    
def check_exists_by_xpath(xpath,driver):
    try:
        driver.find_element(By.XPATH, xpath)
    except NoSuchElementException:
        return False
    return True
def random_time():
    time.sleep(random.randint(2, 3))
def add_ingredient(ingredient, driver):
    """Add an ingredient to the HEB cart"""
    try:
        # Find search bar
        search_bar = driver.find_element(By.ID, "search-input")
        
        # Clear the search bar properly - use multiple methods to ensure it's cleared
        search_bar.clear()
        # Also select all and delete as backup
        search_bar.send_keys(Keys.CONTROL + "a")
        search_bar.send_keys(Keys.DELETE)
        random_time()
        
        # Enter the search term
        if ingredient.get_tag() == "vegetable" or ingredient.get_tag() == "fruit":
            search_bar.send_keys("organic ", ingredient.get_name())
        else:
            search_bar.send_keys(ingredient.get_name())
        random_time()
        
        # Submit search
        search_bar.send_keys(Keys.ENTER)
        random_time()
        
        # Wait for search results and add to cart
        if(check_exists_by_xpath('//*[@id="search_product_grid"]/div[2]/div/div[1]/div/div/div/div/div/button', driver)):
            add_to_cart_button = driver.find_element(By.XPATH,'//*[@id="search_product_grid"]/div[2]/div/div[1]/div/div/div/div/div/button')
            
            # Try normal click first, fall back to JavaScript if blocked
            try:
                add_to_cart_button.click()
            except:
                driver.execute_script("arguments[0].click();", add_to_cart_button)
            
            # Wait a moment for the item to be added
            random_time()
        else:
            print(f"    ⚠️  Add to cart button not found for: {ingredient.get_name()}")
            return 0
    except Exception as e:
        logger.log_failure(
            driver=driver,
            function_name="add_ingredient",
            error=e,
            additional_info={
                "ingredient": ingredient.get_name(),
                "ingredient_tag": ingredient.get_tag()
            }
        )
        raise
def clear_cart(driver):
    """Clear all items from the HEB shopping cart"""
    try:
        cart_button = driver.find_element(By.XPATH, "/html/body/div/header/div[1]/div[2]/a[2]")
        cart_button.click()
        random_time()
        if (check_exists_by_xpath("/html/body/div[1]/main/div/div/div[1]/div/section[2]/div[2]/button", driver)):
            clear_cart_button = driver.find_element(By.XPATH,"/html/body/div[1]/main/div/div/div[1]/div/section[2]/div[2]/button")
            random_time()
            # scroll down half the page to make sure the button is visible
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight/2);")
            clear_cart_button.click()
            random_time()
            confirm_empty = driver.find_element(By.XPATH, "/html/body/div[3]/div/div/div/div[2]/button[2]")
            confirm_empty.click()
            random_time()
            home = driver.find_element(By.XPATH, "//html/body/div/header/div[1]/div[2]/a[1]")
            home.click()
            random_time()
        else:
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
    """Reserve a delivery time slot on HEB website"""
    try:
        # Construct an XPath to find elements containing the search word
        xpath = f"//*[contains(text(), 'Change time')]"
        if not check_exists_by_xpath(xpath, driver):
            # try:
            # navigate to the cart
            # cart_button = driver.find_element(By.XPATH, "/html/body/div/header/div[1]/div[2]/a[2]")
            # cart_button = driver.find_element(By.CSS_SELECTOR, '[href="/cart/"]')
            # cart_button.click()
            driver.get("https://www.heb.com/cart/")
        random_time()
        # click the reserve time slot button
        reserve_button = driver.find_element(By.CSS_SELECTOR, '[data-qe-id="chooseReservationTime"]')
        reserve_button.click()
        random_time()
        # tomorrow = driver.find_element(By.XPATH, "/html/body/div[3]/div/div/div/div/div/div/div/div[2]/div[2]/button[2]")
        # # find the evening slots sections by searching for all elements with the same class and an h3 tag with the text "Evening"
        # evening_slots_header = driver.find_element(By.XPATH, "//div[@class='sc-cyxg30-0 bQqawu']/div/h3[text()='Evening']")

        # Define the specific days you're looking for
        days = ["Today", "Tomorrow","Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

        # Iterate through the days list and search for matching elements
        # for day in days:
        #     # Construct an XPath to find elements containing both the day and "Free"
        #     # xpath = f"//button[descendant-or-self::text() = {day}, '{day}') and contains(descendant-or-self::text(), 'Free')]"
        #     xpath = f"//*[text() = {day}, '{day}']"
            
        #     # Find all matching elements with the specified XPath
        #     matching_elements = driver.find_elements(By.XPATH, xpath)

        #     if matching_elements:
        #         # Click the first matching element found
        #         print("found a free day!")
        #         matching_elements[0].click()
        #         time.sleep(3)
        #         break  # Exit the loop once a match is found

        # TERRIBLE IMPLEMENTATION I WAS FORCED TO USE BECAUSE I COULDNT GET ABOVE WORKING
        matching_elements = []
        for day in days:
            xpath = f"//*[contains(text(), '{day}')]"
            matching_elements += driver.find_elements(By.XPATH, xpath)
        print(matching_elements)


        if matching_elements:
            print("in matching elements")
            for match in matching_elements:
                free_element = match.find_elements(By.XPATH, "//*[contains(text(), 'Free')]")
                if free_element:
                    match.find_element(By.XPATH, "..").find_element(By.XPATH, "..").find_element(By.XPATH, "..").click()

                    random_time()

                    xpath = f"//*[contains(text(), 'Evening')]"
                    if check_exists_by_xpath(xpath, driver):
                        print("found a free day!")
                        break

        random_time()
        # Define the specific word you're looking for
        search_word = "Evening"

        # Construct an XPath to find elements containing the search word
        xpath = f"//*[contains(text(), '{search_word}')]"

        if check_exists_by_xpath(xpath, driver):
            # Find all matching elements on the page
            evening_slots_header = driver.find_element(By.XPATH, xpath)
            print(evening_slots_header)
            # # go up two levels to get the container for the evening slots
            evening_slots_container = (evening_slots_header.find_element(By.XPATH, "..")).find_element(By.XPATH, "..")

            evening_slots_container = evening_slots_container.find_elements(By.TAG_NAME, "button")

            for time in evening_slots_container:
                # check if day.accesible_name contains open 
                if "Free" in time.get_attribute("aria-label"):
                    print("found a free time!")
                    time.click()
                    break
                print(time.accessible_name) 


            # Define the specific word you're looking for
            search_word = "Save"
            # Construct an XPath to find elements containing the search word
            xpath = f"//*[contains(text(), '{search_word}')]"

            confirm_reserve = driver.find_element(By.XPATH, xpath)
            
            # Try to click using JavaScript if normal click fails (due to overlays/prompts)
            try:
                confirm_reserve.click()
            except:
                print("  ℹ️  Normal click failed, using JavaScript click...")
                driver.execute_script("arguments[0].click();", confirm_reserve)
            
            random_time()
            close_modal_button = driver.find_element(By.CSS_SELECTOR, '[aria-label="Close Modal"]')
            
            # Use JavaScript click for modal close button too
            try:
                close_modal_button.click()
            except:
                print("  ℹ️  Normal click failed on modal, using JavaScript click...")
                driver.execute_script("arguments[0].click();", close_modal_button)
        else: 
            print("No evening slots available")
    
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
        raise

from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

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
        login(driver)
        random_time()
        driver.maximize_window()
        
        # Clear cart
        clear_cart(driver)
        random_time()

        # Reserve time slot
        print("\n📅 Attempting to reserve time slot...")
        reserve_time_slot(driver)
        print("✓ Time slot reserved")
        random_time()

        # Add all ingredients to cart
        print(f"\n🛒 Adding {len(ingredient_list.get_ingredients())} ingredients to cart...")
        while ingredient_list.get_ingredients():
            ingredient = ingredient_list.remove_last_ingredient()
            print(f"  Adding: {ingredient.get_name()}")
            add_ingredient(ingredient, driver)
            random_time()
        
        print("\n✓ All ingredients added to cart!")
        print("\n" + "="*60)
        print("🧪 TEST MODE COMPLETE")
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
        login(driver)
        random_time()
        driver.maximize_window()
        
        # Clear cart
        clear_cart(driver)
        random_time()

        # Reserve time slot
        print("\n📅 Attempting to reserve time slot...")
        reserve_time_slot(driver)
        print("✓ Time slot reserved")
        random_time()

        # Add all ingredients to cart
        print(f"\n🛒 Adding {len(ingredient_list.get_ingredients())} ingredients to cart...")
        while ingredient_list.get_ingredients():
            ingredient = ingredient_list.remove_last_ingredient()
            print(f"  Adding: {ingredient.get_name()}")
            add_ingredient(ingredient, driver)
            random_time()
        
        print("\n✓ All ingredients added to cart!")
        
        # Prompt user before checkout
        print("\n" + "="*60)
        print("🛒 Ready to checkout!")
        print("="*60)
        response = input("\nProceed with checkout? (yes/no): ").strip().lower()
        
        if response in ['yes', 'y']:
            print("\n💳 Proceeding with checkout...")
            checkout(driver)
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
        login(driver)
        random_time()
        driver.maximize_window()
        
        # Clear cart
        clear_cart(driver)
        random_time()

        # Reserve time slot
        print("\n📅 Attempting to reserve time slot...")
        reserve_time_slot(driver)
        print("✓ Time slot reserved")
        random_time()

        # Add all ingredients to cart
        print(f"\n🛒 Adding {len(ingredient_list.get_ingredients())} ingredients to cart...")
        while ingredient_list.get_ingredients():
            ingredient = ingredient_list.remove_last_ingredient()
            print(f"  Adding: {ingredient.get_name()}")
            add_ingredient(ingredient, driver)
            random_time()
        
        print("\n✓ All ingredients added to cart!")
        
        # Automatically checkout
        print("\n💳 Automatically processing checkout...")
        checkout(driver)
        
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
    
    # MODE SELECTION: Choose one of: 'test', 'checkout_with_prompt', 'auto_checkout'
    MODE = 'test'  # Change this to switch modes
    
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
    driver = uc.Chrome(version_main=116, options=options, use_subprocess=True)
    
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