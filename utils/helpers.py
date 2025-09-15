from __future__ import annotations
"""
Helper utilities.

Provides:
- timezone helpers (IST conversions)
- directory creation helper using config.reporting
- friendly date string for report filenames
- safe rounding and numeric helpers
"""

from datetime import datetime, date, time, timezone
from zoneinfo import ZoneInfo
from pathlib import Path
from typing import Optional, Iterable, Any

IST = ZoneInfo("Asia/Kolkata")


def to_ist(dt: datetime) -> datetime:
    """
    Convert an unaware or other-tz aware datetime to IST timezone-aware datetime.
    """
    if dt.tzinfo is None:
        # assume naive times are local system time -> convert to UTC then to IST would be risky.
        # It's safer to attach UTC and convert, but BRD uses IST everywhere; prefer treating naive as IST.
        return dt.replace(tzinfo=IST)
    return dt.astimezone(IST)


def now_ist() -> datetime:
    """Return current datetime in IST (tz-aware)."""
    return datetime.now(IST)


def date_str_for_reports(dt: Optional[datetime] = None) -> str:
    """
    Produce a safe date string for filenames: YYYY-MM-DD
    """
    d = dt or now_ist()
    d = to_ist(d)
    return d.strftime("%Y-%m-%d")


def ensure_dirs(paths: Iterable[Path]) -> None:
    """
    Ensure directories exist.
    """
    for p in paths:
        Path(p).mkdir(parents=True, exist_ok=True)


def safe_round(value: Any, ndigits: int = 2) -> float:
    """
    Safely round numeric-like values, returning 0.0 on failure.
    """
    try:
        return round(float(value), ndigits)
    except Exception:
        return 0.0
