"""
Portfolio Backtest Simulator Page

Comprehensive portfolio performance analysis with:
- DRIP (Dividend Reinvestment Plan) simulation
- Tax impact modeling
- Advanced risk metrics
- Benchmark comparison (S&P 500)
"""

import streamlit as st
import pandas as pd
import numpy as np
from datetime import datetime
import sys
import os

# Add parent directory to path for imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modules.portfolio_backtester import PortfolioBacktester
from modules.visualization import (
    create_portfolio_growth_chart,
    create_dividend_income_chart,
    create_cumulative_dividend_chart,
    create_underwater_chart,
    create_return_distribution_chart,
    create_tax_payment_chart,
    create_pre_post_tax_comparison
)
from utils.cache_manager import load_main_dataframe
from config import BacktestConfig

# Page configuration
st.set_page_config(
    page_title="Portfolio Backtest",
    page_icon="📊",
    layout="wide"
)

# Header
st.title("📊 Portfolio Backtest Simulator")
st.markdown("""
Comprehensive portfolio performance analysis featuring:
- **DRIP Simulation**: Automatic dividend reinvestment with fractional shares
- **Tax Modeling**: Qualified dividend and capital gains tax calculation
- **Risk Metrics**: Sharpe, Sortino, MDD, Beta, Alpha, VaR and more
- **Benchmark Comparison**: Compare against S&P 500 (SPY)
""")

st.divider()

# Load main dataframe
df = load_main_dataframe()

if df is None or df.empty:
    st.error("Failed to load dividend data. Please check data files.")
    st.stop()

# --- SIDEBAR: Portfolio Configuration ---
st.sidebar.header("1. Portfolio Composition")

# Stock selection
selected_stocks = st.sidebar.multiselect(
    "Select Stocks (max 20)",
    options=sorted(df['Symbol'].unique().tolist()),
    default=[],
    help="Choose up to 20 stocks for your portfolio"
)

if len(selected_stocks) > BacktestConfig.MAX_PORTFOLIO_STOCKS:
    st.sidebar.error(f"Maximum {BacktestConfig.MAX_PORTFOLIO_STOCKS} stocks allowed!")
    selected_stocks = selected_stocks[:BacktestConfig.MAX_PORTFOLIO_STOCKS]

# Allocation method
allocation_method = st.sidebar.radio(
    "Allocation Method",
    BacktestConfig.ALLOCATION_METHODS,
    help="Choose how to allocate your investment across selected stocks"
)

# Custom weights (if selected)
weights = {}
if allocation_method == "Custom Weight" and len(selected_stocks) > 0:
    st.sidebar.subheader("Custom Allocation")

    for stock in selected_stocks:
        weights[stock] = st.sidebar.slider(
            f"{stock} Weight (%)",
            min_value=0,
            max_value=100,
            value=100 // len(selected_stocks),
            step=1
        ) / 100

    # Validate total weight
    total_weight = sum(weights.values())
    if not np.isclose(total_weight, 1.0, atol=0.01):
        st.sidebar.warning(f"⚠️ Total weight: {total_weight*100:.1f}% (must be 100%)")
    else:
        st.sidebar.success(f"✓ Total weight: {total_weight*100:.1f}%")

st.sidebar.divider()

# --- SIDEBAR: Backtest Settings ---
st.sidebar.header("2. Backtest Settings")

# Date range
col1, col2 = st.sidebar.columns(2)
with col1:
    start_date = st.date_input(
        "Start Date",
        value=pd.to_datetime(BacktestConfig.DEFAULT_START_DATE),
        min_value=pd.to_datetime("2000-01-01"),
        max_value=pd.to_datetime("today")
    )

with col2:
    end_date = st.date_input(
        "End Date",
        value=pd.to_datetime("today"),
        min_value=start_date
    )

# Investment amounts
initial_investment = st.sidebar.number_input(
    "Initial Investment ($)",
    min_value=1000,
    max_value=10000000,
    value=BacktestConfig.DEFAULT_INITIAL_INVESTMENT,
    step=1000,
    help="Initial lump sum investment"
)

monthly_contribution = st.sidebar.number_input(
    "Monthly Contribution ($)",
    min_value=0,
    max_value=100000,
    value=BacktestConfig.DEFAULT_MONTHLY_CONTRIBUTION,
    step=100,
    help="Amount to invest each month"
)

