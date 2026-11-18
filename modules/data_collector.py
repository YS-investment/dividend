"""
Data collection module
Handles web scraping and data processing
"""

import pandas as pd
import numpy as np
import os
import sys
import time
from datetime import datetime, timezone

# Allow running as standalone script from any directory
if __name__ == "__main__":
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
import shutil
import warnings
from typing import Optional, Callable
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from tqdm import tqdm
import yfinance as yf

from config import AppConfig, get_data_path, get_main_data_path, get_raw_data_path, get_last_updated_path


class DividendDataCollector:
    """
    Data collection and processing class
    """

    def __init__(self):
        self.data_dir = AppConfig.DATA_DIR

    def update_all_data(self, use_scraping: bool = True, progress_callback: Optional[Callable] = None) -> pd.DataFrame:
        """
        Main data update function
        Complete workflow: scraping → validation → processing → enrichment → save

        Every run is appended to data/update_history.csv. A failed run, or one
        where more than 10% of symbols failed enrichment, sends a Telegram
        alert when TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID are set.

        Args:
            use_scraping: If True, scrape new data. If False, process existing raw data.
            progress_callback: Optional callback for progress updates

        Returns:
            Processed DataFrame
        """
        from modules.update_log import record_update, notify

        started = datetime.now(timezone.utc).isoformat()
        self._run_info = {'mode': 'scrape' if use_scraping else 'reprocess'}
        try:
            final_df = self._run_update_pipeline(use_scraping, progress_callback)
        except BaseException as e:
            record_update(started_at=started, finished_at=datetime.now(timezone.utc).isoformat(),
                          status='failed', error=f"{type(e).__name__}: {str(e)[:300]}", **self._run_info)
            notify(f"❌ Dividend data update FAILED ({self._run_info['mode']})\n{type(e).__name__}: {str(e)[:500]}")
            raise

        n_fail = self._run_info.get('enrichment_failures', 0)
        degraded = n_fail > 0.10 * max(len(final_df), 1)
        record_update(started_at=started, finished_at=datetime.now(timezone.utc).isoformat(),
                      status='degraded' if degraded else 'success', **self._run_info)
        if degraded:
            notify(f"⚠️ Dividend data update degraded: {n_fail} of {len(final_df)} symbols failed "
                   f"enrichment (see data/enrichment_failures.csv)")
        return final_df

    def _run_update_pipeline(self, use_scraping: bool, progress_callback: Optional[Callable]) -> pd.DataFrame:
        """Pipeline stages; update_all_data() wraps this with logging/alerts."""
        # Stage 0: Backup existing data
        print("=" * 60)
        print("STAGE 0: Backing up existing data...")
        print("=" * 60)
        self.backup_existing_data()

        # Macro benchmarks (10Y Treasury MA, CPI) - the universe's 5Y CAGR
        # floor depends on CPI, so refresh before Stage 2
        from modules.macro_benchmarks import refresh_macro_benchmarks
        macro = refresh_macro_benchmarks()
        print(f"✓ Macro benchmarks ({macro.get('source')}): "
              f"10Y {AppConfig.RATE_MA_YEARS}Y MA {macro['treasury_10y_ma']:.2%}, "
              f"CPI {AppConfig.CPI_YEARS}Y {macro['cpi_annualized']:.2%}")
        for err in macro.get('errors', []):
            print(f"  ⚠ {err}")
        self._run_info.update(macro_source=macro.get('source'),
                              treasury_10y_ma=macro.get('treasury_10y_ma'),
                              cpi_annualized=macro.get('cpi_annualized'))

        # Stage 1: Data Collection
        print("\n" + "=" * 60)
        print("STAGE 1: Data Collection")
        print("=" * 60)

        if use_scraping:
            # Scrape new data from StockAnalysis.com
            raw_df = self.collect_stockanalysis_data(progress_callback=progress_callback)

            # Validate scraped data
            print("\nValidating scraped data...")
            validation_report = self.validate_scraped_data(raw_df)

            if not validation_report['valid']:
                error_msg = "Data validation failed:\n" + "\n".join(validation_report['errors'])
                raise ValueError(error_msg)

            print("✓ Data validation passed")

            # Save raw data
            raw_data_path = get_raw_data_path()
            raw_df.to_csv(raw_data_path, index=False)
            print(f"✓ Raw data saved to {raw_data_path}")

        else:
            # Load existing raw data
            raw_data_path = get_raw_data_path()

            if not os.path.exists(raw_data_path):
                raise FileNotFoundError(
                    f"Raw data file not found: {raw_data_path}\n"
                    "Please enable scraping or ensure dividend_from_stockanalysis.csv exists."
                )

            raw_df = pd.read_csv(raw_data_path)
            print(f"✓ Loaded existing raw data from {raw_data_path}")

        self._run_info['raw_rows'] = len(raw_df)

        # Stage 2: Data Processing & Filtering
        print("\n" + "=" * 60)
        print("STAGE 2: Data Processing & Filtering")
        print("=" * 60)

        aristocrats_set, kings_set, schd_set = self.load_premium_stock_lists()
        premium_symbols = aristocrats_set | kings_set | schd_set

        filtered_df = self.process_raw_data_from_df(raw_df, premium_symbols)
        print(f"✓ Applied initial filters: {len(filtered_df)} stocks remaining")

        # Stage 2.5: Add Premium Stock Categories
        print("\n" + "=" * 60)
        print("STAGE 2.5: Adding Premium Stock Categories")
        print("=" * 60)

        filtered_df = self.add_missing_premium_stocks(
            filtered_df, aristocrats_set, kings_set, schd_set
        )
        print(f"✓ Total stocks after adding missing premium stocks: {len(filtered_df)}")

        filtered_df = self.categorize_stocks(
            filtered_df, aristocrats_set, kings_set, schd_set
        )
        print(f"✓ Categorization complete")

        category_counts = filtered_df['Category'].value_counts()
        print("\nCategory breakdown:")
        for category, count in category_counts.items():
            print(f"  {category}: {count}")

        # Stage 3: Yahoo Finance Enrichment
        print("\n" + "=" * 60)
        print("STAGE 3: Yahoo Finance Enrichment")
        print("=" * 60)

        enriched_df = self.enrich_with_yfinance(filtered_df)

        # Stage 4: Yield-vs-history columns (informational; no filtering)
        print("\n" + "=" * 60)
        print("STAGE 4: Yield Comparison Columns")
        print("=" * 60)

        final_df = self.add_yield_comparison_columns(enriched_df)

        # Stage 5: Save Final Data
        print("\n" + "=" * 60)
        print("STAGE 5: Saving Results")
        print("=" * 60)

        output_path = get_main_data_path()
        final_df.to_csv(output_path, index=False)
        print(f"✓ Final data saved to {output_path}")
        print(f"✓ Total stocks in final dataset: {len(final_df)}")
        self._run_info['final_rows'] = len(final_df)

        # Record the actual completion time (UTC), since file mtimes get
        # reset on every git checkout/redeploy and don't reflect this.
        with open(get_last_updated_path(), "w") as f:
            f.write(datetime.now(timezone.utc).isoformat())

        print("\n" + "=" * 60)
        print("DATA UPDATE COMPLETE")
        print("=" * 60)

        return final_df

    def process_raw_data_from_df(self, df: pd.DataFrame, premium_symbols: set = None) -> pd.DataFrame:
        """
        Process raw DataFrame (alternative to process_raw_data that takes a file path)

        Args:
            df: Raw DataFrame
            premium_symbols: Optional pre-loaded set of upper-cased Aristocrats/Kings/SCHD
                              tickers, so callers that already loaded the lists (e.g.
                              update_all_data) don't re-read the CSVs. Loaded internally
                              if not provided.

        Returns:
            Processed DataFrame
        """
        if premium_symbols is None:
            aristocrats_set, kings_set, schd_set = self.load_premium_stock_lists()
            premium_symbols = aristocrats_set | kings_set | schd_set

        # Data preprocessing
        df = self.convert_percentage_columns(df)
        df = self.convert_numeric_columns(df)
        df = self.apply_initial_filters(df, premium_symbols)

        # Apply 5-criteria filtering from notebook
        df = self.apply_dividend_criteria_filters(df, premium_symbols)

        return df

    def apply_dividend_criteria_filters(self, df: pd.DataFrame, premium_symbols: set = None) -> pd.DataFrame:
        """
        Apply the 5 dividend quality criteria filters
        Premium stocks (Aristocrats/Kings/SCHD) bypass these filters

        Args:
            df: Input DataFrame
            premium_symbols: Optional pre-loaded set of upper-cased premium tickers.
                              Loaded internally if not provided.

        Returns:
            Filtered DataFrame
        """
        result = df.copy()

        if 'Symbol' not in result.columns:
            return result

        if premium_symbols is None:
            aristocrats_set, kings_set, schd_set = self.load_premium_stock_lists()
            premium_symbols = aristocrats_set | kings_set | schd_set

        premium_mask = result['Symbol'].str.upper().isin(premium_symbols)
        premium_stocks = result[premium_mask].copy()
        regular_stocks = result[~premium_mask].copy()

        print(f"  Premium stocks (bypass filters): {len(premium_stocks)}")
        print(f"  Regular stocks (apply filters): {len(regular_stocks)}")

        # Universe = loosest bar shared by both screeners. No payout gate here
        # (sector unknown before yfinance; payout rules are sector-specific and
        # applied in data_processor.filter_stocks()).
        from modules.macro_benchmarks import load_macro_benchmarks
        cpi_floor = load_macro_benchmarks()['cpi_annualized']

        if 'Div. Yield' in regular_stocks.columns:
            regular_stocks = regular_stocks[regular_stocks['Div. Yield'] >= AppConfig.UNIVERSE_MIN_YIELD]

        if 'Div. Gr. Years' in regular_stocks.columns:
            regular_stocks = regular_stocks[regular_stocks['Div. Gr. Years'] >= AppConfig.UNIVERSE_MIN_GROWTH_YEARS]

        if 'Div. Growth' in regular_stocks.columns:
            regular_stocks = regular_stocks[regular_stocks['Div. Growth'] >= AppConfig.UNIVERSE_MIN_GROWTH_1Y]

        if 'Div. Growth 5Y' in regular_stocks.columns:
            regular_stocks = regular_stocks[regular_stocks['Div. Growth 5Y'] >= cpi_floor]

        result = pd.concat([premium_stocks, regular_stocks], ignore_index=True)

        print(f"  After filtering: {len(result)} total stocks")

        return result

    def load_premium_stock_lists(self) -> tuple:
        """
        Load premium stock lists from CSV files

        Returns:
            tuple: (aristocrats_set, kings_set, schd_set) as sets of ticker symbols
        """
        aristocrats_set = set()
        kings_set = set()
        schd_set = set()

        try:
            aristocrats_path = get_data_path(AppConfig.DIVIDEND_ARISTOCRATS_FILE)
            if os.path.exists(aristocrats_path):
                aristocrats_df = pd.read_csv(aristocrats_path)
                aristocrats_set = set(aristocrats_df['Symbol'].str.upper())
                print(f"  Loaded {len(aristocrats_set)} Dividend Aristocrats")
            else:
                print(f"  Warning: {aristocrats_path} not found")
        except Exception as e:
            print(f"  Warning: Could not load Aristocrats list: {e}")

        try:
            kings_path = get_data_path(AppConfig.DIVIDEND_KINGS_FILE)
            if os.path.exists(kings_path):
                kings_df = pd.read_csv(kings_path)
                kings_set = set(kings_df['Symbol'].str.upper())
                print(f"  Loaded {len(kings_set)} Dividend Kings")
            else:
                print(f"  Warning: {kings_path} not found")
        except Exception as e:
            print(f"  Warning: Could not load Kings list: {e}")

        try:
            schd_path = get_data_path(AppConfig.SCHD_HOLDINGS_FILE)
            if os.path.exists(schd_path):
                schd_df = pd.read_csv(schd_path)
                schd_set = set(schd_df['Symbol'].str.upper())
                print(f"  Loaded {len(schd_set)} SCHD holdings")
            else:
                print(f"  Warning: {schd_path} not found")
        except Exception as e:
            print(f"  Warning: Could not load SCHD list: {e}")

        return aristocrats_set, kings_set, schd_set

    def categorize_stocks(self, df: pd.DataFrame, aristocrats_set: set,
                         kings_set: set, schd_set: set) -> pd.DataFrame:
        """
        Add Category column to DataFrame based on premium stock membership

        Args:
            df: Input DataFrame with Symbol column
            aristocrats_set: Set of Dividend Aristocrat tickers
            kings_set: Set of Dividend King tickers
            schd_set: Set of SCHD holdings tickers

        Returns:
            DataFrame with new Category column
        """
        result = df.copy()

        def get_category(symbol):
            categories = []

            symbol_upper = str(symbol).upper()

            if symbol_upper in aristocrats_set:
                categories.append('Aristocrat')
            if symbol_upper in kings_set:
                categories.append('King')
            if symbol_upper in schd_set:
                categories.append('SCHD')

            if categories:
                return '+'.join(categories)
            else:
                return 'Others'

        result['Category'] = result['Symbol'].apply(get_category)

        return result

    def add_missing_premium_stocks(self, df: pd.DataFrame, aristocrats_set: set,
                                   kings_set: set, schd_set: set) -> pd.DataFrame:
        """
        Add premium stocks that are missing from the DataFrame

        Args:
            df: Current DataFrame
            aristocrats_set: Set of Dividend Aristocrat tickers
            kings_set: Set of Dividend King tickers
            schd_set: Set of SCHD holdings tickers

        Returns:
            DataFrame with missing premium stocks added
        """
        result = df.copy()

        all_premium_stocks = aristocrats_set | kings_set | schd_set

        if 'Symbol' in result.columns:
            existing_symbols = set(result['Symbol'].str.upper())
        else:
            existing_symbols = set()

        missing_symbols = all_premium_stocks - existing_symbols

        if not missing_symbols:
            print(f"  All premium stocks already present in dataset")
            return result

        print(f"  Adding {len(missing_symbols)} missing premium stocks: {sorted(missing_symbols)}")

        missing_rows = []
        for symbol in missing_symbols:
            row_data = {
                'Symbol': symbol,
                'Company Name': f"{symbol} (Premium Stock)",
            }

            for col in result.columns:
                if col not in row_data:
                    if result[col].dtype in ['float64', 'float32', 'int64', 'int32']:
                        row_data[col] = 0.0
                    else:
                        row_data[col] = ''

            missing_rows.append(row_data)

        if missing_rows:
            missing_df = pd.DataFrame(missing_rows)
            result = pd.concat([result, missing_df], ignore_index=True)
            result = result.drop_duplicates(subset=['Symbol'], keep='first')

        return result

    def process_raw_data(self, raw_data_path: str) -> pd.DataFrame:
        """
        Process raw data from StockAnalysis.com

        Args:
            raw_data_path: Path to raw CSV file

        Returns:
            Processed DataFrame
        """
        # Load raw data
        df = pd.read_csv(raw_data_path)

        # Data preprocessing
        df = self.convert_percentage_columns(df)
        df = self.convert_numeric_columns(df)
        df = self.apply_initial_filters(df)

        return df

    def convert_percentage_columns(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Convert percentage string columns to float

        Args:
            df: Input DataFrame

        Returns:
            DataFrame with converted percentages
        """
        result = df.copy()

        # Percentage columns to convert
        pct_columns = ['Div. Yield', 'Payout Ratio', 'Div. Growth', 'Div. Growth 5Y', 'Div. Growth 3Y']

        for col in pct_columns:
            if col in result.columns:
                result[col] = result[col].apply(self._convert_percentage)

        return result

    @staticmethod
    def _convert_percentage(value):
        """Convert percentage string to float"""
        try:
            if pd.isna(value) or value == '-':
                return None
            # Remove % and convert to decimal
            return float(str(value).replace('%', '')) / 100
        except:
            return None

    def convert_numeric_columns(self, df: pd.DataFrame) -> pd.DataFrame:
        """Convert numeric string columns"""
        result = df.copy()

        # Convert Years column
        if 'Div. Gr. Years' in result.columns:
            result['Div. Gr. Years'] = pd.to_numeric(result['Div. Gr. Years'], errors='coerce')
        if 'Div. Years' in result.columns:
            result['Div. Years'] = pd.to_numeric(result['Div. Years'], errors='coerce')

        return result

    def apply_initial_filters(self, df: pd.DataFrame, premium_symbols: set = None) -> pd.DataFrame:
        """
        Apply initial data quality filters
        Premium stocks (Aristocrats/Kings/SCHD) bypass the yield check - a
        scraping glitch reporting a missing/zero yield shouldn't strip their
        real scraped row before Stage 2.5 can categorize and enrich them.

        Args:
            df: Input DataFrame
            premium_symbols: Optional pre-loaded set of upper-cased premium tickers.
                              Loaded internally if not provided.

        Returns:
            Filtered DataFrame
        """
        result = df.copy()

        if 'Div. Yield' not in result.columns:
            return result

        # Remove rows with missing dividend yield
        valid_yield_mask = result['Div. Yield'].notna() & (result['Div. Yield'] > 0)

        if 'Symbol' in result.columns:
            if premium_symbols is None:
                aristocrats_set, kings_set, schd_set = self.load_premium_stock_lists()
                premium_symbols = aristocrats_set | kings_set | schd_set
            premium_mask = result['Symbol'].str.upper().isin(premium_symbols)
            return result[premium_mask | valid_yield_mask]

        return result[valid_yield_mask]

    def _dismiss_overlays(self, driver):
        """Remove iframe overlays and dismiss popups that block clicks."""
        try:
            driver.execute_script("document.querySelectorAll('iframe').forEach(f => f.remove());")
        except:
            pass
        try:
            popup = driver.find_element(By.XPATH, AppConfig.POPUP_XPATH)
            driver.execute_script("arguments[0].click();", popup)
            time.sleep(0.5)
        except:
            pass

    def _try_click(self, driver, xpath: str, label: str = ""):
        """Click an element by XPath, removing overlays first. Falls back to JS click."""
        self._dismiss_overlays(driver)
        try:
            element = driver.find_element(By.XPATH, xpath)
            try:
                element.click()
            except:
                driver.execute_script("arguments[0].click();", element)
            time.sleep(AppConfig.PAGE_LOAD_WAIT)
            print(f"  ✓ {label}")
        except Exception as e:
            print(f"  ⚠ Could not click '{label}': {e}")

    def _select_indicator_columns(self, driver):
        """Select indicator checkboxes by label text rather than positional XPath."""
        try:
            panel = driver.find_element(By.XPATH, AppConfig.INDICATOR_PANEL_XPATH)
        except Exception as e:
            print(f"  ⚠ Indicator panel not found: {e}")
            return

        divs = panel.find_elements(By.XPATH, './div')
        targets = set(AppConfig.INDICATOR_LABELS)
        found = set()

        for div in divs:
            label = div.text.strip()
            if label in targets:
                try:
                    checkbox = div.find_element(By.TAG_NAME, 'input')
                    if not checkbox.is_selected():
                        checkbox.click()
                        time.sleep(0.3)
                    found.add(label)
                    print(f"  ✓ Indicator selected: {label}")
                except Exception as e:
                    print(f"  ⚠ Could not select indicator '{label}': {e}")

        missing = targets - found
        if missing:
            print(f"  ⚠ Indicator labels not found in panel: {missing}")

    def get_chrome_driver(self):
        """
        Initialize Chrome WebDriver in headless mode
        Optimized for Streamlit Cloud deployment

        Returns:
            WebDriver instance
        """
        options = webdriver.ChromeOptions()

        # Don't wait for every subresource (ads/trackers) to finish loading —
        # only for DOM interactive. The explicit WebDriverWait for #main-table
        # right after driver.get() handles waiting for the actual content.
        # Without this, a slow/hanging third-party resource can block driver.get()
        # past the WebDriver client's read timeout.
        options.page_load_strategy = 'eager'

        # Always run in headless mode (user requirement). "new" headless renders
        # much closer to a real browser than the legacy "--headless" mode, which
        # is more readily fingerprinted by bot-detection.
        options.add_argument('--headless=new')
        options.add_argument('--no-sandbox')
        options.add_argument('--disable-dev-shm-usage')
        options.add_argument('--disable-gpu')
        options.add_argument('--disable-setuid-sandbox')
        # options.add_argument('--single-process')
        options.add_argument('--disable-software-rasterizer')
        options.add_argument('--disable-extensions')

        # Don't force a User-Agent string here: a hardcoded version drifts out
        # of sync with the actual Chrome build over time (e.g. claiming
        # Chrome/114 while running Chrome/152), and Chrome's Client Hints
        # headers (Sec-CH-UA) always report the real version regardless of any
        # --user-agent override — the mismatch itself is a bot-detection signal.
        # Leaving it unset means Chrome sends its own consistent, matching UA.

        # Reduce automation fingerprints that anti-bot systems check for.
        options.add_argument('--disable-blink-features=AutomationControlled')
        options.add_experimental_option('excludeSwitches', ['enable-automation'])
        options.add_experimental_option('useAutomationExtension', False)

        # Resolve Chrome/Chromium binary path (system install takes priority).
        # Checks PATH first, then common per-OS install locations, so this
        # works both on the Linux CI runner and a local Windows/Mac dev
        # machine — a bare hardcoded '/usr/bin/...' path is always truthy
        # even when it doesn't exist, which silently broke non-Linux runs.
        binary_candidates = [
            shutil.which('chromium'),
            shutil.which('chromium-browser'),
            shutil.which('google-chrome-stable'),
            shutil.which('google-chrome'),
            shutil.which('chrome'),
            '/usr/bin/chromium',
            '/usr/bin/chromium-browser',
            r'C:\Program Files\Google\Chrome\Application\chrome.exe',
            r'C:\Program Files (x86)\Google\Chrome\Application\chrome.exe',
        ]
        chromium_bin = next((p for p in binary_candidates if p and os.path.exists(p)), None)
        if chromium_bin:
            options.binary_location = chromium_bin

        # Resolve chromedriver path (system install takes priority). Falls
        # through to the webdriver-manager branch below when neither exists,
        # instead of trying a Linux-only path that isn't actually there.
        chromedriver_candidate = shutil.which('chromedriver') or '/usr/bin/chromedriver'
        chromedriver_path = chromedriver_candidate if os.path.exists(chromedriver_candidate) else None

        if chromedriver_path:
            try:
                print(f"Using system chromedriver: {chromedriver_path}, browser: {chromium_bin}")
                service = Service(chromedriver_path)
                driver = webdriver.Chrome(service=service, options=options)
                self._hide_webdriver_flag(driver)
                return driver
            except Exception as e:
                print(f"System chromedriver failed: {e}")

        # Fallback to webdriver-manager (local development)
        print("Using webdriver-manager to install chromedriver")
        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=options)
        self._hide_webdriver_flag(driver)
        return driver

    @staticmethod
    def _hide_webdriver_flag(driver):
        """Mask navigator.webdriver, which Selenium sets to true by default,
        and strip "Headless" from the User-Agent Chrome reports for itself —
        both are common, simple signals bot-detection checks for. The version
        number is left untouched (read from the real UA), so this can't drift
        out of sync the way a hardcoded UA string does."""
        try:
            driver.execute_cdp_cmd('Page.addScriptToEvaluateOnNewDocument', {
                'source': "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
            })
        except Exception:
            pass
        try:
            real_ua = driver.execute_script("return navigator.userAgent")
            if real_ua and 'Headless' in real_ua:
                driver.execute_cdp_cmd('Network.setUserAgentOverride', {
                    'userAgent': real_ua.replace('Headless', '')
                })
        except Exception:
            pass

    def collect_stockanalysis_data(self, progress_callback: Optional[Callable] = None) -> pd.DataFrame:
        """
        Web scraping from StockAnalysis.com

        Args:
            progress_callback: Optional callback function(current, total) for progress updates

        Returns:
            DataFrame with scraped dividend stock data
        """
        import sys
        from selenium.webdriver.support.ui import WebDriverWait
        from selenium.webdriver.support import expected_conditions as EC

        print("Initializing web scraper...")
        sys.stdout.flush()
        driver = self.get_chrome_driver()

        try:
            # Navigate to StockAnalysis.com screener
            print(f"Accessing {AppConfig.STOCKANALYSIS_URL}")
            sys.stdout.flush()
            try:
                driver.get(AppConfig.STOCKANALYSIS_URL)
            except Exception as e:
                print(f"  ⚠ Initial page load failed, retrying once... ({e})")
                sys.stdout.flush()
                time.sleep(3)
                driver.get(AppConfig.STOCKANALYSIS_URL)

            # Wait for page to fully load (wait for table to appear)
            try:
                WebDriverWait(driver, 15).until(
                    EC.presence_of_element_located((By.ID, "main-table"))
                )
                print("  ✓ Page loaded successfully")
            except Exception as e:
                print(f"  ⚠ Page load wait timeout, continuing anyway: {e}")
                # #main-table missing this early usually means the real page
                # never rendered (bot-detection challenge/block page, etc.)
                # rather than a normal slow load — log enough to tell the two
                # apart next time instead of guessing from cascading failures.
                try:
                    print(f"  ⚠ Page title at timeout: {driver.title!r}")
                    print(f"  ⚠ Page source snippet: {driver.page_source[:500]!r}")
                except Exception:
                    pass
                time.sleep(3)
            sys.stdout.flush()

            # Configure UI: Step 1 - Click Dividends preset
            print("Configuring screener UI...")
            sys.stdout.flush()
            self._try_click(driver, AppConfig.SCRAPER_XPATHS[0], "Dividends preset")

            # Step 2 - Open indicator panel, select columns by label, close panel
            self._try_click(driver, AppConfig.INDICATORS_TOGGLE_XPATH, "Open Indicators panel")
            time.sleep(1)
            self._select_indicator_columns(driver)
            self._try_click(driver, AppConfig.INDICATORS_TOGGLE_XPATH, "Close Indicators panel")

            # Step 3 - Set 50 rows per page
            self._try_click(driver, AppConfig.SCRAPER_XPATHS[1], "Open rows dropdown")
            self._try_click(driver, AppConfig.SCRAPER_XPATHS[2], "Select 50 rows")
            sys.stdout.flush()

            # Wait for table to reload after config changes
            print("Waiting for table to reload after configuration...")
            sys.stdout.flush()
            try:
                WebDriverWait(driver, 10).until(
                    EC.presence_of_element_located((By.ID, "main-table"))
                )
                # Extra wait for table data to fully render
                time.sleep(2)
                print("  ✓ Table ready")
            except Exception as e:
                print(f"  ⚠ Table wait timeout: {e}")
                time.sleep(3)
            sys.stdout.flush()

            # Scrape all pages
            print(f"\nScraping {AppConfig.MAX_SCRAPE_PAGES} pages...")
            sys.stdout.flush()
            df_list = []
            consecutive_errors = 0
            MAX_CONSECUTIVE_ERRORS = 3

            for page_num in tqdm(range(AppConfig.MAX_SCRAPE_PAGES), desc="Scraping pages"):
                try:
                    # Try to close popup
                    try:
                        popup = driver.find_element(By.XPATH, AppConfig.POPUP_XPATH)
                        popup.click()
                        time.sleep(0.3)
                    except:
                        pass

                    # Wait for table to be present
                    try:
                        WebDriverWait(driver, 10).until(
                            EC.presence_of_element_located((By.ID, "main-table"))
                        )
                    except Exception as e:
                        print(f"\n⚠ Table not found on page {page_num + 1}, retrying... ({e})")
                        sys.stdout.flush()
                        time.sleep(2)
                        # Retry once
                        try:
                            WebDriverWait(driver, 10).until(
                                EC.presence_of_element_located((By.ID, "main-table"))
                            )
                        except:
                            print(f"\n✗ Table still not found on page {page_num + 1}, skipping")
                            sys.stdout.flush()
                            consecutive_errors += 1
                            if consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                                print(f"\n✗ {MAX_CONSECUTIVE_ERRORS} consecutive errors, stopping scrape")
                                sys.stdout.flush()
                                break
                            continue

                    # Extract table HTML
                    table_html = driver.find_element(By.ID, "main-table").get_attribute('outerHTML')

                    # Parse with BeautifulSoup
                    soup = BeautifulSoup(table_html, 'html.parser')

                    # Extract headers
                    headers = [header.text.strip() for header in soup.find_all('th')]

                    # Extract rows
                    rows = []
                    for row in soup.find_all('tr')[1:]:  # Skip header row
                        rows.append([cell.text.strip() for cell in row.find_all('td')])

                    # Create DataFrame
                    if rows and headers:
                        page_df = pd.DataFrame(rows, columns=headers)
                        df_list.append(page_df)
                        consecutive_errors = 0  # Reset on success

                    # Update progress
                    if progress_callback:
                        progress_callback(page_num + 1, AppConfig.MAX_SCRAPE_PAGES)

                    # Navigate to next page
                    if page_num < AppConfig.MAX_SCRAPE_PAGES - 1:
                        try:
                            self._dismiss_overlays(driver)
                            next_button = driver.find_element(By.XPATH, AppConfig.NEXT_BUTTON_XPATH)
                            try:
                                next_button.click()
                            except:
                                driver.execute_script("arguments[0].click();", next_button)
                            time.sleep(AppConfig.PAGE_LOAD_WAIT)
                        except Exception as e:
                            print(f"\n⚠ Could not navigate to next page: {e}")
                            sys.stdout.flush()
                            break

                except KeyboardInterrupt:
                    print(f"\n✗ Scraping interrupted by user at page {page_num + 1}")
                    sys.stdout.flush()
                    break
                except Exception as e:
                    print(f"\n⚠ Error scraping page {page_num + 1}: {type(e).__name__}: {e}")
                    sys.stdout.flush()
                    consecutive_errors += 1
                    if consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                        print(f"\n✗ {MAX_CONSECUTIVE_ERRORS} consecutive errors, stopping scrape")
                        sys.stdout.flush()
                        break

            # Concatenate all DataFrames
            if df_list:
                final_df = pd.concat(df_list, ignore_index=True)
                # StockAnalysis.com renamed 'Div. ($)' to 'Dividend' (Oct 2026);
                # downstream code and final_df2.csv still use the old name.
                final_df = final_df.rename(columns={'Dividend': 'Div. ($)'})
                print(f"\n✓ Successfully scraped {len(final_df)} stocks from {len(df_list)} pages")
                sys.stdout.flush()
                return final_df
            else:
                raise ValueError("No data was scraped - table element may have changed or page failed to load")

        except BaseException as e:
            # Catch BaseException to log even Streamlit StopException or SystemExit
            print(f"\n✗ Scraper terminated: {type(e).__name__}: {e}")
            sys.stdout.flush()
            raise

        finally:
            try:
                driver.quit()
            except:
                pass
            print("WebDriver closed")
            sys.stdout.flush()

    def backup_existing_data(self):
        """
        Create backup of existing data (no timestamp - single backup file)
        Only maintains 2 files: current data + one backup
        """
        raw_path = os.path.join(self.data_dir, 'dividend_from_stockanalysis.csv')
        backup_path = os.path.join(self.data_dir, 'dividend_from_stockanalysis_backup.csv')
        final_path = os.path.join(self.data_dir, 'final_df2.csv')
        final_backup_path = os.path.join(self.data_dir, 'final_df2_backup.csv')

        # Backup raw data
        if os.path.exists(raw_path):
            shutil.copy2(raw_path, backup_path)
            print(f"✓ Backed up raw data to {backup_path}")

        # Backup processed data
        if os.path.exists(final_path):
            shutil.copy2(final_path, final_backup_path)
            print(f"✓ Backed up processed data to {final_backup_path}")

    def validate_scraped_data(self, df: pd.DataFrame) -> dict:
        """
        Validate scraped data and return quality report

        Args:
            df: DataFrame to validate

        Returns:
            dict with validation results and statistics
        """
        validation_report = {
            'valid': True,
            'errors': [],
            'warnings': [],
            'stats': {}
        }

        # Required columns from StockAnalysis.com
        required_columns = [
            'Symbol', 'Company Name', 'Market Cap',
            'Div. ($)', 'Div. Yield', 'Payout Ratio',
            'Div. Growth', 'Payout Freq.', 'Div. Gr. Years',
            'Div. Years', 'Div. Growth 3Y', 'Div. Growth 5Y'
        ]

        # 1. Check DataFrame not empty
        if df.empty:
            validation_report['valid'] = False
            validation_report['errors'].append("Scraped data is empty")
            return validation_report

        # 2. Check minimum row count
        if len(df) < AppConfig.MIN_EXPECTED_STOCKS:
            validation_report['valid'] = False
            validation_report['errors'].append(
                f"Too few stocks scraped: {len(df)} (expected >{AppConfig.MIN_EXPECTED_STOCKS})"
            )

        # 3. Validate column schema
        missing_cols = set(required_columns) - set(df.columns)
        if missing_cols:
            validation_report['valid'] = False
            validation_report['errors'].append(f"Missing columns: {missing_cols}")

        # 4. Data quality checks
        validation_report['stats']['total_rows'] = len(df)
        validation_report['stats']['total_columns'] = len(df.columns)

        # Check for missing/invalid dividend yields
        if 'Div. Yield' in df.columns:
            invalid_yields = df[df['Div. Yield'] == '-']
            validation_report['stats']['stocks_with_dividends'] = len(df) - len(invalid_yields)
            validation_report['stats']['stocks_without_dividends'] = len(invalid_yields)

        # Check for duplicate symbols
        if 'Symbol' in df.columns:
            duplicates = df[df.duplicated('Symbol', keep=False)]
            if len(duplicates) > 0:
                validation_report['warnings'].append(f"Found {len(duplicates)} duplicate symbols")
                validation_report['stats']['duplicate_count'] = len(duplicates)

        return validation_report

    def enrich_with_yfinance(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Enrich each symbol with yfinance metrics via
        modules.dividend_metrics.compute_ticker_metrics (sector, leverage,
        multi-year coverage/growth, dividend history, yield bands, buybacks).

        Runs AppConfig.YFINANCE_MAX_WORKERS threads. Per-symbol failures are
        written to data/enrichment_failures.csv; failed metrics stay NaN.

        Args:
            df: DataFrame with Symbol column

        Returns:
            DataFrame with additional YF columns
        """
        from concurrent.futures import ThreadPoolExecutor, as_completed
        from modules.dividend_metrics import compute_ticker_metrics

        print("\nEnriching data with Yahoo Finance metrics...")
        result = df.copy()
        failures = []  # (symbol, stage, reason)
        metrics_by_symbol = {}

        def _one(symbol):
            try:
                return symbol, compute_ticker_metrics(symbol), None
            except Exception as e:
                return symbol, None, str(e)[:100]

        symbols = result['Symbol'].astype(str).tolist()
        with ThreadPoolExecutor(max_workers=AppConfig.YFINANCE_MAX_WORKERS) as ex:
            futures = [ex.submit(_one, s) for s in symbols]
            for fut in tqdm(as_completed(futures), total=len(futures), desc="Fetching Yahoo Finance data"):
                symbol, metrics, err = fut.result()
                if err:
                    failures.append((symbol, 'ticker_init', err))
                    continue
                for stage, msg in metrics.pop('_errors', []):
                    failures.append((symbol, stage, msg))
                metrics_by_symbol[symbol] = metrics

        # Second pass: retry symbols that failed outright, sequentially and
        # slowly (failures are usually Yahoo throttling under parallel load)
        def _throttled(stage, msg):
            return stage == 'ticker_init' or 'Rate limited' in msg or 'Too Many Requests' in msg

        retry = sorted({s for s, stage, msg in failures if _throttled(stage, msg)})
        if retry:
            print(f"  Retrying {len(retry)} failed/throttled symbols sequentially...")
            failures = [f for f in failures if f[0] not in retry]
            for s in retry:
                time.sleep(2)
                symbol, metrics, err = _one(s)
                if err:
                    failures.append((symbol, 'ticker_init', err))
                    continue
                for stage, msg in metrics.pop('_errors', []):
                    failures.append((symbol, stage, msg))
                metrics_by_symbol[symbol] = metrics

        metrics_df = pd.DataFrame.from_dict(metrics_by_symbol, orient='index')
        metrics_df.index.name = 'Symbol'
        metrics_df = metrics_df.reset_index()

        # Replace any stale enrichment columns from a previous run
        overlap = [c for c in metrics_df.columns if c != 'Symbol' and c in result.columns]
        result = result.drop(columns=overlap).merge(metrics_df, on='Symbol', how='left')
        result['Sector'] = result['Sector'].fillna('')
        result['Industry'] = result['Industry'].fillna('')

        if hasattr(self, '_run_info'):
            self._run_info['enrichment_failures'] = len({f[0] for f in failures})
        fail_path = os.path.join(self.data_dir, 'enrichment_failures.csv')
        if failures:
            fail_df = pd.DataFrame(failures, columns=['Symbol', 'stage', 'reason'])
            fail_df.to_csv(fail_path, index=False)
            print(f"⚠ Enrichment failures: {len(failures)} total — {fail_df['stage'].value_counts().to_dict()}")
            print(f"  Saved to {fail_path}")
        else:
            if os.path.exists(fail_path):
                os.remove(fail_path)
            print("✓ Enrichment complete — no failures")

        return result

    def add_yield_comparison_columns(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Informational yield-vs-history columns (no filtering). Current TTM
        yield and the bands share one source (yfinance, raw prices), so the
        comparison is like-for-like. Valuation itself is judged by
        Yield_Pctl_5Y in data_processor.add_valuation_signal().
        """
        result = df.copy()
        for p in ('5Y', '10Y'):
            avg = pd.to_numeric(result.get(f'Trainling_{p}_avg_dividend_yield'), errors='coerce')
            cur = pd.to_numeric(result.get('Yield_TTM'), errors='coerce')
            col = 'Five_y_DividendYield_diff' if p == '5Y' else 'Ten_y_DividendYield_diff'
            result[col] = ((cur - avg) / avg).where(avg > 0).round(4)
        print(f"✓ Added yield comparison columns: {len(result)} stocks")
        return result


if __name__ == "__main__":

    print("=" * 60)
    print("Standalone Data Collector - Crawl Only")
    print("=" * 60)

    collector = DividendDataCollector()

    try:
        df = collector.collect_stockanalysis_data()

        output_path = os.path.join(
            os.path.dirname(__file__), '..', 'data', 'dividend_from_stockanalysis_solo.csv'
        )
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        df.to_csv(output_path, index=False)

        print(f"\n{'=' * 60}")
        print(f"Results saved to: {output_path}")
        print(f"  Rows: {len(df)}")
        print(f"  Columns: {list(df.columns)}")
        if len(df) > 0:
            print(f"  Sample (first 3 rows):")
            print(df.head(3).to_string(index=False))
        print("=" * 60)

    except Exception as e:
        print(f"\n✗ Crawling failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
