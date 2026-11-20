"""
포트폴리오 진단·개선: diagnose_portfolio + per-holding action, rebalance
targets for concentration, replacement candidates for '교체 검토' holdings.

usage: portfolio.py [--text "KO 100, O 50"] [--file holdings.csv] [--alternatives 3]
  --text wins over --file; with neither, holdings.csv in the repo root is used.
"""

import argparse
import sys

import pandas as pd

from _common import (AppConfig, BUYABLE, HOLDINGS_FILE, action, emit, freshness, load_holdings_file,
                     load_universe, macro, parse_holdings_text, records, screen)
from modules.portfolio_diagnosis import diagnose_portfolio

HOLD_COLS = ['Symbol', 'Company Name', 'Sector_Label', 'Shares', 'Price', 'Value', 'Value_Share',
             'Annual_Income', 'Income_Share', 'Yield_On_Price', 'Div_CAGR_5Y_Adj', 'Safety_Grade', 'Valuation',
             'Yield_Pctl_5Y', 'Timing_Signal', 'Cut_Flag', 'Div_Suspended', 'Yield_Trap', 'Crisis_Passed', 'Growth_Badge',
             'Category', 'Action', 'Hold_Action', 'Action_Reasons']
# Same action label read from the holder's side
HOLD_LABEL = {'교체 검토': '교체 검토', '관찰': '보유·관찰', '관망': '보유 (추가매수 보류)',
              '분할매수': '보유 + 분할 추가매수', '매수 검토': '보유 + 추가매수 가능', '보유 (ETF)': '보유 (ETF)'}
ALT_COLS = ['Symbol', 'Company Name', 'Sector', 'Sector_Group', 'Div. Yield', 'Div_CAGR_5Y_Adj', 'Safety_Grade',
            'Valuation', 'Timing_Signal', 'Score', 'Track', 'Action']


def rebalance(h: pd.DataFrame, sectors: pd.DataFrame) -> list:
    """Concentration fixes: shares to keep a holding at the income cap; sector value over cap."""
    out = []
    cap_h = AppConfig.PORTFOLIO_MAX_HOLDING_INCOME_SHARE
    for _, p in h[h['Income_Share'] > cap_h].iterrows():
        # income share x = a/(a+b); keep a' with a'/(a'+b) = cap -> a' = cap*b/(1-cap)
        a = p['Annual_Income']
        b = h['Annual_Income'].sum() - a
        keep = cap_h * b / (1 - cap_h)
        out.append({'type': '종목 소득 집중', 'symbol': p['Symbol'], 'income_share': p['Income_Share'],
                    'cap': cap_h, 'shares_now': p['Shares'],
                    'shares_target': int(p['Shares'] * keep / a) if a else None,
                    'alt': '다른 종목 추가 매수로 희석해도 됨'})
    cap_s = AppConfig.PORTFOLIO_MAX_SECTOR_VALUE_SHARE
    total = h['Value'].sum()
    for _, s in sectors[(sectors['Value_Share'] > cap_s) & (sectors['Sector_Label'] != 'ETF')].iterrows():
        # same algebra on value: sector value v, rest r -> v' = cap*r/(1-cap)
        v, rest = s['Value'], total - s['Value']
        out.append({'type': '섹터 집중', 'sector': s['Sector_Label'], 'value_share': s['Value_Share'],
                    'cap': cap_s, 'reduce_value_usd': v - cap_s * rest / (1 - cap_s),
                    'or_add_other_sectors_usd': v / cap_s - total})
    return out


def alternatives(h: pd.DataFrame, uni: pd.DataFrame, n: int) -> list:
    """For each '교체 검토' holding: top buyable stocks (both tracks), same Sector_Group first."""
    weak = h[h['Action'] == '교체 검토']
    if weak.empty:
        return []
    pool = []
    for t in ('high', 'growth'):
        s = screen(uni, t).assign(Track=t)
        s['Action'] = s.apply(lambda r: action(r)['label'], axis=1)
        pool.append(s[s['Action'].isin(BUYABLE)])
    pool = (pd.concat(pool).sort_values('Score', ascending=False).drop_duplicates('Symbol'))
    pool = pool[~pool['Symbol'].astype(str).str.upper().isin(set(h['Symbol']))]
    out = []
    for _, w in weak.iterrows():
        same = pool[pool['Sector_Group'] == w.get('Sector_Group')]
        pick = pd.concat([same, pool[~pool.index.isin(same.index)]]).head(n)
        out.append({'replace': w['Symbol'], 'reasons': w['Action_Reasons'], 'sector_group': w.get('Sector_Group'),
                    'candidates': records(pick, ALT_COLS)})
    return out


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--text')
    ap.add_argument('--file')
    ap.add_argument('--alternatives', type=int, default=3)
    a = ap.parse_args()
    if a.text:
        holdings, source = parse_holdings_text(a.text), 'text'
    else:
        path = a.file or HOLDINGS_FILE
        holdings, source = load_holdings_file(path), str(path)
    if not holdings:
        emit({'mode': 'portfolio', 'error': f'보유 종목 없음 (source={source}). "KO 100, O 50" 형식이나 '
                                            f'{HOLDINGS_FILE.name}(symbol,shares)를 주세요'})
        sys.exit(1)

    uni = load_universe()
    d = diagnose_portfolio(holdings, uni)
    h = d['holdings'].copy()
    # Sector_Group is needed for alternatives; diagnose_portfolio keeps it
    acts = h.apply(action, axis=1)
    h['Action'] = acts.map(lambda x: x['label'])
    h['Action_Reasons'] = acts.map(lambda x: ', '.join(x['reasons']))
    h['Hold_Action'] = h['Action'].map(HOLD_LABEL)

    emit({
        'mode': 'portfolio',
        'source': source,
        'freshness': freshness(uni),
        'macro': macro(),
        'summary': d['summary'],
        'holdings': records(h, HOLD_COLS),
        'monthly_income_usd': d['monthly'].to_dict('records'),
        'sectors': records(d['sectors'], ['Sector_Label', 'Value', 'Annual_Income', 'Value_Share', 'Income_Share']),
        'grades': d['grades'].to_dict('records'),
        'by_action': h['Hold_Action'].value_counts().to_dict(),
        'rebalance': rebalance(h, d['sectors']),
        'alternatives': alternatives(h, uni, a.alternatives),
    })
