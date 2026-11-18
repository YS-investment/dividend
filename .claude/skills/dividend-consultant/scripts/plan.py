"""
목표 현금흐름 설계: target after-tax monthly income (KRW) <-> capital, using
the screened weight proposal's yield; Korean tax, 종합과세 check, growth
projection and a monthly payment calendar with gap-filling candidates.

usage: plan.py (--monthly-krw 3000000 | --capital-krw 500000000)
               [--track high|growth|mix] [--n 10] [--other-income-krw 0] [--fx 1400]
"""

import argparse
import math
from concurrent.futures import ThreadPoolExecutor

import pandas as pd

from _common import (AppConfig, BUYABLE, action, cap_weights, emit, freshness, load_universe, macro,
                     propose_weights, records, screen)
from modules.macro_benchmarks import load_macro_benchmarks
from config import BacktestConfig
from modules.portfolio_diagnosis import _yf_snapshot

TAX = AppConfig.KR_DIVIDEND_WITHHOLDING
THRESHOLD = BacktestConfig.KR_FINANCIAL_INCOME_THRESHOLD_KRW
SENS_YIELDS = [0.03, 0.04, 0.05, 0.06, 0.07]
POS_COLS = ['Symbol', 'Company Name', 'Sector_Label', 'Weight', 'Div. Yield', 'Div_CAGR_5Y_Adj', 'Safety_Grade',
            'Valuation', 'Timing_Signal', 'Track', 'Amount_KRW', 'Shares', 'Price_USD', 'Pay_Months']


def build_proposal(uni, track, n):
    if track != 'mix':
        p = propose_weights(screen(uni, track), n).assign(Track=track)
        return p, {track: p}
    parts = {t: propose_weights(screen(uni, t), math.ceil(n / 2)).assign(Track=t) for t in ('high', 'growth')}
    p = pd.concat([x.assign(Weight=x['Weight'] / 2) for x in parts.values()])
    agg = p.groupby('Symbol', as_index=False)['Weight'].sum()
    p = p.drop_duplicates('Symbol').drop(columns='Weight').merge(agg, on='Symbol')
    return cap_weights(p), parts


def snapshots(symbols):
    with ThreadPoolExecutor(max_workers=5) as ex:
        return dict(zip(symbols, ex.map(_yf_snapshot, symbols)))


