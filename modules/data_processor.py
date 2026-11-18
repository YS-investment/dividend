"""
Data processing: sector grouping, derived dividend metrics, sector-aware
filtering, percentile scoring, safety grade and valuation signals.

Typical use (pages and skill scripts):
    df = prepare_all_metrics(df)          # full universe - ranks are universe-wide
    out = filter_stocks(df, ...)          # pass/fail gates
    out = calculate_composite_score(out, weights, score_type)
"""

import numpy as np
import pandas as pd
from typing import Dict

from config import AppConfig

NAN = np.nan


# ---------------------------------------------------------------------------
# Sector grouping
# ---------------------------------------------------------------------------

def sector_group(sector, industry) -> str:
    """Map yfinance Sector/Industry to a SECTOR_RULES key."""
    sector = str(sector or '')
    industry = str(industry or '')
    if sector == 'Real Estate':
        return 'reit'
    if 'Midstream' in industry:
        return 'mlp'
    if sector == 'Utilities':
        return 'utility'
    if industry.startswith('Banks'):
        return 'bank'
    if sector == 'Financial Services':
        return 'financial'
    if sector == 'Energy':
        return 'energy'
    return 'general'


def add_sector_group(df: pd.DataFrame) -> pd.DataFrame:
    result = df.copy()
    sec = result['Sector'] if 'Sector' in result.columns else pd.Series('', index=result.index)
    ind = result['Industry'] if 'Industry' in result.columns else pd.Series('', index=result.index)
    result['Sector_Group'] = [sector_group(s, i) for s, i in zip(sec, ind)]
    return result


def _rule(group: str) -> dict:
    return AppConfig.SECTOR_RULES.get(group, AppConfig.SECTOR_RULES['general'])


def _col(df: pd.DataFrame, name: str) -> pd.Series:
    """Numeric column or all-NaN if absent."""
    if name in df.columns:
        return pd.to_numeric(df[name], errors='coerce')
    return pd.Series(NAN, index=df.index)


# ---------------------------------------------------------------------------
# Derived dividend metrics
# ---------------------------------------------------------------------------

def add_adjusted_dividend_metrics(df: pd.DataFrame) -> pd.DataFrame:
    """
    Div_CAGR_5Y_Adj: 5Y CAGR corrected for cut-rebound base effects.
      streak >= CUT_CHECK_STREAK_YEARS -> StockAnalysis 5Y CAGR as-is (no cut possible)
      otherwise -> min(StockAnalysis 5Y, peak-based 5Y from yfinance)
    Cut_Flag: cut detected by both yfinance methods AND streak below the
      check threshold (a long streak proves the detection was a false positive).
    """
    result = df.copy()
    streak = _col(result, 'Div. Gr. Years')
    sa_5y = _col(result, 'Div. Growth 5Y')
    peak_5y = _col(result, 'Div_CAGR_5Y_Peak')
    long_streak = streak >= AppConfig.CUT_CHECK_STREAK_YEARS

    adj = np.where(long_streak, sa_5y, np.fmin(sa_5y, peak_5y))
    result['Div_CAGR_5Y_Adj'] = pd.Series(adj, index=result.index).round(4)

    detected = result['Div_Cut_Detected'].fillna(False).astype(bool) \
        if 'Div_Cut_Detected' in result.columns else pd.Series(False, index=result.index)
    result['Cut_Flag'] = detected & ~long_streak
    return result


def add_div_coverage(df: pd.DataFrame) -> pd.DataFrame:
    """Div_Coverage: sector-appropriate dividend coverage (x times covered)."""
    result = df.copy()
    if 'Sector_Group' not in result.columns:
        result = add_sector_group(result)
    fcf = _col(result, 'FCF_Dividend_Ratio')
    ocf = _col(result, 'OCF_Dividend_Ratio')
    payout = _col(result, 'Payout Ratio')
    eps_cov = (1 / payout).where(payout > 0)
    basis = result['Sector_Group'].map(lambda g: _rule(g)['coverage'])
    result['Coverage_Basis'] = basis
    result['Div_Coverage'] = np.select(
        [basis == 'fcf', basis == 'ocf', basis == 'eps'], [fcf, ocf, eps_cov], default=NAN
    ).round(3)
    return result


