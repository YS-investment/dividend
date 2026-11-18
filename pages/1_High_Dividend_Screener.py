"""
High Dividend Stock Screener
Filter and rank stocks based on dividend yield with customizable criteria
"""

import streamlit as st
import pandas as pd
from utils.cache_manager import load_prepared_dataframe, load_macro, show_data_freshness_warning
from modules.data_processor import (
    filter_stocks,
    calculate_composite_score,
)
from modules.visualization import (
    create_top_stocks_bar_chart,
    create_scatter_plot,
    create_distribution_histogram
)
from config import AppConfig

st.set_page_config(page_title="High Dividend Screener", page_icon="📊", layout="wide")

st.title("📊 High Dividend Stock Screener")
show_data_freshness_warning()
st.markdown("Filter and analyze high-yielding dividend stocks with custom criteria and weightings.")

# Load data (derived metrics + universe-wide percentile ranks already computed)
df = load_prepared_dataframe()

if df is None:
    st.error("No data available. Please return to home page and load data.")
    st.stop()

macro = load_macro()
rate_floor_pct = max(round(macro['treasury_10y_ma'] * 100, 2), AppConfig.UNIVERSE_MIN_YIELD * 100)
cpi_pct = round(macro['cpi_annualized'] * 100, 2)

# Sidebar Filters
st.sidebar.header("🔍 Filter Criteria")
st.sidebar.caption(
    f"기준값 — 10년물 국채 {AppConfig.RATE_MA_YEARS}년 평균 **{macro['treasury_10y_ma']:.2%}** "
    f"(기준일 {macro.get('rate_as_of') or 'N/A'}), CPI {AppConfig.CPI_YEARS}년 연환산 "
    f"**{macro['cpi_annualized']:.2%}** (기준월 {macro.get('cpi_as_of') or 'N/A'})"
    + (" ⚠️ 기본값 사용 중" if macro.get('source') == 'config_fallback' else "")
)

min_yield = st.sidebar.slider(
    "Minimum Dividend Yield (%)",
    min_value=AppConfig.UNIVERSE_MIN_YIELD * 100,
    max_value=15.0,
    value=rate_floor_pct,
    step=0.01,
    help="기본값 = 10년물 국채 3년 이동평균 (배당률 > 이자율 원칙). 최소 2%."
)

payout_range = st.sidebar.slider(
    "Payout Ratio Range (%)",
    min_value=0,
    max_value=100,
    value=(20, 70),
    step=5,
    help="General/Energy only. Sector overrides: Utilities ≤80%, Banks/Financials ≤60%, "
         "REITs/MLPs exempt (OCF coverage ≥1.2x instead)."
)

min_years = st.sidebar.slider(
    "Minimum Dividend Growth Years",
    min_value=0,
    max_value=70,
    value=5,
    step=1,
    help="Consecutive years of dividend increase"
)

min_div_years = st.sidebar.slider(
    "Minimum Dividend Payment Years",
    min_value=0,
    max_value=70,
    value=5,
    step=1,
    help="Consecutive years of dividend payments (without decrease)"
)

min_growth = st.sidebar.slider(
    "Minimum 1Y Dividend Growth (%)",
    min_value=0.0,
    max_value=50.0,
    value=3.0,
    step=0.5,
    help="Year-over-year dividend growth rate"
)

min_growth_5y = st.sidebar.slider(
    "Minimum 5Y Dividend Growth (CAGR %)",
    min_value=0.0,
    max_value=50.0,
    value=cpi_pct,
    step=0.01,
    help="기본값 = CPI 5년 연환산 (배당성장률 > 물가 원칙). 삭감 후 회복 기저효과를 보정한 "
         "Div_CAGR_5Y_Adj 기준."
)

min_roe = st.sidebar.slider(
    "Minimum ROE (%)",
    min_value=-50.0,
    max_value=50.0,
    value=0.0,
    step=1.0,
    help="Pass/fail quality gate - minimum capital efficiency. Missing data passes through. "
         "Negative ROE also passes through unfiltered - it almost always signals negative "
         "shareholders' equity from buybacks (e.g. Philip Morris), not real unprofitability. "
         "REITs/MLPs exempt."
)

