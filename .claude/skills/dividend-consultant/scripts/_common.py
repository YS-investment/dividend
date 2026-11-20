"""
Shared helpers for the dividend-consultant skill scripts.

Every script prints one JSON object to stdout. All judgments (gates, grades,
action labels, weights, flags) are decided here or in the app modules; the
skill only reads and explains them.
"""

import json
import math
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
os.chdir(REPO)  # config paths are relative to the repo root
sys.path.insert(0, str(REPO))
try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from config import AppConfig, get_main_data_path, get_last_updated_path  # noqa: E402
from modules.data_processor import (  # noqa: E402
    prepare_all_metrics, filter_stocks, calculate_composite_score, market_cap_usd,
)
from modules.macro_benchmarks import load_macro_benchmarks  # noqa: E402
from modules.update_log import data_age_days  # noqa: E402

NAN = np.nan
HOLDINGS_FILE = REPO / 'holdings.csv'
REPROCESS_CMD = ('.venv/Scripts/python.exe -c "from modules.data_collector import DividendDataCollector; '
                 'DividendDataCollector().update_all_data(use_scraping=False)"')

# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------

def load_universe() -> pd.DataFrame:
    """final_df2.csv with every derived column (ranks are universe-wide)."""
    return prepare_all_metrics(pd.read_csv(get_main_data_path()))


def freshness(uni: pd.DataFrame = None) -> dict:
    age = data_age_days()
    try:
        last = Path(get_last_updated_path()).read_text().strip()
    except OSError:
        last = None
    timing = None
    if uni is not None and 'Timing_As_Of' in uni.columns:
        timing = pd.Series(uni['Timing_As_Of']).dropna().astype(str).max() or None
    return {
        'last_updated_utc': last,
        'age_days': round(age, 1) if age is not None else None,
        'stale': age is None or age > AppConfig.STALE_DATA_DAYS,
        'stale_after_days': AppConfig.STALE_DATA_DAYS,
        'timing_as_of': timing,
        'reprocess_cmd': REPROCESS_CMD,
    }


def macro() -> dict:
    m = load_macro_benchmarks()
    return {
        'treasury_10y_ma': m.get('treasury_10y_ma'),
        'rate_as_of': m.get('rate_as_of'),
        'cpi_annualized': m.get('cpi_annualized'),
        'cpi_as_of': m.get('cpi_as_of'),
        'fallback': m.get('source') == 'config_fallback',
    }


# ---------------------------------------------------------------------------
# Tracks (same defaults as the screener pages)
# ---------------------------------------------------------------------------

def track_params(track: str, large_cap: bool = False) -> dict:
    m = load_macro_benchmarks()
    rate, cpi = m['treasury_10y_ma'], m['cpi_annualized']
    if track == 'high':
        return dict(min_yield=max(round(rate, 4), AppConfig.UNIVERSE_MIN_YIELD), payout_min=0.20, payout_max=0.70,
                    min_years=5, min_div_years=5, min_growth=0.03, min_growth_5y=round(cpi, 4), min_roe=0.0,
                    apply_chowder=False, min_market_cap=None)
    if track == 'growth':
        return dict(min_yield=AppConfig.UNIVERSE_MIN_YIELD, payout_min=0.15, payout_max=0.60,
                    min_years=10, min_div_years=10, min_growth=0.05, min_growth_5y=max(0.05, round(cpi, 4)),
                    min_roe=8.0, apply_chowder=True,
                    min_market_cap=AppConfig.GROWTH_MIN_MARKET_CAP_USD if large_cap else None)
    raise ValueError(f"unknown track: {track}")


TRACK_SCORE = {
    'high': ('high_dividend', 'high_div_composite', {'yield': 0.50, 'cagr': 0.25, 'fcf_coverage': 0.25}),
    'growth': ('dividend_growth', 'dividend_growth_composite', {'cagr': 0.60, 'yield': 0.40}),
}


def screen(uni: pd.DataFrame, track: str, large_cap: bool = False, sectors=None) -> pd.DataFrame:
    """Gate + score one track; sorted by score (desc). Adds 'Score'."""
    params = track_params(track, large_cap)
    passed = filter_stocks(uni, sectors=sectors, **params)
    score_type, col, weights = TRACK_SCORE[track]
    passed = calculate_composite_score(passed, weights=weights, score_type=score_type)
    passed['Score'] = passed[col]
    return passed.sort_values('Score', ascending=False)


