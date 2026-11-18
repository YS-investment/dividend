"""
Per-ticker fundamental and dividend-history metrics from yfinance.

compute_ticker_metrics(symbol) returns one flat dict per ticker. It is used by
the data pipeline (DividendDataCollector.enrich_with_yfinance) and can be
called directly for any ticker outside the screened universe.

Conventions
  - Ratios/growth rates are decimals (0.05 = 5%); ROE stays in percent
    (legacy scale used by the ROE gate).
  - NaN means "no data" - never 0.0.
  - Multi-year figures use annual statements (newest column first in yfinance).
  - Yield history uses RAW prices (auto_adjust=False). Dividend-adjusted closes
    understate past prices and inflate historical yields.
"""

import time

import numpy as np
import pandas as pd

from config import AppConfig

NAN = np.nan


def _row(stmt: pd.DataFrame, keys) -> pd.Series:
    """First matching statement row, newest first, NaN dropped (empty if none)."""
    if stmt is None or stmt.empty:
        return pd.Series(dtype=float)
    for k in keys:
        if k in stmt.index:
            return pd.to_numeric(stmt.loc[k], errors='coerce').dropna()
    return pd.Series(dtype=float)


def _cagr(latest, base, years):
    if pd.isna(latest) or pd.isna(base) or base <= 0 or years <= 0:
        return NAN
    if latest <= 0:
        return -1.0
    return float((latest / base) ** (1 / years) - 1)


def _coverage(numer: pd.Series, div_paid: pd.Series, n: int = 3):
    """Sum of last n years of numer / sum of dividends paid (aligned by year)."""
    if numer.empty or div_paid.empty:
        return NAN
    both = pd.concat([numer, div_paid.abs()], axis=1, join='inner').dropna().head(n)
    if both.empty or both.iloc[:, 1].sum() <= 0:
        return NAN
    return round(float(both.iloc[:, 0].sum() / both.iloc[:, 1].sum()), 3)


# ---------------------------------------------------------------------------
# Dividend history: special-dividend removal, cut detection, peak-based CAGR
# ---------------------------------------------------------------------------

def regular_dividends(div: pd.Series) -> tuple:
    """Drop special dividends (> 1.5x the local median payment). Returns (regular, n_special)."""
    if div.empty:
        return div, 0
    med = div.rolling(5, center=True, min_periods=1).median()
    special = div > 1.5 * med
    return div[~special], int(special.sum())


def dividend_history_metrics(div: pd.Series, as_of: pd.Timestamp) -> dict:
    """
    Cut detection uses two independent methods; each has known false positives
    (per-payment: frequency changes; calendar-year: payments slipping across
    Dec/Jan), so a cut is only "detected" when BOTH fire. data_processor then
    cross-checks against the StockAnalysis growth streak.
    """
    out = {'Div_Cut_Detected': False, 'Div_Last_Cut_Year': NAN,
           'Div_CAGR_5Y_Peak': NAN, 'Div_Special_Count': 0}
    if div is None or len(div) < 4:
        return out

    reg, n_special = regular_dividends(div)
    out['Div_Special_Count'] = n_special
    thr = -AppConfig.CUT_DETECT_THRESHOLD
    last_full_year = as_of.year - 1
    window_start = as_of - pd.DateOffset(years=10)

    # f = typical regular payments per year (median of last 5 complete years,
    # so a partial current year or one missing yfinance record doesn't skew it)
    f = payments_per_year(reg, as_of)

    # Method 1: payment vs the same slot one year earlier (shift f), so
    # uneven interim/final payers (semi-annual ADRs) don't read as cuts
    recent = reg[reg.index >= window_start - pd.DateOffset(years=1)]
    pay_chg = (recent / recent.shift(f) - 1).dropna()
    pay_chg = pay_chg[pay_chg.index >= window_start]
    pay_cut_years = set(pay_chg[pay_chg < thr].index.year)

    # Method 2: calendar-year total drop (complete years only)
    annual = reg.groupby(reg.index.year).sum()
    annual = annual.reindex(range(last_full_year - 10, last_full_year + 1)).fillna(0.0)
    cal = annual.loc[last_full_year - 9:last_full_year]
    cal_chg = (cal / cal.shift(1).replace(0, np.nan) - 1).dropna()
    cal_cut_years = set(cal_chg[cal_chg < thr].index)

    # Both methods must agree on a cut within +/-1 year
    matched = [y for y in cal_cut_years if any(abs(y - p) <= 1 for p in pay_cut_years)]
    if matched:
        out['Div_Cut_Detected'] = True
        out['Div_Last_Cut_Year'] = int(max(matched))

    # Peak-based 5Y CAGR. Annual rate at each year-end = sum of the last f
    # regular payments (f = typical payments per year), which - unlike
    # calendar totals - doesn't jump when a payment slips across Dec/Jan.
    rate = reg.rolling(f).sum().dropna()

    def year_end_rate(y):
        x = rate[rate.index <= pd.Timestamp(year=y, month=12, day=31)]
        return x.iloc[-1] if len(x) else NAN

    base_year = last_full_year - 5
    peak_base = pd.Series([year_end_rate(y) for y in range(base_year - 4, base_year + 1)]).max() \
        if len(rate) else NAN
    out['Div_CAGR_5Y_Peak'] = _cagr(year_end_rate(last_full_year), peak_base, 5)
    return out