with st.sidebar.expander("ℹ️ Sector-specific gates (always on)"):
    st.markdown(
        "| Group | Net debt/EBITDA | Interest cov. | Coverage |\n|---|---|---|---|\n"
        + "\n".join(
            f"| {g} | ≤{r['max_nd_ebitda'] or '—'} | ≥{r['min_int_cov'] or '—'} | "
            f"{r['coverage'].upper()}{' ≥' + str(r['min_coverage']) if r['min_coverage'] else ''} |"
            for g, r in AppConfig.SECTOR_RULES.items()
        )
        + "\n\nAlso: Trailing EPS > 0 and no "
        f"{AppConfig.REVENUE_DECLINE_YEARS_FAIL} consecutive annual revenue declines. Missing data passes."
    )

# Sector filter (if available)
if 'Sector' in df.columns:
    available_sectors = sorted(df['Sector'].dropna().unique().tolist())
    selected_sectors = st.sidebar.multiselect(
        "Sectors",
        options=available_sectors,
        default=[],
        help="Filter by specific sectors (empty = all)"
    )
else:
    selected_sectors = []

# Market Cap Tier filter
if 'mkt_cap_tier' in df.columns:
    available_tiers = ['Mega-cap', 'Large-cap', 'Mid-cap', 'Small-cap', 'Micro-cap', 'Nano-cap']
    selected_tiers = st.sidebar.multiselect(
        "Market Cap Tiers",
        options=available_tiers,
        default=[],
        help="Filter by market capitalization tier (empty = all)"
    )
else:
    selected_tiers = []

# Main content - Scoring Weights
st.subheader("⚖️ Customize Scoring Weights")
st.markdown("Adjust weights to prioritize different metrics (must sum to 1.0)")
st.caption(
    "Only these 3 metrics are scored, as percentile ranks across the whole universe "
    "(score 70 = better than ~70% of the universe on the weighted blend). Growth years, payout, "
    "leverage, interest coverage, earnings, ROE and revenue trend are pass/fail gates instead - "
    "so no dividend metric can outweigh a fundamentals red flag. Safety_Grade and Valuation are "
    "informational."
)

col1, col2, col3 = st.columns(3)

with col1:
    w_yield = st.number_input("Dividend Yield", min_value=0.0, max_value=1.0, value=0.50, step=0.05)
with col2:
    w_cagr = st.number_input("5Y CAGR", min_value=0.0, max_value=1.0, value=0.25, step=0.05)
with col3:
    w_fcf = st.number_input("Dividend Coverage", min_value=0.0, max_value=1.0, value=0.25, step=0.05,
                             help="Sector-appropriate coverage (Div_Coverage): 3Y FCF/dividends, "
                                  "3Y OCF/dividends for REITs/MLPs, 1/payout for utilities and financials")

# Validate weights
total_weight = w_yield + w_cagr + w_fcf
if abs(total_weight - 1.0) > 0.01:
    st.warning(f"⚠️ Weights sum to {total_weight:.2f}. Please adjust to 1.0")
    st.stop()
else:
    st.success(f"✅ Weights sum to {total_weight:.2f}")

# Apply filters
filtered_df = filter_stocks(
    df,
    min_yield=min_yield / 100,
    payout_min=payout_range[0] / 100,
    payout_max=payout_range[1] / 100,

    min_years=min_years,
    min_div_years=min_div_years,
    min_growth=min_growth / 100,
    min_growth_5y=min_growth_5y / 100,
    min_roe=min_roe,
    sectors=selected_sectors if selected_sectors else None,
    mkt_cap_tiers=selected_tiers if selected_tiers else None
)

st.divider()

