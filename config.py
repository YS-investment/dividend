"""
Configuration settings and constants for the Dividend Stock Analysis Platform
"""

import os
from dataclasses import dataclass

@dataclass
class AppConfig:
    # Data paths
    DATA_DIR = "data"
    MAIN_DATA_FILE = "final_df2.csv"
    RAW_DATA_FILE = "dividend_from_stockanalysis.csv"
    LAST_UPDATED_FILE = "last_updated.txt"
    SECTOR_DATA_FILE = "sector_industry.csv"
    DIVIDEND_ARISTOCRATS_FILE = "dividend_aristocrats.csv"
    DIVIDEND_KINGS_FILE = "dividend_kings.csv"
    SCHD_HOLDINGS_FILE = "schd_holdings.csv"

    # Scraping settings
    STOCKANALYSIS_URL = "https://stockanalysis.com/stocks/screener/"
    SELENIUM_HEADLESS = True
    MAX_SCRAPE_PAGES = 115
    SCRAPE_TIMEOUT = 300  # 5 minutes
    PAGE_LOAD_WAIT = 1  # seconds between actions

    # XPath selectors for web scraping
    POPUP_XPATH = '/html/body/div/div[2]/div/button'
    NEXT_BUTTON_XPATH = '//*[@id="main"]/div[3]/nav[2]/button[2]'

    # Screener UI setup XPaths (non-indicator steps)
    SCRAPER_XPATHS = [
        "//button[contains(text(), 'Dividends')]",  # Click Dividends filter
        '//*[@id="main"]/div[3]/nav[2]/div/div/button',  # Open rows dropdown
        '//*[@id="main"]/div[3]/nav[2]/div/div/div/button[2]',  # Select 50 rows
    ]

    # Indicator panel toggle button (open and close, same element)
    INDICATORS_TOGGLE_XPATH = '//*[@id="main"]/div[3]/div[1]/div/div[3]/button'

    # Indicator panel checkbox container
    INDICATOR_PANEL_XPATH = '//*[@id="main"]/div[3]/div[1]/div/div[3]/div/div[2]'

    # Label text to search for inside the indicator panel (site display strings)
    INDICATOR_LABELS = [
        'Dividend Growth Years',   # → Div. Gr. Years
        'Dividend Payment Years',  # → Div. Years
        'Dividend Growth (3Y)',    # → Div. Growth 3Y
        'Dividend Growth (5Y)',    # → Div. Growth 5Y
    ]

    # Data validation thresholds
    MIN_EXPECTED_STOCKS = 1000  # Minimum stocks to consider scraping successful

    # API settings
    YFINANCE_MAX_WORKERS = 5
    REQUEST_DELAY = 0.5  # seconds

    # Default filter values - High Dividend
    DEFAULT_MIN_YIELD = 0.035
    DEFAULT_PAYOUT_MIN = 0.20
    DEFAULT_PAYOUT_MAX = 0.80
    DEFAULT_MIN_YEARS = 5
    DEFAULT_MIN_DIV_YEARS = 5
    DEFAULT_MIN_GROWTH = 0.01
    DEFAULT_MIN_GROWTH_5Y = 0.01

    # Scoring weights (High Dividend)
    HIGH_DIV_WEIGHTS = {
        'yield': 0.5,
        'years': 0.1,
        'div_years': 0.1,
        'cagr': 0.1,
        'growth': 0.1,
        'payout': 0.1
    }

    # Scoring weights (Dividend Growth)
    DIV_GROWTH_WEIGHTS = {
        'cagr': 0.35,
        'growth': 0.2,
        'yield': 0.25,
        'years': 0.05,
        'div_years': 0.05,
        'payout': 0.1
    }

    # Cache settings
    CACHE_TTL_HOURS = 24

    # UI settings
    TABLE_PAGE_SIZE = 50
    CHART_HEIGHT = 500

    # Telegram settings (optional)
    TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
    TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")


@dataclass
class BacktestConfig:
    """Portfolio backtest configuration"""

    # Default parameters
    DEFAULT_INITIAL_INVESTMENT = 10000
    DEFAULT_MONTHLY_CONTRIBUTION = 0
    DEFAULT_DRIP_FEE = 0.0

    # Tax rates (default values)
    DEFAULT_QUALIFIED_DIVIDEND_TAX = 0.15
    DEFAULT_ORDINARY_DIVIDEND_TAX = 0.22
    DEFAULT_LONG_TERM_CAPITAL_GAINS_TAX = 0.15
    DEFAULT_SHORT_TERM_CAPITAL_GAINS_TAX = 0.22

    # Risk-free rate for Sharpe/Sortino calculation
    RISK_FREE_RATE = 0.02  # 2%

    # Benchmark
    DEFAULT_BENCHMARK = 'SPY'

    # Max stocks in portfolio
    MAX_PORTFOLIO_STOCKS = 20

    # Allocation methods
    ALLOCATION_METHODS = [
        "Equal Weight",
        "Custom Weight",
        "Yield Weight",
        "Market Cap Weight"
    ]

    # Date range defaults
    DEFAULT_START_DATE = "2015-01-01"
    DEFAULT_END_DATE = "2023-12-31"

    # Rebalancing settings
    REBALANCING_FREQUENCIES = [
        "No Rebalancing",
        "Monthly",
        "Quarterly",
        "Semi-Annually",
        "Annually"
    ]

    DEFAULT_REBALANCING_FREQUENCY = "No Rebalancing"
    DEFAULT_REBALANCING_FEE = 0.001  # 0.1% per trade
    DEFAULT_REBALANCING_THRESHOLD = 0.05  # 5% deviation threshold


# Helper functions
def get_data_path(filename: str) -> str:
    """Get full path for data file"""
    return os.path.join(AppConfig.DATA_DIR, filename)


def get_main_data_path() -> str:
    """Get path for main processed data"""
    return get_data_path(AppConfig.MAIN_DATA_FILE)


def get_raw_data_path() -> str:
    """Get path for raw scraped data"""
    return get_data_path(AppConfig.RAW_DATA_FILE)


def get_last_updated_path() -> str:
    """Get path for the data-update timestamp marker file"""
    return get_data_path(AppConfig.LAST_UPDATED_FILE)
