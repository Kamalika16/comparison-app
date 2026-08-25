"""
Normalization utilities.

Two spreadsheets exported from different systems will almost never agree on
formatting out of the box:
    - "John Smith" vs "Smith, John" vs "john   smith"
    - "2024-01-05" vs "1/5/2024" vs a datetime.datetime object
    - "8" vs "8.0" vs "8h 00m" vs "08:00"

These helpers coerce all of that into comparable canonical forms.
"""
from __future__ import annotations

import re
from datetime import date, datetime
from typing import Optional, Union

import pandas as pd


def normalize_name(raw: Optional[str]) -> str:
    """
    Normalize an employee name for comparison:
    - lowercases
    - strips extra whitespace
    - converts "Last, First" -> "first last"
    - removes punctuation
    """
    if raw is None or (isinstance(raw, float) and pd.isna(raw)):
        return ""

    name = str(raw).strip()
    if "," in name:
        parts = [p.strip() for p in name.split(",", 1)]
        if len(parts) == 2:
            name = f"{parts[1]} {parts[0]}"

    name = re.sub(r"[^\w\s]", "", name)
    name = re.sub(r"\s+", " ", name).strip().lower()
    return name


def normalize_date(raw: Union[str, datetime, date, None]) -> Optional[str]:
    """
    Normalize a date value to ISO format YYYY-MM-DD, or None if it can't
    be parsed.
    """
    if raw is None or (isinstance(raw, float) and pd.isna(raw)):
        return None

    if isinstance(raw, datetime):
        return raw.date().isoformat()
    if isinstance(raw, date):
        return raw.isoformat()

    raw_str = str(raw).strip()
    if not raw_str:
        return None

    try:
        parsed = pd.to_datetime(raw_str, errors="raise")
        return parsed.date().isoformat()
    except (ValueError, TypeError):
        return None


TIME_RANGE_RE = re.compile(
    r"(\d{1,2}):(\d{2})\s*(?:am|pm)?\s*-\s*(\d{1,2}):(\d{2})\s*(am|pm)?", re.IGNORECASE
)
HOURS_MINUTES_RE = re.compile(r"(\d+)\s*h(?:ours?)?\s*(\d+)?\s*m(?:in(?:utes?)?)?", re.IGNORECASE)


def normalize_hours(raw: Union[str, int, float, None]) -> Optional[float]:
    """
    Normalize a "worked hours" value to a float number of decimal hours.

    Handles:
        8, 8.5, "8", "8.5"
        "8h 30m", "8h", "30m"
        "08:00" (treated as HH:MM duration, not clock time)
        time-range strings like "09:00-17:30" (computes duration)
    """
    if raw is None or (isinstance(raw, float) and pd.isna(raw)):
        return None

    if isinstance(raw, (int, float)):
        return round(float(raw), 2)

    raw_str = str(raw).strip().lower()
    if not raw_str:
        return None

    # Plain numeric string, e.g. "8" or "8.5"
    try:
        return round(float(raw_str), 2)
    except ValueError:
        pass

    # Time range e.g. "09:00-17:30"
    range_match = TIME_RANGE_RE.search(raw_str)
    if range_match:
        h1, m1, h2, m2, meridiem = range_match.groups()
        start = int(h1) * 60 + int(m1)
        end = int(h2) * 60 + int(m2)
        if meridiem == "pm" and int(h2) != 12:
            end += 12 * 60
        diff_minutes = end - start
        if diff_minutes < 0:
            diff_minutes += 24 * 60
        return round(diff_minutes / 60, 2)

    # "8h 30m" style
    hm_match = HOURS_MINUTES_RE.search(raw_str)
    if hm_match:
        hours = int(hm_match.group(1))
        minutes = int(hm_match.group(2)) if hm_match.group(2) else 0
        return round(hours + minutes / 60, 2)

    # "HH:MM" duration
    if re.fullmatch(r"\d{1,2}:\d{2}", raw_str):
        h, m = raw_str.split(":")
        return round(int(h) + int(m) / 60, 2)

    return None
