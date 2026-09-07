import json
import shutil
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, UploadFile, File, Form, HTTPException
from fastapi.responses import FileResponse

from ..config import UPLOAD_DIR, OUTPUT_DIR
from ..services.excel_loader import get_columns, load_records, detect_hours_column
from ..services.hours_comparator import compare_records
from ..services.report_writer import write_report


router = APIRouter(prefix="/api", tags=["compare"])

ALLOWED_EXT = {".xlsx", ".xls", ".csv"}


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
):
    att_path = _save_upload(attendance_file, UPLOAD_DIR)
    cli_path = _save_upload(client_file, UPLOAD_DIR)

    try:
        att_records = load_records(str(att_path))
        cli_records = load_records(str(cli_path))

        att_hours_column = detect_hours_column(
            att_records,
            exclude=[attendance_key_column]
        )

        cli_hours_column = detect_hours_column(
            cli_records,
            exclude=[client_key_column]
        )

        meta = {
            "attendance_key_column": attendance_key_column,
            "client_key_column": client_key_column,
            "attendance_hours_column": att_hours_column,
            "client_hours_column": cli_hours_column,
        }

        result = compare_records(
            att_records,
            cli_records,
            attendance_key_column,
            client_key_column,
            att_hours_column,
            cli_hours_column,
        )

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