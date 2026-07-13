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
    → modules/data_collector.py → data/final_df2.csv + data/last_updated.txt
                                        ↓
Yahoo Finance (yfinance API)     utils/cache_manager.py (@st.cache_data, 1h TTL for main df)
    → per-symbol historical data        ↓
                                  Streamlit pages (UI)
                                        ↓
                              modules/visualization.py (Plotly charts)
```

### Key modules

- **[app.py](app.py)** — Home page: data source selection (cached CSV vs live scrape), displays main dataset table.
- **[config.py](config.py)** — All constants: file paths, scraping XPaths, default filter values, scoring weights, backtest defaults. Central place for tuning. `AppConfig` for app/scraper settings, `BacktestConfig` for backtest defaults. **Gotcha:** `pages/1_High_Dividend_Screener.py` and `pages/2_Dividend_Growth_Screener.py` hardcode their own slider/weight `value=` defaults rather than reading `AppConfig.DEFAULT_*` / `HIGH_DIV_WEIGHTS` / `DIV_GROWTH_WEIGHTS` — when changing a default, update both the config constant (documentation of intent) and the page's widget default (actual behavior).
- **[modules/data_collector.py](modules/data_collector.py)** — Selenium-based scraper for StockAnalysis.com (`DividendDataCollector`). `update_all_data()` runs the full pipeline in stages: backup existing data → scrape (`collect_stockanalysis_data`) → validate (min 1,000 stocks, `validate_scraped_data`) → filter/process (`process_raw_data_from_df`) → tag Aristocrats/Kings/SCHD categories (`load_premium_stock_lists`, `add_missing_premium_stocks`, `categorize_stocks`) → enrich with yfinance (`enrich_with_yfinance`, adds `FCF_Dividend_Ratio`, `Debt_to_Equity`, `ROE`, `EPS_Growth` and trailing yield stats) → final yield-comparison filter (`apply_yield_comparison_filter`) → save `final_df2.csv` and stamp `data/last_updated.txt` with the completion time (UTC). **Tip:** `update_all_data(use_scraping=False)` skips Selenium entirely and reuses the existing `dividend_from_stockanalysis.csv` raw scrape, re-running only the processing/enrichment stages — use this to backfill a new yfinance field (like `EPS_Growth` was added) into `final_df2.csv` in a few minutes instead of a full re-scrape.
- **[modules/data_processor.py](modules/data_processor.py)** — `filter_stocks()` + `calculate_composite_score()`. Score = Σ(min-max normalized metric × user weight) × 100. `calculate_normalized_metrics()` normalizes yield/years/CAGR/growth/payout plus `FCF_Dividend_Ratio` and `Debt_to_Equity` via `normalize_with_missing_and_outliers()` — a 0.0 value in those two columns means yfinance had no data (scored neutrally at 0.5), and remaining values are winsorized to the 1st/99th percentile before min-max scaling so one extreme outlier doesn't skew everyone else's score. `add_chowder_number()` adds an informational `chowder_number` column (Div. Yield % + 5Y CAGR %) used only by the Dividend Growth Screener, not in scoring. `add_eps_growth_alert()` adds an informational `EPS_Alert` column flagging stocks where 1Y `Div. Growth` exceeds 1Y `EPS_Growth` (dividend growing faster than earnings — a payout-ratio-expansion red flag); stocks with no EPS data (`EPS_Growth == 0.0`) are not flagged. Neither Chowder Number nor the EPS alert affects filtering or scoring. Also has `categorize_market_cap()` / `add_market_cap_tier()` (Russell-style tiers from the `Market Cap` string column).
- **[modules/portfolio_backtester.py](modules/portfolio_backtester.py)** — Day-by-day simulation engine (`run_backtest`). Handles DRIP (fractional shares via `_apply_drip`), qualified/ordinary dividend tax and capital gains tax, rebalancing with deviation threshold (`_should_rebalance` / `_rebalance_portfolio`), and computes 12+ performance metrics via `calculate_performance_metrics` (Sharpe, Sortino, alpha/beta, VaR, max drawdown).
- **[modules/visualization.py](modules/visualization.py)** — Plotly chart builders (bar, scatter/bubble, histogram, gauge, dual-axis, portfolio growth, underwater, tax charts) called from pages.
- **[utils/cache_manager.py](utils/cache_manager.py)** — `@st.cache_data` wrappers: `load_main_dataframe` (1h TTL), `load_historical_prices` / `load_benchmark_data` (24h TTL, per-symbol yfinance history). `clear_all_caches()` clears both `st.cache_data` and `st.cache_resource`; note `app.py`'s own update flow calls `st.cache_data.clear()` directly rather than this helper.
- **[utils/data_loader.py](utils/data_loader.py)** — `DataManager` class; routes between cached CSV load and live scrape depending on user's sidebar selection. `get_data_info()` reports the "Last Updated" timestamp by preferring `data/last_updated.txt` (written at scrape completion, UTC) over the CSV's filesystem mtime — mtime resets on every git checkout/redeploy so it doesn't reflect the real update time. All display timestamps are converted to US Eastern (`US_EASTERN` / `zoneinfo`).

### Pages ([pages/](pages/))

| File | Purpose |
|---|---|
| `1_High_Dividend_Screener.py` | Filters + scores stocks prioritizing yield (default weight 35%, plus FCF-coverage/debt-to-equity sustainability weights). Flags `Div. Yield` above `AppConfig.HIGH_YIELD_WARNING_THRESHOLD` (10%) with an `Alert` column instead of filtering the stock out — a spiked yield is often a falling price, not a bargain. |
| `2_Dividend_Growth_Screener.py` | Same UI pattern but weights 5Y CAGR at 35% and payout ratio at 17% (room-to-grow signal); default min consecutive years is 10 (aligned with Dividend Achievers/Growers index methodology). Displays the informational Chowder Number (`add_chowder_number()`) and EPS growth alert (`add_eps_growth_alert()`). |
| `3_Stock_Details.py` | Per-symbol deep dive: price/yield history (yfinance), dividend history, company info |
| `4_Portfolio_Backtest.py` | Configures and runs `portfolio_backtester.py`, displays metrics + 4-tab chart view |

### Data files ([data/](data/))

- `final_df2.csv` — Primary dataset consumed by the app, produced by the scraper pipeline. Row count varies with market conditions and filtering (currently ~200) — `MIN_EXPECTED_STOCKS = 1000` validates the *raw* scrape (`dividend_from_stockanalysis.csv`, ~5,000+ rows) before Stage 2+ filtering narrows it down, not the final output.
- `dividend_from_stockanalysis.csv` — Raw scrape output before enrichment/filtering; `*_backup.csv` / `*_solo.csv` variants are pipeline backups
- `last_updated.txt` — UTC ISO timestamp marker written when a scrape completes; see `DataManager._get_last_updated_time` above
- `dividend_aristocrats.csv`, `dividend_kings.csv`, `schd_holdings.csv` — Static reference lists used to tag the `Category` column
- `sector_industry.csv`, `screener_indicator_xpaths.csv` — Supporting reference/scraper metadata

### Scraping notes

- Scraper uses Selenium with headless Chrome; XPaths for StockAnalysis.com are stored in `AppConfig.SCRAPER_XPATHS` (plus `POPUP_XPATH`, `NEXT_BUTTON_XPATH`, `INDICATORS_TOGGLE_XPATH`, `INDICATOR_PANEL_XPATH`) in [config.py](config.py). When the site changes layout, update these XPaths (use `find_xpaths.py` and `debug_scraper*.py` at the repo root to probe the new structure).
- `MAX_SCRAPE_PAGES = 115` and `MIN_EXPECTED_STOCKS = 1000` are validation guards; a scrape that returns fewer than 1,000 stocks fails validation and aborts before overwriting `final_df2.csv`.
- A full scrape+enrich run takes ~3-5 minutes (Selenium paging + yfinance enrichment across `YFINANCE_MAX_WORKERS = 5` workers).
