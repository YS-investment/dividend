"""
Data update history and alerts.

- record_update(): appends one row per pipeline run to data/update_history.csv
- notify(): sends a Telegram message when TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID
  are set (no-op otherwise); never raises
- data_age_days(): days since the last successful update (data/last_updated.txt)
"""

import json
import os
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Optional

import pandas as pd

from config import AppConfig, get_data_path, get_last_updated_path

HISTORY_COLUMNS = ['started_at', 'finished_at', 'status', 'mode', 'raw_rows', 'final_rows',
                   'enrichment_failures', 'macro_source', 'treasury_10y_ma', 'cpi_annualized', 'error']


def history_path() -> str:
    return get_data_path(AppConfig.UPDATE_HISTORY_FILE)


def record_update(**fields) -> None:
    """Append one run to update_history.csv (missing fields left blank)."""
    row = {c: fields.get(c, '') for c in HISTORY_COLUMNS}
    path = history_path()
    df = pd.DataFrame([row], columns=HISTORY_COLUMNS)
    df.to_csv(path, mode='a', header=not os.path.exists(path), index=False)


def load_history(n: int = 20) -> pd.DataFrame:
    path = history_path()
    if not os.path.exists(path):
        return pd.DataFrame(columns=HISTORY_COLUMNS)
    return pd.read_csv(path).tail(n)


def data_age_days(now: Optional[datetime] = None) -> Optional[float]:
    """Days since data/last_updated.txt (None if the marker is missing/unreadable)."""
    try:
        with open(get_last_updated_path()) as f:
            updated = datetime.fromisoformat(f.read().strip())
    except (OSError, ValueError):
        return None
    now = now or datetime.now(timezone.utc)
    return (now - updated).total_seconds() / 86400


def notify(message: str) -> bool:
    """Send a Telegram message if configured. Returns True if sent."""
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        return False
    try:
        data = urllib.parse.urlencode({'chat_id': chat_id, 'text': message}).encode()
        req = urllib.request.Request(f"https://api.telegram.org/bot{token}/sendMessage", data=data)
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode()).get('ok', False)
    except Exception as e:
        print(f"  ⚠ Telegram notification failed: {e}")
        return False
