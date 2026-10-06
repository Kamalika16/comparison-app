import json
import shutil
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, UploadFile, File, Form, HTTPException
from fastapi.responses import FileResponse

from ..config import UPLOAD_DIR, OUTPUT_DIR
from ..services.excel_loader import (
    get_columns, load_records, detect_hours_column, _is_missing,
    detect_billable_column, detect_non_billable_column, detect_date_column,
)
from ..services.llm_column_detector import detect_billable_and_non_billable_via_llm
from ..services.hours_comparator import compare_records, validate_expected_hours
from ..services.completeness_checker import (
    attach_notification_drafts,
    build_project_completeness,
    check_completeness,
    count_working_days,
)
from ..services.report_writer import write_report


router = APIRouter(prefix="/api", tags=["compare"])

ALLOWED_EXT = {".xlsx", ".xls", ".csv"}


def _client_display_name(records: list[dict]) -> str:
    """Read the client label from the first file's second column."""
    if not records:
        return "Client"
    columns = list(records[0])
    if len(columns) < 2:
        return "Client"
    client_column = columns[1]
    for record in records:
        value = record.get(client_column)
        if not _is_missing(value):
            return str(value).strip()
    return "Client"


def _save_upload(file: UploadFile, dest_dir: Path) -> Path:
    ext = Path(file.filename).suffix.lower()

    if ext not in ALLOWED_EXT:
        raise HTTPException(
            400,
            f"'{file.filename}' is not an Excel file."
        )

    dest = dest_dir / f"{uuid.uuid4().hex}{ext}"

    with dest.open("wb") as f:
        shutil.copyfileobj(file.file, f)

    return dest


@router.post("/columns")
async def detect_columns(file: UploadFile = File(...)):
    """
    Read an uploaded Excel file just to discover its column headers,
    so the UI can offer them as primary-identifier candidates.
    """
    path = _save_upload(file, UPLOAD_DIR)

    try:
        columns = get_columns(str(path))
    except Exception as e:
        raise HTTPException(
            400,
            f"Could not read columns from '{file.filename}': {e}"
        )
    finally:
        path.unlink(missing_ok=True)

    return {
        "filename": file.filename,
        "columns": columns
    }


