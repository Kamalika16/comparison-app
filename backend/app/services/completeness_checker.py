"""Stage 0 period detection and monthly Project ID completeness checks.

Period detection scopes both files to their reporting month and preserves
the client period's expected-week count for Level 1. Project totals are
compared at month level using the Client file as the source of truth.
"""
from __future__ import annotations

from datetime import date, timedelta
from collections import Counter

import pandas as pd

from .excel_loader import _as_number, _is_missing
from .hours_comparator import _display_identifier, _display_name, _employee_key

# Both real sample files use Saturday-start work weeks (columns literally
# ordered Sat, Sun, Mon, Tue, Wed, Thu, Fri in the client template), so
# weeks are anchored to Saturday, not Monday/ISO.
_SATURDAY = 5  # date.weekday(): Mon=0 ... Sun=6


def count_working_days(year: int, month_num: int) -> int:
    """Weekdays (Mon-Fri) in this calendar month. No holiday exclusion --
    confirmed not needed; every non-weekend day counts."""
    first = date(year, month_num, 1)
    next_month = date(year + (month_num == 12), (month_num % 12) + 1, 1)
    count = 0
    cursor = first
    while cursor < next_month:
        if cursor.weekday() < 5:
            count += 1
        cursor += timedelta(days=1)
    return count


def _week_start(d: date) -> date:
    """Saturday on/before d, i.e. the start of d's Sat-Fri work week."""
    return d - timedelta(days=(d.weekday() - _SATURDAY) % 7)


def _parse_date(raw) -> date | None:
    """Parse a date value, always day-first for ambiguous string dates
    (these files use DD-MM-YYYY; pandas' default MM-DD guess is wrong here
    and silently produces a different month)."""
    if raw is None:
        return None
    if isinstance(raw, date):
        return raw
    if isinstance(raw, pd.Timestamp):
        return raw.date()
    raw_str = str(raw).strip()
    if not raw_str:
        return None
    # Unambiguous ISO format (e.g. WeekDate cells already stored as
    # YYYY-MM-DD): parse directly, no dayfirst guessing needed/warned about.
    parsed = pd.to_datetime(raw_str, format="%Y-%m-%d", errors="coerce")
    if pd.isna(parsed):
        # Ambiguous DD-MM-YYYY / D-M-YYYY style strings: these files are
        # day-first, and pandas' default (month-first) guess is wrong here.
        parsed = pd.to_datetime(raw_str, dayfirst=True, errors="coerce")
    return parsed.date() if not pd.isna(parsed) else None


def normalize_date(raw) -> str | None:
    d = _parse_date(raw)
    return d.isoformat() if d else None


def _detect_period_from_month_columns(records: list[dict]) -> tuple | None:
    """If the file has Month/Year columns, use the most common (month, year)
    pair as the reporting period. Returns (month_name, year) or None."""
    if not records or "Month" not in records[0] or "Year" not in records[0]:
        return None
    pairs = [
        (r.get("Month"), r.get("Year"))
        for r in records
        if not _is_missing(r.get("Month")) and not _is_missing(r.get("Year"))
    ]
    if not pairs:
        return None
    return max(set(pairs), key=pairs.count)


def _expected_weeks_for_month(year: int, month_num: int) -> list[date]:
    """Every Sat-start work week that begins within this calendar month."""
    first = date(year, month_num, 1)
    next_month = date(year + (month_num == 12), (month_num % 12) + 1, 1)
    weeks = []
    cursor = _week_start(first)
    if cursor < first:
        cursor += timedelta(days=7)  # week starting before the 1st: not this month's
    while cursor < next_month:
        weeks.append(cursor)
        cursor += timedelta(days=7)
    return weeks


_MONTH_NUM = {
    m: i
    for i, m in enumerate(
        ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
         "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"],
        start=1,
    )
}