def payments_per_year(reg: pd.Series, as_of: pd.Timestamp) -> int:
    """Typical regular payments per year: median over the last 5 complete years."""
    last_full_year = as_of.year - 1
    counts = reg.groupby(reg.index.year).size().reindex(
        range(last_full_year - 4, last_full_year + 1)).dropna()
    return max(int(round(counts.median())), 1) if len(counts) else 4


def yield_band_metrics(close: pd.Series, div: pd.Series) -> dict:
    """
    Trailing yield on raw prices: current value, 5Y/10Y avg/min/max, 5Y percentile.
    Annual dividend = sum of the last f REGULAR payments (f = payments/year),
    not a 365-day window - payment-date jitter can put 5 quarterly payments in
    one 365D window (+25% spike), and special dividends would distort valuation.
    """
    out = {'Yield_TTM': NAN, 'Yield_Pctl_5Y': NAN}
    for p in ('5Y', '10Y'):
        for s in ('avg', 'min', 'max'):
            out[f'Trainling_{p}_{s}_dividend_yield'] = NAN
    if close.empty or div.empty:
        return out

    reg, _ = regular_dividends(div)
    f = payments_per_year(reg, close.index[-1])
    annual = reg.rolling(f).sum().dropna()
    # A dividend that stopped should not be carried forward: drop the rate
    # once ~1.5 payment intervals pass without a new payment
    stale_after = pd.Timedelta(days=int(365 / f * 1.5) + 15)
    idx = annual.reindex(close.index, method='ffill')
    last_pay = pd.Series(annual.index, index=annual.index).reindex(close.index, method='ffill')
    idx[(close.index - last_pay) > stale_after] = 0.0
    yld = (idx / close).dropna()
    if yld.empty:
        return out
    last = yld.index[-1]
    out['Yield_TTM'] = round(float(yld.iloc[-1]), 5)

    for p, yrs, min_years in (('5Y', 5, 3), ('10Y', 10, 6)):
        w = yld[yld.index >= last - pd.DateOffset(years=yrs)]
        if len(w) and (w.index[-1] - w.index[0]).days >= min_years * 365:
            out[f'Trainling_{p}_avg_dividend_yield'] = round(float(w.mean()), 5)
            out[f'Trainling_{p}_min_dividend_yield'] = round(float(w.min()), 5)
            out[f'Trainling_{p}_max_dividend_yield'] = round(float(w.max()), 5)
            if p == '5Y':
                out['Yield_Pctl_5Y'] = round(float((w < w.iloc[-1]).mean() * 100), 1)
    return out