@router.post("/compare")
async def compare(
    attendance_file: UploadFile = File(...),
    client_file: UploadFile = File(...),
    attendance_key_column: Optional[str] = Form(None),
    client_key_column: Optional[str] = Form(None),
    attendance_date_column: Optional[str] = Form(None),
    client_date_column: Optional[str] = Form(None),
):
    att_path = _save_upload(attendance_file, UPLOAD_DIR)
    cli_path = _save_upload(client_file, UPLOAD_DIR)

    try:
        att_records = load_records(str(att_path))
        cli_records = load_records(str(cli_path))
        client_display_name = _client_display_name(att_records)

        # --- Stage 0: completeness -------------------------------------
        # date_column is auto-detected when not explicitly given -- the
        # iLink Timesheet has no Month/Year columns, so without this it has
        # no way to know its own reporting period at all.
        attendance_date_column = attendance_date_column or detect_date_column(
            att_records, exclude=[attendance_key_column]
        )
        client_date_column = client_date_column or detect_date_column(
            cli_records, exclude=[client_key_column]
        )
        completeness = {
            "attendance": check_completeness(
                att_records, attendance_key_column,
                date_column=attendance_date_column, label="iLink Timesheet",
            ),
            "client": check_completeness(
                cli_records, client_key_column,
                date_column=client_date_column, label=client_display_name,
            ),
        }
        # Keep the detected-period rows for completeness validation only.
        records_in_period = {
            side: c.pop("records_in_period", [])
            for side, c in completeness.items()
        }
        if any(
            c.get("error") or not records_in_period[side]
            for side, c in completeness.items()
        ):
            return {
                "stage": "completeness",
                "completeness": completeness,
                "summary": {"total_records_compared": 0, "matches": 0, "mismatches": 0},
                "mismatches": [],
                "matched": [],
                "client_display_name": client_display_name,
            }

        # Resolve these columns once; the completeness table and both
        # existing comparison stages use the same detected values.
        billable_col = detect_billable_column(
            cli_records, exclude=[client_key_column]
        )
        non_billable_col = detect_non_billable_column(
            cli_records, exclude=[client_key_column]
        )
        if not billable_col or not non_billable_col:
            print("LLM fallback triggered")
            llm_columns = detect_billable_and_non_billable_via_llm(
                [str(column) for column in cli_records[0].keys()] if cli_records else []
            )
            billable_col = billable_col or llm_columns["billable_column"]
            non_billable_col = non_billable_col or llm_columns["non_billable_column"]
        if (
            not billable_col
            or not non_billable_col
            or billable_col == non_billable_col
        ):
            raise HTTPException(
                400,
                "Could not confidently detect distinct Billable Hours and "
                "Non-Billable Hours columns in the client file. Check the "
                "column names and ensure both columns contain numeric hours."
            )
        att_hours_column = detect_hours_column(
            att_records,
            exclude=[attendance_key_column],
        )
        completeness["projects"] = build_project_completeness(
            cli_records,
            att_records,
            client_key_column,
            attendance_key_column,
            billable_col,
            att_hours_column,
        )
        attach_notification_drafts(
            completeness["projects"],
            att_records,
            attendance_key_column,
            completeness["client"].get("period") or "the reporting period",
        )

        # --- Level 1: all client rows' billable+non-billable vs auto-calculated total ---
        # Expected hours = working days (Mon-Fri, no holiday exclusion) in
        # the client file's own reporting month x 8. No manual entry.
        client_period = completeness["client"]
        expected_total_hours = count_working_days(
            client_period["year"], client_period["month_num"]
        ) * 8
        stage1 = validate_expected_hours(
            cli_records, client_key_column, billable_col, non_billable_col,
            expected_total_hours,
        )
        allowed_ids = {row["employee_id"] for row in stage1["matched"]}

        # --- Level 2: only Level-1-matched employees, BILLABLE HOURS ONLY
        # from the client side (not billable+non-billable) vs the iLink
        # Timesheet. Both sides use all uploaded rows; only the client rows
        # are restricted to Level-1-matched IDs. iLink's Hour(s) column is
        # confirmed billable-only, so no Billing Status filtering is needed.
        cli_records_for_stage2 = [
            r for r in cli_records
            if str(r.get(client_key_column, "")).strip() in allowed_ids
        ]
        if not cli_records_for_stage2:
            # Nothing matched Level 1 -- a real, reachable outcome (e.g. no
            # one's actual hours equal the calculated Expected Total Hrs),
            # not an error. Return what we have instead of letting hours
            # detection crash on an empty dataset.
            return {
                "stage": "stage1_no_matches",
                "completeness": completeness,
                "stage1": stage1,
                "summary": {"total_records_compared": 0, "matches": 0, "mismatches": 0},
                "mismatches": [],
                "matched": [],
                "client_display_name": client_display_name,
            }

        # Billable Hours specifically -- the same column Level 1 already
        # detected/was given, not a fresh generic detection.
        cli_hours_column = billable_col

        meta = {
            "attendance_key_column": attendance_key_column,
            "client_key_column": client_key_column,
            "attendance_hours_column": att_hours_column,
            "client_hours_column": cli_hours_column,
            "client_display_name": client_display_name,
        }

        result = compare_records(
            att_records,
            cli_records_for_stage2,
            attendance_key_column,
            client_key_column,
            att_hours_column,
            cli_hours_column,
            file1_label="iLink Timesheet",
            file2_label=client_display_name,
        )
        result["completeness"] = completeness
        result["stage1"] = stage1

    except json.JSONDecodeError:
        raise HTTPException(
            502,
            "The AI did not return valid JSON. Please try again."
        )

    except HTTPException:
        raise

    except Exception as e:
        raise HTTPException(
            500,
            f"Comparison failed: {e}"
        )

    finally:
        att_path.unlink(missing_ok=True)
        cli_path.unlink(missing_ok=True)

    # Basic shape check before we hand this to the report writer / frontend.
    if (
        not isinstance(result, dict)
        or "summary" not in result
        or "mismatches" not in result
    ):
        raise HTTPException(
            502,
            f"AI response was valid JSON but not in the expected shape. "
            f"Got: {result}",
        )

    report_id = uuid.uuid4().hex
    report_path = OUTPUT_DIR / f"{report_id}.xlsx"

    try:
        write_report(
            result,
            str(report_path),
            meta=meta
        )

    except Exception as e:
        raise HTTPException(
            500,
            f"Report generation failed: {e}. Raw result: {result}"
        )

    result["report_id"] = report_id
    result["client_display_name"] = meta["client_display_name"]

    return result


@router.get("/reports/{report_id}/download")
async def download_report(report_id: str):
    path = OUTPUT_DIR / f"{report_id}.xlsx"

    if not path.exists():
        raise HTTPException(
            404,
            "Report not found or has expired."
        )

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    return FileResponse(
        path,
        media_type=(
            "application/vnd.openxmlformats-officedocument."
            "spreadsheetml.sheet"
        ),
        filename=f"hours_comparison_report_{stamp}.xlsx",
    )