"""
Stock Details Page
Deep dive analysis for individual stocks with visualizations
"""

import streamlit as st
import pandas as pd
import yfinance as yf
from config import AppConfig
from utils.cache_manager import load_prepared_dataframe, load_historical_prices, show_data_freshness_warning
from modules.visualization import (
    create_price_chart_with_ema,
    create_yield_chart_with_stats,
    create_dividend_history_bar
)

st.set_page_config(page_title="Stock Details", page_icon="🔍", layout="wide")

st.title("🔍 Stock Details & Analysis")
show_data_freshness_warning()
st.markdown("Deep dive into individual stock dividend analysis with historical data and visualizations.")

# Load data
df = load_prepared_dataframe()

if df is None:
    st.error("No data available. Please return to home page and load data.")
    st.stop()

# Stock selector
st.subheader("Select Stock")

# Get available symbols
available_symbols = sorted(df['Symbol'].unique().tolist()) if 'Symbol' in df.columns else []

if not available_symbols:
    st.error("No stock symbols available")
    st.stop()

selected_symbol = st.selectbox(
    "Choose a stock to analyze",
    options=available_symbols,
    index=0
)

# Get stock data
stock_data = df[df['Symbol'] == selected_symbol].iloc[0] if len(df[df['Symbol'] == selected_symbol]) > 0 else None

if stock_data is None:
    st.error(f"No data found for {selected_symbol}")
    st.stop()

st.divider()

# Display key metrics
st.subheader(f"{selected_symbol} - {stock_data.get('Company Name', 'N/A')}")

col1, col2, col3, col4 = st.columns(4)

with col1:
    st.metric("Dividend Yield", f"{stock_data.get('Div. Yield', 0) * 100:.2f}%")
    st.metric("Annual Dividend", f"${stock_data.get('Div. ($)', 0):.2f}")

with col2:
    st.metric("Payout Ratio", f"{stock_data.get('Payout Ratio', 0) * 100:.1f}%")
    st.metric("Dividend Growth Years", f"{int(stock_data.get('Div. Gr. Years', 0))}")

with col3:
    st.metric("Dividend Payment Years", f"{int(stock_data.get('Div. Years', 0))}")
    st.metric("1Y Growth", f"{stock_data.get('Div. Growth', 0) * 100:.2f}%")

with col4:
    st.metric("5Y CAGR", f"{stock_data.get('Div. Growth 5Y', 0) * 100:.2f}%")
    st.metric(
        "Market Cap Tier",
        stock_data.get('mkt_cap_tier', 'N/A'),
        help="Russell Index style tier: Mega ($200B+) / Large ($10-200B) / Mid ($2-10B) / Small ($300M-2B) / Micro ($50-300M) / Nano (<$50M)"
    )

# Financial Health Metrics
st.markdown("---")
st.subheader("Financial Health Metrics")
st.caption(
    f"Sector group: **{stock_data.get('Sector_Group', 'N/A')}** — the screeners apply this group's "
    "leverage / coverage / payout rules. Coverage basis: "
    f"**{str(stock_data.get('Coverage_Basis', 'N/A')).upper()}**."
)


def _fmt(value, kind):
    if value is None or (not isinstance(value, str) and pd.isna(value)):
        return "N/A"
    if kind == 'x':
        return f"{value:.2f}x"
    if kind == 'pct':
        return f"{value * 100:.2f}%"
    if kind == 'pct_raw':
        return f"{value:.2f}%"
    if kind == 'num':
        return f"{value:.1f}"
    if isinstance(value, str) and not value:
        return "—"
    if kind == 'int':
        return f"{int(value)} / {len(AppConfig.CRISIS_YEARS)}"
    return str(value)