# DRIP settings
drip_enabled = st.sidebar.checkbox(
    "Enable DRIP",
    value=True,
    help="Automatically reinvest dividends to purchase additional shares"
)

drip_fee = 0.0
if drip_enabled:
    drip_fee = st.sidebar.number_input(
        "DRIP Fee (%)",
        min_value=0.0,
        max_value=5.0,
        value=BacktestConfig.DEFAULT_DRIP_FEE,
        step=0.1,
        help="Fee charged for dividend reinvestment (typically 0%)"
    ) / 100

# Tax settings
tax_enabled = st.sidebar.checkbox(
    "Include Tax Impact",
    value=False,
    help="Model the impact of dividend income and capital gains taxes"
)

tax_config = None
if tax_enabled:
    with st.sidebar.expander("⚙️ Tax Configuration", expanded=False):
        tax_config = {
            'qualified_dividend_rate': st.number_input(
                "Qualified Dividend Tax Rate (%)",
                min_value=0.0,
                max_value=50.0,
                value=BacktestConfig.DEFAULT_QUALIFIED_DIVIDEND_TAX * 100,
                step=0.5,
                help="Tax rate for qualified dividends (held > 60 days)"
            ) / 100,
            'ordinary_dividend_rate': st.number_input(
                "Ordinary Dividend Tax Rate (%)",
                min_value=0.0,
                max_value=50.0,
                value=BacktestConfig.DEFAULT_ORDINARY_DIVIDEND_TAX * 100,
                step=0.5,
                help="Tax rate for ordinary dividends"
            ) / 100,
            'long_term_capital_gains_rate': st.number_input(
                "Long-term Capital Gains Tax Rate (%)",
                min_value=0.0,
                max_value=50.0,
                value=BacktestConfig.DEFAULT_LONG_TERM_CAPITAL_GAINS_TAX * 100,
                step=0.5,
                help="Tax rate for assets held > 1 year"
            ) / 100
        }

st.sidebar.divider()

# --- REBALANCING SETTINGS ---
st.sidebar.header("3. Rebalancing Strategy")

rebalancing_frequency = st.sidebar.selectbox(
    "Rebalancing Frequency",
    options=BacktestConfig.REBALANCING_FREQUENCIES,
    index=0,
    help="How often to rebalance portfolio back to target weights"
)

rebalancing_fee = 0.0
if rebalancing_frequency != "No Rebalancing":
    rebalancing_fee = st.sidebar.number_input(
        "Rebalancing Fee (%)",
        min_value=0.0,
        max_value=2.0,
        value=BacktestConfig.DEFAULT_REBALANCING_FEE * 100,
        step=0.01,
        help="Trading fee percentage per rebalancing transaction"
    ) / 100

    st.sidebar.info(f"📊 Rebalancing will occur **{rebalancing_frequency.lower()}** to maintain target allocation weights.")

st.sidebar.divider()

# --- RUN BACKTEST BUTTON ---
run_backtest = st.sidebar.button(
    "🚀 Run Backtest",
    type="primary",
    width='stretch'
)