# Calculate scores
if len(filtered_df) > 0:
    weights = {
        'yield': w_yield,
        'cagr': w_cagr,
        'fcf_coverage': w_fcf
    }

    filtered_df = calculate_composite_score(filtered_df, weights=weights, score_type='high_dividend')
    filtered_df = filtered_df.sort_values('high_div_composite', ascending=False)

    # Flag abnormally high yields for manual review rather than filtering them out -
    # a spiked yield is often a symptom of a falling stock price, not a bargain.
    if 'Div. Yield' in filtered_df.columns:
        filtered_df['Alert'] = filtered_df['Div. Yield'].apply(
            lambda y: '⚠️ 주가급락 확인필요'
            if pd.notna(y) and y > AppConfig.HIGH_YIELD_WARNING_THRESHOLD
            else ''
        )

    st.subheader(f"📋 Screener Results ({len(filtered_df)} stocks found)")

    # Display market cap tier classification
    with st.expander("ℹ️ Market Cap Tier Classification (Russell Index)"):
        st.markdown("""
        - **Mega-cap**: $200B+
        - **Large-cap**: $10B ~ $200B
        - **Mid-cap**: $2B ~ $10B
        - **Small-cap**: $300M ~ $2B
        - **Micro-cap**: $50M ~ $300M
        - **Nano-cap**: <$50M
        """)

    # Column selector
    all_columns = filtered_df.columns.tolist()
    default_columns = ['Symbol', 'Alert', 'Yield_Trap', 'Company Name', 'Category', 'Sector_Group', 'Market Cap',
                       'Div. Yield', 'Safety_Grade', 'Valuation', 'Yield_Pctl_5Y', 'Timing_Signal', 'Div_Coverage',
                       'Net_Debt_EBITDA', 'Payout Ratio', 'Div. Gr. Years', 'Crisis_Passed', 'Growth_Badge',
                       'Div_CAGR_5Y_Adj', 'Shareholder_Yield', 'high_div_composite']
    available_default = [col for col in default_columns if col in all_columns]

    display_columns = st.multiselect(
        "Select Columns to Display",
        options=all_columns,
        default=available_default
    )

    if not display_columns:
        st.warning("Please select at least one column to display")
    else:
        # Sort by composite score
        sorted_df = filtered_df.sort_values('high_div_composite', ascending=False)

        # Format for display
        display_df = sorted_df[display_columns].head(50).copy()

        # Format percentage columns
        pct_cols = ['Div. Yield', 'Payout Ratio', 'Div. Growth', 'Div. Growth 5Y', 'Div_CAGR_5Y_Adj',
                    'Revenue_Growth', 'Revenue_CAGR_3Y', 'EPS_CAGR_3Y', 'Shareholder_Yield',
                    'Net_Buyback_Yield', 'Shares_Change_3Y', 'Yield_TTM']
        for col in pct_cols:
            if col in display_df.columns:
                vals = pd.to_numeric(display_df[col], errors='coerce')
                display_df[col] = vals.map(lambda v: f"{v * 100:.2f}%" if pd.notna(v) else '')

        st.dataframe(display_df, width='stretch', hide_index=True)

        # Download button
        csv = sorted_df[display_columns].to_csv(index=False)
        st.download_button(
            label="📥 Download Results (CSV)",
            data=csv,
            file_name=f"high_dividend_stocks_{pd.Timestamp.now().strftime('%Y%m%d')}.csv",
            mime="text/csv"
        )

    # Visualizations
    st.divider()
    st.subheader("📊 Visualizations")

    # Scatter plot - moved to top
    if 'Div. Yield' in filtered_df.columns and 'Div. Gr. Years' in filtered_df.columns:
        st.subheader("Dividend Yield vs Years (bubble size = score)")
        fig3 = create_scatter_plot(
            filtered_df.head(50),
            x_col='Div. Gr. Years',
            y_col='Div. Yield',
            size_col='high_div_composite',
            title="Dividend Yield vs Dividend Years",
            hover_data=['Company Name', 'Payout Ratio']
        )
        st.plotly_chart(fig3, width='stretch')

    viz_col1, viz_col2 = st.columns(2)

    with viz_col1:
        # Top 10 bar chart
        if len(filtered_df) >= 10:
            fig1 = create_top_stocks_bar_chart(
                filtered_df,
                'high_div_composite',
                title="Top 10 High Dividend Stocks"
            )
            st.plotly_chart(fig1, width='stretch')

    with viz_col2:
        # Distribution histogram
        if 'Div. Yield' in filtered_df.columns:
            fig2 = create_distribution_histogram(
                filtered_df,
                'Div. Yield',
                title="Dividend Yield Distribution",
                bins=30
            )
            st.plotly_chart(fig2, width='stretch')

else:
    st.warning("No stocks match the current filter criteria. Please adjust the filters.")