HEALTH_METRICS = [
    ("Safety Grade", 'Safety_Grade', 'str', "A-F from coverage, leverage, interest coverage, cut history, earnings "
                                            "stability, plus a bonus for growing the dividend through 2008"),
    ("Dividend Coverage", 'Div_Coverage', 'x', "Sector-appropriate: 3Y FCF/div, 3Y OCF/div (REIT/MLP), or 1/payout"),
    ("Net Debt / EBITDA", 'Net_Debt_EBITDA', 'x', "Negative = net cash"),
    ("Interest Coverage", 'Interest_Coverage', 'x', "EBIT / interest expense (latest year)"),
    ("Adj. 5Y Div CAGR", 'Div_CAGR_5Y_Adj', 'pct', "5Y CAGR corrected for cut-rebound base effects"),
    ("Valuation", 'Valuation', 'str', "From the current TTM yield's percentile within its 5Y history"),
    ("Yield Percentile (5Y)", 'Yield_Pctl_5Y', 'num', "0 = lowest yield (richest) in 5Y, 100 = highest (cheapest)"),
    ("P/FCF (3Y avg)", 'P_FCF', 'num', "Market cap / 3Y average free cash flow"),
    ("Revenue CAGR 3Y", 'Revenue_CAGR_3Y', 'pct', "Annual statements"),
    ("EPS CAGR 3Y", 'EPS_CAGR_3Y', 'pct', "Diluted EPS, annual statements"),
    ("ROE", 'ROE', 'pct_raw', "Return on equity"),
    ("Trailing EPS", 'Trailing_EPS', 'num', "Net-loss gate (EPS <= 0 fails, except REIT/MLP)"),
    ("Shareholder Yield", 'Shareholder_Yield', 'pct', "Dividend yield + net buyback yield"),
    ("Net Buyback Yield", 'Net_Buyback_Yield', 'pct', "(Repurchases - issuance) / market cap, latest year"),
    ("Shares Change 3Y", 'Shares_Change_3Y', 'pct', "Negative = buybacks shrinking share count; positive = dilution"),
    ("Crises Passed", 'Crisis_Count', 'int', "Crises (2000/2008/2020) the dividend kept growing through, from the "
                                              "consecutive-increase streak. Passing 2008 adds a safety bonus"),
    ("Price vs 20D MA", 'Price_vs_MA20', 'pct', "Last close vs 20-day average (as of data update)"),
    ("RSI (14)", 'RSI_14', 'num', f"≤{AppConfig.TIMING_RSI_OVERSOLD} = oversold"),
    ("MFI (14)", 'MFI_14', 'num', f"≤{AppConfig.TIMING_MFI_OVERSOLD} = oversold (volume-weighted)"),
    ("Timing", 'Timing_Signal', 'str', "과매도 / 20일선 아래 - reference only, not a filter"),
]

for row_start in range(0, len(HEALTH_METRICS), 5):
    cols = st.columns(5)
    for col, (label, key, kind, help_text) in zip(cols, HEALTH_METRICS[row_start:row_start + 5]):
        with col:
            st.metric(label, _fmt(stock_data.get(key), kind), help=help_text)

flags = []
if bool(stock_data.get('Div_Suspended')):
    flags.append(f"⛔ 배당 중단 의심 — 마지막 정기 배당 {stock_data.get('Div_Last_Pay_Date') or '?'} 이후 지급 없음")
elif bool(stock_data.get('Cut_Flag')):
    last_cut = stock_data.get('Div_Last_Cut_Year')
    flags.append(f"⚠️ 최근 10년 내 배당 삭감 감지 ({int(last_cut) if pd.notna(last_cut) else '?'}년)")
for key in ('Yield_Trap', 'EPS_Alert'):
    if stock_data.get(key):
        flags.append(str(stock_data.get(key)))
if flags:
    st.warning("  \n".join(flags))
badges = [b for b in (stock_data.get('Growth_Badge'),
                      f"위기 통과: {stock_data.get('Crisis_Passed')}" if stock_data.get('Crisis_Passed') else '') if b]
if badges:
    st.success("  \n".join(f"✅ {b}" for b in badges))
if stock_data.get('Timing_As_Of'):
    st.caption(f"Timing indicators as of {stock_data.get('Timing_As_Of')}")
if stock_data.get('Safety_Detail'):
    st.caption(f"Safety components (0-2 each): {stock_data.get('Safety_Detail')}")

st.divider()

# Tabs for different analyses
tab1, tab2, tab3 = st.tabs([
    "📈 Price & Yield History",
    "💰 Dividend History",
    "ℹ️ Company Info"
])

# Fetch historical data
with st.spinner(f"Loading historical data for {selected_symbol}..."):
    try:
        ticker = yf.Ticker(selected_symbol)
        hist_data = ticker.history(period="5y", auto_adjust=False)
        dividends = ticker.dividends
        calendar = ticker.calendar
        info = ticker.info
    except Exception as e:
        st.error(f"Error fetching data: {str(e)}")
        hist_data = None
        dividends = None
        calendar = None
        info = {}

