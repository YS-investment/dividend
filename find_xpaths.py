"""
Enumerate all indicator checkboxes in the StockAnalysis.com Dividends screener.
Results are printed to console AND saved to data/screener_indicator_xpaths.csv
"""
import time
import sys
import os
import csv
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

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
    options.add_argument('--user-agent=Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36')
    service = Service(ChromeDriverManager().install())
    return webdriver.Chrome(service=service, options=options)

def main():
    driver = get_chrome_driver()
    results = []

    try:
        driver.get(AppConfig.STOCKANALYSIS_URL)
        WebDriverWait(driver, 15).until(EC.presence_of_element_located((By.ID, "main-table")))
        print("✓ Page loaded\n")

        # Click Dividends preset
        div_btn = driver.find_element(By.XPATH, "//button[contains(text(), 'Dividends')]")
        div_btn.click()
        time.sleep(2)
        print("✓ Clicked Dividends preset\n")

        # Open Indicators panel
        indicator_btn = driver.find_element(By.XPATH, '//*[@id="main"]/div[3]/div[1]/div/div[3]/button')
        indicator_btn.click()
        time.sleep(1)
        print("✓ Opened Indicators panel\n")

        # Find ALL checkbox divs inside indicator panel
        panel_xpath = '//*[@id="main"]/div[3]/div[1]/div/div[3]/div/div[2]'
        panel = driver.find_element(By.XPATH, panel_xpath)
        divs = panel.find_elements(By.XPATH, './div')

        print(f"Found {len(divs)} indicator items\n")
        print(f"{'Index':<10} {'Label':<30} {'Checked':<10} {'XPath'}")
        print("-" * 100)

        for i, div in enumerate(divs):
            try:
                label = div.text.strip()
                checkbox = div.find_element(By.TAG_NAME, 'input')
                checked = checkbox.is_selected()
                xpath = f'{panel_xpath}/div[{i+1}]/input'

                marker = ""
                for keyword in ['Growth 5Y', 'Growth 3Y', 'Years', 'CAGR', 'Growth 10Y']:
                    if keyword.lower() in label.lower():
                        marker = " ← !!!"
                        break

                status = "✓" if checked else "○"
                print(f"div[{i+1}]    {label:<30} {status:<10} {xpath}{marker}")

                results.append({
                    'index': i + 1,
                    'label': label,
                    'checked': checked,
                    'xpath': xpath
                })
            except Exception as e:
                print(f"div[{i+1}]    (error: {e})")

        # Save to CSV
        output_path = os.path.join('data', 'screener_indicator_xpaths.csv')
        os.makedirs('data', exist_ok=True)
        with open(output_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=['index', 'label', 'checked', 'xpath'])
            writer.writeheader()
            writer.writerows(results)

        print(f"\n✓ Results saved to {output_path}")

    except Exception as e:
        import traceback
        print(f"\n✗ Error: {e}")
        traceback.print_exc()
    finally:
        driver.quit()
        print("WebDriver closed")

if __name__ == "__main__":
    main()
