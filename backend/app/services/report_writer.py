from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

SEVERITY_FILL = {
    "HIGH": PatternFill(start_color="FFC7CE", end_color="FFC7CE", fill_type="solid"),
    "MEDIUM": PatternFill(start_color="FFEB9C", end_color="FFEB9C", fill_type="solid"),
    "LOW": PatternFill(start_color="DDEBF7", end_color="DDEBF7", fill_type="solid"),
    "MATCH": PatternFill(start_color="C6E0B4", end_color="C6E0B4", fill_type="solid"),
}

HEADER_FILL = PatternFill(start_color="305496", end_color="305496", fill_type="solid")
HEADER_FONT = Font(color="FFFFFF", bold=True)


def detail_headers(meta: dict | None) -> list[str]:
    """Column layout for the joined comparison result."""
    meta = meta or {}
    client_name = meta.get("client_display_name", "Client")
    return [
        "Employee Name",
        "ID",
        "iLink Timesheet Hours",
        f"{client_name} Hours",
        "Difference",
        "Status",
        "Reason",
    ]


def _difference(m: dict):
    """|Attendance - Client| rounded to 2 dp — identical to the value the UI
    shows; blank when either side has no value."""
    a, b = m.get("company_hours"), m.get("client_hours")
    if a is None or b is None:
        return None
    try:
        return round(abs(float(a) - float(b)), 2)
    except (TypeError, ValueError):
        return None


def _classification_label(m: dict, client_name: str = "Client") -> str:
    """Human-readable classification identical to the UI badge, derived from
    the same null checks (never invented)."""
    if m.get("classification") == "MATCH":
        return "Matched"
    has_att = m.get("company_hours") is not None
    has_cli = m.get("client_hours") is not None
    if has_att and not has_cli:
        return "Only in iLink Timesheet"
    if has_cli and not has_att:
        return f"Only in {client_name}"
    if has_att and has_cli:
        return "Hours mismatch"
    return "Incomplete record"


def _autosize_columns(ws, headers) -> None:
    for idx, header in enumerate(headers, start=1):
        col_letter = get_column_letter(idx)
        max_len = max(
            [len(str(header))]
            + [len(str(cell.value)) for cell in ws[col_letter] if cell.value is not None]
        )
        ws.column_dimensions[col_letter].width = min(max(max_len + 2, 12), 45)


def write_report(result: dict, output_path: str, meta: dict | None = None) -> Path:
    summary = result.get("summary", {})
    mismatches = result.get("mismatches", [])
    matched = result.get("matched", [])
    meta = meta or {}

    wb = Workbook()

    # --- Summary sheet (metrics + factual export metadata) ---
    ws_summary = wb.active
    ws_summary.title = "Summary"
    ws_summary.append(["Metric", "Value"])
    for cell in ws_summary[1]:
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT

    summary_rows = [
        ("Generated (UTC)", datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")),
        ("Total Records Compared", summary.get("total_records_compared", 0)),
        ("Matches", summary.get("matches", 0)),
        ("Mismatches", summary.get("mismatches", 0)),
        ("Needs Review (High Severity)", summary.get("review_required", 0)),
        ("Attendance Primary Identifier", meta.get("attendance_key_column", "n/a")),
        ("Client Primary Identifier", meta.get("client_key_column", "n/a")),
        ("Attendance Hours Column", meta.get("attendance_hours_column", "n/a")),
        ("Client Hours Column", meta.get("client_hours_column", "n/a")),
    ]
    for label, value in summary_rows:
        ws_summary.append([label, value])

    ws_summary.column_dimensions["A"].width = 32
    ws_summary.column_dimensions["B"].width = 34

    # --- Details sheet: ONE combined final list -- Level 1 mismatches,
    # Level 2 mismatches, and Level 2 matches all together, per the
    # original spec ("final list will have level 1 mismatched and level 2
    # mismatched and matched employees too"). Replaces the separate
    # Details + Expected Hours sheets from the earlier version.
    stage1 = result.get("stage1") or {}
    combined_headers = [
        "Employee ID", "Employee Name",
        "Billable Hours", "Non-Billable Hours", "Level 1 Total",
        "Level 1 Expected Total", "Level 1 Status",
        "iLink Timesheet Hours", "Client Billable Hours (Level 2)",
        "Level 2 Difference", "Level 2 Status",
        "Overall Status", "Reason",
    ]
    ws_details = wb.create_sheet("Details")
    ws_details.append(combined_headers)
    for cell in ws_details[1]:
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.alignment = Alignment(horizontal="center")

    # Level 1 mismatches never reach Level 2 -- no iLink-side data exists
    # for them, those columns are left blank rather than a fabricated 0.
    for row in stage1.get("mismatched", []):
        ws_details.append([
            row.get("employee_id", ""), row.get("employee_name", ""),
            row.get("billable_hours"), row.get("non_billable_hours"),
            row.get("total_hours"), row.get("expected_total_hours"),
            "Mismatched", "", "", "", "",
            "Level 1 Mismatch",
            f"Level 1: billable+non-billable total {row.get('total_hours')} vs "
            f"expected {row.get('expected_total_hours')}, "
            f"difference {row.get('difference')}.",
        ])
        for cell in ws_details[ws_details.max_row]:
            cell.fill = SEVERITY_FILL["MEDIUM"]

    # Level 2 rows -- only employees who matched Level 1 reach here, so
    # their Level 1 figures are looked up (all should be found).
    stage1_matched_lookup = {
        row.get("employee_id"): row for row in stage1.get("matched", [])
    }
    for m in result.get("mismatches", []) + result.get("matched", []):
        emp_id = m.get("id", m.get("employee_id", ""))
        s1 = stage1_matched_lookup.get(emp_id, {})
        is_match = str(m.get("status", "")).lower().startswith("match")
        ws_details.append([
            emp_id, m.get("employee_name", "") or s1.get("employee_name", ""),
            s1.get("billable_hours"), s1.get("non_billable_hours"),
            s1.get("total_hours"), s1.get("expected_total_hours"),
            "Matched",
            m.get("file1_total_hours", m.get("company_hours")),
            m.get("file2_hours", m.get("client_hours")),
            m.get("difference", _difference(m)),
            m.get("status", "Mismatch"),
            "Matched" if is_match else "Level 2 Mismatch",
            m.get("reason", "") or "",
        ])
        if not is_match:
            fill = SEVERITY_FILL.get(m.get("severity"), SEVERITY_FILL.get("MEDIUM"))
            for cell in ws_details[ws_details.max_row]:
                cell.fill = fill

    ws_details.freeze_panes = "A2"
    ws_details.auto_filter.ref = ws_details.dimensions
    _autosize_columns(ws_details, combined_headers)

    # --- Completeness sheet (Stage 0) ---
    completeness = result.get("completeness")
    if completeness:
        ws_comp = wb.create_sheet("Completeness")
        comp_headers = [
            "Project ID", "Employee Name", "Client Billable Hours",
            "iLink Hours", "Status", "Reason",
        ]
        ws_comp.append(comp_headers)
        for cell in ws_comp[1]:
            cell.fill = HEADER_FILL
            cell.font = HEADER_FONT
        for row in completeness.get("projects", []):
            ws_comp.append([
                row.get("project_id", ""),
                row.get("employee_name", ""),
                row.get("client_billable_hours", ""),
                row.get("ilink_total_hours", ""),
                row.get("status", ""),
                row.get("reason", ""),
            ])
        ws_comp.auto_filter.ref = ws_comp.dimensions
        _autosize_columns(ws_comp, comp_headers)

    output_path = Path(output_path)
    wb.save(output_path)
    return output_path