def chowder_threshold(div_yield: float) -> float:
    """Traditional Chowder Rule: yield >= 3% needs 12, otherwise 15."""
    if pd.isna(div_yield):
        return NAN
    if div_yield >= AppConfig.CHOWDER_YIELD_PIVOT:
        return AppConfig.CHOWDER_MIN_HIGH_YIELD
    return AppConfig.CHOWDER_MIN_LOW_YIELD


def add_chowder_number(df: pd.DataFrame) -> pd.DataFrame:
    """chowder_number = Div. Yield % + adjusted 5Y CAGR %, plus pass flag."""
    result = df.copy()
    cagr = _col(result, 'Div_CAGR_5Y_Adj') if 'Div_CAGR_5Y_Adj' in result.columns else _col(result, 'Div. Growth 5Y')
    yld = _col(result, 'Div. Yield')
    result['chowder_number'] = ((yld + cagr) * 100).round(1)
    result['chowder_min'] = yld.map(chowder_threshold)
    result['chowder_pass'] = result['chowder_number'] >= result['chowder_min']
    return result


def add_eps_growth_alert(df: pd.DataFrame) -> pd.DataFrame:
    """
    Flag when the dividend has grown faster than earnings over a multi-year
    window (adjusted 5Y dividend CAGR > 3Y EPS CAGR) - payout-ratio expansion
    that is hard to sustain. Missing data is not flagged. Informational only.
    """
    result = df.copy()
    div_g = _col(result, 'Div_CAGR_5Y_Adj') if 'Div_CAGR_5Y_Adj' in result.columns else _col(result, 'Div. Growth 5Y')
    eps_g = _col(result, 'EPS_CAGR_3Y')
    flag = (div_g > eps_g) & div_g.notna() & eps_g.notna()
    result['EPS_Alert'] = np.where(flag, '⚠️ 이익성장 대비 배당성장 과도', '')
    return result


def add_crisis_test(df: pd.DataFrame, as_of_year: int = None) -> pd.DataFrame:
    """
    Crisis_Passed: crises (AppConfig.CRISIS_YEARS) the dividend kept growing
    through, judged by the consecutive-increase streak covering the year a cut
    would have shown up (streak >= as_of_year - year). Crisis_Count = number passed.
    Missing streak -> '' / NaN.
    """
    result = df.copy()
    year = as_of_year or pd.Timestamp.now().year
    streak = _col(result, 'Div. Gr. Years')
    passed = {lbl: streak >= (year - y) for lbl, y in AppConfig.CRISIS_YEARS.items()}
    labels = []
    for i in result.index:
        labels.append(', '.join(lbl for lbl, ok in passed.items() if ok[i]))
    result['Crisis_Passed'] = labels
    result['Crisis_Count'] = pd.DataFrame(passed).sum(axis=1).where(streak.notna())
    return result


def add_growth_badge(df: pd.DataFrame) -> pd.DataFrame:
    """Growth_Badge: revenue AND EPS both grew over 3Y (informational)."""
    result = df.copy()
    both = (_col(result, 'Revenue_CAGR_3Y') > 0) & (_col(result, 'EPS_CAGR_3Y') > 0)
    result['Growth_Badge'] = np.where(both, '매출·이익 동반 성장', '')
    return result


def add_timing_signal(df: pd.DataFrame) -> pd.DataFrame:
    """
    Timing_Signal from RSI_14 / MFI_14 / Price_vs_MA20 (display only):
      '과매도' if RSI <= oversold or MFI <= oversold,
      '20일선 아래' if price is below its 20-day average, else ''.
    """
    result = df.copy()
    rsi, mfi, ma = _col(result, 'RSI_14'), _col(result, 'MFI_14'), _col(result, 'Price_vs_MA20')
    oversold = (rsi <= AppConfig.TIMING_RSI_OVERSOLD) | (mfi <= AppConfig.TIMING_MFI_OVERSOLD)
    result['Timing_Signal'] = np.select([oversold, ma < 0], ['과매도', '20일선 아래'], default='')
    return result


def add_shareholder_yield(df: pd.DataFrame) -> pd.DataFrame:
    """Shareholder_Yield = Div. Yield + Net_Buyback_Yield (informational)."""
    result = df.copy()
    result['Shareholder_Yield'] = (_col(result, 'Div. Yield') + _col(result, 'Net_Buyback_Yield')).round(4)
    return result


# ---------------------------------------------------------------------------
# Safety grade and valuation signal
# ---------------------------------------------------------------------------

