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
    DEFAULT_PAYOUT_MAX = 0.70
    DEFAULT_MIN_YEARS = 5
    DEFAULT_MIN_DIV_YEARS = 5
    DEFAULT_MIN_GROWTH = 0.03
    DEFAULT_MIN_GROWTH_5Y = 0.03

    # Universe (pipeline Stage 2) gates for non-premium stocks - the loosest
    # bar both screeners share. Payout ratio is NOT gated here: the raw scrape
    # has no sector, and payout rules are sector-specific (see SECTOR_RULES),
    # so payout is gated in filter_stocks() where Sector is known.
    UNIVERSE_MIN_YIELD = 0.02          # dividend yield floor (both screeners)
    UNIVERSE_MIN_GROWTH_YEARS = 5      # consecutive dividend growth years
    UNIVERSE_MIN_GROWTH_1Y = 0.03      # 1Y dividend growth
    # 5Y dividend CAGR floor = 5Y annualized CPI (macro_benchmarks.json)

    # Macro benchmarks (modules/macro_benchmarks.py -> data/macro_benchmarks.json)
    MACRO_BENCHMARKS_FILE = "macro_benchmarks.json"
    RATE_TICKER = "^TNX"               # 10Y US Treasury yield (yfinance, in %)
    RATE_MA_YEARS = 3                  # High Dividend yield floor = 10Y 3Y moving average
    CPI_FRED_SERIES = "CPIAUCSL"       # CPI-U, seasonally adjusted (FRED)
    CPI_YEARS = 5                      # dividend 5Y CAGR is compared to 5Y annualized CPI
    MACRO_FALLBACK_RATE = 0.045        # used only if no fetch has ever succeeded
    MACRO_FALLBACK_CPI = 0.03

    # Chowder Rule (Dividend Growth track gate): Div. Yield % + 5Y CAGR %
    CHOWDER_YIELD_PIVOT = 0.03         # yield >= 3% -> needs CHOWDER_MIN_HIGH_YIELD
    CHOWDER_MIN_HIGH_YIELD = 12.0
    CHOWDER_MIN_LOW_YIELD = 15.0

    # 5Y CAGR cut-rebound correction: below this streak, 5Y CAGR is replaced
    # by min(StockAnalysis 5Y, peak-based 5Y) and cut detection applies.
    CUT_CHECK_STREAK_YEARS = 10
    CUT_DETECT_THRESHOLD = 0.10        # >10% drop counts as a cut
    # Suspension: no regular payment for SUSPEND_GAP_INTERVALS payment intervals
    # (+ grace days for date jitter), e.g. quarterly -> 151 days. Also used to
    # stop carrying a stopped dividend forward in Yield_TTM.
    SUSPEND_GAP_INTERVALS = 1.5
    SUSPEND_GAP_GRACE_DAYS = 15

    # Sector-specific cutoffs. Group is assigned by data_processor.sector_group().
    #   max_nd_ebitda / min_int_cov: None = not applicable (gate skipped)
    #   coverage: which coverage metric feeds Div_Coverage
    #     'fcf' = 3Y FCF / dividends, 'ocf' = 3Y operating cash flow / dividends,
    #     'eps' = 1 / payout ratio (earnings coverage)
    #   min_coverage: pass/fail gate on Div_Coverage (None = scored only)
    #   payout_max: None = use screener slider, 'exempt' = no payout gate,
    #     float = sector cap replaces the slider maximum
    #   exempt_eps_roe: skip Trailing_EPS<=0 and ROE gates (GAAP earnings are
    #     structurally distorted by depreciation for REITs/MLPs)
    SECTOR_RULES = {
        'general':   {'max_nd_ebitda': 3.5, 'min_int_cov': 5.0, 'coverage': 'fcf', 'min_coverage': None, 'payout_max': None,     'exempt_eps_roe': False},
        'energy':    {'max_nd_ebitda': 2.0, 'min_int_cov': 5.0, 'coverage': 'fcf', 'min_coverage': None, 'payout_max': None,     'exempt_eps_roe': False},
        'utility':   {'max_nd_ebitda': 6.5, 'min_int_cov': 2.0, 'coverage': 'eps', 'min_coverage': None, 'payout_max': 0.80,     'exempt_eps_roe': False},
        'reit':      {'max_nd_ebitda': 6.5, 'min_int_cov': 2.0, 'coverage': 'ocf', 'min_coverage': 1.2,  'payout_max': 'exempt', 'exempt_eps_roe': True},
        'mlp':       {'max_nd_ebitda': 6.5, 'min_int_cov': 2.0, 'coverage': 'ocf', 'min_coverage': 1.2,  'payout_max': 'exempt', 'exempt_eps_roe': True},
        'bank':      {'max_nd_ebitda': None, 'min_int_cov': None, 'coverage': 'eps', 'min_coverage': None, 'payout_max': 0.60,   'exempt_eps_roe': False},
        'financial': {'max_nd_ebitda': 3.5, 'min_int_cov': 5.0, 'coverage': 'eps', 'min_coverage': None, 'payout_max': 0.60,     'exempt_eps_roe': False},
    }

    # Revenue trend gate: N consecutive annual revenue declines fails the stock
    REVENUE_DECLINE_YEARS_FAIL = 3

    # Valuation signal (Yield_Pctl_5Y = percentile of current TTM yield within
    # its own 5Y daily history, raw prices)
    VALUATION_CHEAP_PCTL = 70
    VALUATION_RICH_PCTL = 30

    # Dividend safety grade cutoffs (share of available component points)
    SAFETY_GRADE_CUTOFFS = [('A', 0.85), ('B', 0.70), ('C', 0.55), ('D', 0.40)]  # else 'F'
    SAFETY_MIN_COMPONENTS = 3

    # Crisis test: label -> year a cut would show up. A stock "passed" a crisis
    # when its consecutive-increase streak (Div. Gr. Years) covers that year:
    # streak >= current_year - year. Passing SAFETY_CRISIS_BONUS_LABEL adds a
    # bonus safety component (2 points); failing it adds nothing (no penalty).
    CRISIS_YEARS = {'2000 IT버블': 2001, '2008 금융위기': 2009, '2020 코로나': 2020}
    SAFETY_CRISIS_BONUS_LABEL = '2008 금융위기'

    # Buy-timing indicators (display only, as of the data update date)
    TIMING_MA_DAYS = 20
    TIMING_RSI_DAYS = 14
    TIMING_RSI_OVERSOLD = 30
    TIMING_MFI_DAYS = 14
    TIMING_MFI_OVERSOLD = 20

    # Dividend Growth screener optional market-cap floor (off by default)
    GROWTH_MIN_MARKET_CAP_USD = 20e9

    # Dividend yield above this is flagged as "verify for price collapse"
    # rather than filtered out (see High Dividend Screener Alert column)
    HIGH_YIELD_WARNING_THRESHOLD = 0.10

    # ROE gate (percentage scale, 15.0 =~ 15%). Leverage is gated per sector
    # via SECTOR_RULES (net debt / EBITDA + interest coverage), not D/E:
    # D/E is distorted by buybacks shrinking equity (HD, PEP, CL...).
    # Missing data (NaN) passes through as "unknown" rather than failing.
    DEFAULT_MIN_ROE = 0.0

    # Scoring weights (High Dividend)
    # Redesigned from a 10-factor weighted blend to a 3-factor composite:
    # spreading weight across 10 metrics diluted differentiation (a stock
    # mediocre on everything could outscore one excellent on the metrics
    # that actually matter for "high quality high yield"). Years, payout,
    # 1Y growth, debt, revenue growth, and ROE are now pass/fail gates
    # (sidebar filters in the screener page) instead of scored inputs -
    # mirroring how SCHD's underlying index (Dow Jones US Dividend 100)
    # screens on eligibility first and ranks survivors on just 4 factors,
    # and how the "Chowder Rule" treats payout ratio as a pre-screen rather
    # than part of the score. Payout ratio in particular is dropped from
    # scoring because it's a GAAP/net-income metric that's structurally
    # distorted for REITs/utilities (high non-cash depreciation) -
    # fcf_coverage (cash-flow based) carries that signal more reliably.
    HIGH_DIV_WEIGHTS = {
        'yield': 0.50,
        'cagr': 0.25,
        'fcf_coverage': 0.25
    }

    # Scoring weights (Dividend Growth)
    # Redesigned from an 8-factor weighted blend to a 2-factor composite,
    # mirroring the Chowder Rule - the industry-standard dividend-growth
    # heuristic (yield + 5Y dividend growth CAGR, summed) - and real index
    # methodologies (S&P Dividend Growers Index / VIG, Nasdaq Dividend
    # Achievers) which don't score payout/years/ROE/revenue growth at all,
    # only screen on them. Growth years, payment years, 1Y growth, payout
    # ratio, debt-to-equity, ROE, and revenue growth are now pass/fail
    # gates (sidebar filters) instead of scored inputs, same rationale as
    # HIGH_DIV_WEIGHTS. cagr is weighted above yield (60/40 rather than the
    # Chowder Rule's even split) to preserve this screener's growth-first
    # identity relative to the High Dividend Screener.
    DIV_GROWTH_WEIGHTS = {
        'cagr': 0.60,
        'yield': 0.40
    }

    # Cache settings
    CACHE_TTL_HOURS = 24

    # UI settings
    TABLE_PAGE_SIZE = 50
    CHART_HEIGHT = 500

    # Portfolio diagnosis (modules/portfolio_diagnosis.py) concentration flags
    PORTFOLIO_MAX_HOLDING_INCOME_SHARE = 0.20   # one holding > 20% of dividend income
    PORTFOLIO_MAX_SECTOR_VALUE_SHARE = 0.35     # one sector group > 35% of portfolio value
    PORTFOLIO_MAX_WEAK_GRADE_INCOME_SHARE = 0.25  # Safety D/F/N/A > 25% of income
    KR_DIVIDEND_WITHHOLDING = 0.15              # US withholding for Korean residents

    # Data freshness: warn in the app when the last successful update is older
    # than this (calendar days - covers weekends/holidays without nagging)
    STALE_DATA_DAYS = 4
    UPDATE_HISTORY_FILE = "update_history.csv"

    # Telegram settings (optional) - used by modules/update_log.py to alert on
    # failed or degraded data updates. Set both env vars to enable.
    TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
    TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

    # ===== Korean stocks (docs/kr_design.md) - collection stage only for now =====
    KR_UNIVERSE_MIN_MARCAP_KRW = 100_000_000_000   # 1,000억 market cap
    KR_UNIVERSE_MIN_AMOUNT20_KRW = 500_000_000     # 5억 20-day average traded value
    # DART reports to pull: business-report years for 배당사항 (each covers 3 years),
    # full financials (each covers 2 years) and treasury stock (1 year each)
    KR_DART_ALOT_YEARS = (2017, 2020, 2023, 2025)
    KR_DART_FIN_YEARS = (2023, 2025)
    KR_DART_TREASURY_YEARS = (2023, 2024, 2025)
    KR_DART_RATE_S = 1.0                           # seconds between DART calls (limit 20,000/day)
    KR_KIS_DIVIDEND_SINCE = "20020101"             # KIS 예탁원 배당일정 history start


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

    # Risk-free rate for Sharpe/Sortino: the backtester uses the ^IRX average
    # over the backtest period; this is only the fallback if that fetch fails
    RISK_FREE_RATE = 0.03

    # Tax presets (rates as decimals). 'annual_cg_deduction_krw' switches the
    # capital-gains model to Korean rules: gains/losses net within a calendar
    # year and only the excess over the deduction is taxed.
    TAX_PRESETS = {
        '한국 거주자 (KR)': {
            'qualified_dividend_rate': 0.15,       # US withholding under the KR-US treaty
            'ordinary_dividend_rate': 0.15,
            'long_term_capital_gains_rate': 0.22,  # 20% + 2% local income tax
            'annual_cg_deduction_krw': 2_500_000,
        },
        '미국 거주자 (US)': {
            'qualified_dividend_rate': 0.15,
            'ordinary_dividend_rate': 0.22,
            'long_term_capital_gains_rate': 0.15,
        },
    }
    DEFAULT_TAX_PRESET = '한국 거주자 (KR)'
    # Korean comprehensive financial income taxation threshold (dividends +
    # interest per calendar year). Above it, income is taxed at progressive
    # rates up to 49.5% - the backtest only flags the years, it can't model it.
    KR_FINANCIAL_INCOME_THRESHOLD_KRW = 20_000_000
    FX_TICKER = 'KRW=X'  # USD/KRW

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