# --- MAIN CONTENT AREA ---
if run_backtest:
    if len(selected_stocks) == 0:
        st.error("⚠️ Please select at least one stock to backtest.")
        st.stop()

    # Calculate weights based on allocation method
    if allocation_method == "Equal Weight":
        weights = {stock: 1/len(selected_stocks) for stock in selected_stocks}

    elif allocation_method == "Yield Weight":
        # Weight by dividend yield
        stock_data = df[df['Symbol'].isin(selected_stocks)].set_index('Symbol')
        yields = stock_data['Div. Yield'].fillna(0)
        total_yield = yields.sum()

        if total_yield > 0:
            weights = {stock: yields[stock]/total_yield for stock in selected_stocks}
        else:
            st.warning("No yield data available, using equal weights")
            weights = {stock: 1/len(selected_stocks) for stock in selected_stocks}

    elif allocation_method == "Market Cap Weight":
        st.info("Market cap weighting requires additional data. Using equal weights for now.")
        weights = {stock: 1/len(selected_stocks) for stock in selected_stocks}

    elif allocation_method == "Custom Weight":
        # Weights already defined above
        pass

    # Validate weights
    if not np.isclose(sum(weights.values()), 1.0, atol=0.01):
        st.error("Weights must sum to 100%. Please adjust your custom weights.")
        st.stop()

    # Run backtest
    with st.spinner("🔄 Running backtest... This may take 10-30 seconds for large portfolios."):
        try:
            # Initialize backtester
            backtester = PortfolioBacktester(
                stocks=selected_stocks,
                weights=weights,
                start_date=start_date.strftime('%Y-%m-%d'),
                end_date=end_date.strftime('%Y-%m-%d'),
                initial_investment=initial_investment,
                monthly_contribution=monthly_contribution
            )

            # Fetch data
            st.info("📥 Fetching historical data from Yahoo Finance...")
            backtester.fetch_historical_data()
            backtester.fetch_benchmark_data()
            backtester.fetch_schd_data()

            # Run backtest
            st.info("⚙️ Simulating portfolio performance...")
            results = backtester.run_backtest(
                drip_enabled=drip_enabled,
                drip_fee=drip_fee,
                tax_config=tax_config,
                rebalancing_frequency=rebalancing_frequency,
                rebalancing_fee=rebalancing_fee
            )

            # Store results in session state
            st.session_state['backtest_results'] = results
            st.session_state['backtest_params'] = {
                'stocks': selected_stocks,
                'weights': weights,
                'start_date': start_date,
                'end_date': end_date,
                'initial_investment': initial_investment,
                'monthly_contribution': monthly_contribution,
                'drip_enabled': drip_enabled,
                'tax_enabled': tax_enabled,
                'rebalancing_frequency': rebalancing_frequency,
                'rebalancing_fee': rebalancing_fee
            }

            st.success("✅ Backtest complete!")

        except Exception as e:
            st.error(f"❌ Error running backtest: {str(e)}")
            st.exception(e)
            st.stop()