def _coverage_points(group: str, cov: float, payout: float) -> float:
    basis = _rule(group)['coverage']
    if basis == 'eps':
        if pd.isna(payout) or payout <= 0:
            return NAN
        cap = _rule(group)['payout_max']
        cap = cap if isinstance(cap, float) else 0.70
        if payout <= cap - 0.10:
            return 2
        return 1 if payout <= cap else 0
    if pd.isna(cov):
        return NAN
    if basis == 'ocf':
        floor = _rule(group)['min_coverage'] or 1.2
        return 2 if cov >= floor + 0.2 else (1 if cov >= floor else 0)
    return 2 if cov >= 1.5 else (1 if cov >= 1.0 else 0)


def _leverage_points(group: str, nd_ebitda: float) -> float:
    limit = _rule(group)['max_nd_ebitda']
    if limit is None or pd.isna(nd_ebitda):
        return NAN
    if nd_ebitda <= 0.7 * limit:
        return 2
    return 1 if nd_ebitda <= limit else 0


def _interest_points(group: str, int_cov: float) -> float:
    floor = _rule(group)['min_int_cov']
    if floor is None or pd.isna(int_cov):
        return NAN
    if int_cov >= 2 * floor:
        return 2
    return 1 if int_cov >= floor else 0


def _stability_points(eps_cv: float) -> float:
    if pd.isna(eps_cv):
        return NAN
    return 2 if eps_cv <= 0.2 else (1 if eps_cv <= 0.4 else 0)


def add_safety_grade(df: pd.DataFrame) -> pd.DataFrame:
    """
    Safety_Grade A-F from up to 6 components (0-2 points each): coverage,
    leverage, interest coverage, cut history, earnings stability, plus a
    crisis bonus (2 points, only when the streak covers the 2008 crisis; it
    does not count toward SAFETY_MIN_COMPONENTS). Grade =
    share of points over the components that have data; fewer than
    SAFETY_MIN_COMPONENTS available -> 'N/A'.
    """
    result = df.copy()
    if 'Sector_Group' not in result.columns:
        result = add_sector_group(result)
    if 'Cut_Flag' not in result.columns:
        result = add_adjusted_dividend_metrics(result)
    if 'Div_Coverage' not in result.columns:
        result = add_div_coverage(result)
    if 'Crisis_Passed' not in result.columns:
        result = add_crisis_test(result)
    bonus_lbl = AppConfig.SAFETY_CRISIS_BONUS_LABEL

    grades, scores, details = [], [], []
    for _, r in result.iterrows():
        g = r['Sector_Group']
        pts = {
            'coverage': _coverage_points(g, r.get('Div_Coverage'), r.get('Payout Ratio')),
            'leverage': _leverage_points(g, r.get('Net_Debt_EBITDA')),
            'interest': _interest_points(g, r.get('Interest_Coverage')),
            'cut_history': 0 if bool(r.get('Cut_Flag')) else 2,
            'stability': _stability_points(r.get('EPS_CV')),
            # Bonus only: counted when the streak covers the crisis, absent otherwise
            'crisis': 2 if bonus_lbl in str(r.get('Crisis_Passed') or '') else NAN,
        }
        avail = {k: v for k, v in pts.items() if not pd.isna(v)}
        if len([k for k in avail if k != 'crisis']) < AppConfig.SAFETY_MIN_COMPONENTS:
            grades.append('N/A'); scores.append(NAN)
        else:
            share = sum(avail.values()) / (2 * len(avail))
            grade = next((lbl for lbl, cut in AppConfig.SAFETY_GRADE_CUTOFFS if share >= cut), 'F')
            grades.append(grade); scores.append(round(share * 100, 1))
        details.append(' '.join(f"{k}={int(v)}" for k, v in avail.items()))
    result['Safety_Grade'] = grades
    result['Safety_Score'] = scores
    result['Safety_Detail'] = details
    return result


