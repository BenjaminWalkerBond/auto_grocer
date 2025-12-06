"""
Driver Logger - Captures HTML snapshots and logs for debugging
Automatically saves HTML when exceptions occur to help debug HEB website changes
"""
import os
import datetime
import traceback
import json
from functools import wraps


class DriverLogger:
    """
    Logger for Selenium WebDriver operations.
    Captures HTML snapshots, screenshots, and error details when operations fail.
    """
    
    def __init__(self, log_dir="debug_logs"):
        """
        Initialize the logger.
        
        Args:
            log_dir (str): Directory to store debug logs and HTML snapshots
        """
        self.log_dir = log_dir
        self.session_dir = None
        self.create_log_directory()
    
    def create_log_directory(self):
        """Create a timestamped directory for this session's logs"""
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        self.session_dir = os.path.join(self.log_dir, f"session_{timestamp}")
        os.makedirs(self.session_dir, exist_ok=True)
        print(f"📁 Debug logs will be saved to: {self.session_dir}")
    
    def save_html_snapshot(self, driver, function_name, error_type="unknown"):
        """
        Save the current HTML page source to a file.
        
        Args:
            driver: Selenium WebDriver instance
            function_name (str): Name of the function that failed
            error_type (str): Type of error that occurred
        
        Returns:
            str: Path to the saved HTML file
        """
        try:
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            filename = f"{timestamp}_{function_name}_{error_type}.html"
            filepath = os.path.join(self.session_dir, filename)
            
            # Get the page source
            html_content = driver.page_source
            
            # Save to file
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(html_content)
            
            print(f"📄 HTML snapshot saved: {filepath}")
            return filepath
        
        except Exception as e:
            print(f"⚠️  Failed to save HTML snapshot: {e}")
            return None
    
    def save_screenshot(self, driver, function_name, error_type="unknown"):
        """
        Save a screenshot of the current page.
        
        Args:
            driver: Selenium WebDriver instance
            function_name (str): Name of the function that failed
            error_type (str): Type of error that occurred
        
        Returns:
            str: Path to the saved screenshot file
        """
        try:
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            filename = f"{timestamp}_{function_name}_{error_type}.png"
            filepath = os.path.join(self.session_dir, filename)
            
            driver.save_screenshot(filepath)
            print(f"📸 Screenshot saved: {filepath}")
            return filepath
        
        except Exception as e:
            print(f"⚠️  Failed to save screenshot: {e}")
            return None
    
    def save_error_log(self, function_name, error, driver=None, additional_info=None):
        """
        Save detailed error information to a JSON file.
        
        Args:
            function_name (str): Name of the function that failed
            error (Exception): The exception that was raised
            driver: Selenium WebDriver instance (optional)
            additional_info (dict): Any additional context to log
        
        Returns:
            str: Path to the saved error log file
        """
        try:
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            filename = f"{timestamp}_{function_name}_error.json"
            filepath = os.path.join(self.session_dir, filename)
            
            error_data = {
                "timestamp": datetime.datetime.now().isoformat(),
                "function_name": function_name,
                "error_type": type(error).__name__,
                "error_message": str(error),
                "traceback": traceback.format_exc(),
                "additional_info": additional_info or {}
            }
            
            # Add driver info if available
            if driver:
                try:
                    error_data["current_url"] = driver.current_url
                    error_data["page_title"] = driver.title
                except:
                    pass
            
            # Save to JSON file
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(error_data, f, indent=2)
            
            print(f"📝 Error log saved: {filepath}")
            return filepath
        
        except Exception as e:
            print(f"⚠️  Failed to save error log: {e}")
            return None
    
    def log_failure(self, driver, function_name, error, additional_info=None):
        """
        Complete failure logging: HTML, screenshot, and error details.
        
        Args:
            driver: Selenium WebDriver instance
            function_name (str): Name of the function that failed
            error (Exception): The exception that was raised
            additional_info (dict): Any additional context to log
        """
        print(f"\n{'='*60}")
        print(f"🚨 ERROR in {function_name}: {type(error).__name__}")
        print(f"{'='*60}\n")
        
        error_type = type(error).__name__
        
        # Save all debug information
        html_path = self.save_html_snapshot(driver, function_name, error_type)
        screenshot_path = self.save_screenshot(driver, function_name, error_type)
        log_path = self.save_error_log(function_name, error, driver, additional_info)
        
        print(f"\n{'='*60}")
        print(f"Debug files saved in: {self.session_dir}")
        print(f"{'='*60}\n")
        
        return {
            "html_path": html_path,
            "screenshot_path": screenshot_path,
            "log_path": log_path
        }
    
    def log_interrupt(self, driver=None, context="unknown"):
        """
        Log session interruption (e.g., Ctrl+C).
        Saves a snapshot of the current state when user interrupts.
        
        Args:
            driver: Selenium WebDriver instance (optional)
            context (str): Description of what was happening when interrupted
        """
        import time
        
        try:
            print("\n⏸️  Pausing for 2 seconds to capture browser state...")
            time.sleep(2)  # Wait 2 seconds before capturing
            
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            filename = f"{timestamp}_interrupted_{context}.json"
            filepath = os.path.join(self.session_dir, filename)
            
            interrupt_data = {
                "timestamp": datetime.datetime.now().isoformat(),
                "event": "user_interrupt",
                "context": context,
                "message": "Session interrupted by user (Ctrl+C)"
            }
            
            # Add driver info if available
            if driver:
                try:
                    interrupt_data["current_url"] = driver.current_url
                    interrupt_data["page_title"] = driver.title
                except Exception as e:
                    print(f"⚠️  Could not get driver info: {e}")
                
                # Save screenshot and HTML at time of interrupt
                print("📸 Capturing browser state...")
                try:
                    self.save_html_snapshot(driver, "interrupted", context)
                except Exception as e:
                    print(f"⚠️  Failed to save HTML: {e}")
                
                try:
                    self.save_screenshot(driver, "interrupted", context)
                except Exception as e:
                    print(f"⚠️  Failed to save screenshot: {e}")
            
            # Save to JSON file
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(interrupt_data, f, indent=2)
            
            print(f"📝 Interrupt log saved: {filepath}")
            return filepath
            
        except Exception as e:
            print(f"⚠️  Failed to save interrupt log: {e}")
            traceback.print_exc()
            return None


def logged_driver_function(logger):
    """
    Decorator to automatically log failures in driver functions.
    
    Usage:
        @logged_driver_function(logger)
        def my_function(driver, arg1, arg2):
            # Your code here
            pass
    
    Args:
        logger (DriverLogger): The logger instance to use
    
    Returns:
        function: Decorated function
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            # Find the driver in args (usually first argument)
            driver = None
            for arg in args:
                if hasattr(arg, 'page_source'):  # Duck typing for WebDriver
                    driver = arg
                    break
            
            try:
                return func(*args, **kwargs)
            except Exception as e:
                if driver:
                    logger.log_failure(
                        driver=driver,
                        function_name=func.__name__,
                        error=e,
                        additional_info={
                            "args": str(args[1:]),  # Skip driver
                            "kwargs": str(kwargs)
                        }
                    )
                # Re-raise the exception
                raise
        
        return wrapper
    return decorator


# Example usage in your code:
if __name__ == "__main__":
    print("Driver Logger Module")
    print("This module provides automatic HTML snapshot capture on errors.")
    print("\nUsage:")
    print("  logger = DriverLogger()")
    print("  logger.log_failure(driver, 'function_name', exception)")
    print("\nOr use the decorator:")
    print("  @logged_driver_function(logger)")
    print("  def my_function(driver):")
    print("      # your code")