# --- DISPLAY RESULTS ---
if 'backtest_results' in st.session_state:
    results = st.session_state['backtest_results']
    params = st.session_state.get('backtest_params', {})
    metrics = results['metrics']

    st.header("📈 Performance Summary")

    # --- KEY METRICS (4 columns) ---
    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.metric(
            "Final Portfolio Value",
            f"${metrics['final_value']:,.2f}",
            delta=f"{metrics['total_return']:.2f}%",
            help="Total value of portfolio at end of backtest period. Delta shows total return percentage from initial investment."
        )
        st.metric(
            "Total Dividends Received",
            f"${metrics['total_dividends']:,.2f}",
            help="Sum of all dividend payments received during the entire backtest period. If DRIP is enabled, these dividends were automatically reinvested."
        )

    with col2:
        st.metric(
            "Annualized Return",
            f"{metrics['annualized_return']:.2f}%",
            help="Average daily return scaled to annual basis (daily return × 252 trading days). Shows what you'd expect to earn per year on average."
        )
        st.metric(
            "Annual Dividend Income",
            f"${metrics['annual_dividend_income']:,.2f}",
            help="Average dividend income per year (total dividends ÷ number of years). Represents steady cash flow from dividends."
        )

    with col3:
        st.metric(
            "CAGR",
            f"{metrics['cagr']:.2f}%",
            help="Compound Annual Growth Rate: The rate at which your investment would grow each year if it grew at a steady rate. More accurate than simple annualized return."
        )
        st.metric(
            "Sharpe Ratio",
            f"{metrics['sharpe_ratio']:.2f}",
            help="Risk-adjusted return metric (return ÷ volatility). Higher is better. >1 is good, >2 is very good. Measures excess return per unit of risk."
        )

    with col4:
        st.metric(
            "Max Drawdown",
            f"{metrics['max_drawdown']:.2f}%",
            delta=None,
            delta_color="inverse",
            help="Largest peak-to-trough decline during the period. Shows the worst loss you would have experienced. Lower (less negative) is better."
        )
        st.metric(
            "Sortino Ratio",
            f"{metrics['sortino_ratio']:.2f}",
            help="Like Sharpe Ratio but only considers downside volatility. Better measure of risk-adjusted returns. Higher values indicate better risk management."
        )

    # --- ADVANCED RISK METRICS (Expandable) ---
    with st.expander("📊 Advanced Risk Metrics", expanded=False):
        col1, col2, col3, col4 = st.columns(4)

        with col1:
            st.metric(
                "Calmar Ratio",
                f"{metrics['calmar_ratio']:.2f}",
                help="CAGR divided by absolute Max Drawdown. Measures return relative to worst loss. >0.5 is good, >1.0 is excellent. Shows if high returns justify the risk."
            )
            st.metric(
                "Beta (vs SPY)",
                f"{metrics['beta']:.2f}",
                help="Measures volatility relative to S&P 500. β<1 means less volatile (defensive), β=1 matches market, β>1 is more volatile (aggressive). Your portfolio's sensitivity to market movements."
            )

        with col2:
            st.metric(
                "Alpha",
                f"{metrics['alpha']:.2f}%",
                help="Excess return beyond what Beta predicts. Positive alpha means outperforming the market after adjusting for risk. Measures manager skill or strategy effectiveness."
            )
            st.metric(
                "Annual Volatility",
                f"{metrics['volatility']:.2f}%",
                help="Standard deviation of returns annualized. Shows how much returns fluctuate. Lower is more stable. Typical stock portfolios: 15-25%. Your comfort with price swings."
            )

        with col3:
            st.metric(
                "VaR (95%)",
                f"{metrics['var_95']:.2f}%",
                help="Value at Risk: Maximum expected daily loss at 95% confidence. There's only a 5% chance of losing more than this in a single day. Risk management metric."
            )
            st.metric(
                "Benchmark Return",
                f"{metrics['benchmark_return']:.2f}%",
                help="Total return of S&P 500 (SPY) over the same period with same settings. Used to compare your portfolio's performance against the market."
            )

        with col4:
            st.metric(
                "Outperformance",
                f"{metrics['outperformance']:.2f}%",
                help="Portfolio return minus benchmark return. Positive means you beat the market. Shows whether active management added value vs. just buying SPY."
            )
            st.metric(
                "Win Rate",
                f"{metrics['win_rate']:.2f}%",
                help="Percentage of trading days with positive returns. >50% means more up days than down days. Reflects consistency of gains but doesn't measure magnitude."
            )

    st.divider()

    # --- CHARTS (4 Tabs) ---
    st.header("📊 Visual Analysis")

    chart_tab1, chart_tab2, chart_tab3, chart_tab4 = st.tabs([
        "📈 Portfolio Growth",
        "💰 Dividend Income",
        "📉 Drawdown Analysis",
        "💸 Tax Impact"
    ])

    with chart_tab1:
        st.subheader("Portfolio Value Over Time")

        try:
            fig = create_portfolio_growth_chart(
                results['daily_values'],
                results['daily_values_no_drip'],
                results['benchmark_values'],
                results.get('buyhold_values'),
                results.get('schd_values')
            )
            st.plotly_chart(fig, width='stretch')
        except Exception as e:
            st.error(f"Error creating portfolio growth chart: {str(e)}")
            st.info("Chart visualization functions are being implemented. Using placeholder.")

    with chart_tab2:
        st.subheader("Dividend Income Analysis")

        if not results['dividend_history'].empty:
            try:
                # Annual dividend income chart
                fig1 = create_dividend_income_chart(results['dividend_history'])
                st.plotly_chart(fig1, width='stretch')

                # Cumulative dividend chart
                fig2 = create_cumulative_dividend_chart(results['dividend_history'])
                st.plotly_chart(fig2, width='stretch')
            except Exception as e:
                st.error(f"Error creating dividend charts: {str(e)}")
                st.info("Chart visualization functions are being implemented.")
        else:
            st.info("No dividend data available for the selected period.")

    with chart_tab3:
        st.subheader("Risk & Drawdown Analysis")

        try:
            # Underwater chart
            fig1 = create_underwater_chart(results['daily_values'])
            st.plotly_chart(fig1, width='stretch')

            # Return distribution
            fig2 = create_return_distribution_chart(results['daily_values'])
            st.plotly_chart(fig2, width='stretch')
        except Exception as e:
            st.error(f"Error creating drawdown charts: {str(e)}")
            st.info("Chart visualization functions are being implemented.")

    with chart_tab4:
        if tax_enabled and not results['tax_payments'].empty:
            st.subheader("Tax Impact Analysis")

            try:
                # Tax payment timeline
                fig1 = create_tax_payment_chart(results['tax_payments'])
                st.plotly_chart(fig1, width='stretch')

                # Pre vs post-tax comparison
                fig2 = create_pre_post_tax_comparison(results)
                st.plotly_chart(fig2, width='stretch')
            except Exception as e:
                st.error(f"Error creating tax charts: {str(e)}")
                st.info("Chart visualization functions are being implemented.")
        else:
            st.info("💡 Tax impact analysis is disabled. Enable it in the sidebar to see tax-related charts.")

    st.divider()

    # --- DETAILED HOLDINGS TABLE ---
    with st.expander("📋 View Detailed Holdings", expanded=False):
        if not results['holdings'].empty:
            st.dataframe(
                results['holdings'],
                column_config={
                    "Symbol": st.column_config.TextColumn("Ticker", width="small"),
                    "Shares": st.column_config.NumberColumn("Shares", format="%.4f"),
                    "Current Price": st.column_config.NumberColumn("Price", format="$%.2f"),
                    "Market Value": st.column_config.NumberColumn("Value", format="$%.2f"),
                    "Total Dividends": st.column_config.NumberColumn("Dividends Received", format="$%.2f")
                },
                width='stretch',
                hide_index=True
            )

            # Download CSV button
            csv = results['holdings'].to_csv(index=False)
            st.download_button(
                label="📥 Download Holdings as CSV",
                data=csv,
                file_name=f"portfolio_holdings_{datetime.now().strftime('%Y%m%d')}.csv",
                mime="text/csv"
            )
        else:
            st.info("No holdings data available.")

    # --- REBALANCING HISTORY ---
    if not results.get('rebalancing_history', pd.DataFrame()).empty:
        with st.expander("🔄 View Rebalancing History", expanded=False):
            rebalancing_df = results['rebalancing_history']

            st.markdown(f"**Total Rebalancing Events:** {len(rebalancing_df)}")

            if len(rebalancing_df) > 0:
                total_rebal_fees = rebalancing_df['Fees'].sum()
                total_rebal_taxes = rebalancing_df['Taxes'].sum()

                col1, col2, col3 = st.columns(3)
                with col1:
                    st.metric("Total Rebalancing Events", len(rebalancing_df))
                with col2:
                    st.metric("Total Fees Paid", f"${total_rebal_fees:,.2f}")
                with col3:
                    st.metric("Total Taxes Paid", f"${total_rebal_taxes:,.2f}")

                st.dataframe(
                    rebalancing_df,
                    column_config={
                        "Date": st.column_config.DateColumn("Date", format="YYYY-MM-DD"),
                        "Fees": st.column_config.NumberColumn("Fees", format="$%.2f"),
                        "Taxes": st.column_config.NumberColumn("Taxes", format="$%.2f")
                    },
                    width='stretch',
                    hide_index=True
                )

                # Download CSV button
                csv = rebalancing_df.to_csv(index=False)
                st.download_button(
                    label="📥 Download Rebalancing History as CSV",
                    data=csv,
                    file_name=f"rebalancing_history_{datetime.now().strftime('%Y%m%d')}.csv",
                    mime="text/csv"
                )