def add_valuation_signal(df: pd.DataFrame) -> pd.DataFrame:
    """
    Valuation from Yield_Pctl_5Y (current TTM yield's percentile within its own
    5Y daily history): >= CHEAP -> 저평가, <= RICH -> 고평가, else 적정.
    A cheap reading with deteriorating fundamentals (3Y EPS CAGR < 0,
    coverage < 1, or a cut flag) is marked as a possible yield trap.
    """
    result = df.copy()
    if 'Div_Coverage' not in result.columns:
        result = add_div_coverage(result)
    if 'Cut_Flag' not in result.columns:
        result = add_adjusted_dividend_metrics(result)
    pctl = _col(result, 'Yield_Pctl_5Y')
    signal = np.select(
        [pctl >= AppConfig.VALUATION_CHEAP_PCTL, pctl <= AppConfig.VALUATION_RICH_PCTL, pctl.notna()],
        ['저평가', '고평가', '적정'], default='N/A'
    )
    weak = (_col(result, 'EPS_CAGR_3Y') < 0) | (_col(result, 'Div_Coverage') < 1) | result['Cut_Flag'].astype(bool)
    result['Valuation'] = signal
    result['Yield_Trap'] = np.where((signal == '저평가') & weak, '⚠️ 함정 의심', '')
    return result


# ---------------------------------------------------------------------------
# Filtering
# ---------------------------------------------------------------------------

def filter_stocks(
    df: pd.DataFrame,
    min_yield: float = AppConfig.UNIVERSE_MIN_YIELD,
    payout_min: float = 0.0,
    payout_max: float = 0.80,
    min_years: int = AppConfig.UNIVERSE_MIN_GROWTH_YEARS,
    min_div_years: int = AppConfig.UNIVERSE_MIN_GROWTH_YEARS,
    min_growth: float = AppConfig.UNIVERSE_MIN_GROWTH_1Y,
    min_growth_5y: float = 0.0,
    min_roe: float = AppConfig.DEFAULT_MIN_ROE,
    apply_chowder: bool = False,
    min_market_cap: float = None,
    sectors: list = None,
    mkt_cap_tiers: list = None,
) -> pd.DataFrame:
    """
    Pass/fail gates. Missing data (NaN) passes as "unknown" except where noted.

    Dividend gates: yield, consecutive growth/payment years, 1Y growth,
      adjusted 5Y CAGR (Div_CAGR_5Y_Adj), optional Chowder Rule.
    Sector-aware gates (AppConfig.SECTOR_RULES by Sector_Group):
      payout   - slider range, a sector cap, or exempt (REIT/MLP)
      leverage - Net_Debt_EBITDA <= max_nd_ebitda; Interest_Coverage >= min_int_cov
      coverage - Div_Coverage >= min_coverage (REIT/MLP OCF coverage)
      earnings - Trailing_EPS > 0 and ROE floor (exempt for REIT/MLP); negative
                 ROE passes (negative-equity artifact, e.g. buybacks)
      revenue  - fails on REVENUE_DECLINE_YEARS_FAIL consecutive annual revenue
                 declines (a trend, not a single quarter or a flat stretch)
    """
    f = df.copy()
    if 'Sector_Group' not in f.columns:
        f = add_sector_group(f)
    if 'Div_CAGR_5Y_Adj' not in f.columns:
        f = add_adjusted_dividend_metrics(f)
    if 'Div_Coverage' not in f.columns:
        f = add_div_coverage(f)

    keep = pd.Series(True, index=f.index)
    yld = _col(f, 'Div. Yield')
    keep &= yld >= min_yield
    keep &= _col(f, 'Div. Gr. Years') >= min_years
    keep &= _col(f, 'Div. Years') >= min_div_years
    keep &= _col(f, 'Div. Growth') >= min_growth
    keep &= _col(f, 'Div_CAGR_5Y_Adj') >= min_growth_5y

    if apply_chowder:
        f = add_chowder_number(f)
        keep &= f['chowder_pass'].fillna(False).astype(bool)

    rules = f['Sector_Group'].map(_rule)
    payout = _col(f, 'Payout Ratio')
    nd = _col(f, 'Net_Debt_EBITDA')
    icov = _col(f, 'Interest_Coverage')
    cov = _col(f, 'Div_Coverage')
    eps = _col(f, 'Trailing_EPS')
    roe = _col(f, 'ROE')
    rev_decline = _col(f, 'Revenue_Decline_Years')

    def _payout_ok(i):
        cap = rules[i]['payout_max']
        p = payout[i]
        if cap == 'exempt':
            return True
        if pd.isna(p):
            return True
        upper = cap if isinstance(cap, float) else payout_max
        return payout_min <= p <= upper

    keep &= pd.Series([_payout_ok(i) for i in f.index], index=f.index)

    max_nd = rules.map(lambda r: r['max_nd_ebitda'])
    min_ic = rules.map(lambda r: r['min_int_cov'])
    min_cov = rules.map(lambda r: r['min_coverage'])
    exempt = rules.map(lambda r: r['exempt_eps_roe']).astype(bool)

    keep &= ~(max_nd.notna() & (nd > max_nd.astype(float)))
    keep &= ~(min_ic.notna() & (icov < min_ic.astype(float)))
    keep &= ~(min_cov.notna() & (cov < min_cov.astype(float)))
    keep &= ~(~exempt & (eps <= 0))
    keep &= ~(~exempt & (roe >= 0) & (roe < min_roe))
    keep &= ~(rev_decline >= AppConfig.REVENUE_DECLINE_YEARS_FAIL)

    if min_market_cap:
        # Optional size floor (Dividend Growth track); unknown size fails here
        keep &= market_cap_usd(f) >= min_market_cap

    if sectors and 'Sector' in f.columns:
        keep &= f['Sector'].isin(sectors)
    if mkt_cap_tiers and 'mkt_cap_tier' in f.columns:
        keep &= f['mkt_cap_tier'].isin(mkt_cap_tiers)

    return f[keep]


