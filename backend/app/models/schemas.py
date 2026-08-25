"""
Pydantic models describing the shape of API requests and responses.
"""
from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class Severity(str, Enum):
    MATCH = "match"
    MINOR = "minor"
    MAJOR = "major"
    MISSING_ATTENDANCE = "missing_attendance"
    MISSING_CLIENT_WORK = "missing_client_work"
    REVIEW = "review"


class RowComparison(BaseModel):
    employee_name: str
    date: str
    attendance_hours: Optional[float] = None
    client_hours: Optional[float] = None
    difference: Optional[float] = None
    severity: Severity
    rule_triggered: str
    notes: Optional[str] = None


class ComparisonSummary(BaseModel):
    total_records: int
    matches: int
    minor_mismatches: int
    major_mismatches: int
    missing_in_attendance: int
    missing_in_client_work: int
    needs_review: int


class CompareResponse(BaseModel):
    summary: ComparisonSummary
    rows: list[RowComparison]
    report_filename: str = Field(
        ..., description="Filename of the generated Excel report, for download"
    )


class ColumnMappingInfo(BaseModel):
    detected_field: str
    matched_column: Optional[str] = None
    confidence: int = 0
