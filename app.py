"""
Dividend Stock Analysis Platform - Main Application
Streamlit-based web application for dividend stock analysis
"""

import streamlit as st
import os
from datetime import datetime
from utils.cache_manager import load_main_dataframe, clear_all_caches
from utils.data_loader import DataManager, check_data_file_exists
from config import AppConfig

# Page configuration
st.set_page_config(
    page_title="Dividend Stock Analysis Platform",
    page_icon="💰",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS
st.markdown("""
<style>
    .main-header {
        font-size: 2.5rem;
        font-weight: bold;
        color: #1f77b4;
    }
    .metric-card {
        background-color: #f0f2f6;
        padding: 1rem;
        border-radius: 0.5rem;
        margin: 0.5rem 0;
    }
</style>
""", unsafe_allow_html=True)

# Initialize session state variables at the top
if 'update_in_progress' not in st.session_state:
    st.session_state['update_in_progress'] = False
if 'update_completed' not in st.session_state:
    st.session_state['update_completed'] = False
if 'data_source_mode' not in st.session_state:
    st.session_state['data_source_mode'] = 'cached'

# Sidebar - Data Source Selection
st.sidebar.header("⚙️ Data Settings")

data_source = st.sidebar.radio(
    "Select Data Source",
    options=["📁 Use Existing Data (Fast)", "🔄 Crawl Latest Data (3-5 min)"],
    index=0,
    help="Existing data loads instantly. Crawling provides latest information."
)

# Update data_source_mode based on radio selection (for UI display only)
crawl_mode_selected = "🔄 Crawl Latest Data" in data_source

# Display data source information
if not crawl_mode_selected:
    # Use Existing Data mode
    if check_data_file_exists():
        data_info = DataManager.get_data_info()
        if data_info['exists']:
            st.sidebar.success("✅ Using Existing Data")
            st.sidebar.info(
                f"📅 Last Updated: {data_info['last_modified'].strftime('%Y-%m-%d %H:%M')}"
            )
            st.sidebar.metric("Total Stocks", f"{data_info.get('row_count', 'N/A'):,}")
    else:
        st.sidebar.error("❌ No existing data file found!")
        st.sidebar.warning("Please select 'Crawl Latest Data'")
        st.stop()
else:
    # Crawl Latest Data mode selected
    st.sidebar.warning("⚠️ Click 'Start Data Update' to begin crawling (3-5 min)")

    # Show completion message if update just finished
    if st.session_state['update_completed']:
        st.sidebar.success("✅ Data updated successfully!")
        if 'last_update' in st.session_state:
            st.sidebar.info(f"🕐 Updated: {st.session_state['last_update']}")
        if 'update_stats' in st.session_state:
            st.sidebar.markdown("### 📊 Update Summary")
            stats = st.session_state['update_stats']
            st.sidebar.markdown(f"- Total stocks: **{stats.get('total', 0):,}**")
            st.sidebar.markdown(f"- Avg dividend yield: **{stats.get('avg_yield', 'N/A')}**")

        # Show button to switch back to existing data mode
        if st.sidebar.button("Use Updated Data"):
            st.session_state['update_completed'] = False
            st.session_state['data_source_mode'] = 'cached'
            st.rerun()

    # Only show the update button if not in progress and not just completed
    if not st.session_state['update_completed']:
        # Button to trigger update
        button_clicked = st.sidebar.button(
            "🚀 Start Data Update",
            type="primary",
            disabled=st.session_state['update_in_progress']
        )

        # Only execute update when button is clicked AND not already in progress
        if button_clicked and not st.session_state['update_in_progress']:
            try:
                # Set update flag to prevent re-entry
                st.session_state['update_in_progress'] = True
                st.session_state['update_completed'] = False

                from datetime import datetime
                from modules.data_collector import DividendDataCollector

                # Progress tracking UI elements
                progress_bar = st.sidebar.progress(0)
                status_text = st.sidebar.empty()

                # Initialize collector
                collector = DividendDataCollector()

                # Progress callback for scraping
                def update_scraping_progress(current, total):
                    progress = int((current / total) * 50)  # 0-50% for scraping
                    progress_bar.progress(progress)
                    status_text.text(f"📊 Scraping page {current}/{total}...")

                # Stage 1: Scraping & Validation (0-50%)
                status_text.text("🚀 Starting web scraper...")

                df = collector.update_all_data(
                    use_scraping=True,
                    progress_callback=update_scraping_progress
                )

                # Stage 2: Processing complete (50-70%)
                progress_bar.progress(70)
                status_text.text("✓ Data processing complete")

                # Stage 3: Clear caches (70-100%)
                status_text.text("🧹 Clearing caches...")
                st.cache_data.clear()
                progress_bar.progress(100)

                # Store completion info in session state
                update_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                st.session_state['last_update'] = update_time
                st.session_state['data_source'] = 'crawled'

                # Store stats for display
                stats = {'total': len(df)}
                if 'Div. Yield' in df.columns:
                    avg_yield = df['Div. Yield'].mean()
                    stats['avg_yield'] = f"{avg_yield:.2%}"
                st.session_state['update_stats'] = stats

                # Mark as completed BEFORE rerun
                st.session_state['update_in_progress'] = False
                st.session_state['update_completed'] = True
                st.session_state['data_source_mode'] = 'cached'

                # Clear progress indicators
                progress_bar.empty()
                status_text.empty()

                # Trigger rerun to load new data and show completion message
                st.rerun()

            except Exception as e:
                st.session_state['update_in_progress'] = False
                st.session_state['update_completed'] = False
                st.sidebar.error(f"❌ Update failed: {str(e)}")
                st.sidebar.info("💡 Tip: Use existing data instead")

                # Show error details in expander
                with st.sidebar.expander("Show error details"):
                    import traceback
                    st.code(traceback.format_exc())

                # Clear progress indicators
                if 'progress_bar' in locals():
                    progress_bar.empty()
                if 'status_text' in locals():
                    status_text.empty()

# Load data based on session state mode (not radio button selection)
# This prevents automatic crawling when radio is changed
try:
    use_cached = st.session_state['data_source_mode'] == 'cached'
    df = load_main_dataframe(use_cached=use_cached)

    if df is None:
        st.error("Failed to load data. Please check data files.")
        st.stop()

except Exception as e:
    st.error(f"Error loading data: {str(e)}")
    st.stop()

# Main content
st.markdown('<p class="main-header">💰 Summary</p>', unsafe_allow_html=True)

st.markdown("""
Welcome to the comprehensive dividend stock analysis platform. This tool helps you:
- Browse the complete dividend stocks dataset below
- Use screener pages for filtered analysis with custom criteria
- Analyze individual stocks with detailed metrics and visualizations
- Backtest portfolios with DRIP and tax considerations

Navigate using the sidebar to access specialized analysis tools.
""")

st.divider()

# Interactive Dataset Display
st.subheader("Dividend Stocks Dataset")

# Configure column display formatting
column_config = {
    "Symbol": st.column_config.TextColumn(
        "Symbol",
        help="Stock ticker symbol (e.g., AAPL, MSFT)"
    ),
    "Company Name": st.column_config.TextColumn(
        "Company Name",
        help="Full legal name of the company"
    ),
    "Category": st.column_config.TextColumn(
        "Category",
        help="Dividend achievement status (Aristocrats: 25+ years, Kings: 50+ years, Champions: consecutive increases)"
    ),
    "Div. Yield": st.column_config.NumberColumn(
        "Div. Yield",
        format="%.2f%%",
        help="Annual dividend yield - Annual dividends per share divided by current stock price"
    ),
    "Div. Growth 5Y": st.column_config.NumberColumn(
        "Div. Growth 5Y",
        format="%.2f%%",
        help="5-year dividend growth rate (CAGR) - Compound annual growth rate of dividends over the past 5 years"
    ),
    "Years": st.column_config.NumberColumn(
        "Years",
        help="Number of consecutive years the company has paid dividends without interruption"
    ),
    "Payout Ratio": st.column_config.NumberColumn(
        "Payout Ratio",
        format="%.2f%%",
        help="Dividend payout ratio - Percentage of net income paid out as dividends (lower is more sustainable)"
    ),
    "Market Cap": st.column_config.NumberColumn(
        "Market Cap",
        format="$%.2fB",
        help="Market capitalization in billions - Total market value of all outstanding shares (Share Price × Total Shares)"
    ),
    "Sector": st.column_config.TextColumn(
        "Sector",
        help="Primary business sector (e.g., Technology, Healthcare, Financials)"
    ),
    "Industry": st.column_config.TextColumn(
        "Industry",
        help="Specific industry classification within the sector (e.g., Software, Biotechnology, Banks)"
    ),
    "Five_y_DividendYield_diff": st.column_config.NumberColumn(
        "5Y Yield Diff",
        format="%.2f%%",
        help="Difference from 5-year average dividend yield - Positive means current yield is higher than historical average (potentially undervalued)"
    ),
    "Ten_y_DividendYield_diff": st.column_config.NumberColumn(
        "10Y Yield Diff",
        format="%.2f%%",
        help="Difference from 10-year average dividend yield - Positive means current yield is higher than historical average (potentially undervalued)"
    ),
}

# Prepare dataframe for display - convert decimal to percentage for display
display_df = df.copy()

# Convert decimal columns to percentage for proper display
import pandas as pd
percentage_cols = ['Div. Yield', 'Div. Growth 5Y', 'Payout Ratio',
                   'Five_y_DividendYield_diff', 'Ten_y_DividendYield_diff']
for col in percentage_cols:
    if col in display_df.columns:
        display_df[col] = pd.to_numeric(display_df[col], errors='coerce') * 100

# Convert Market Cap to numeric (handle string values like "911.47B")
if 'Market Cap' in display_df.columns:
    def parse_market_cap(value):
        if pd.isna(value):
            return None
        if isinstance(value, (int, float)):
            return value / 1e9

        value_str = str(value).strip().upper()
        if not value_str or value_str == '-':
            return None

        # Remove $ if present
        value_str = value_str.replace('$', '')

        # Extract multiplier
        multiplier = 1
        if value_str.endswith('T'):
            multiplier = 1e12
            value_str = value_str[:-1]
        elif value_str.endswith('B'):
            multiplier = 1e9
            value_str = value_str[:-1]
        elif value_str.endswith('M'):
            multiplier = 1e6
            value_str = value_str[:-1]
        elif value_str.endswith('K'):
            multiplier = 1e3
            value_str = value_str[:-1]

        try:
            numeric_value = float(value_str)
            return (numeric_value * multiplier) / 1e9
        except ValueError:
            return None

    display_df['Market Cap'] = display_df['Market Cap'].apply(parse_market_cap)

# Select columns to display
display_columns = ['Symbol', 'Company Name', 'Category', 'Div. Yield', 'Div. Growth 5Y',
                   'Years', 'Payout Ratio', 'Market Cap', 'Sector', 'Industry',
                   'Five_y_DividendYield_diff', 'Ten_y_DividendYield_diff']

# Filter to only existing columns
available_columns = [col for col in display_columns if col in display_df.columns]

# Display interactive dataframe
st.dataframe(
    display_df[available_columns],
    column_config=column_config,
    width='stretch',
    hide_index=True,
    height=600
)

# Footer
st.divider()
st.markdown("""
<div style='text-align: center; color: gray; padding: 2rem;'>
    <p>💡 Use the sidebar navigation to access screening, analysis, and backtesting tools</p>
    <p style='font-size: 0.8rem;'>Data sources: StockAnalysis.com & Yahoo Finance</p>
</div>
""", unsafe_allow_html=True)