# ---------------------------------------------------------------------------
# Scoring (universe-wide percentile ranks)
# ---------------------------------------------------------------------------

def _pct_rank(series: pd.Series, invert: bool = False) -> pd.Series:
    """Percentile rank 0-1 over non-missing values; missing -> neutral 0.5."""
    s = pd.to_numeric(series, errors='coerce')
    r = s.rank(pct=True, method='average')
    if invert:
        r = 1 - r + (1 / max(s.notna().sum(), 1))
    return r.fillna(0.5)


def calculate_normalized_metrics(df: pd.DataFrame) -> pd.DataFrame:
    """
    norm_* columns as percentile ranks. Call on the FULL universe before
    filtering so a score means the same thing regardless of filter settings
    (e.g. norm_yield 0.7 = higher yield than 70% of the universe).
    """
    result = df.copy()
    if 'Div_Coverage' not in result.columns:
        result = add_div_coverage(result)
    if 'Div_CAGR_5Y_Adj' not in result.columns:
        result = add_adjusted_dividend_metrics(result)

    result['norm_yield'] = _pct_rank(_col(result, 'Div. Yield'))
    result['norm_cagr'] = _pct_rank(_col(result, 'Div_CAGR_5Y_Adj'))
    result['norm_div_growth'] = _pct_rank(_col(result, 'Div. Growth'))
    result['norm_years'] = _pct_rank(_col(result, 'Div. Gr. Years'))
    result['norm_div_years'] = _pct_rank(_col(result, 'Div. Years'))
    result['norm_payout'] = _pct_rank(_col(result, 'Payout Ratio'), invert=True)
    result['norm_coverage'] = _pct_rank(_col(result, 'Div_Coverage'))
    return result


def calculate_composite_score(
    df: pd.DataFrame,
    weights: Dict[str, float] = None,
    score_type: str = 'high_dividend'
) -> pd.DataFrame:
    """
    Composite score (0-100) = sum(weight x percentile rank) x 100.
    Weight keys: yield, cagr, growth, years, div_years, payout, fcf_coverage
    ('fcf_coverage' uses the sector-appropriate Div_Coverage).
    """
    result = df.copy()
    if weights is None:
        weights = AppConfig.HIGH_DIV_WEIGHTS if score_type == 'high_dividend' else AppConfig.DIV_GROWTH_WEIGHTS
    if 'norm_yield' not in result.columns:
        result = calculate_normalized_metrics(result)

    col_map = {'yield': 'norm_yield', 'cagr': 'norm_cagr', 'growth': 'norm_div_growth',
               'years': 'norm_years', 'div_years': 'norm_div_years', 'payout': 'norm_payout',
               'fcf_coverage': 'norm_coverage'}
    score = sum(w * result[col_map[k]] for k, w in weights.items() if k in col_map and w)
    score_column = {'high_dividend': 'high_div_composite',
                    'dividend_growth': 'dividend_growth_composite'}.get(score_type, f'{score_type}_composite')
    result[score_column] = (score * 100).round(1)
    return result