with tab1:
    st.subheader("Price & Dividend Yield History")

    # Period selector
    period = st.radio(
        "Select Time Period",
        options=["1Y", "3Y", "5Y", "10Y", "Max"],
        index=2,
        horizontal=True
    )

    period_map = {"1Y": "1y", "3Y": "3y", "5Y": "5y", "10Y": "10y", "Max": "max"}

    with st.spinner(f"Loading {period} data..."):
        try:
            period_data = load_historical_prices(selected_symbol, period=period_map[period])

            if period_data is not None and len(period_data) > 0:
                # Price chart with EMA
                st.markdown("### Stock Price with EMA")
                price_fig = create_price_chart_with_ema(
                    period_data,
                    title=f"{selected_symbol} - Price with EMA ({period})"
                )
                st.plotly_chart(price_fig, width='stretch')

                # Calculate dividend yield
                if len(dividends) > 0:
                    # Align dividends with price data
                    yield_series = pd.Series(index=period_data.index, dtype=float)

                    for date in period_data.index:
                        # Get last known dividend
                        recent_divs = dividends[dividends.index <= date]
                        if len(recent_divs) > 0:
                            last_div = recent_divs.iloc[-1]
                            # Annualize (assuming quarterly)
                            annual_div = last_div * 4
                            yield_series[date] = annual_div / period_data.loc[date, 'Close']
                        else:
                            yield_series[date] = 0

                    # Dividend yield chart with statistics
                    st.markdown("### Dividend Yield with Statistics")
                    yield_fig = create_yield_chart_with_stats(
                        yield_series,
                        title=f"{selected_symbol} - Dividend Yield ({period})"
                    )
                    st.plotly_chart(yield_fig, width='stretch')
                else:
                    st.info("No dividend data available for yield calculation")
            else:
                st.warning(f"No price data available for {period}")

        except Exception as e:
            st.error(f"Error loading period data: {str(e)}")

with tab2:
    st.subheader("Dividend Payment History")

    # Show upcoming dividend dates if available
    if calendar and isinstance(calendar, dict):
        ex_div_date = calendar.get('Ex-Dividend Date')
        div_date = calendar.get('Dividend Date')

        if ex_div_date or div_date:
            st.markdown("#### Upcoming Dividend Information")
            col1, col2 = st.columns(2)

            with col1:
                if ex_div_date:
                    st.metric("Next Ex-Dividend Date", ex_div_date.strftime('%Y-%m-%d'))

            with col2:
                if div_date:
                    st.metric("Next Payment Date", div_date.strftime('%Y-%m-%d'))

            st.divider()

    if dividends is not None and len(dividends) > 0:
        # Bar chart of annual dividends
        fig = create_dividend_history_bar(dividends)
        st.plotly_chart(fig, width='stretch')

        # Dividend payment table
        st.subheader("Historical Dividend Payments")
        recent_divs = dividends.tail(20).sort_index(ascending=False)
        div_df = pd.DataFrame({
            'Date': recent_divs.index.strftime('%Y-%m-%d'),
            'Dividend ($)': recent_divs.values.round(4)
        })
        st.dataframe(div_df, width='stretch', hide_index=True)
    else:
        st.info("No dividend payment history available")

with tab3:
    st.subheader("Company Information")

    if info:
        # Display company details
        col1, col2 = st.columns(2)

        with col1:
            st.markdown("**Sector:**")
            st.write(info.get('sector', 'N/A'))

            st.markdown("**Industry:**")
            st.write(info.get('industry', 'N/A'))

            st.markdown("**Website:**")
            website = info.get('website', '')
            if website:
                st.markdown(f"[{website}]({website})")
            else:
                st.write("N/A")

        with col2:
            st.markdown("**Market Cap:**")
            market_cap = info.get('marketCap', 0)
            if market_cap > 1e9:
                st.write(f"${market_cap / 1e9:.2f}B")
            elif market_cap > 1e6:
                st.write(f"${market_cap / 1e6:.2f}M")
            else:
                st.write("N/A")

            st.markdown("**Employees:**")
            st.write(f"{info.get('fullTimeEmployees', 'N/A'):,}" if info.get('fullTimeEmployees') else "N/A")

            st.markdown("**Exchange:**")
            st.write(info.get('exchange', 'N/A'))

        # Company description
        st.divider()
        st.markdown("**Business Description:**")
        description = info.get('longBusinessSummary', info.get('description', 'No description available'))
        st.write(description)

    else:
        st.info("Company information not available")

# Footer note
st.divider()
st.caption("Data provided by Yahoo Finance. Information may be delayed.")
