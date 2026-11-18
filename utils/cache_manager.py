"""
Caching strategies for Streamlit application
"""

import streamlit as st
import pandas as pd
from typing import Optional
from utils.data_loader import DataManager


@st.cache_data(ttl=3600)  # Cache for 1 hour
def load_main_dataframe(use_cached: bool = True) -> Optional[pd.DataFrame]:
    """
    Load and cache the main dividend dataset

    Args:
        use_cached: Whether to use cached CSV file

    Returns:
        DataFrame with dividend data
    """
    manager = DataManager()
    df = manager.get_main_dataframe(use_cached=use_cached)

    if df is not None:
        # Data type optimization
        if 'Symbol' in df.columns:
            df['Symbol'] = df['Symbol'].astype('category')
        if 'Sector' in df.columns:
            df['Sector'] = df['Sector'].astype('category')

    return df


def show_data_freshness_warning() -> None:
    """Warn on a page when the data is older than AppConfig.STALE_DATA_DAYS,
    and surface the last failed update from data/update_history.csv."""
    from config import AppConfig
    from modules.update_log import data_age_days, load_history

    age = data_age_days()
    if age is None or age <= AppConfig.STALE_DATA_DAYS:
        return
    msg = f"⚠️ 데이터가 {age:.0f}일 전 기준입니다 (마지막 성공 갱신 이후 {AppConfig.STALE_DATA_DAYS}일 초과)."
    hist = load_history(5)
    failed = hist[hist['status'] == 'failed'] if not hist.empty else hist
    if not failed.empty:
        last = failed.iloc[-1]
        msg += f" 최근 실패: {str(last['finished_at'])[:16]} — {str(last['error'])[:150]}"
    st.warning(msg)


@st.cache_data(ttl=3600)
def load_macro() -> dict:
    """Macro benchmarks snapshot (10Y Treasury MA, CPI) written by the pipeline."""
    from modules.macro_benchmarks import load_macro_benchmarks
    return load_macro_benchmarks()


@st.cache_data(ttl=3600)
def load_prepared_dataframe() -> Optional[pd.DataFrame]:
    """Main dataset with every derived column (sector group, adjusted CAGR,
    coverage, safety grade, valuation, universe-wide percentile ranks)."""
    from modules.data_processor import prepare_all_metrics
    df = load_main_dataframe(use_cached=True)
    if df is None:
        return None
    df = df.copy()
    for col in ('Symbol', 'Sector'):
        if col in df.columns:
            df[col] = df[col].astype(object).where(df[col].notna(), '').astype(str)
    return prepare_all_metrics(df)


@st.cache_data(ttl=86400)  # Cache for 24 hours
def load_historical_prices(symbol: str, period: str = "max", start_date: str = None, end_date: str = None):
    """
    Cache historical price data per symbol

    Args:
        symbol: Stock symbol
        period: Time period (default: "max")
        start_date: Start date (YYYY-MM-DD) - overrides period if provided
        end_date: End date (YYYY-MM-DD)

    Returns:
        DataFrame with historical price data including Close and Dividends columns
    """
    import yfinance as yf
    ticker = yf.Ticker(symbol)

    if start_date and end_date:
        hist = ticker.history(start=start_date, end=end_date, auto_adjust=False)
    else:
        hist = ticker.history(period=period, auto_adjust=False)

    # Ensure Dividends column exists
    if 'Dividends' not in hist.columns:
        hist['Dividends'] = 0.0

    return hist


@st.cache_data(ttl=86400)  # Cache for 24 hours
def load_benchmark_data(symbol: str = 'SPY', start_date: str = None, end_date: str = None) -> pd.DataFrame:
    """
    Load benchmark (S&P 500) historical data with caching.

    Args:
        symbol: Benchmark ticker (default: SPY)
        start_date: Start date (YYYY-MM-DD)
        end_date: End date (YYYY-MM-DD)

    Returns:
        DataFrame with Date index, Close and Dividends columns
    """
    import yfinance as yf

    ticker = yf.Ticker(symbol)

    if start_date and end_date:
        hist = ticker.history(start=start_date, end=end_date, auto_adjust=False)
    else:
        hist = ticker.history(period='max', auto_adjust=False)

    # Ensure Dividends column exists
    if 'Dividends' not in hist.columns:
        hist['Dividends'] = 0.0

    return hist[['Close', 'Dividends']] if not hist.empty else pd.DataFrame()


@st.cache_resource
def get_yfinance_session():
    """Reuse yfinance session across calls"""
    import yfinance as yf
    return yf.Session()


def clear_all_caches():
    """Clear all Streamlit caches"""
    st.cache_data.clear()
    st.cache_resource.clear()