def prepare_all_metrics(df: pd.DataFrame) -> pd.DataFrame:
    """Every derived column, computed on the full universe (call before filtering)."""
    out = add_sector_group(df)
    out = add_adjusted_dividend_metrics(out)
    out = add_div_coverage(out)
    out = add_chowder_number(out)
    out = add_eps_growth_alert(out)
    out = add_shareholder_yield(out)
    out = add_crisis_test(out)
    out = add_growth_badge(out)
    out = add_timing_signal(out)
    out = add_safety_grade(out)
    out = add_valuation_signal(out)
    out = calculate_normalized_metrics(out)
    if 'Market Cap' in out.columns and 'mkt_cap_tier' not in out.columns:
        out = add_market_cap_tier(out)
    return out


def get_top_stocks(
    df: pd.DataFrame,
    score_column: str = 'high_div_composite',
    n: int = 20
) -> pd.DataFrame:
    """Top N stocks by score column."""
    if score_column not in df.columns:
        raise ValueError(f"Score column '{score_column}' not found in dataframe")
    return df.nlargest(n, score_column)


# ---------------------------------------------------------------------------
# Market cap tiers
# ---------------------------------------------------------------------------

def categorize_market_cap(market_cap_value):
    """
    Categorize market cap into tiers based on Russell Index criteria

    Args:
        market_cap_value: Market cap as string (e.g., "911.47B") or numeric in billions

    Returns:
        String representing the market cap tier
    """
    if pd.isna(market_cap_value):
        return 'Unknown'

    if isinstance(market_cap_value, str):
        value_str = market_cap_value.strip().upper()
        if not value_str or value_str == '-':
            return 'Unknown'

        value_str = value_str.replace('$', '')

        multiplier = 1
        if value_str.endswith('T'):
            multiplier = 1e12
            value_str = value_str[:-1]
        elif value_str.endswith('B'):
            multiplier = 1e9
            value_str = value_str[:-1]
        elif value_str.endswith('M'):
            multiplier = 1e6
            value_str = value_str[:-1]
        elif value_str.endswith('K'):
            multiplier = 1e3
            value_str = value_str[:-1]

        try:
            numeric_value = float(value_str)
            market_cap_millions = (numeric_value * multiplier) / 1e6
        except ValueError:
            return 'Unknown'
    elif isinstance(market_cap_value, (int, float)):
        market_cap_millions = market_cap_value * 1000
    else:
        return 'Unknown'

    if market_cap_millions >= 200000:
        return 'Mega-cap'
    elif market_cap_millions >= 10000:
        return 'Large-cap'
    elif market_cap_millions >= 2000:
        return 'Mid-cap'
    elif market_cap_millions >= 300:
        return 'Small-cap'
    elif market_cap_millions >= 50:
        return 'Micro-cap'
    else:
        return 'Nano-cap'


def parse_market_cap(value) -> float:
    """'911.47B' / '1.2T' / '350M' -> USD; numeric input is taken as billions."""
    if isinstance(value, (int, float, np.number)) and not pd.isna(value):
        return float(value) * 1e9
    if not isinstance(value, str):
        return NAN
    s = value.strip().upper().replace('$', '').replace(',', '')
    mult = {'T': 1e12, 'B': 1e9, 'M': 1e6, 'K': 1e3}.get(s[-1:], 1.0)
    try:
        return float(s[:-1] if s[-1:] in 'TBMK' else s) * mult
    except ValueError:
        return NAN


def market_cap_usd(df: pd.DataFrame) -> pd.Series:
    if 'Market Cap' not in df.columns:
        return pd.Series(NAN, index=df.index)
    return df['Market Cap'].map(parse_market_cap)


def add_market_cap_tier(df: pd.DataFrame) -> pd.DataFrame:
    """Add market cap tier column to dataframe"""
    result = df.copy()
    if 'Market Cap' in result.columns:
        result['mkt_cap_tier'] = result['Market Cap'].apply(categorize_market_cap)
    return result


def prepare_display_dataframe(
    df: pd.DataFrame,
    display_columns: list = None
) -> pd.DataFrame:
    """Format percentage columns (x100) and select display columns."""
    result = df.copy()
    pct_columns = ['Div. Yield', 'Payout Ratio', 'Div. Growth', 'Div. Growth 5Y']
    for col in pct_columns:
        if col in result.columns:
            result[col] = (result[col] * 100).round(2)
    if display_columns:
        available_cols = [col for col in display_columns if col in result.columns]
        result = result[available_cols]
    return result
