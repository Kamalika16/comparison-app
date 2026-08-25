
from __future__ import annotations

from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

SEVERITY_FILL = {
    "HIGH": PatternFill(start_color="FFC7CE", end_color="FFC7CE", fill_type="solid"),
    "MEDIUM": PatternFill(start_color="FFEB9C", end_color="FFEB9C", fill_type="solid"),
    "LOW": PatternFill(start_color="DDEBF7", end_color="DDEBF7", fill_type="solid"),
}

HEADER_FILL = PatternFill(start_color="305496", end_color="305496", fill_type="solid")
HEADER_FONT = Font(color="FFFFFF", bold=True)

DETAIL_HEADERS = [
    "Employee ID",
    "Employee Name",
    "Date",
    "Company Status",
    "Company Hours",
    "Client Hours",
    "Classification",
    "Severity",
    "Reason",
    "Recommendation",
]


def _autosize_columns(ws) -> None:
    for idx, header in enumerate(DETAIL_HEADERS, start=1):
        col_letter = get_column_letter(idx)
        max_len = max(
            [len(str(header))]
            + [len(str(cell.value)) for cell in ws[col_letter] if cell.value is not None]
        )
        ws.column_dimensions[col_letter].width = min(max(max_len + 2, 12), 45)


def write_report(result: dict, output_path: str) -> Path:

    summary = result.get("summary", {})
    mismatches = result.get("mismatches", [])

    wb = Workbook()

    # --- Summary sheet ---
    ws_summary = wb.active
    ws_summary.title = "Summary"
    ws_summary.append(["Metric", "Count"])
    for cell in ws_summary[1]:
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT

    summary_rows = [
        ("Total Records Compared", summary.get("total_records_compared", 0)),
        ("Matches", summary.get("matches", 0)),
        ("Mismatches", summary.get("mismatches", 0)),
        ("Needs Review (High Severity)", summary.get("review_required", 0)),
    ]
    for label, value in summary_rows:
        ws_summary.append([label, value])

    ws_summary.column_dimensions["A"].width = 30
    ws_summary.column_dimensions["B"].width = 14

    # --- Details sheet (mismatches only — that's all the schema provides) ---
    ws_details = wb.create_sheet("Details")
    ws_details.append(DETAIL_HEADERS)
    for cell in ws_details[1]:
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.alignment = Alignment(horizontal="center")

    for m in mismatches:
        ws_details.append(
            [
                m.get("employee_id", ""),
                m.get("employee_name", ""),
                m.get("date", ""),
                m.get("company_attendance_status", ""),
                m.get("company_hours"),
                m.get("client_hours"),
                m.get("classification", ""),
                m.get("severity", ""),
                m.get("reason", ""),
                m.get("recommendation", "") or "",
            ]
        )
        fill = SEVERITY_FILL.get(m.get("severity"))
        if fill:
            for cell in ws_details[ws_details.max_row]:
                cell.fill = fill

    ws_details.freeze_panes = "A2"
    ws_details.auto_filter.ref = ws_details.dimensions
    _autosize_columns(ws_details)

    output_path = Path(output_path)
    wb.save(output_path)
    return output_path