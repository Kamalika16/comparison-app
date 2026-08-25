"""
Semantic column mapper.

Attendance and client-work exports rarely use identical headers
("Emp Name" vs "Employee" vs "Full Name"). This module fuzzy-matches
incoming column headers to the canonical fields we need:

    - employee_name
    - date
    - hours

using a small synonym dictionary plus rapidfuzz for scoring.
"""
from __future__ import annotations

from typing import Optional

from rapidfuzz import fuzz, process

from app.config import COLUMN_MATCH_THRESHOLD

# Canonical field -> list of known synonyms / common header variants
FIELD_SYNONYMS: dict[str, list[str]] = {
    "employee_name": [
        "employee name", "employee", "emp name", "full name", "name",
        "staff name", "worker", "resource name", "resource", "consultant",
    ],
    "date": [
        "date", "work date", "attendance date", "day", "shift date",
        "log date", "entry date",
    ],
    "hours": [
        "hours", "hours worked", "total hours", "duration", "time logged",
        "hrs", "billable hours", "worked hours", "clock hours",
    ],
    "employee_id": [
        "employee id", "emp id", "id", "staff id", "badge number", "badge id",
    ],
    "project": [
        "project", "project name", "client", "task", "engagement",
    ],
}


def map_columns(headers: list[str]) -> dict[str, Optional[str]]:
    """
    Given a list of raw column headers from an uploaded spreadsheet,
    return a mapping of canonical field name -> best-matching raw header
    (or None if no confident match was found).
    """
    normalized_headers = {h: h.strip().lower() for h in headers}
    result: dict[str, Optional[str]] = {}

    for field, synonyms in FIELD_SYNONYMS.items():
        best_header = None
        best_score = 0

        for raw_header, norm_header in normalized_headers.items():
            match = process.extractOne(
                norm_header, synonyms, scorer=fuzz.token_sort_ratio
            )
            if match and match[1] > best_score:
                best_score = match[1]
                best_header = raw_header

        result[field] = best_header if best_score >= COLUMN_MATCH_THRESHOLD else None

    return result


def validate_required_fields(
    mapping: dict[str, Optional[str]], required: list[str] | None = None
) -> list[str]:
    """
    Return a list of required canonical fields that could not be mapped.
    """
    required = required or ["employee_name", "date", "hours"]
    return [field for field in required if not mapping.get(field)]