def pay_months(snap) -> list:
    return sorted({int(d.month) for d in snap['payments'].index}) if len(snap['payments']) else []


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument('--monthly-krw', type=float, help='target AFTER-TAX monthly dividend (KRW)')
    g.add_argument('--capital-krw', type=float, help='capital to invest (KRW)')
    ap.add_argument('--track', choices=['high', 'growth', 'mix'], default='mix')
    ap.add_argument('--n', type=int, default=10)
    ap.add_argument('--other-income-krw', type=float, default=0.0, help='other annual interest+dividend income')
    ap.add_argument('--fx', type=float, help='USD/KRW override')
    a = ap.parse_args()

    uni = load_universe()
    prop, _ = build_proposal(uni, a.track, a.n)
    y = float((prop['Weight'] * prop['Div. Yield']).sum())
    gcagr = float((prop['Weight'] * prop['Div_CAGR_5Y_Adj'].fillna(0)).sum())
    y_net = y * (1 - TAX)

    if a.monthly_krw:
        target_m = a.monthly_krw
        capital = target_m * 12 / y_net
    else:
        capital = a.capital_krw
        target_m = capital * y_net / 12
    gross_annual = capital * y
    total_fin = gross_annual + a.other_income_krw

    syms = prop['Symbol'].tolist()
    universe_buyable = []
    for t in ('high', 'growth'):
        s = screen(uni, t)
        s = s[s.apply(lambda r: action(r)['label'] in BUYABLE, axis=1)]
        universe_buyable.append(s)
    extra_pool = (pd.concat(universe_buyable).sort_values('Score', ascending=False)
                  .drop_duplicates('Symbol'))
    extra_pool = extra_pool[~extra_pool['Symbol'].isin(syms)].head(15)
    snaps = snapshots(syms + extra_pool['Symbol'].tolist())
    fx = a.fx
    if not fx:
        try:
            import yfinance as yf
            fx = float(yf.Ticker(BacktestConfig.FX_TICKER).fast_info['last_price'])
        except Exception:
            fx = None

    monthly = pd.Series(0.0, index=range(1, 13))
    prop['Amount_KRW'] = (prop['Weight'] * capital).round(0)
    prop['Price_USD'] = prop['Symbol'].map(lambda s: snaps[s]['price'])
    prop['Shares'] = (prop['Amount_KRW'] / fx / prop['Price_USD']).round(2) if fx else None
    prop['Pay_Months'] = prop['Symbol'].map(lambda s: pay_months(snaps[s]))
    if fx:
        for _, p in prop.iterrows():
            for d, amt in snaps[p['Symbol']]['payments'].items():
                monthly[d.month] += amt * p['Shares'] * fx * (1 - TAX)
    empty = [m for m, v in monthly.items() if v == 0]
    fillers = []
    for m in empty:
        hits = [r['Symbol'] for _, r in extra_pool.iterrows() if m in pay_months(snaps[r['Symbol']])]
        fillers.append({'month': m, 'candidates': hits[:3]})

    cpi = load_macro_benchmarks()['cpi_annualized']

    def project(g, years, reinvest):
        k = (1 + g) * ((1 + y_net) if reinvest else 1)
        return round(target_m * k ** years, -2)

    scenarios = {'historical': gcagr, 'conservative_cpi': cpi}

    emit({
        'mode': 'plan',
        'freshness': freshness(uni),
        'macro': macro(),
        'inputs': {'track': a.track, 'monthly_krw': a.monthly_krw, 'capital_krw': a.capital_krw,
                   'other_income_krw': a.other_income_krw, 'usdkrw': fx,
                   'assumptions': '일반 계좌, 한국 거주자, 미국 원천징수 15%, 다른 금융소득은 입력값'},
        'portfolio': {'gross_yield': y, 'after_tax_yield': y_net, 'weighted_div_cagr_5y': gcagr,
                      'positions': records(prop, POS_COLS),
                      'sector_shares': prop.groupby('Sector_Label')['Weight'].sum().round(4).to_dict()},
        'result': {
            'capital_krw': round(capital, -4),
            'capital_usd': round(capital / fx, 0) if fx else None,
            'monthly_after_tax_krw': round(target_m, -2),
            'annual_gross_dividend_krw': round(gross_annual, -3),
            'annual_after_tax_krw': round(gross_annual * (1 - TAX), -3),
        },
        'tax': {
            'withholding': TAX,
            'financial_income_total_krw': round(total_fin, -3),
            'threshold_krw': THRESHOLD,
            'comprehensive_taxation': total_fin > THRESHOLD,
            'max_monthly_after_tax_below_threshold_krw':
                round(max(THRESHOLD - a.other_income_krw, 0) * (1 - TAX) / 12, -2),
        },
        'sensitivity': [{'gross_yield': sy,
                         ('capital_krw' if a.monthly_krw else 'monthly_after_tax_krw'):
                             round(target_m * 12 / (sy * (1 - TAX)), -4) if a.monthly_krw
                             else round(capital * sy * (1 - TAX) / 12, -2)} for sy in SENS_YIELDS],
        'projection_monthly_after_tax_krw': {
            'assumption': 'historical=가중 보정 5년 CAGR, conservative_cpi=물가만큼 성장. 배당률 불변, '
                          'reinvest=세후 배당 전액 재투자',
            'growth_rates': scenarios,
            **{name: {'no_reinvest': {str(t): project(g_, t, False) for t in (5, 10)},
                      'reinvest': {str(t): project(g_, t, True) for t in (5, 10)}}
               for name, g_ in scenarios.items()},
        },
        'calendar': {
            'basis': '최근 12개월 배당락일 기준, 세후 원화',
            'monthly_after_tax_krw': {int(m): round(v, -2) for m, v in monthly.items()},
            'empty_months': empty,
            'fillers': fillers,
        },
    })