def check_completeness(
    records: list[dict],
    key_column: str,
    date_column: str | None = None,
    label: str = "file",
    holidays: set | None = None,
) -> dict:
    """Detect the reporting period and retain its rows for downstream checks.

    The expected-count calculation is retained for Level 1's existing
    working-weeks x 40 expected-hours rule. Completeness is evaluated by
    ``build_project_completeness`` as a monthly ID-and-hours comparison.
    """
    result = {
        "granularity": "week",
        "expected_count": 0,
        "period": None,
        "error": None,
    }

    if not records:
        result["error"] = f"No rows found in {label}."
        return result

    holiday_dates = set()
    for h in (holidays or []):
        d = h if isinstance(h, date) else _parse_date(h)
        if d:
            holiday_dates.add(d)

    month_year = _detect_period_from_month_columns(records)

    if month_year and month_year[0] in _MONTH_NUM:
        return _check_week_level(records, key_column, date_column, month_year)

    if not date_column:
        result["error"] = (
            f"Could not detect a reporting period for {label}: "
            "no Month/Year columns and no date column given."
        )
        return result
    return _check_day_level(records, key_column, date_column, holiday_dates, label)


def _check_week_level(records, key_column, date_column, month_year) -> dict:
    """Scope Month/Year-tagged client rows and retain their week count."""
    result = {
        "granularity": "week",
        "expected_count": 0, "period": None, "error": None,
    }
    month_name, year = month_year
    year = int(year)
    result["period"] = f"{month_name} {year}"
    result["year"] = year
    result["month_num"] = _MONTH_NUM[month_name]
    result["year"] = year
    result["month_num"] = _MONTH_NUM[month_name]
    week_col = "WeekDate" if "WeekDate" in records[0] else None

    def row_week(r):
        if week_col and not _is_missing(r.get(week_col)):
            d = _parse_date(r.get(week_col))
            if d:
                return _week_start(d)
        d = _parse_date(r.get(date_column)) if date_column else None
        return _week_start(d) if d else None

    rows_in_period = [
        r for r in records
        if r.get("Month") == month_name and int(r.get("Year", year) or year) == year
    ]
    # Trust the file's own week<->month labeling rather than recomputing
    # calendar boundaries, which can disagree at month edges.
    expected_weeks = sorted({wk for r in rows_in_period if (wk := row_week(r))})
    result["expected_count"] = len(expected_weeks)
    result["records_in_period"] = rows_in_period
    return result


def _check_day_level(records, key_column, date_column, holiday_dates, label) -> dict:
    """Scope date-based rows to their most common month and retain its count."""
    result = {
        "granularity": "day",
        "expected_count": 0, "period": None, "error": None,
    }
    parsed_dates = [d for r in records if (d := _parse_date(r.get(date_column)))]
    if not parsed_dates:
        result["error"] = f"No parseable dates found in {label}."
        return result

    month_num = max(
        set(d.month for d in parsed_dates),
        key=lambda m: sum(1 for d in parsed_dates if d.month == m),
    )
    year = max(d.year for d in parsed_dates if d.month == month_num)
    result["period"] = f"{list(_MONTH_NUM.keys())[month_num - 1]} {year}"
    result["year"] = year
    result["month_num"] = month_num
    result["year"] = year
    result["month_num"] = month_num

    first = date(year, month_num, 1)
    next_month = date(year + (month_num == 12), (month_num % 12) + 1, 1)
    expected_days = []
    cursor = first
    while cursor < next_month:
        if cursor.weekday() < 5 and cursor not in holiday_dates:  # Mon-Fri only
            expected_days.append(cursor)
        cursor += timedelta(days=1)
    result["expected_count"] = len(expected_days)

    rows_in_period = [
        r for r in records
        if (d := _parse_date(r.get(date_column))) and d.month == month_num and d.year == year
    ]

    result["records_in_period"] = rows_in_period
    return result


