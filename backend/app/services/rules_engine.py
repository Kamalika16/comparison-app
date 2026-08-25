"""
Rules engine for comparing attendance records against client work logs.

Each incoming (employee, date) pair from either source is evaluated against
the following ordered rules. The first rule that matches wins.

    Rule 1  - Exact match: both sources report the same hours (within
              HOURS_TOLERANCE_MINOR) -> MATCH
    Rule 2  - Minor variance: difference is within HOURS_TOLERANCE_MAJOR but
              above HOURS_TOLERANCE_MINOR -> MINOR mismatch
    Rule 3  - Major variance: difference exceeds HOURS_TOLERANCE_MAJOR
              -> MAJOR mismatch
    Rule 4  - Present in attendance, absent from client work -> MISSING_CLIENT_WORK
    Rule 5  - Present in client work, absent from attendance -> MISSING_ATTENDANCE
    Rule 6  - Zero hours recorded on one side while the other is > 0
              -> MAJOR mismatch (flag as likely data-entry error)
    Rule 7  - Duplicate (employee, date) entries on either side
              -> REVIEW (can't reliably compare, needs human eyes)
    Rule 8  - Weekend/holiday date with hours logged on either side
              -> REVIEW (may be legitimate overtime, may be an error)
    Rule 9  - Unparseable / malformed row (missing name or date after
              normalization) -> REVIEW
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from app.config import HOURS_TOLERANCE_MAJOR, HOURS_TOLERANCE_MINOR
from app.models.schemas import Severity


@dataclass
class NormalizedRecord:
    employee_name: str
    date: Optional[str]
    hours: Optional[float]
    raw_name: str = ""


@dataclass
class RuleResult:
    severity: Severity
    rule_triggered: str
    notes: str = ""


def _is_weekend(iso_date: str) -> bool:
    import datetime as _dt

    try:
        d = _dt.date.fromisoformat(iso_date)
        return d.weekday() >= 5  # 5=Saturday, 6=Sunday
    except ValueError:
        return False


def evaluate_pair(
    attendance: Optional[NormalizedRecord],
    client_work: Optional[NormalizedRecord],
    attendance_duplicate: bool = False,
    client_work_duplicate: bool = False,
) -> RuleResult:
    """
    Apply Rules 1-9 to a single (employee, date) key, given the matching
    attendance record and client-work record (either may be None).
    """
    # Rule 9: malformed rows
    for rec in (attendance, client_work):
        if rec is not None and (not rec.employee_name or not rec.date):
            return RuleResult(
                Severity.REVIEW,
                "Rule 9",
                "Row missing employee name or date after normalization.",
            )

    # Rule 7: duplicates on either side make the comparison unreliable
    if attendance_duplicate or client_work_duplicate:
        return RuleResult(
            Severity.REVIEW,
            "Rule 7",
            "Duplicate employee/date entries found; manual review required.",
        )

    # Rule 4: only in attendance
    if attendance is not None and client_work is None:
        return RuleResult(
            Severity.MISSING_CLIENT_WORK,
            "Rule 4",
            "Employee has attendance recorded but no client work log.",
        )

    # Rule 5: only in client work
    if client_work is not None and attendance is None:
        return RuleResult(
            Severity.MISSING_ATTENDANCE,
            "Rule 5",
            "Client work logged but no matching attendance record.",
        )

    # Both present from here on
    assert attendance is not None and client_work is not None
    a_hours = attendance.hours or 0.0
    c_hours = client_work.hours or 0.0
    diff = round(abs(a_hours - c_hours), 2)

    # Rule 8: weekend/holiday work logged
    if attendance.date and _is_weekend(attendance.date) and (a_hours > 0 or c_hours > 0):
        return RuleResult(
            Severity.REVIEW,
            "Rule 8",
            "Hours logged on a weekend date; confirm this is expected overtime.",
        )

    # Rule 6: zero on one side, nonzero on the other
    if (a_hours == 0 and c_hours > 0) or (c_hours == 0 and a_hours > 0):
        return RuleResult(
            Severity.MAJOR,
            "Rule 6",
            f"Zero hours on one side (attendance={a_hours}, client={c_hours}); likely data entry error.",
        )

    # Rule 1: match within minor tolerance
    if diff <= HOURS_TOLERANCE_MINOR:
        return RuleResult(Severity.MATCH, "Rule 1", "Hours match within tolerance.")

    # Rule 2: minor variance
    if diff <= HOURS_TOLERANCE_MAJOR:
        return RuleResult(
            Severity.MINOR,
            "Rule 2",
            f"Minor variance of {diff} hours between sources.",
        )

    # Rule 3: major variance
    return RuleResult(
        Severity.MAJOR,
        "Rule 3",
        f"Major variance of {diff} hours between sources.",
    )
