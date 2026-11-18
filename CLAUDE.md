# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

**Investing rules live in [docs/investment_criteria.md](docs/investment_criteria.md)** (Korean) — why each threshold exists, sector rules, safety grade, valuation, portfolio and Korean-tax criteria. This file covers code structure only. Numeric thresholds are defined once in [config.py](config.py); when a rule changes, update config first, then the criteria doc.

## Commands

```bash
# Use the project venv - the global Python lacks selenium and other deps
.venv/Scripts/python.exe -m pip install -r requirements.txt

# Run the app (http://localhost:8501)
.venv/Scripts/streamlit.exe run app.py

# Full data update (scrape + process + enrich + git commit/push)
.venv/Scripts/python.exe local_update.py

# Re-process/enrich only, reusing the last raw scrape (~3 min, no Selenium)
.venv/Scripts/python.exe -c "from modules.data_collector import DividendDataCollector; DividendDataCollector().update_all_data(use_scraping=False)"
```

No test suite or linter is configured. Page smoke test: `streamlit.testing.v1.AppTest.from_file('pages/<page>.py').run()` and check `at.exception`.

## Architecture

Streamlit multi-page app for dividend stock screening, per-stock analysis, portfolio diagnosis and backtesting.

### Data flow

```
StockAnalysis.com (Selenium) ─┐
FRED CPI + ^TNX (macro) ──────┼─ modules/data_collector.py ─→ data/final_df2.csv (~380 rows)
Yahoo Finance (yfinance) ─────┘   (enrichment: modules/dividend_metrics.py)
                                              │
                    utils/cache_manager.load_prepared_dataframe()
                    = final_df2.csv → data_processor.prepare_all_metrics()  (universe-wide)
                                              │
              pages: filter_stocks() → calculate_composite_score() / diagnose_portfolio()
```

Derived columns (sector group, safety grade, valuation, scores...) are **not stored** in the CSV — they are recomputed by `prepare_all_metrics()` on load. Only raw/enriched fields are persisted.

### Update pipeline — `DividendDataCollector.update_all_data(use_scraping=True)`

Wraps `_run_update_pipeline()`; every run is logged to `data/update_history.csv` and a Telegram alert is sent on failure or when >10% of tickers fail enrichment.

| Stage | What | Method |
|---|---|---|
| 0 | Backup data, refresh macro benchmarks (10Y Treasury 3Y MA, 5Y annualized CPI) | `backup_existing_data`, `macro_benchmarks.refresh_macro_benchmarks` |
| 1 | Scrape (or load raw CSV), validate ≥ `MIN_EXPECTED_STOCKS` (1,000) raw rows | `collect_stockanalysis_data`, `validate_scraped_data` |
| 2 | Universe filter: yield ≥ 2%, growth streak ≥ 5y, 1Y growth ≥ 3%, 5Y CAGR ≥ CPI. Aristocrats/Kings/SCHD bypass | `process_raw_data_from_df` → `apply_dividend_criteria_filters` |
| 2.5 | Add missing premium stocks, tag `Category` | `add_missing_premium_stocks`, `categorize_stocks` |
| 3 | yfinance enrichment (thread pool `YFINANCE_MAX_WORKERS`=5 + sequential retry pass); failures → `data/enrichment_failures.csv` | `enrich_with_yfinance` → `dividend_metrics.compute_ticker_metrics` |
| 4 | Informational yield-vs-history diff columns (**no filtering**) | `add_yield_comparison_columns` |
| 5 | Save `final_df2.csv`, stamp `last_updated.txt` (UTC) | — |

### Key modules

