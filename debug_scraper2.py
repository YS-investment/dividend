"""
Focused test: replicate the exact scraping loop to find the failure
"""
import time
import traceback
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
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
    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=options)
    return driver

def run_test():
    driver = get_chrome_driver()
    print("✓ Driver started")
    
    try:
        driver.get(AppConfig.STOCKANALYSIS_URL)
        time.sleep(3)
        print(f"✓ Page loaded: {driver.title}")
        
        # Click config elements
        for i, xpath in enumerate(AppConfig.SCRAPER_XPATHS):
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
                print(f"  ✓ Clicked {i+1}/{len(AppConfig.SCRAPER_XPATHS)}")
            except Exception as e:
                print(f"  ✗ Failed {i+1}: {e}")
        
        time.sleep(2)  # Extra wait after config
        
        # Now replicate EXACTLY what the scraping loop does for page 0
        print("\n=== Simulating scraping loop iteration 0 ===")
        
        # Step A: popup close
        print("Step A: Trying popup close...")
        try:
            popup = driver.find_element(By.XPATH, AppConfig.POPUP_XPATH)
            popup.click()
            print("  Popup closed")
        except Exception as e:
            print(f"  No popup (expected): {type(e).__name__}")
        
        # Step B: Find table
        print("Step B: Finding main-table...")
        try:
            table_element = driver.find_element(By.ID, "main-table")
            print(f"  ✓ Found main-table, tag={table_element.tag_name}")
            
            table_html = table_element.get_attribute('outerHTML')
            print(f"  ✓ Got outerHTML, length={len(table_html)}")
            
            # Step C: Parse with BeautifulSoup
            print("Step C: Parsing with BeautifulSoup...")
            soup = BeautifulSoup(table_html, 'html.parser')
            
            headers = [header.text.strip() for header in soup.find_all('th')]
            print(f"  Headers ({len(headers)}): {headers}")
            
            rows = []
            for row in soup.find_all('tr')[1:]:
                rows.append([cell.text.strip() for cell in row.find_all('td')])
            print(f"  Data rows: {len(rows)}")
            
            if rows:
                print(f"  First row sample: {rows[0][:5]}")
            
        except Exception as e:
            print(f"  ✗ FAILED: {type(e).__name__}: {e}")
            traceback.print_exc()
        
        # Step D: Try next button
        print("Step D: Trying next button...")
        try:
            next_button = driver.find_element(By.XPATH, AppConfig.NEXT_BUTTON_XPATH)
            print(f"  ✓ Found next button: text='{next_button.text}', enabled={next_button.is_enabled()}")
            next_button.click()
            time.sleep(2)
            print(f"  ✓ Clicked next, new URL: {driver.current_url}")
            
            # Try to read table on page 2
            print("Step E: Reading page 2 table...")
            table_element = driver.find_element(By.ID, "main-table")
            table_html = table_element.get_attribute('outerHTML')
            soup = BeautifulSoup(table_html, 'html.parser')
            rows = []
            for row in soup.find_all('tr')[1:]:
                rows.append([cell.text.strip() for cell in row.find_all('td')])
            print(f"  ✓ Page 2 rows: {len(rows)}")
            if rows:
                print(f"  First row: {rows[0][:3]}")
                
        except Exception as e:
            print(f"  ✗ FAILED: {type(e).__name__}: {e}")
            traceback.print_exc()
        
    except Exception as e:
        print(f"\n!!! UNEXPECTED ERROR !!!")
        traceback.print_exc()
    finally:
        driver.quit()
        print("\nDriver closed")

if __name__ == "__main__":
    run_test()
