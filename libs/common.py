import time
from selenium.common.exceptions import NoSuchElementException

def wait_and_click(driver, by, locator, timeout=10):
    end = time.time() + timeout
    while time.time() < end:
        try:
            el = driver.find_element(by, locator)
            el.click()
            return True
        except Exception:
            time.sleep(0.5)
    raise NoSuchElementException(f"Could not click {locator}")

def element_text(driver, by, locator):
    el = driver.find_element(by, locator)
    return el.text

def screenshot_bytes_from_selenium(driver):
    """Return PNG bytes for the current page (Selenium)."""
    return driver.get_screenshot_as_png()
