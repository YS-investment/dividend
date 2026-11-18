"""
종목 발굴: track gates -> score -> action label -> weight proposal.

usage: screen.py --track high|growth [--top 15] [--n 10] [--large-cap]
                 [--sector "Utilities" ...] [--exclude KO,PEP]
"""

import argparse

from _common import (AppConfig, STOCK_COLS, action, emit, freshness, load_universe, macro, market_cap_usd,
                     propose_weights, records, screen, track_params)

SMALL_CAP_USD = 2e9  # Russell small-cap upper bound (see Market Cap Tier)


def run(track, top=15, n=10, large_cap=False, sectors=None, exclude=()):
    uni = load_universe()
    passed = screen(uni, track, large_cap, sectors)
    if exclude:
        passed = passed[~passed['Symbol'].astype(str).str.upper().isin({e.upper() for e in exclude})]
    acts = passed.apply(action, axis=1)
    passed = passed.assign(Action=acts.map(lambda a: a['label']),
                           Action_Reasons=acts.map(lambda a: ', '.join(a['reasons'])))
    passed['Alert'] = (passed['Div. Yield'] > 0.10).map({True: '배당률 10% 초과', False: ''})

    prop = propose_weights(passed, n)
    yld = (prop['Weight'] * prop['Div. Yield']).sum() if len(prop) else None
    growth = (prop['Weight'] * prop['Div_CAGR_5Y_Adj'].fillna(0)).sum() if len(prop) else None

    return {
        'mode': 'screen',
        'track': track,
        'freshness': freshness(uni),
        'macro': macro(),
        'params': track_params(track, large_cap) | {'sectors': sectors, 'exclude': list(exclude)},
        'counts': {
            'universe': len(uni),
            'passed': len(passed),
            'by_action': passed['Action'].value_counts().to_dict(),
        },
        'candidates': records(passed.head(top), STOCK_COLS + ['Action', 'Action_Reasons', 'Alert']),
        'proposal': {
            'positions': records(prop, ['Symbol', 'Company Name', 'Sector_Label', 'Weight', 'Div. Yield',
                                        'Div_CAGR_5Y_Adj', 'Safety_Grade', 'Valuation', 'Timing_Signal',
                                        'Score', 'Action']),
            'expected_yield': yld,
            'expected_after_tax_yield': yld * (1 - AppConfig.KR_DIVIDEND_WITHHOLDING) if yld else None,
            'monthly_after_tax_krw_per_100m': round(1e8 * yld * (1 - AppConfig.KR_DIVIDEND_WITHHOLDING) / 12, -3)
            if yld else None,
            'small_caps': prop.loc[market_cap_usd(prop) < SMALL_CAP_USD, 'Symbol'].tolist() if len(prop) else [],
            'weighted_div_cagr_5y': growth,
            'sector_shares': prop.groupby('Sector_Label')['Weight'].sum().round(4).to_dict() if len(prop) else {},
            'requested_positions': n,
            'filled_positions': len(prop),
            'rules': {
                'max_income_share': AppConfig.PORTFOLIO_MAX_HOLDING_INCOME_SHARE,
                'max_sector_share': AppConfig.PORTFOLIO_MAX_SECTOR_VALUE_SHARE,
                'eligible_actions': ['분할매수', '매수 검토'],
            },
        },
    }


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--track', choices=['high', 'growth'], required=True)
    ap.add_argument('--top', type=int, default=15)
    ap.add_argument('--n', type=int, default=10, help='positions in the weight proposal')
    ap.add_argument('--large-cap', action='store_true', help='growth track: market cap >= $20B')
    ap.add_argument('--sector', action='append', help='StockAnalysis Sector name (repeatable)')
    ap.add_argument('--exclude', default='', help='comma-separated symbols to leave out')
    a = ap.parse_args()
    emit(run(a.track, a.top, a.n, a.large_cap, a.sector, [s for s in a.exclude.split(',') if s.strip()]))
