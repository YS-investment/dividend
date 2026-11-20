"""
개별 종목 분석: universe row (or live yfinance enrichment) -> grade detail,
cut/crisis, valuation/timing, gate result per track, action, checklist keys.

usage: stock.py KO [O PEP ...]
"""

import argparse

import pandas as pd

from _common import (AppConfig, action, clean, emit, freshness, gate_report, load_universe, macro,
                     prepare_all_metrics, screen)
from modules.portfolio_diagnosis import _outside_universe_row, _yf_snapshot

FIELDS = {
    'profile': ['Symbol', 'Company Name', 'Sector', 'Industry', 'Sector_Group', 'Category', 'Market Cap',
                'mkt_cap_tier', 'Payout Freq.'],
    'dividend': ['Div. ($)', 'Div. Yield', 'Div. Growth', 'Div. Growth 5Y', 'Div_CAGR_5Y_Adj', 'Div. Gr. Years',
                 'Div. Years', 'Payout Ratio', 'chowder_number', 'Shareholder_Yield', 'Net_Buyback_Yield'],
    'safety': ['Safety_Grade', 'Safety_Score', 'Safety_Detail', 'Div_Coverage', 'Coverage_Basis',
               'Net_Debt_EBITDA', 'Interest_Coverage', 'EPS_CV'],
    'fundamentals': ['Trailing_EPS', 'ROE', 'Revenue_CAGR_3Y', 'EPS_CAGR_3Y', 'Revenue_Decline_Years',
                     'Growth_Badge', 'EPS_Alert', 'P_FCF'],
    'cut_crisis': ['Cut_Flag', 'Div_Suspended', 'Div_Last_Pay_Date', 'Div_Cut_Detected', 'Div_Last_Cut_Year', 'Crisis_Passed', 'Crisis_Count'],
    'valuation': ['Valuation', 'Yield_Trap', 'Yield_TTM', 'Yield_Pctl_5Y', 'Trainling_5Y_avg_dividend_yield',
                  'Trainling_5Y_min_dividend_yield', 'Trainling_5Y_max_dividend_yield',
                  'Trainling_10Y_avg_dividend_yield'],
    'timing': ['Timing_Signal', 'Price_vs_MA20', 'RSI_14', 'MFI_14', 'Timing_As_Of'],
}


def checklist(r) -> list:
    """Criteria doc §11 items that apply to this stock (keys + trigger)."""
    if r.get('Safety_Grade') == 'ETF':
        return [{'key': 'ETF', 'why': '총보수, 분배금 연도별 편차, 커버드콜 여부'}]
    out = []
    if not str(r.get('Growth_Badge') or ''):
        out.append({'key': '실적 방향', 'why': '매출·이익 동반 성장 배지 없음'})
    cc = r.get('Crisis_Count')
    if pd.notna(cc) and cc < len(AppConfig.CRISIS_YEARS):
        out.append({'key': '위기 이력', 'why': f'위기 {int(cc)}/{len(AppConfig.CRISIS_YEARS)}회 통과'})
    if r.get('Sector_Group') == 'reit':
        out.append({'key': '리츠', 'why': '신용등급·입주율·임대만기·금리 민감도'})
    if r.get('Sector_Group') == 'mlp':
        out.append({'key': 'MLP', 'why': 'K-1/세금 구조, 계약 물량·원자재 노출'})
    yrs = pd.to_numeric(r.get('Div. Gr. Years'), errors='coerce')
    if pd.notna(yrs) and yrs < 5:
        out.append({'key': '짧은 배당 이력', 'why': f'연속 증가 {int(yrs)}년'})
    if pd.to_numeric(r.get('Div. Yield'), errors='coerce') > 0.10:
        out.append({'key': '초고배당', 'why': '배당률 10% 초과 — 지속성 확인'})
    if str(r.get('EPS_Alert') or ''):
        out.append({'key': '배당성장 > 이익성장', 'why': '배당성향 상승으로 만든 성장'})
    return out


def analyze(sym, uni, ranked):
    match = uni[uni['Symbol'].astype(str).str.upper() == sym]
    in_universe = len(match) > 0
    if in_universe:
        r = match.iloc[0]
    else:
        snap = _yf_snapshot(sym)
        if pd.isna(snap['price']):
            return {'symbol': sym, 'error': '시세를 찾을 수 없음 (티커 확인)'}
        r = prepare_all_metrics(pd.DataFrame([_outside_universe_row(sym, snap)])).iloc[0]
        if snap['info'].get('quoteType') in ('ETF', 'MUTUALFUND'):
            r['Safety_Grade'] = 'ETF'
    out = {'symbol': sym, 'in_universe': in_universe}
    for grp, cols in FIELDS.items():
        out[grp] = {c: clean(r.get(c)) for c in cols if c in r.index}
    out['tracks'] = {}
    for t in (() if r.get('Safety_Grade') == 'ETF' else ('high', 'growth')):
        g = gate_report(r, t)
        rank = ranked[t]
        hit = rank.index[rank['Symbol'].astype(str).str.upper() == sym]
        g['rank'] = int(rank.index.get_loc(hit[0]) + 1) if len(hit) else None
        g['of'] = len(rank)
        g['score'] = clean(rank.loc[hit[0], 'Score']) if len(hit) else None
        out['tracks'][t] = g
    out['action'] = action(r)
    out['checklist'] = checklist(r)
    if not in_universe:
        out['note'] = '유니버스 밖 종목 — 실시간 계산, 백분위 점수·순위 없음'
    return out


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('symbols', nargs='+')
    a = ap.parse_args()
    uni = load_universe()
    ranked = {t: screen(uni, t).reset_index(drop=True) for t in ('high', 'growth')}
    emit({
        'mode': 'stock',
        'freshness': freshness(uni),
        'macro': macro(),
        'stocks': [analyze(s.strip().upper(), uni, ranked) for s in a.symbols],
    })