- **[config.py](config.py)** — All constants. `AppConfig`: universe floors, macro settings, Chowder constants, `SECTOR_RULES`, safety-grade cutoffs, crisis years, timing-indicator settings, portfolio flag thresholds, staleness/Telegram. `BacktestConfig`: backtest defaults, `TAX_PRESETS` (KR default / US), `KR_FINANCIAL_INCOME_THRESHOLD_KRW`, `FX_TICKER`.
- **[modules/dividend_metrics.py](modules/dividend_metrics.py)** — Per-ticker yfinance metrics, shared by the pipeline and portfolio diagnosis. `compute_ticker_metrics(symbol)` returns leverage (`Net_Debt_EBITDA`, `Interest_Coverage`), 3Y coverage (`FCF_Dividend_Ratio`, `OCF_Dividend_Ratio`), 3Y revenue/EPS CAGR, `Revenue_Decline_Years`, `EPS_CV`, buybacks, yield bands (`Yield_TTM`, `Yield_Pctl_5Y`, 5Y/10Y avg/min/max), cut detection (`Div_Cut_Detected`, `Div_Last_Cut_Year`, `Div_CAGR_5Y_Peak`) and timing (`Price_vs_MA20`, `RSI_14`, `MFI_14`, `Timing_As_Of`), plus an `_errors` list.
- **[modules/macro_benchmarks.py](modules/macro_benchmarks.py)** — `refresh_macro_benchmarks()` writes `data/macro_benchmarks.json`; `load_macro_benchmarks()` reads it, falling back to config defaults (`source='config_fallback'`).
- **[modules/data_processor.py](modules/data_processor.py)** — All derived metrics and screening. Call `prepare_all_metrics(df)` on the **full universe** first (percentile ranks are universe-wide), then `filter_stocks(...)`, then `calculate_composite_score(df, weights, score_type)` (`high_dividend` → `high_div_composite`, `dividend_growth` → `dividend_growth_composite`, 0–100).
  - `sector_group()` → `Sector_Group` (general/energy/utility/reit/mlp/bank/financial) keys into `AppConfig.SECTOR_RULES`.
  - `add_adjusted_dividend_metrics()` → `Div_CAGR_5Y_Adj`, `Cut_Flag`; `add_div_coverage()` → `Div_Coverage`, `Coverage_Basis`; `add_chowder_number()`; `add_eps_growth_alert()`; `add_shareholder_yield()`; `add_crisis_test()` → `Crisis_Passed`, `Crisis_Count`; `add_growth_badge()`; `add_timing_signal()`; `add_safety_grade()` → `Safety_Grade/Score/Detail`; `add_valuation_signal()` → `Valuation`, `Yield_Trap`.
  - `filter_stocks()` gates: dividend floors, optional Chowder, sector payout/leverage/interest/coverage rules, EPS > 0, ROE floor, 3 consecutive revenue declines, optional `min_market_cap`. **NaN passes as "unknown"** (except `min_market_cap`).
  - `calculate_normalized_metrics()` → percentile ranks (`norm_*`, missing = 0.5). Weight key `fcf_coverage` maps to `norm_coverage`.
- **[modules/portfolio_diagnosis.py](modules/portfolio_diagnosis.py)** — `diagnose_portfolio(holdings, universe)` → `holdings`, `monthly`, `sectors`, `grades`, `summary` (USD/KRW, after-tax, flags). No Streamlit; symbols outside the universe (incl. ETFs) are enriched live.
- **[modules/portfolio_backtester.py](modules/portfolio_backtester.py)** — Day-by-day simulation (`run_backtest`): DRIP, dividend/capital-gains tax with FIFO tax lots (KR preset: annual netting + ₩2.5M deduction), rebalancing, metrics (Sharpe/Sortino/alpha/beta/VaR/MDD) using the period-average ^IRX risk-free rate, `krw_summary()`.
- **[modules/update_log.py](modules/update_log.py)** — `record_update()`, `load_history()`, `data_age_days()`, `notify()` (Telegram via `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` env vars; never raises, silent when unset).
- **[modules/visualization.py](modules/visualization.py)** — Plotly chart builders.
- **[utils/cache_manager.py](utils/cache_manager.py)** — `load_prepared_dataframe()` (cached prepared universe; use this in pages), `load_main_dataframe()`, `load_macro()`, `show_data_freshness_warning()` (warns past `STALE_DATA_DAYS`=4 with the last failure), `load_historical_prices()` / `load_benchmark_data()`, `clear_all_caches()`.
- **[utils/data_loader.py](utils/data_loader.py)** — `DataManager`; "Last Updated" prefers `data/last_updated.txt` over file mtime (reset by git checkout); displayed in US Eastern.
- **[local_update.py](local_update.py)** — Scheduled local update: `git pull --ff-only` → full pipeline → commit/push `DATA_FILES`; Telegram alert on pull/push failure. Exists because Cloudflare blocks the GitHub Actions scrape (scheduled Actions run is disabled; manual dispatch only).