def timing_metrics(hist: pd.DataFrame) -> dict:
    """
    Buy-timing indicators on raw daily OHLCV (display only):
      Price_vs_MA20 - last close / 20-day SMA - 1
      RSI_14        - Wilder RSI
      MFI_14        - money flow index (volume-weighted RSI)
      Timing_As_Of  - date of the last bar
    """
    from config import AppConfig
    out = {'Price_vs_MA20': NAN, 'RSI_14': NAN, 'MFI_14': NAN, 'Timing_As_Of': ''}
    need = {'High', 'Low', 'Close', 'Volume'}
    if hist is None or hist.empty or not need.issubset(hist.columns):
        return out
    h = hist[list(need)].dropna()
    n_ma, n_rsi, n_mfi = AppConfig.TIMING_MA_DAYS, AppConfig.TIMING_RSI_DAYS, AppConfig.TIMING_MFI_DAYS
    if len(h) < max(n_ma, n_rsi, n_mfi) + 1:
        return out
    close = h['Close']
    out['Timing_As_Of'] = str(h.index[-1].date())
    ma = close.rolling(n_ma).mean().iloc[-1]
    if ma > 0:
        out['Price_vs_MA20'] = round(float(close.iloc[-1] / ma - 1), 4)

    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / n_rsi, adjust=False).mean().iloc[-1]
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / n_rsi, adjust=False).mean().iloc[-1]
    if loss > 0:
        out['RSI_14'] = round(float(100 - 100 / (1 + gain / loss)), 1)
    elif gain > 0:
        out['RSI_14'] = 100.0

    typical = (h['High'] + h['Low'] + close) / 3
    flow = typical * h['Volume']
    up = flow.where(typical.diff() > 0, 0.0).tail(n_mfi).sum()
    down = flow.where(typical.diff() < 0, 0.0).tail(n_mfi).sum()
    if down > 0:
        out['MFI_14'] = round(float(100 - 100 / (1 + up / down)), 1)
    elif up > 0:
        out['MFI_14'] = 100.0
    return out


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def compute_ticker_metrics(symbol: str, retries: int = 3) -> dict:
    """
    All yfinance-derived metrics for one ticker. Raises only if every attempt
    to read basic info fails; individual sub-metrics degrade to NaN.
    Returns dict with an '_errors' list of (stage, message) for diagnostics.
    """
    import yfinance as yf

    yf_symbol = symbol.replace('.', '-')  # BF.B -> BF-B
    errors = []

    info = None
    for attempt in range(retries + 1):
        try:
            tk = yf.Ticker(yf_symbol)
            info = tk.info or {}
            break
        except Exception as e:
            if attempt == retries:
                raise
            time.sleep(3 * (attempt + 1))  # Yahoo throttling: back off

    m = {
        'Sector': info.get('sector', '') or '',
        'Industry': info.get('industry', '') or '',
        'fiveYearAvgDivdendYield': round(info['fiveYearAvgDividendYield'] / 100, 4)
            if info.get('fiveYearAvgDividendYield') else NAN,
        'Debt_to_Equity': round(info['debtToEquity'], 2) if info.get('debtToEquity') else NAN,
        'ROE': round(info['returnOnEquity'] * 100, 2) if info.get('returnOnEquity') else NAN,
        'EPS_Growth': round(info['earningsGrowth'], 4) if info.get('earningsGrowth') else NAN,
        'Revenue_Growth': round(info['revenueGrowth'], 4) if info.get('revenueGrowth') else NAN,
        'Trailing_EPS': round(info['trailingEps'], 4) if info.get('trailingEps') is not None else NAN,
    }
    market_cap = info.get('marketCap')

    # Leverage: net debt / EBITDA (negative = net cash)
    total_debt, cash, ebitda = info.get('totalDebt'), info.get('totalCash'), info.get('ebitda')
    if total_debt is not None and ebitda:
        m['Net_Debt_EBITDA'] = round((total_debt - (cash or 0)) / ebitda, 2) if ebitda > 0 else 99.0
    else:
        m['Net_Debt_EBITDA'] = NAN

    # Cash flow statement: coverage, P/FCF, buybacks
    m.update({'FCF_Dividend_Ratio': NAN, 'FCF_Dividend_Ratio_1Y': NAN, 'OCF_Dividend_Ratio': NAN,
              'P_FCF': NAN, 'Net_Buyback_Yield': NAN})
    try:
        cf = tk.cashflow
        fcf = _row(cf, ['Free Cash Flow'])
        ocf = _row(cf, ['Operating Cash Flow'])
        div_paid = _row(cf, ['Cash Dividends Paid', 'Common Stock Dividend Paid', 'Dividends Paid'])
        m['FCF_Dividend_Ratio'] = _coverage(fcf, div_paid, 3)
        m['FCF_Dividend_Ratio_1Y'] = _coverage(fcf, div_paid, 1)
        m['OCF_Dividend_Ratio'] = _coverage(ocf, div_paid, 3)
        if market_cap and not fcf.empty:
            avg_fcf = fcf.head(3).mean()
            m['P_FCF'] = round(market_cap / avg_fcf, 2) if avg_fcf > 0 else NAN
        repurchase = _row(cf, ['Repurchase Of Capital Stock', 'Common Stock Payments'])
        issuance = _row(cf, ['Issuance Of Capital Stock', 'Common Stock Issuance'])
        if market_cap and (not repurchase.empty or not issuance.empty):
            rep = abs(repurchase.iloc[0]) if not repurchase.empty else 0.0
            iss = abs(issuance.iloc[0]) if not issuance.empty else 0.0
            m['Net_Buyback_Yield'] = round((rep - iss) / market_cap, 4)
    except Exception as e:
        errors.append(('cashflow', str(e)[:100]))

    # Income statement: 3Y CAGRs, earnings stability, interest coverage
    m.update({'Revenue_CAGR_3Y': NAN, 'Revenue_Decline_Years': NAN, 'EPS_CAGR_3Y': NAN,
              'EPS_CV': NAN, 'Interest_Coverage': NAN})
    try:
        inc = tk.income_stmt
        rev = _row(inc, ['Total Revenue'])
        eps = _row(inc, ['Diluted EPS', 'Basic EPS'])
        if len(rev) >= 4:
            m['Revenue_CAGR_3Y'] = round(_cagr(rev.iloc[0], rev.iloc[3], 3), 4)
        if len(rev) >= 2:
            # Consecutive annual revenue declines counted back from the latest year
            streak = 0
            for newer, older in zip(rev.values[:-1], rev.values[1:]):
                if newer < older:
                    streak += 1
                else:
                    break
            m['Revenue_Decline_Years'] = streak
        if len(eps) >= 4:
            m['EPS_CAGR_3Y'] = round(_cagr(eps.iloc[0], eps.iloc[3], 3), 4)
        if len(eps) >= 3 and eps.head(4).mean() > 0:
            m['EPS_CV'] = round(float(eps.head(4).std() / eps.head(4).mean()), 3)
        ebit = _row(inc, ['EBIT', 'Operating Income'])
        int_exp = _row(inc, ['Interest Expense', 'Interest Expense Non Operating'])
        if not ebit.empty and not int_exp.empty and abs(int_exp.iloc[0]) > 0:
            m['Interest_Coverage'] = round(float(ebit.iloc[0] / abs(int_exp.iloc[0])), 2)
    except Exception as e:
        errors.append(('income_stmt', str(e)[:100]))

    # Balance sheet: 3Y share count change (dilution / buyback)
    m['Shares_Change_3Y'] = NAN
    try:
        shares = _row(tk.balance_sheet, ['Ordinary Shares Number', 'Share Issued'])
        if len(shares) >= 4 and shares.iloc[3] > 0:
            m['Shares_Change_3Y'] = round(float(shares.iloc[0] / shares.iloc[3] - 1), 4)
    except Exception as e:
        errors.append(('balance_sheet', str(e)[:100]))

    # Dividend history + yield bands (raw prices)
    try:
        div = tk.dividends
        if div is None or div.empty or not isinstance(div.index, pd.DatetimeIndex):
            div = pd.Series(dtype=float, index=pd.DatetimeIndex([]))
        elif div.index.tz is not None:
            div.index = div.index.tz_localize(None)
        hist = tk.history(period="11y", auto_adjust=False)
        if hist.empty or not isinstance(hist.index, pd.DatetimeIndex):
            close = pd.Series(dtype=float, index=pd.DatetimeIndex([]))
        else:
            close = hist['Close'].dropna()
            if close.index.tz is not None:
                close.index = close.index.tz_localize(None)
        as_of = close.index[-1] if len(close) else pd.Timestamp.now()
        m.update(yield_band_metrics(close, div))
        m.update(dividend_history_metrics(div, as_of))
        m.update(timing_metrics(hist.tail(120) if not hist.empty else hist))
    except Exception as e:
        errors.append(('dividend_history', str(e)[:100]))
        m.update(yield_band_metrics(pd.Series(dtype=float), pd.Series(dtype=float)))
        m.update(dividend_history_metrics(pd.Series(dtype=float), pd.Timestamp.now()))
        m.update(timing_metrics(pd.DataFrame()))

    m['_errors'] = errors
    return m
