"""
Diagnostic script to identify why scraper stops at 0%
Tests: Chrome stability, table element detection, page structure
"""
import time
import traceback
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager

from config import AppConfig

def get_chrome_driver():
    options = webdriver.ChromeOptions()
    options.add_argument('--headless=new')
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    options.add_argument('--disable-gpu')
    options.add_argument('--disable-setuid-sandbox')
    options.add_argument('--disable-software-rasterizer')
    options.add_argument('--disable-extensions')
    options.add_argument('--user-agent=Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36')
    
    print("Using webdriver-manager to install chromedriver")
    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=options)
    return driver

def run_diagnostic():
    driver = None
    try:
        driver = get_chrome_driver()
        print(f"✓ Chrome WebDriver started successfully")
        
        # Step 1: Navigate to the screener
        url = AppConfig.STOCKANALYSIS_URL
        print(f"\n--- Step 1: Navigating to {url} ---")
        driver.get(url)
        time.sleep(3)
        print(f"  Page title: {driver.title}")
        print(f"  Current URL: {driver.current_url}")
        
        # Step 2: Click the UI config elements
        print(f"\n--- Step 2: Clicking {len(AppConfig.SCRAPER_XPATHS)} UI config elements ---")
        for i, xpath in enumerate(AppConfig.SCRAPER_XPATHS):
            # Try to close popup
            try:
                popup = driver.find_element(By.XPATH, AppConfig.POPUP_XPATH)
                popup.click()
                time.sleep(0.5)
            except:
                pass
            
            try:
                element = driver.find_element(By.XPATH, xpath)
                element.click()
                time.sleep(AppConfig.PAGE_LOAD_WAIT)
                print(f"  ✓ Clicked element {i+1}/{len(AppConfig.SCRAPER_XPATHS)}")
            except Exception as e:
                print(f"  ✗ FAILED element {i+1}: {e}")
        
        # Step 3: Wait longer after config
        print(f"\n--- Step 3: Waiting 3s for table to load after config ---")
        time.sleep(3)
        
        # Step 4: Check if Chrome is still alive
        print(f"\n--- Step 4: Chrome health check ---")
        try:
            _ = driver.title
            print(f"  ✓ Chrome is still responsive. Title: {driver.title}")
        except Exception as e:
            print(f"  ✗ Chrome is DEAD: {e}")
            return
        
        # Step 5: Look for table elements
        print(f"\n--- Step 5: Searching for table elements ---")
        
        # Try ID="main-table"
        try:
            table = driver.find_element(By.ID, "main-table")
            print(f"  ✓ Found element with ID='main-table': tag={table.tag_name}")
        except Exception as e:
            print(f"  ✗ No element with ID='main-table': {e}")
        
        # Try all tables
        try:
            tables = driver.find_elements(By.TAG_NAME, "table")
            print(f"  Found {len(tables)} <table> elements:")
            for idx, t in enumerate(tables):
                tid = t.get_attribute("id") or "(no id)"
                tclass = t.get_attribute("class") or "(no class)"
                rows = t.find_elements(By.TAG_NAME, "tr")
                print(f"    Table {idx}: id='{tid}', class='{tclass}', rows={len(rows)}")
        except Exception as e:
            print(f"  ✗ Error finding tables: {e}")
        
        # Try common CSS selectors
        selectors_to_try = [
            ("CSS: table.svelte", "table[class*='svelte']"),
            ("CSS: [data-test]", "[data-test*='table']"),
            ("CSS: #main table", "#main table"),
            ("CSS: .tv-data-table", ".tv-data-table"),
            ("CSS: table", "table"),
        ]
        
        print(f"\n--- Step 6: Trying CSS selectors ---")
        for name, selector in selectors_to_try:
            try:
                elements = driver.find_elements(By.CSS_SELECTOR, selector)
                print(f"  {name}: found {len(elements)} elements")
            except Exception as e:
                print(f"  {name}: error - {e}")
        
        # Step 7: Dump page source snippet for investigation
        print(f"\n--- Step 7: Page source analysis ---")
        source = driver.page_source
        print(f"  Page source length: {len(source)} chars")
        
        # Look for table-related content
        import re
        table_ids = re.findall(r'id=["\']([^"\']*table[^"\']*)["\']', source, re.IGNORECASE)
        print(f"  IDs containing 'table': {table_ids}")
        
        # Check for specific patterns
        if 'main-table' in source:
            print(f"  ✓ 'main-table' found in page source")
        else:
            print(f"  ✗ 'main-table' NOT found in page source")
        
        # Look for the data table region
        table_match = re.search(r'<table[^>]*>(.*?)</table>', source, re.DOTALL)
        if table_match:
            table_html = table_match.group(0)[:500]
            print(f"  First table HTML (truncated): {table_html}")
        else:
            print(f"  ✗ No <table> tag found in page source at all!")
        
        # Step 8: Check next button
        print(f"\n--- Step 8: Check next button ---")
        try:
            next_btn = driver.find_element(By.XPATH, AppConfig.NEXT_BUTTON_XPATH)
            print(f"  ✓ Next button found: text='{next_btn.text}', enabled={next_btn.is_enabled()}")
        except Exception as e:
            print(f"  ✗ Next button not found: {e}")
        
        # Try alternative next button selectors
        try:
            nav_buttons = driver.find_elements(By.CSS_SELECTOR, "nav button")
            print(f"  Found {len(nav_buttons)} nav buttons:")
            for idx, btn in enumerate(nav_buttons):
                print(f"    Button {idx}: text='{btn.text}', enabled={btn.is_enabled()}")
        except Exception as e:
            print(f"  Error finding nav buttons: {e}")
        
    except Exception as e:
        print(f"\n!!! UNEXPECTED ERROR !!!")
        print(traceback.format_exc())
    finally:
        if driver:
            driver.quit()
            print("\n--- WebDriver closed ---")

if __name__ == "__main__":
    run_diagnostic()