### Pages ([pages/](pages/))

| File | Purpose |
|---|---|
| `1_High_Dividend_Screener.py` | Yield floor defaults to the 10Y Treasury 3Y MA, 5Y CAGR floor to CPI. Score: yield 50 / adj. 5Y CAGR 25 / dividend coverage 25. `Alert` flags yield > 10% |
| `2_Dividend_Growth_Screener.py` | Yield ≥ 2%, 10y streaks, 5Y CAGR ≥ max(5%, CPI), Chowder Rule gate (on), optional market cap ≥ $20B. Score: adj. 5Y CAGR 60 / yield 40 |
| `3_Stock_Details.py` | Per-symbol deep dive: 20-metric health grid, cut/trap/EPS flags, crisis and growth badges, price/yield/dividend history |
| `4_Portfolio_Backtest.py` | Backtest with tax presets (KR default), KRW view, survivorship-bias warning |
| `5_Portfolio_Diagnosis.py` | Holdings (table or pasted "SYMBOL SHARES") → income, monthly calendar, sector/grade concentration, flags |

### Data files ([data/](data/))

- `final_df2.csv` — App dataset (~380 rows). `MIN_EXPECTED_STOCKS` validates the *raw* scrape (~5,700 rows), not this.
- `dividend_from_stockanalysis.csv` — Raw scrape; `*_backup.csv` are pipeline backups.
- `macro_benchmarks.json` — 10Y Treasury MA / CPI used as default floors.
- `update_history.csv` — One row per pipeline run (status, mode, row counts, failures, macro values, error).
- `enrichment_failures.csv` — Present only when the last run had yfinance failures.
- `last_updated.txt` — UTC completion timestamp.
- `dividend_aristocrats.csv`, `dividend_kings.csv`, `schd_holdings.csv` — Premium lists for `Category`; `sector_industry.csv`, `screener_indicator_xpaths.csv` — reference/scraper metadata.

## Gotchas

- **Always `auto_adjust=False` for yfinance `history()`** (pipeline, cache_manager, backtester). The default dividend-adjusted close inflates historical yields and double-counts dividends in the DRIP backtest.
- **Screener widget defaults are hardcoded in the pages**, not read from `AppConfig.DEFAULT_*` / `*_WEIGHTS`. Macro-linked defaults (yield floor, 5Y CAGR) come from `load_macro()`. When changing a default, update the page widget (actual behavior) and config/criteria doc (intent).
- **Rank before filtering**: percentile scores must come from `prepare_all_metrics()` on the whole universe; ranking a filtered subset changes every score.
- **Annual dividend = sum of the last f regular payments** (f = median payments/year over 5 complete years, specials > 1.5× median excluded), not a 365-day window — date jitter can catch 5 quarterly payments.
- **Cut detection needs both methods to agree** (per-payment YoY and calendar-year totals, ±1 year), and a streak ≥ `CUT_CHECK_STREAK_YEARS` (10) overrides it. Either method alone gave many false positives (frequency changes, year-boundary payments, missing yfinance records).
- **Yahoo rate limits** (`YFRateLimitError`) after heavy runs: `compute_ticker_metrics` retries with backoff and the pipeline does a sequential retry pass; if a rerun still fails, wait and rerun.
- **Tickers with dots** (`BF.B`) must be passed to yfinance as `BF-B` — convert only at the yfinance call; keep `Symbol` as-is (it is the join key with the premium lists).
- **Share-class duplicates**: the universe can hold two classes of one company (currently `MKC` and `MKC.V`), counted as separate rows. Unresolved.
- **Don't replace `Div. Gr. Years` with a yfinance count**: counting increases from yfinance dividend history badly undercounts (KO 64 → 23 years, PH 70 → 9) because of gaps in its long history. Keep the StockAnalysis value.
- **Windows console encoding**: set `PYTHONIOENCODING=utf-8` (or reconfigure stdout as `local_update.py` does) — the pipeline prints ✓/⚠ and Korean text.
- Scraper XPaths live in `AppConfig.SCRAPER_XPATHS` etc.; when StockAnalysis.com changes layout, probe with `find_xpaths.py` / `debug_scraper*.py`. The site now labels the dividend column `Dividend`; `collect_stockanalysis_data` renames it back to `Div. ($)` after concatenating pages (validation requires it).
