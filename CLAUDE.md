# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Install dependencies
pip install -r requirements.txt

# Run the app
streamlit run app.py
# Opens at http://localhost:8501
```

No test suite or linter is configured in this project.

## Architecture

This is a Streamlit multi-page web app for dividend stock screening, analysis, and portfolio backtesting.

### Data flow

```
StockAnalysis.com (Selenium scraping)
    → modules/data_collector.py → data/final_df2.csv
                                        ↓
Yahoo Finance (yfinance API)     utils/cache_manager.py (@st.cache_data, 1h TTL)
    → per-symbol historical data        ↓
                                  Streamlit pages (UI)
                                        ↓
                              modules/visualization.py (Plotly charts)
```

### Key modules

- **[app.py](app.py)** — Home page: data source selection (cached CSV vs live scrape), displays main dataset table.
- **[config.py](config.py)** — All constants: file paths, scraping XPaths, default filter values, scoring weights, backtest defaults. Central place for tuning.
- **[modules/data_collector.py](modules/data_collector.py)** — Selenium-based scraper for StockAnalysis.com (`DividendDataCollector`). `update_all_data()` runs the full pipeline: scrape → validate (min 1,000 stocks) → enrich with yfinance → save CSV.
- **[modules/data_processor.py](modules/data_processor.py)** — `filter_stocks()` + `calculate_composite_score()`. Score = Σ(min-max normalized metric × user weight) × 100.
- **[modules/portfolio_backtester.py](modules/portfolio_backtester.py)** — Day-by-day simulation engine. Handles DRIP (fractional shares), qualified/ordinary dividend tax, rebalancing with deviation threshold, and computes 12+ performance metrics (Sharpe, Sortino, alpha, beta, VaR, max drawdown).
- **[modules/visualization.py](modules/visualization.py)** — Plotly chart builders (bar, bubble, line, histogram, underwater charts) called from pages.
- **[utils/cache_manager.py](utils/cache_manager.py)** — `@st.cache_data` wrappers: `load_main_dataframe` (1h TTL), `load_historical_prices` / `load_benchmark_data` (24h TTL). Call `clear_all_caches()` after a scrape to force reload.
- **[utils/data_loader.py](utils/data_loader.py)** — `DataManager` class; routes between cached CSV load and live scrape depending on user's sidebar selection.

### Pages ([pages/](pages/))

| File | Purpose |
|---|---|
| `1_High_Dividend_Screener.py` | Filters + scores stocks prioritizing yield (default weight 50%) |
| `2_Dividend_Growth_Screener.py` | Same UI pattern but weights 5Y CAGR at 35% |
| `3_Stock_Details.py` | Per-symbol deep dive: price/yield history (yfinance), dividend history, company info |
| `4_Portfolio_Backtest.py` | Configures and runs `portfolio_backtester.py`, displays metrics + 4-tab chart view |

### Data files ([data/](data/))

- `final_df2.csv` — Primary dataset (~1,000+ stocks, produced by scraper)
- `dividend_aristocrats.csv`, `dividend_kings.csv`, `schd_holdings.csv` — Static reference lists

### Scraping notes

- Scraper uses Selenium with headless Chrome; XPaths for StockAnalysis.com are stored in `AppConfig.SCRAPER_XPATHS` in [config.py](config.py). When the site changes layout, update these XPaths (use `find_xpaths.py` and `debug_scraper*.py` to probe the new structure).
- `MAX_SCRAPE_PAGES = 115` and `MIN_EXPECTED_STOCKS = 1000` are validation guards.