GATE_COLS = {
    'Div. Yield': '배당률', 'Div. Gr. Years': '연속 증가 연수', 'Div. Years': '무삭감 연수',
    'Div. Growth': '1년 배당성장률', 'Div_CAGR_5Y_Adj': '보정 5년 CAGR', 'Payout Ratio': '배당성향',
    'Net_Debt_EBITDA': '순부채/EBITDA', 'Interest_Coverage': '이자보상배율', 'Div_Coverage': '배당 커버리지',
    'Trailing_EPS': 'EPS(적자)', 'ROE': 'ROE', 'Revenue_Decline_Years': '매출 연속 감소',
    'Div_Suspended': '배당 중단',
}
# Neutral value per gate column when another gate is under test: dividend
# floors (>=) fail on NaN, so they get a value that always clears them
_NEUTRAL = {'Div. Yield': 1e9, 'Div. Gr. Years': 1e9, 'Div. Years': 1e9, 'Div. Growth': 1e9,
            'Div_CAGR_5Y_Adj': 1e9, 'Div_Suspended': False}


def gate_report(row: pd.Series, track: str, large_cap: bool = False) -> dict:
    """
    Which track gates one stock fails. Each gate column is tested alone
    (all other gate columns set to a neutral value), so the result comes
    from filter_stocks itself rather than a re-implementation.
    """
    params = track_params(track, large_cap)
    one = pd.DataFrame([row])
    base = {**params, 'apply_chowder': False, 'min_market_cap': None}
    failed = []
    for c in GATE_COLS:
        if c not in one.columns:
            one[c] = NAN
    for c, label in GATE_COLS.items():
        t = one.copy()
        for other in GATE_COLS:
            if other != c:
                t[other] = _NEUTRAL.get(other, NAN)
        if filter_stocks(t, **base).empty:
            missing = pd.isna(pd.to_numeric(one[c], errors='coerce').iloc[0])
            failed.append(f'{label} (데이터 없음)' if missing else label)
    if params['apply_chowder'] and not bool(row.get('chowder_pass')):
        failed.append('Chowder Rule')
    if params['min_market_cap'] and not (market_cap_usd(one).iloc[0] >= params['min_market_cap']):
        failed.append('시가총액')
    return {'passed': not failed, 'failed_gates': failed}


# ---------------------------------------------------------------------------
# Action label (criteria doc §7 + §8)
# ---------------------------------------------------------------------------

def action(row) -> dict:
    """
    One label per stock, first match wins:
      교체 검토  - Safety D/F, Cut_Flag or Yield_Trap
      관찰       - Safety C or N/A
      관망       - valuation 고평가 (A/B)
      분할매수   - A/B, 저평가/적정, Timing_Signal set
      매수 검토  - A/B, 저평가/적정
    ETFs (Safety_Grade 'ETF') -> '보유 (ETF)'.
    """
    g = str(row.get('Safety_Grade') or 'N/A')
    val = str(row.get('Valuation') or 'N/A')
    timing = str(row.get('Timing_Signal') or '')
    reasons = []
    if g == 'ETF':
        return {'label': '보유 (ETF)', 'reasons': ['분산 상품 — 등급 미산정']}
    if g in ('D', 'F'):
        reasons.append(f'안전성 {g}')
    if _true(row.get('Div_Suspended')):
        reasons.append(f"배당 중단 (마지막 지급 {row.get('Div_Last_Pay_Date') or '?'})")
    elif _true(row.get('Cut_Flag')):
        reasons.append('최근 배당 삭감 이력')
    if str(row.get('Yield_Trap') or ''):
        reasons.append('수익률 함정 의심')
    if reasons:
        return {'label': '교체 검토', 'reasons': reasons}
    if g in ('C', 'N/A'):
        return {'label': '관찰', 'reasons': [f'안전성 {g}']}
    if val == '고평가':
        return {'label': '관망', 'reasons': [f'안전성 {g}', '배당률 5년 하단(고평가)']}
    base = [f'안전성 {g}', f'밸류 {val}']
    if timing:
        return {'label': '분할매수', 'reasons': base + [f'타이밍 {timing}']}
    return {'label': '매수 검토', 'reasons': base}


BUYABLE = ('분할매수', '매수 검토')


# ---------------------------------------------------------------------------
# Weight proposal
# ---------------------------------------------------------------------------

def sector_label(row) -> str:
    s = row.get('Sector')
    return str(s) if isinstance(s, str) and s else str(row.get('Sector_Group') or 'general')