def build_project_completeness(
    client_records: list[dict],
    attendance_records: list[dict],
    client_key_column: str,
    attendance_key_column: str,
    client_billable_column: str,
    attendance_hours_column: str,
) -> list[dict]:
    """Compare monthly billable totals for client-side IDs only."""
    def aggregate(records, key_column, hour_columns, label):
        grouped = {}
        for record in records:
            key = _employee_key(record, key_column)
            if not key:
                continue
            entry = grouped.setdefault(key, {
                "project_id": _display_identifier(record, key_column),
                "total": 0.0,
                "name_counts": Counter(),
                "name_values": {},
            })
            name = _display_name(record, label, key_column)
            if name:
                name_key = name.casefold()
                entry["name_counts"][name_key] += 1
                entry["name_values"][name_key] = name
            for column in hour_columns:
                raw = record.get(column)
                if _is_missing(raw):
                    continue
                try:
                    entry["total"] += _as_number(raw)
                except (TypeError, ValueError):
                    continue

        for entry in grouped.values():
            if entry["name_counts"]:
                name_key, _ = entry["name_counts"].most_common(1)[0]
                entry["employee_name"] = entry["name_values"][name_key]
            else:
                entry["employee_name"] = ""
            entry["total"] = round(entry["total"], 2)
        return grouped

    client = aggregate(
        client_records,
        client_key_column,
        [client_billable_column],
        "Client Worksheet",
    )
    attendance = aggregate(
        attendance_records,
        attendance_key_column,
        [attendance_hours_column],
        "iLink Attendance",
    )

    projects = []
    for key, client_entry in client.items():
        attendance_entry = attendance.get(key)
        client_total = client_entry["total"]
        attendance_total = attendance_entry["total"] if attendance_entry else None
        if attendance_entry is None:
            status = "Project ID Not Found"
            reason = "Project ID not found in iLink for this period."
        elif client_total == attendance_total:
            status = "Match"
            reason = "Monthly totals match."
        else:
            status = "Mismatch"
            reason = "Monthly hours differ — Project ID may be missing for some weeks."
        projects.append({
            "project_id": client_entry["project_id"],
            "employee_name": (
                client_entry["employee_name"]
                or (attendance_entry or {}).get("employee_name", "")
            ),
            "client_billable_hours": client_total,
            "ilink_total_hours": attendance_total,
            "status": status,
            "reason": reason,
        })
    return projects


def attach_notification_drafts(
    projects: list[dict],
    attendance_records: list[dict],
    attendance_key_column: str,
    period: str,
) -> None:
    """Attach review-only email drafts to completeness exceptions."""
    emails_by_project = {}
    for record in attendance_records:
        key = _employee_key(record, attendance_key_column)
        raw_email = record.get("Email ID")
        if key and key not in emails_by_project and not _is_missing(raw_email):
            email = str(raw_email).strip()
            if email:
                emails_by_project[key] = email

    for project in projects:
        status = project.get("status")
        if status not in {"Mismatch", "Project ID Not Found"}:
            continue

        project_id = project.get("project_id", "")
        project_key = _employee_key(
            {attendance_key_column: project_id}, attendance_key_column
        )
        project["email"] = emails_by_project.get(project_key)
        employee_name = project.get("employee_name") or "Employee"
        client_hours = project.get("client_billable_hours", 0)
        client_hours_text = f"{float(client_hours):g}"

        if status == "Mismatch":
            ilink_hours_text = f"{float(project.get('ilink_total_hours', 0)):g}"
            project["email_subject"] = (
                f"Action needed: Project ID {project_id} hours discrepancy for {period}"
            )
            project["email_body"] = (
                f"Hello {employee_name},\n\n"
                f"For {period}, Project ID {project_id} shows {client_hours_text} "
                f"billable hours in the Client file and {ilink_hours_text} hours in iLink.\n\n"
                "Your logged hours differ between systems for this period. This usually means "
                "the Project ID wasn't entered for all relevant weeks in iPeople's Sub Project "
                f"field. Please review and correct your entries for {period}."
            )
        else:
            project["email_subject"] = (
                f"Action needed: Project ID {project_id} not found in iLink for {period}"
            )
            project["email_body"] = (
                f"Hello {employee_name},\n\n"
                f"For {period}, the Client file records {client_hours_text} billable hours for "
                f"Project ID {project_id}.\n\n"
                "This Project ID has no matching entries in iLink for this period. Please confirm "
                "you've entered this Project ID in the Sub Project field for all relevant weeks "
                f"in {period}."
            )