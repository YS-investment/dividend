"""
Dividend Growth Stock Screener
Focus on stocks with strong dividend growth momentum
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

st.set_page_config(page_title="Dividend Growth Screener", page_icon="📈", layout="wide")

st.title("📈 Dividend Growth Stock Screener")
show_data_freshness_warning()
st.markdown("Identify stocks with consistent and strong dividend growth rates.")

# Load data (derived metrics + universe-wide percentile ranks already computed)
df = load_prepared_dataframe()

if df is None:
    st.error("No data available. Please return to home page and load data.")
    st.stop()

macro = load_macro()
cpi_pct = round(macro['cpi_annualized'] * 100, 2)

# Sidebar Filters
st.sidebar.header("🔍 Filter Criteria")
st.sidebar.caption(
    f"기준값 — CPI {AppConfig.CPI_YEARS}년 연환산 **{macro['cpi_annualized']:.2%}** "
    f"(기준월 {macro.get('cpi_as_of') or 'N/A'})"
    + (" ⚠️ 기본값 사용 중" if macro.get('source') == 'config_fallback' else "")
)

min_yield = st.sidebar.slider(
    "Minimum Dividend Yield (%)",
    min_value=AppConfig.UNIVERSE_MIN_YIELD * 100,
    max_value=10.0,
    value=AppConfig.UNIVERSE_MIN_YIELD * 100,
    step=0.1,
    help="최소 2% (2% 미만 배당성장주는 유니버스에서 제외)."
)

apply_chowder = st.sidebar.checkbox(
    "Apply Chowder Rule",
    value=True,
    help=f"Div. Yield % + adjusted 5Y CAGR % ≥ {AppConfig.CHOWDER_MIN_HIGH_YIELD:g} "
         f"(yield ≥ {AppConfig.CHOWDER_YIELD_PIVOT:.0%}) or ≥ {AppConfig.CHOWDER_MIN_LOW_YIELD:g} (yield below)."
)

apply_min_cap = st.sidebar.checkbox(
    f"Market Cap ≥ ${AppConfig.GROWTH_MIN_MARKET_CAP_USD / 1e9:.0f}B",
    value=False,
    help="대형주만 보기 (주가 변동이 큰 소형주 제외, 리스크 관리). 시가총액을 모르는 종목은 제외됩니다."
)

payout_range = st.sidebar.slider(
    "Payout Ratio Range (%)",
    min_value=0,
    max_value=100,
    value=(15, 60),  # Upper bound aligned to the growth-stock payout "sweet spot"
    step=5,
    help="General/Energy only. Sector overrides: Utilities ≤80%, Banks/Financials ≤60%, "
         "REITs/MLPs exempt (OCF coverage ≥1.2x instead)."
)

min_years = st.sidebar.slider(
    "Minimum Dividend Growth Years",
    min_value=0,
    max_value=70,
    value=10,  # Aligned with Dividend Achievers / Dividend Growers index entry bar
    step=1,
    help="Consecutive years of dividend increase"
)

min_div_years = st.sidebar.slider(
    "Minimum Dividend Payment Years",
    min_value=0,
    max_value=70,
    value=10,
    step=1,
    help="Consecutive years of dividend payments (without decrease)"
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
    value=max(5.0, cpi_pct),  # growth focus, never below inflation
    step=0.01,
    help="기본값 = max(5%, CPI 5년 연환산). 삭감 후 회복 기저효과를 보정한 Div_CAGR_5Y_Adj 기준."
)

min_roe = st.sidebar.slider(
    "Minimum ROE (%)",
    min_value=-50.0,
    max_value=50.0,
    value=8.0,  # Higher than High Dividend Screener's 0% - growth investing
    # leans on Buffett/Munger-style capital efficiency as part of the thesis
    step=1.0,
    help="Pass/fail quality gate - minimum capital efficiency (higher bar than the High "
         "Dividend Screener since growth investing weighs capital efficiency more heavily). "
         "Missing data passes through. Negative ROE also passes through unfiltered - it "
         "almost always signals negative shareholders' equity from buybacks (e.g. Philip "
         "Morris), not real unprofitability. REITs/MLPs exempt."
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
st.caption(
    "Only these 2 metrics are scored (universe-wide percentile ranks), mirroring the Chowder Rule "
    "(yield + 5Y growth). Growth years, payout, leverage, interest coverage, earnings, ROE, revenue "
    "trend and the Chowder Rule itself are pass/fail gates instead - so no dividend metric can "
    "outweigh a fundamentals red flag."
)

col1, col2 = st.columns(2)

with col1:
    w_cagr = st.number_input("5Y CAGR", min_value=0.0, max_value=1.0, value=0.60, step=0.05)
with col2:
    w_yield = st.number_input("Dividend Yield", min_value=0.0, max_value=1.0, value=0.40, step=0.05)

# Validate weights
total_weight = w_cagr + w_yield
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
    apply_chowder=apply_chowder,
    min_market_cap=AppConfig.GROWTH_MIN_MARKET_CAP_USD if apply_min_cap else None,
    sectors=selected_sectors if selected_sectors else None,
    mkt_cap_tiers=selected_tiers if selected_tiers else None
)

st.divider()

# Calculate scores
if len(filtered_df) > 0:
    weights = {
        'cagr': w_cagr,
        'yield': w_yield
    }

    filtered_df = calculate_composite_score(filtered_df, weights=weights, score_type='dividend_growth')
    filtered_df = filtered_df.sort_values('dividend_growth_composite', ascending=False)

    st.subheader(f"📋 Screener Results ({len(filtered_df)} stocks found)")

    with st.expander("ℹ️ Chowder Number"):
        st.markdown("""
        **Chowder Number = Div. Yield (%) + adjusted 5Y Dividend Growth CAGR (%)**

        A dividend-growth-investing heuristic for expected long-term total return.
        Applied as a pass/fail gate when "Apply Chowder Rule" is checked:
        - Yield ≥ 3%: Chowder Number ≥ 12
        - Yield < 3%: Chowder Number ≥ 15
        """)

    with st.expander("⚠️ EPS Growth Alert"):
        st.markdown("""
        **EPS_Alert flags stocks where the adjusted 5Y dividend CAGR > 3Y EPS CAGR.**

        When dividends grow faster than earnings over several years, the increase is
        coming from a rising payout ratio rather than genuine earnings growth - harder
        to sustain. Informational only. Stocks with no EPS history are not flagged.
        """)

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
    default_columns = ['Symbol', 'EPS_Alert', 'Yield_Trap', 'Company Name', 'Category', 'Sector_Group', 'Market Cap',
                       'Div_CAGR_5Y_Adj', 'Div. Growth', 'EPS_CAGR_3Y', 'Revenue_CAGR_3Y', 'Div. Yield',
                       'chowder_number', 'Safety_Grade', 'Valuation', 'Timing_Signal', 'Growth_Badge',
                       'Crisis_Passed', 'Div. Gr. Years', 'Shareholder_Yield', 'dividend_growth_composite']
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
        pct_cols = ['Div. Yield', 'Payout Ratio', 'Div. Growth', 'Div. Growth 5Y', 'Div_CAGR_5Y_Adj',
                    'EPS_Growth', 'Revenue_Growth', 'Revenue_CAGR_3Y', 'EPS_CAGR_3Y', 'Shareholder_Yield',
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
            hover_data=['Company Name', 'Div. Gr. Years']
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
