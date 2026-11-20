"""
Portfolio diagnosis for an existing dividend portfolio (holdings -> shares).

diagnose_portfolio() returns plain DataFrames/dicts (no Streamlit), so the
app page and skill scripts share one implementation:
  holdings  - per-position value, forward income, safety grade, valuation, flags
  monthly   - expected income by calendar month (last 12 months' payment pattern)
  sectors   - value and income share by sector group
  grades    - income share by safety grade
  summary   - totals (USD/KRW), yield, after-tax income, concentration flags

Symbols outside the screened universe are enriched on the fly with
modules.dividend_metrics.compute_ticker_metrics + yfinance info.
"""

from typing import Dict, Optional

import numpy as np
import pandas as pd

from config import AppConfig, BacktestConfig
from modules.data_processor import prepare_all_metrics

NAN = np.nan


def _yf_snapshot(symbol: str) -> dict:
    """Price, forward dividend and last-12-month payments (ex-dates) for one symbol."""
    import yfinance as yf
    tk = yf.Ticker(symbol.replace('.', '-'))
    price, div_rate = NAN, NAN
    try:
        price = float(tk.fast_info['last_price'])
    except Exception:
        pass
    info = {}
    try:
        info = tk.info or {}
        if pd.isna(price):
            price = float(info.get('currentPrice') or info.get('regularMarketPrice') or NAN)
        div_rate = float(info.get('dividendRate') or NAN)
    except Exception:
        pass
    payments = pd.Series(dtype=float)
    try:
        d = tk.dividends
        if len(d):
            d.index = d.index.tz_localize(None)
            payments = d[d.index >= d.index.max() - pd.DateOffset(days=364)]
    except Exception:
        pass
    if pd.isna(div_rate) and len(payments):
        div_rate = float(payments.sum())  # ETFs/funds report no dividendRate: use trailing 12M paid
    return {'price': price, 'div_rate': div_rate, 'payments': payments, 'info': info}


def _outside_universe_row(symbol: str, snap: dict) -> dict:
    """Build a universe-shaped row for a symbol not in final_df2.csv."""
    from modules.dividend_metrics import compute_ticker_metrics
    m = compute_ticker_metrics(symbol)
    m.pop('_errors', None)
    info = snap['info']
    price, rate = snap['price'], snap['div_rate']
    m.update({
        'Symbol': symbol,
        'Company Name': info.get('shortName', symbol),
        'Category': 'Not in universe',
        'Div. ($)': rate,
        'Div. Yield': rate / price if price and not pd.isna(rate) else NAN,
        'Payout Ratio': info.get('payoutRatio', NAN),
    })
    return m


