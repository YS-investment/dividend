"""
Dividend Growth Stock Screener
Focus on stocks with strong dividend growth momentum
"""

import streamlit as st
import pandas as pd
from utils.cache_manager import load_main_dataframe
from modules.data_processor import (
    filter_stocks,
    calculate_normalized_metrics,
    calculate_composite_score,
    get_top_stocks,
    add_market_cap_tier
)
from modules.visualization import (
    create_top_stocks_bar_chart,
    create_scatter_plot,
    create_distribution_histogram
)
from config import AppConfig

st.set_page_config(page_title="Dividend Growth Screener", page_icon="📈", layout="wide")

st.title("📈 Dividend Growth Stock Screener")
st.markdown("Identify stocks with consistent and strong dividend growth rates.")

# Load data
df = load_main_dataframe(use_cached=True)

if df is None:
    st.error("No data available. Please return to home page and load data.")
    st.stop()

# Add market cap tier column before filtering
df = add_market_cap_tier(df)

# Sidebar Filters
st.sidebar.header("🔍 Filter Criteria")

min_yield = st.sidebar.slider(
    "Minimum Dividend Yield (%)",
    min_value=0.0,
    max_value=15.0,
    value=2.0,  # Lower default for growth stocks
    step=0.1
)

payout_range = st.sidebar.slider(
    "Payout Ratio Range (%)",
    min_value=0,
    max_value=100,
    value=(15, 70),  # Lower for growth potential
    step=5
)

min_years = st.sidebar.slider(
    "Minimum Dividend Years",
    min_value=0,
    max_value=70,
    value=5,
    step=1
)

min_growth = st.sidebar.slider(
    "Minimum 1Y Dividend Growth (%)",
    min_value=0.0,
    max_value=50.0,
    value=5.0,  # Higher for growth focus
    step=0.5
)

min_growth_5y = st.sidebar.slider(
    "Minimum 5Y Dividend Growth (CAGR %)",
    min_value=0.0,
    max_value=50.0,
    value=5.0,  # Higher for growth focus
    step=0.5
)

# Sector filter
if 'Sector' in df.columns:
    available_sectors = sorted(df['Sector'].dropna().unique().tolist())
    selected_sectors = st.sidebar.multiselect(
        "Sectors",
        options=available_sectors,
        default=[]
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

# Main content - Scoring Weights (Growth-focused)
st.subheader("⚖️ Customize Scoring Weights")
st.markdown("Weights are optimized for growth focus (must sum to 1.0)")

col1, col2, col3, col4, col5 = st.columns(5)

with col1:
    w_cagr = st.number_input("5Y CAGR", min_value=0.0, max_value=1.0, value=0.35, step=0.05)
with col2:
    w_yield = st.number_input("Dividend Yield", min_value=0.0, max_value=1.0, value=0.25, step=0.05)
with col3:
    w_growth = st.number_input("1Y Growth", min_value=0.0, max_value=1.0, value=0.20, step=0.05)
with col4:
    w_years = st.number_input("Years", min_value=0.0, max_value=1.0, value=0.10, step=0.05)
with col5:
    w_payout = st.number_input("Payout Ratio", min_value=0.0, max_value=1.0, value=0.10, step=0.05)

# Validate weights
total_weight = w_yield + w_years + w_cagr + w_growth + w_payout
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
    min_growth=min_growth / 100,
    min_growth_5y=min_growth_5y / 100,
    sectors=selected_sectors if selected_sectors else None,
    mkt_cap_tiers=selected_tiers if selected_tiers else None
)

st.divider()

# Calculate scores
if len(filtered_df) > 0:
    weights = {
        'yield': w_yield,
        'years': w_years,
        'cagr': w_cagr,
        'growth': w_growth,
        'payout': w_payout
    }

    filtered_df = calculate_normalized_metrics(filtered_df)
    filtered_df = calculate_composite_score(filtered_df, weights=weights, score_type='dividend_growth')

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
    default_columns = ['Symbol', 'Company Name', 'Category', 'Sector', 'Market Cap', 'mkt_cap_tier', 'Div. Growth 5Y', 'Div. Growth', 'Div. Yield', 'Years', 'dividend_growth_composite']
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
        sorted_df = filtered_df.sort_values('dividend_growth_composite', ascending=False)

        # Format for display
        display_df = sorted_df[display_columns].head(50).copy()

        # Format percentage columns
        pct_cols = ['Div. Yield', 'Payout Ratio', 'Div. Growth', 'Div. Growth 5Y']
        for col in pct_cols:
            if col in display_df.columns:
                display_df[col] = (display_df[col] * 100).round(2).astype(str) + '%'

        # Format composite score
        if 'dividend_growth_composite' in display_df.columns:
            display_df['dividend_growth_composite'] = display_df['dividend_growth_composite'].round(3)

        st.dataframe(display_df, width='stretch', hide_index=True)

        # Download button
        csv = sorted_df[display_columns].to_csv(index=False)
        st.download_button(
            label="📥 Download Results (CSV)",
            data=csv,
            file_name=f"dividend_growth_stocks_{pd.Timestamp.now().strftime('%Y%m%d')}.csv",
            mime="text/csv"
        )

    # Visualizations
    st.divider()
    st.subheader("📊 Visualizations")

    # Bubble chart: Current Yield vs 5Y CAGR - moved to top
    if 'Div. Yield' in filtered_df.columns and 'Div. Growth 5Y' in filtered_df.columns:
        st.subheader("Current Yield vs 5Y CAGR (bubble size = score)")

        # Create bubble chart
        fig3 = create_scatter_plot(
            filtered_df.head(50),
            x_col='Div. Growth 5Y',
            y_col='Div. Yield',
            size_col='dividend_growth_composite',
            title="Dividend Yield vs 5-Year Growth Rate",
            hover_data=['Company Name', 'Years']
        )
        st.plotly_chart(fig3, width='stretch')

    viz_col1, viz_col2 = st.columns(2)

    with viz_col1:
        # Top 10 bar chart
        if len(filtered_df) >= 10:
            fig1 = create_top_stocks_bar_chart(
                filtered_df,
                'dividend_growth_composite',
                title="Top 10 Dividend Growth Stocks"
            )
            st.plotly_chart(fig1, width='stretch')

    with viz_col2:
        # Distribution histogram
        if 'Div. Growth 5Y' in filtered_df.columns:
            fig2 = create_distribution_histogram(
                filtered_df,
                'Div. Growth 5Y',
                title="5Y Dividend Growth (CAGR) Distribution",
                bins=30
            )
            st.plotly_chart(fig2, width='stretch')

else:
    st.warning("No stocks match the current filter criteria. Please adjust the filters.")