else:
    # Initial state - show instructions
    st.info("""
    👈 **Get Started:**

    1. Select stocks from the sidebar (up to 20)
    2. Choose an allocation method
    3. Configure backtest settings (dates, investment amounts)
    4. Optionally enable DRIP and tax modeling
    5. Choose rebalancing strategy (None for Buy & Hold, or Monthly/Quarterly/etc.)
    6. Click "🚀 Run Backtest" to see results

    **Note:** This simulation uses fractional shares for accurate DRIP modeling.

    **Rebalancing:** Choose a frequency to automatically adjust portfolio back to target weights.
    This incurs trading fees and potential capital gains taxes.
    """)

    # Show sample portfolio suggestion
    if not df.empty:
        st.subheader("💡 Sample Portfolio Ideas")

        col1, col2 = st.columns(2)

        with col1:
            st.markdown("**High Dividend Yield**")
            top_yield = df.nlargest(5, 'Div. Yield')[['Symbol', 'Company Name', 'Div. Yield']].head(5)
            st.dataframe(top_yield, hide_index=True, width='stretch')

        with col2:
            st.markdown("**Dividend Aristocrats (25+ years)**")
            aristocrats = df[df['Years'] >= 25].nlargest(5, 'Years')[['Symbol', 'Company Name', 'Years']].head(5)
            if not aristocrats.empty:
                st.dataframe(aristocrats, hide_index=True, width='stretch')
            else:
                st.info("Filter data to see dividend aristocrats")
