import json
import shutil
import uuid
from pathlib import Path

from fastapi import APIRouter, UploadFile, File, HTTPException
from fastapi.responses import FileResponse

from ..config import UPLOAD_DIR, OUTPUT_DIR
from ..services.excel_loader import load_records
from ..services.llm_comparator import compare_via_llm
from ..services.report_writer import write_report

router = APIRouter(prefix="/api", tags=["compare"])

ALLOWED_EXT = {".xlsx", ".xls"}


def _save_upload(file: UploadFile, dest_dir: Path) -> Path:
    ext = Path(file.filename).suffix.lower()
    if ext not in ALLOWED_EXT:
        raise HTTPException(400, f"'{file.filename}' is not an Excel file.")
    dest = dest_dir / f"{uuid.uuid4().hex}{ext}"
    with dest.open("wb") as f:
        shutil.copyfileobj(file.file, f)
    return dest


@router.post("/compare")
async def compare(
    attendance_file: UploadFile = File(...),
    client_file: UploadFile = File(...),
):
    att_path = _save_upload(attendance_file, UPLOAD_DIR)
    cli_path = _save_upload(client_file, UPLOAD_DIR)

    try:
        att_records = load_records(str(att_path))
        cli_records = load_records(str(cli_path))
        result = compare_via_llm(att_records, cli_records)
    except json.JSONDecodeError:
        raise HTTPException(502, "The AI did not return valid JSON. Please try again.")
    except Exception as e:
        raise HTTPException(500, f"Comparison failed: {e}")
    finally:
        att_path.unlink(missing_ok=True)
        cli_path.unlink(missing_ok=True)

    # Basic shape check before we hand this to the report writer / frontend.
    if not isinstance(result, dict) or "summary" not in result or "mismatches" not in result:
        raise HTTPException(
            502,
            f"AI response was valid JSON but not in the expected shape. Got: {result}",
        )

    report_id = uuid.uuid4().hex
    report_path = OUTPUT_DIR / f"{report_id}.xlsx"
    try:
        write_report(result, str(report_path))
    except Exception as e:
        raise HTTPException(500, f"Report generation failed: {e}. Raw result: {result}")

    result["report_id"] = report_id
    return result


@router.get("/reports/{report_id}/download")
async def download_report(report_id: str):
    path = OUTPUT_DIR / f"{report_id}.xlsx"
    if not path.exists():
        raise HTTPException(404, "Report not found or has expired.")
    return FileResponse(
        path,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename="comparison_report.xlsx",
    )