def propose_weights(cands: pd.DataFrame, n: int) -> pd.DataFrame:
    """
    Pick up to n buyable candidates in score order with at most
    floor(n x sector cap) per sector, then weight by score and cap each
    position so its INCOME share stays <= PORTFOLIO_MAX_HOLDING_INCOME_SHARE
    (and value share <= 2/n). Returns rows with 'Weight' (sums to 1).
    """
    cap_sector = max(1, int(n * AppConfig.PORTFOLIO_MAX_SECTOR_VALUE_SHARE))
    picked, per_sector = [], {}
    for idx, r in cands.iterrows():
        if action(r)['label'] not in BUYABLE:
            continue
        s = sector_label(r)
        if per_sector.get(s, 0) >= cap_sector:
            continue
        picked.append(idx)
        per_sector[s] = per_sector.get(s, 0) + 1
        if len(picked) == n:
            break
    p = cands.loc[picked].copy()
    if p.empty:
        p['Weight'] = []
        return p
    p['Weight'] = p['Score'].clip(lower=1).astype(float)
    p['Sector_Label'] = [sector_label(r) for _, r in p.iterrows()]
    return cap_weights(p)


def cap_weights(p: pd.DataFrame) -> pd.DataFrame:
    """Normalize 'Weight' and cap each position: income share <= holding cap, value <= 2/n."""
    w = p['Weight'].astype(float)
    w = w / w.sum()
    yld = pd.to_numeric(p['Div. Yield'], errors='coerce').fillna(0).clip(lower=1e-6)
    cap_inc = AppConfig.PORTFOLIO_MAX_HOLDING_INCOME_SHARE
    cap_val = min(1.0, 2.0 / len(p))
    for _ in range(100):
        inc = w * yld / (w * yld).sum()
        over = (inc > cap_inc + 1e-9) | (w > cap_val + 1e-9)
        if not over.any() or over.all():
            break
        # shrink offenders to their binding cap, redistribute the rest pro rata
        target = np.minimum(w * np.where(inc > cap_inc, cap_inc / inc, 1.0), cap_val)
        freed = (w[over] - target[over]).sum()
        w[over] = target[over]
        w[~over] += freed * w[~over] / w[~over].sum()
    p = p.copy()
    p['Weight'] = (w / w.sum()).round(4)
    return p


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

def _true(v) -> bool:
    try:
        return bool(v) and not (isinstance(v, float) and math.isnan(v))
    except Exception:
        return False


def clean(v):
    if isinstance(v, dict):
        return {str(k): clean(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [clean(x) for x in v]
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (np.floating, float)):
        f = float(v)
        return None if math.isnan(f) or math.isinf(f) else round(f, 4)
    if isinstance(v, np.bool_):
        return bool(v)
    if isinstance(v, pd.Timestamp):
        return v.isoformat()
    if v is pd.NaT:
        return None
    return v


def records(df: pd.DataFrame, cols) -> list:
    cols = [c for c in cols if c in df.columns]
    return [clean(r) for r in df[cols].to_dict('records')]


def emit(obj: dict) -> None:
    print(json.dumps(clean(obj), ensure_ascii=False, indent=1))


def parse_holdings_text(text: str) -> dict:
    """'KO 100, O 50' or one 'SYMBOL SHARES' per line -> {symbol: shares}."""
    out, tokens = {}, text.replace(',', '\n').replace(';', '\n').splitlines()
    for line in tokens:
        parts = line.replace('\t', ' ').split()
        if len(parts) >= 2:
            try:
                sym = parts[0].upper()
                out[sym] = out.get(sym, 0.0) + float(parts[1])
            except ValueError:
                continue
    return {s: q for s, q in out.items() if q > 0}


def load_holdings_file(path: Path = HOLDINGS_FILE) -> dict:
    """holdings.csv with columns symbol, shares (extra columns ignored)."""
    if not Path(path).exists():
        return {}
    df = pd.read_csv(path)
    df.columns = [c.strip().lower() for c in df.columns]
    df = df.dropna(subset=['symbol', 'shares'])
    out = {}
    for _, r in df.iterrows():
        sym = str(r['symbol']).strip().upper()
        out[sym] = out.get(sym, 0.0) + float(r['shares'])
    return {s: q for s, q in out.items() if q > 0}


STOCK_COLS = ['Symbol', 'Company Name', 'Sector', 'Sector_Group', 'Category', 'Market Cap', 'Div. Yield',
              'Div_CAGR_5Y_Adj', 'Div. Growth', 'Div. Gr. Years', 'Payout Ratio', 'Div_Coverage', 'Coverage_Basis',
              'Safety_Grade', 'Safety_Score', 'Valuation', 'Yield_Pctl_5Y', 'Yield_Trap', 'Timing_Signal',
              'Crisis_Passed', 'Growth_Badge', 'EPS_Alert', 'chowder_number', 'Score']
