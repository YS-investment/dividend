"""
Stock Details Page
Deep dive analysis for individual stocks with visualizations
"""

import streamlit as st
import pandas as pd
import yfinance as yf
from utils.cache_manager import load_main_dataframe, load_historical_prices
from modules.visualization import (
    create_price_chart_with_ema,
    create_yield_chart_with_stats,
    create_dividend_history_bar
)

st.set_page_config(page_title="Stock Details", page_icon="🔍", layout="wide")

st.title("🔍 Stock Details & Analysis")
st.markdown("Deep dive into individual stock dividend analysis with historical data and visualizations.")

# Load data
df = load_main_dataframe(use_cached=True)

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

col1, col2, col3 = st.columns(3)

with col1:
    st.metric("Dividend Yield", f"{stock_data.get('Div. Yield', 0) * 100:.2f}%")
    st.metric("Annual Dividend", f"${stock_data.get('Div. ($)', 0):.2f}")

with col2:
    st.metric("Payout Ratio", f"{stock_data.get('Payout Ratio', 0) * 100:.1f}%")
    st.metric("Dividend Years", f"{int(stock_data.get('Years', 0))}")

with col3:
    st.metric("1Y Growth", f"{stock_data.get('Div. Growth', 0) * 100:.2f}%")
    st.metric("5Y CAGR", f"{stock_data.get('Div. Growth 5Y', 0) * 100:.2f}%")

# Financial Health Metrics
st.markdown("---")
st.subheader("Financial Health Metrics")

col4, col5, col6 = st.columns(3)

with col4:
    fcf_ratio = stock_data.get('FCF_Dividend_Ratio', 0)
    if fcf_ratio > 0:
        st.metric(
            "FCF/Dividend Ratio",
            f"{fcf_ratio:.2f}x",
            help="Free Cash Flow divided by Total Dividends Paid. >1.0 means FCF fully covers dividends."
        )
    else:
        st.metric("FCF/Dividend Ratio", "N/A", help="Data not available")

with col5:
    debt_to_equity = stock_data.get('Debt_to_Equity', 0)
    if debt_to_equity >= 0:
        st.metric(
            "Debt-to-Equity (D/E)",
            f"{debt_to_equity:.2f}",
            help="Total debt divided by shareholder equity. Lower values indicate less financial leverage."
        )
    else:
        st.metric("Debt-to-Equity (D/E)", "N/A", help="Data not available")

with col6:
    roe = stock_data.get('ROE', 0)
    if roe != 0:
        st.metric(
            "ROE",
            f"{roe:.2f}%",
            help="Return on Equity. Measures profitability - how much profit is generated per dollar of equity."
        )
    else:
        st.metric("ROE", "N/A", help="Data not available")

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
        hist_data = ticker.history(period="5y")
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
