"""
Portfolio Diagnosis Page
Expected dividend income, monthly calendar, concentration and safety for an
existing portfolio (symbol -> shares). Logic lives in modules/portfolio_diagnosis.py.
"""

import streamlit as st
import pandas as pd
import plotly.express as px

from utils.cache_manager import load_prepared_dataframe, show_data_freshness_warning
from modules.portfolio_diagnosis import diagnose_portfolio
from config import AppConfig, BacktestConfig

st.set_page_config(page_title="Portfolio Diagnosis", page_icon="🩺", layout="wide")

st.title("🩺 Portfolio Diagnosis")
show_data_freshness_warning()
st.markdown(
    "보유 종목과 수량을 입력하면 예상 배당소득(USD/KRW, 세후), 월별 배당 캘린더, 섹터·종목 집중도, "
    "안전성 등급 분포와 주의 신호를 보여줍니다."
)

df = load_prepared_dataframe()
if df is None:
    st.error("No data available. Please return to home page and load data.")
    st.stop()

default_rows = st.session_state.get('diag_holdings', pd.DataFrame({'Symbol': ['', '', ''], 'Shares': [0.0, 0.0, 0.0]}))
edited = st.data_editor(
    default_rows,
    num_rows="dynamic",
    width='stretch',
    column_config={
        'Symbol': st.column_config.TextColumn("Symbol", help="US ticker, e.g. KO, O, SCHD"),
        'Shares': st.column_config.NumberColumn("Shares", min_value=0.0, step=1.0, format="%.4f"),
    },
    key='diag_editor',
)

pasted = st.text_area(
    "또는 붙여넣기 (한 줄에 '종목 수량', 예: KO 100)",
    value=st.session_state.get('diag_pasted', ''),
    height=110,
    help="입력하면 위 표 대신 이 내용으로 진단합니다. 쉼표·탭 구분도 됩니다.",
)


def _parse_pasted(text: str) -> dict:
    out = {}
    for line in text.splitlines():
        parts = line.replace(',', ' ').replace('\t', ' ').split()
        if len(parts) >= 2:
            try:
                out[parts[0].upper()] = out.get(parts[0].upper(), 0.0) + float(parts[1])
            except ValueError:
                continue
    return out


if st.button("🩺 Diagnose", type="primary"):
    if pasted.strip():
        holdings = {s: q for s, q in _parse_pasted(pasted).items() if q > 0}
        st.session_state['diag_pasted'] = pasted
    else:
        holdings = {str(r['Symbol']).strip().upper(): float(r['Shares'] or 0)
                    for _, r in edited.iterrows() if str(r['Symbol']).strip() and (r['Shares'] or 0) > 0}
    if not holdings:
        st.error("종목과 수량(0보다 큰 값)을 하나 이상 입력하세요.")
        st.stop()
    st.session_state['diag_holdings'] = edited
    with st.spinner("Fetching prices and dividend history..."):
        try:
            st.session_state['diag_result'] = diagnose_portfolio(holdings, df)
        except Exception as e:
            st.error(f"진단 실패: {e}")
            st.stop()

result = st.session_state.get('diag_result')
if result:
    s = result['summary']
    st.divider()
    st.subheader("📌 Summary")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("평가액", f"${s['total_value_usd']:,.0f}",
              f"₩{s['total_value_krw']:,.0f}" if pd.notna(s['total_value_krw']) else None, delta_color="off")
    c2.metric("예상 연 배당 (세전)", f"${s['annual_income_usd']:,.0f}",
              f"₩{s['annual_income_krw']:,.0f}" if pd.notna(s['annual_income_krw']) else None, delta_color="off")
    c3.metric(f"세후 (원천징수 {AppConfig.KR_DIVIDEND_WITHHOLDING:.0%})", f"${s['after_tax_income_usd']:,.0f}",
              f"₩{s['after_tax_income_krw']:,.0f}" if pd.notna(s['after_tax_income_krw']) else None, delta_color="off")
    c4.metric("포트폴리오 배당률", f"{s['portfolio_yield']:.2%}",
              f"소득가중 5Y 배당성장 {s['weighted_div_growth_5y']:.1%}", delta_color="off")
    if pd.notna(s['usdkrw']):
        st.caption(f"USD/KRW {s['usdkrw']:,.1f} 적용. 예상 배당 = 현재 연간 배당(주당) × 보유 수량.")
    if s['outside_universe']:
        st.caption(f"스크리너 유니버스 밖 종목(실시간 조회): {', '.join(s['outside_universe'])}")

    if s['flags']:
        st.warning("**주의 신호**\n\n" + "\n".join(f"- {f}" for f in s['flags']))
    else:
        st.success("주의 신호 없음")

    st.subheader("📋 Holdings")
    h = result['holdings'].copy()
    for col in ('Value_Share', 'Income_Share', 'Yield_On_Price', 'Div_CAGR_5Y_Adj'):
        if col in h.columns:
            h[col] = pd.to_numeric(h[col], errors='coerce').map(lambda v: f"{v:.1%}" if pd.notna(v) else '')
    st.dataframe(h, width='stretch', hide_index=True)

    col1, col2 = st.columns(2)
    with col1:
        st.subheader("📅 Monthly Dividend Calendar")
        m = result['monthly']
        fig = px.bar(m, x='Month', y='Income', labels={'Income': 'Income (USD, pre-tax)'})
        fig.update_xaxes(tickmode='linear', dtick=1)
        st.plotly_chart(fig, width='stretch')
        st.caption("최근 12개월 배당락일 기준 패턴 × 현재 수량. 실제 지급일은 보통 2~4주 뒤입니다.")
    with col2:
        st.subheader("🏷️ Sector Concentration")
        sec = result['sectors']
        fig2 = px.bar(sec, x='Sector_Label', y=['Value_Share', 'Income_Share'], barmode='group',
                      labels={'value': 'Share', 'Sector_Label': 'Sector'})
        fig2.update_yaxes(tickformat='.0%')
        st.plotly_chart(fig2, width='stretch')

    st.subheader("🛡️ Income by Safety Grade")
    g = result['grades']
    fig3 = px.bar(g, x='Safety_Grade', y='Income_Share')
    fig3.update_yaxes(tickformat='.0%')
    st.plotly_chart(fig3, width='stretch')
    st.caption(
        f"금융소득 종합과세 기준: 연 ₩{BacktestConfig.KR_FINANCIAL_INCOME_THRESHOLD_KRW:,.0f} "
        "(이자 등 다른 금융소득과 합산). 세금 정보는 일반적인 기준이며 실제 신고는 세무 전문가와 확인하세요."
    )
