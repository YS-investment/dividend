"""
Macro benchmarks used as screening thresholds:
  - 10Y US Treasury yield, 3-year moving average (High Dividend yield floor)
  - 5-year annualized CPI inflation (dividend 5Y CAGR floor)

Fetched during the data pipeline and stored in data/macro_benchmarks.json so
the app and skill scripts read one consistent snapshot instead of hitting the
network on every page load. If a fetch fails, the previous snapshot is kept;
if none exists, AppConfig fallback values are used (flagged in 'source').
"""

import io
import json
import os
import urllib.request
from datetime import datetime, timezone

import pandas as pd

from config import AppConfig, get_data_path

FRED_CSV_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={series}"


def _macro_path() -> str:
    return get_data_path(AppConfig.MACRO_BENCHMARKS_FILE)


def fetch_treasury_ma(ticker: str = AppConfig.RATE_TICKER,
                      years: int = AppConfig.RATE_MA_YEARS) -> dict:
    """10Y Treasury yield: latest close and N-year moving average (decimals)."""
    import yfinance as yf
    hist = yf.Ticker(ticker).history(period=f"{years + 1}y")['Close'].dropna()
    if hist.empty:
        raise ValueError(f"No history for {ticker}")
    hist.index = hist.index.tz_localize(None)
    window = hist[hist.index >= hist.index[-1] - pd.DateOffset(years=years)]
    return {
        'treasury_10y_latest': round(float(hist.iloc[-1]) / 100, 5),
        'treasury_10y_ma': round(float(window.mean()) / 100, 5),
        'rate_as_of': hist.index[-1].date().isoformat(),
    }


def fetch_cpi_annualized(series: str = AppConfig.CPI_FRED_SERIES,
                         years: int = AppConfig.CPI_YEARS) -> dict:
    """N-year annualized CPI inflation from FRED (decimal)."""
    raw = urllib.request.urlopen(FRED_CSV_URL.format(series=series), timeout=20).read().decode()
    cpi = pd.read_csv(io.StringIO(raw))
    cpi.columns = ['date', 'value']
    cpi['date'] = pd.to_datetime(cpi['date'])
    cpi['value'] = pd.to_numeric(cpi['value'], errors='coerce')
    cpi = cpi.dropna().set_index('date')['value']
    last_date, last_val = cpi.index[-1], cpi.iloc[-1]
    # Nearest available month at or before the start date (FRED can have gaps)
    base = cpi[cpi.index <= last_date - pd.DateOffset(years=years)]
    if base.empty:
        raise ValueError("Not enough CPI history")
    base_date, base_val = base.index[-1], base.iloc[-1]
    span_years = (last_date - base_date).days / 365.25
    return {
        'cpi_annualized': round(float((last_val / base_val) ** (1 / span_years) - 1), 5),
        'cpi_as_of': last_date.date().isoformat(),
    }


def load_macro_benchmarks() -> dict:
    """Read the stored snapshot; fall back to config defaults if missing."""
    path = _macro_path()
    if os.path.exists(path):
        try:
            with open(path, encoding='utf-8') as f:
                data = json.load(f)
            if 'treasury_10y_ma' in data and 'cpi_annualized' in data:
                return data
        except (OSError, ValueError):
            pass
    return {
        'treasury_10y_ma': AppConfig.MACRO_FALLBACK_RATE,
        'treasury_10y_latest': None,
        'rate_as_of': None,
        'cpi_annualized': AppConfig.MACRO_FALLBACK_CPI,
        'cpi_as_of': None,
        'fetched_at': None,
        'source': 'config_fallback',
    }


def refresh_macro_benchmarks() -> dict:
    """Fetch both benchmarks and save. Each part keeps its previous value on failure."""
    data = load_macro_benchmarks()
    errors = []
    try:
        data.update(fetch_treasury_ma())
    except Exception as e:
        errors.append(f"treasury: {e}")
    try:
        data.update(fetch_cpi_annualized())
    except Exception as e:
        errors.append(f"cpi: {e}")

    data['rate_ma_years'] = AppConfig.RATE_MA_YEARS
    data['cpi_years'] = AppConfig.CPI_YEARS
    data['fetched_at'] = datetime.now(timezone.utc).isoformat()
    data['source'] = 'fetched' if not errors else ('partial' if len(errors) == 1 else data.get('source', 'stale'))
    data['errors'] = errors

    with open(_macro_path(), 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2)
    return data