def diagnose_portfolio(holdings: Dict[str, float], universe: pd.DataFrame,
                       usdkrw: Optional[float] = None, snapshots: Optional[Dict[str, dict]] = None) -> Dict:
    """
    Args:
        holdings: {symbol: shares}
        universe: final_df2.csv (raw or already passed through prepare_all_metrics)
        usdkrw: USD/KRW rate for KRW totals (None -> fetched; NaN if unavailable)
        snapshots: optional pre-fetched {symbol: _yf_snapshot(...)} (for caching)
    """
    holdings = {s.strip().upper(): float(q) for s, q in holdings.items() if s and q and float(q) > 0}
    if not holdings:
        raise ValueError("No holdings with positive share counts")

    uni = universe if 'Safety_Grade' in universe.columns else prepare_all_metrics(universe)
    uni = uni.assign(Symbol=uni['Symbol'].astype(str).str.upper())
    snapshots = snapshots or {}

    rows, outside = [], []
    for sym in holdings:
        snap = snapshots.get(sym) or _yf_snapshot(sym)
        snapshots[sym] = snap
        match = uni[uni['Symbol'] == sym]
        if len(match):
            rows.append(match.iloc[0].to_dict())
        else:
            outside.append(_outside_universe_row(sym, snap))
    if outside:
        # Ranks are meaningless for a handful of rows, but grades/valuation are row-wise
        rows += prepare_all_metrics(pd.DataFrame(outside)).to_dict('records')

    pos = pd.DataFrame(rows)
    # Concentration is judged on the real sector ('general' lumps many sectors);
    # funds have no sector, so tag them as ETF
    is_fund = pos['Symbol'].map(lambda s: snapshots[s]['info'].get('quoteType') in ('ETF', 'MUTUALFUND'))
    pos.loc[is_fund, 'Sector_Group'] = 'etf'
    pos.loc[is_fund, 'Safety_Grade'] = 'ETF'  # diversified fund: not graded, not "weak"
    sector = pos['Sector'].fillna('').astype(str) if 'Sector' in pos.columns else pd.Series('', index=pos.index)
    pos['Sector_Label'] = np.where(is_fund, 'ETF', np.where(sector != '', sector, pos['Sector_Group']))
    pos['Shares'] = pos['Symbol'].map(holdings)
    pos['Price'] = pos['Symbol'].map(lambda s: snapshots[s]['price'])
    # Forward annual dividend per share: StockAnalysis 'Div. ($)', else yfinance dividendRate
    fwd = pd.to_numeric(pos.get('Div. ($)'), errors='coerce')
    fwd = fwd.where(fwd > 0, pos['Symbol'].map(lambda s: snapshots[s]['div_rate']))
    # A suspended dividend pays nothing going forward, whatever 'Div. ($)' still says
    suspended = pos['Div_Suspended'].fillna(False).astype(bool) if 'Div_Suspended' in pos.columns \
        else pd.Series(False, index=pos.index)
    pos['Annual_Div_Per_Share'] = fwd.where(~suspended, 0.0)
    pos['Value'] = pos['Shares'] * pos['Price']
    pos['Annual_Income'] = pos['Shares'] * pos['Annual_Div_Per_Share']
    pos['Yield_On_Price'] = pos['Annual_Income'] / pos['Value']

    total_value = pos['Value'].sum()
    total_income = pos['Annual_Income'].sum()
    pos['Value_Share'] = pos['Value'] / total_value
    pos['Income_Share'] = pos['Annual_Income'] / total_income if total_income else NAN

    # Monthly calendar: last 12 months of ex-dates scaled to current shares
    monthly = pd.Series(0.0, index=range(1, 13))
    for i, p in pos.iterrows():
        if suspended[i]:
            continue
        pays = snapshots[p['Symbol']]['payments']
        for dt, amt in pays.items():
            monthly[dt.month] += amt * p['Shares']
    monthly_df = pd.DataFrame({'Month': monthly.index, 'Income': monthly.values})

    sectors = (pos.groupby('Sector_Label')[['Value', 'Annual_Income']].sum()
               .assign(Value_Share=lambda x: x['Value'] / total_value,
                       Income_Share=lambda x: x['Annual_Income'] / total_income if total_income else NAN)
               .sort_values('Value', ascending=False))
    grades = (pos.groupby('Safety_Grade')['Annual_Income'].sum()
              .div(total_income if total_income else 1).rename('Income_Share')
              .reindex(['A', 'B', 'C', 'D', 'F', 'N/A', 'ETF']).fillna(0.0))

    if usdkrw is None:
        try:
            import yfinance as yf
            usdkrw = float(yf.Ticker(BacktestConfig.FX_TICKER).fast_info['last_price'])
        except Exception:
            usdkrw = NAN

    flags = []
    cap_h = AppConfig.PORTFOLIO_MAX_HOLDING_INCOME_SHARE
    for _, p in pos[pos['Income_Share'] > cap_h].iterrows():
        flags.append(f"단일 종목 소득 집중: {p['Symbol']}가 배당소득의 {p['Income_Share']:.0%} (기준 {cap_h:.0%})")
    cap_s = AppConfig.PORTFOLIO_MAX_SECTOR_VALUE_SHARE
    for grp, r in sectors[(sectors['Value_Share'] > cap_s) & (sectors.index != 'ETF')].iterrows():
        flags.append(f"섹터 집중: {grp}가 평가액의 {r['Value_Share']:.0%} (기준 {cap_s:.0%})")
    weak = grades.reindex(['D', 'F', 'N/A']).sum()
    if weak > AppConfig.PORTFOLIO_MAX_WEAK_GRADE_INCOME_SHARE:
        flags.append(f"안전성 취약: D/F/N/A 등급이 배당소득의 {weak:.0%} "
                     f"(기준 {AppConfig.PORTFOLIO_MAX_WEAK_GRADE_INCOME_SHARE:.0%})")
    for _, p in pos[suspended].iterrows():
        flags.append(f"배당 중단: {p['Symbol']} (마지막 정기 배당 {p.get('Div_Last_Pay_Date') or '?'}, 예상 소득 0으로 계산)")
    for _, p in pos[pos['Cut_Flag'].fillna(False).astype(bool) & ~suspended].iterrows():
        flags.append(f"최근 10년 배당 삭감 이력: {p['Symbol']}")
    for _, p in pos[pos['Yield_Trap'].fillna('') != ''].iterrows():
        flags.append(f"수익률 함정 의심: {p['Symbol']} (배당률 역사적 상단 + 펀더멘털 약화)")
    empty_months = [int(m) for m, v in monthly.items() if v == 0]
    if empty_months:
        flags.append(f"배당 없는 달: {', '.join(map(str, empty_months))}월 (최근 12개월 배당락일 기준)")

    income_krw = total_income * usdkrw if not pd.isna(usdkrw) else NAN
    threshold = BacktestConfig.KR_FINANCIAL_INCOME_THRESHOLD_KRW
    if not pd.isna(income_krw) and income_krw > threshold:
        flags.append(f"금융소득 종합과세: 예상 연 배당 ₩{income_krw:,.0f}가 기준 ₩{threshold:,.0f} 초과 "
                     "(다른 이자·배당 소득과 합산)")

    summary = {
        'positions': len(pos),
        'outside_universe': [r['Symbol'] for r in outside],
        'total_value_usd': total_value,
        'annual_income_usd': total_income,
        'portfolio_yield': total_income / total_value if total_value else NAN,
        'after_tax_income_usd': total_income * (1 - AppConfig.KR_DIVIDEND_WITHHOLDING),
        'usdkrw': usdkrw,
        'total_value_krw': total_value * usdkrw if not pd.isna(usdkrw) else NAN,
        'annual_income_krw': income_krw,
        'after_tax_income_krw': income_krw * (1 - AppConfig.KR_DIVIDEND_WITHHOLDING) if not pd.isna(income_krw) else NAN,
        'weighted_div_growth_5y': float(np.nansum(pos['Income_Share'] * pd.to_numeric(pos.get('Div_CAGR_5Y_Adj'), errors='coerce'))),
        'flags': flags,
    }

    cols = ['Symbol', 'Company Name', 'Sector_Label', 'Sector_Group', 'Shares', 'Price', 'Value', 'Value_Share',
            'Annual_Div_Per_Share', 'Annual_Income', 'Income_Share', 'Yield_On_Price', 'Div_CAGR_5Y_Adj',
            'Safety_Grade', 'Valuation', 'Yield_Pctl_5Y', 'Timing_Signal', 'Cut_Flag', 'Div_Suspended', 'Div_Last_Pay_Date', 'Yield_Trap',
            'Crisis_Passed', 'Growth_Badge', 'Category']
    holdings_df = pos[[c for c in cols if c in pos.columns]].sort_values('Annual_Income', ascending=False)
    return {'holdings': holdings_df, 'monthly': monthly_df, 'sectors': sectors.reset_index(),
            'grades': grades.reset_index(), 'summary': summary}
