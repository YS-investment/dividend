"""
Data loading utilities for Dividend Stock Analysis Platform
"""

import pandas as pd
import os
from datetime import datetime
from zoneinfo import ZoneInfo
from typing import Optional
from config import AppConfig, get_main_data_path, get_raw_data_path, get_last_updated_path

US_EASTERN = ZoneInfo("America/New_York")


class DataManager:
    """
    Data source management class
    Handles loading from cached CSV files or triggering new data collection
    """

    @staticmethod
    def get_main_dataframe(use_cached: bool = True) -> Optional[pd.DataFrame]:
        """
        Get the main dividend dataframe based on data source selection

        Args:
            use_cached: True to use existing CSV, False to trigger scraping

        Returns:
            pd.DataFrame or None if data not available
        """
        if use_cached:
            # Load from existing data
            data_path = get_main_data_path()
            if os.path.exists(data_path):
                df = pd.read_csv(data_path)
                # Data type optimization
                df['Symbol'] = df['Symbol'].astype('category')
                if 'Sector' in df.columns:
                    df['Sector'] = df['Sector'].astype('category')
                return df
            else:
                return None
        else:
            # Trigger new data collection
            from modules.data_collector import DividendDataCollector
            collector = DividendDataCollector()
            return collector.update_all_data()

    @staticmethod
    def get_data_info() -> dict:
        """
        Get information about the data file

        Returns:
            dict with exists, last_modified, row_count
        """
        info = {}
        data_path = get_main_data_path()

        if os.path.exists(data_path):
            info['exists'] = True
            info['last_modified'] = DataManager._get_last_updated_time(data_path)
            try:
                df = pd.read_csv(data_path)
                info['row_count'] = len(df)
                info['column_count'] = len(df.columns)
            except Exception as e:
                info['error'] = str(e)
        else:
            info['exists'] = False

        return info

    @staticmethod
    def _get_last_updated_time(data_path: str) -> datetime:
        """
        Resolve when the data was actually last updated, in US Eastern time.

        Prefers the timestamp marker written by the scraper at completion
        (data/last_updated.txt, UTC ISO format) since git checkouts reset
        file mtimes on every redeploy and don't reflect real update time.
        Falls back to the CSV's filesystem mtime if the marker is missing
        (e.g. data committed before this marker existed).
        """
        marker_path = get_last_updated_path()
        if os.path.exists(marker_path):
            try:
                with open(marker_path) as f:
                    completed_at = datetime.fromisoformat(f.read().strip())
                return completed_at.astimezone(US_EASTERN)
            except (ValueError, OSError):
                pass

        return datetime.fromtimestamp(os.path.getmtime(data_path), tz=US_EASTERN)

    @staticmethod
    def get_available_sectors(df: pd.DataFrame) -> list:
        """Get list of available sectors from dataframe"""
        if 'Sector' in df.columns:
            return sorted(df['Sector'].dropna().unique().tolist())
        return []

    @staticmethod
    def get_available_symbols(df: pd.DataFrame) -> list:
        """Get list of available stock symbols"""
        if 'Symbol' in df.columns:
            return sorted(df['Symbol'].unique().tolist())
        return []


def load_dividend_data(use_cached: bool = True) -> Optional[pd.DataFrame]:
    """
    Convenience function to load dividend data

    Args:
        use_cached: Whether to use cached data

    Returns:
        DataFrame with dividend stock data
    """
    manager = DataManager()
    return manager.get_main_dataframe(use_cached=use_cached)


def check_data_file_exists() -> bool:
    """Check if main data file exists"""
    return os.path.exists(get_main_data_path())
