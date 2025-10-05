# utils/driver_factory.py
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from typing import Tuple
import os
import stat
import shutil

def create_selenium_driver(headless: bool = True, implicit_wait: int = 5) -> Tuple[str, object, callable]:
    opts = Options()
    if headless:
        # modern headless mode
        opts.add_argument("--headless=new")
        opts.add_argument("--no-sandbox")
    opts.add_argument("--window-size=1920,1080")
    opts.add_argument("--disable-dev-shm-usage")
    # Let Selenium Manager handle driver resolution (Selenium >= 4.10)
    driver = webdriver.Chrome(options=opts)
    driver.implicitly_wait(int(implicit_wait))

    def cleanup():
        try:
            driver.quit()
        except Exception:
            pass

    return ("selenium", driver, cleanup)
