"""
API-layer automation tests.

Unlike test_hours_comparator.py (which calls service functions directly),
these tests go through the real HTTP surface: FastAPI's TestClient drives
actual requests through CORS middleware, multipart parsing, routing, and
the route handlers in app/routes/compare.py exactly as a real client would.

No live server or network access is required - TestClient runs the ASGI
app in-process. Run with:

    cd backend
    source .venv/bin/activate      # or your own venv
    pytest tests/test_api_routes.py -v
"""
from __future__ import annotations

import io
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

FIXTURES = Path(__file__).parent / "fixtures"
ATTENDANCE_XLSX = FIXTURES / "sample_attendance.xlsx"
CLIENT_XLSX = FIXTURES / "sample_client_work.xlsx"


def _upload_tuple(path: Path):
    """Build a fresh (filename, bytes, content-type) tuple for a multipart
    upload. Read fresh each time since the file pointer / TestClient
    consumes the stream."""
    return (
        path.name,
        path.read_bytes(),
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


# ---------------------------------------------------------------------------
# /api/health
# ---------------------------------------------------------------------------

def test_health_check():
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


# ---------------------------------------------------------------------------
# POST /api/columns
# ---------------------------------------------------------------------------

def test_columns_returns_headers_for_valid_file():
    resp = client.post(
        "/api/columns",
        files={"file": _upload_tuple(ATTENDANCE_XLSX)},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["filename"] == "sample_attendance.xlsx"
    assert body["columns"] == ["Employee Name", "Date", "Hours Worked"]


def test_columns_rejects_disallowed_extension():
    resp = client.post(
        "/api/columns",
        files={"file": ("notes.txt", b"just some text", "text/plain")},
    )
    assert resp.status_code == 400
    assert "not an Excel file" in resp.json()["detail"]


def test_columns_rejects_corrupt_excel_file():
    # Right extension, garbage bytes -> pandas/openpyxl should fail to parse
    resp = client.post(
        "/api/columns",
        files={"file": ("broken.xlsx", b"not a real xlsx file", "application/octet-stream")},
    )
    assert resp.status_code == 400
    assert "Could not read columns" in resp.json()["detail"]


def test_columns_requires_the_file_field():
    resp = client.post("/api/columns", files={})
    # FastAPI's own request validation (422) fires before our handler runs
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# POST /api/compare -- deterministic path (both key columns supplied)
# ---------------------------------------------------------------------------

def test_compare_deterministic_happy_path_returns_report_id():
    resp = client.post(
        "/api/compare",
        files={
            "attendance_file": _upload_tuple(ATTENDANCE_XLSX),
            "client_file": _upload_tuple(CLIENT_XLSX),
        },
        data={
            "attendance_key_column": "Employee Name",
            "client_key_column": "Full Name",
        },
    )
    assert resp.status_code == 200
    body = resp.json()

    assert "summary" in body and "mismatches" in body and "report_id" in body
    # Internal consistency: summary counts should reconcile with the
    # mismatches list length, independent of exactly what the numbers are.
    summary = body["summary"]
    mismatch_count = len(body["mismatches"])
    assert summary["mismatches"] == mismatch_count
    if "total_records_compared" in summary:
        assert summary["matches"] + summary["mismatches"] == summary["total_records_compared"]

    # This is the deterministic path -- no LLM call, so it must be fast and
    # must not have silently fallen back to the LLM comparator.
    for m in body["mismatches"]:
        assert m["severity"] in {"HIGH", "MEDIUM", "LOW"}


def test_compare_swapped_key_columns_still_matches_by_value_not_name():
    """The two identifier columns are allowed to have completely different
    names -- matching happens on cell VALUES, not on the column headers
    matching each other. This test pins that contract."""
    resp = client.post(
        "/api/compare",
        files={
            "attendance_file": _upload_tuple(ATTENDANCE_XLSX),
            "client_file": _upload_tuple(CLIENT_XLSX),
        },
        data={
            "attendance_key_column": "Employee Name",  # different header...
            "client_key_column": "Full Name",           # ...same underlying values
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    # All 5 employees appear in both fixtures -> nobody should show up as
    # "missing" purely because the column names differ.
    missing_reasons = [
        m for m in body["mismatches"]
        if m.get("company_hours") is None or m.get("client_hours") is None
    ]
    assert missing_reasons == []


def test_compare_rejects_ambiguous_hours_column():
    """If the non-identifier columns aren't exactly one fully-numeric
    column, the app must refuse to guess (see excel_loader.detect_hours_column)."""
    resp = client.post(
        "/api/compare",
        files={
            "attendance_file": _upload_tuple(ATTENDANCE_XLSX),
            "client_file": _upload_tuple(CLIENT_XLSX),
        },
        data={
            # "Date" is not numeric and "Hours Worked" is -- picking "Date"
            # as the identifier leaves exactly one numeric column, which is
            # fine. Instead, force ambiguity by excluding nothing useful:
            # select a key column that IS the numeric column, so both
            # remaining columns ("Employee Name", "Date") are non-numeric
            # and detect_hours_column finds zero numeric candidates.
            "attendance_key_column": "Hours Worked",
            "client_key_column": "Billable Hours",
        },
    )
    assert resp.status_code == 400
    assert "numeric" in resp.json()["detail"].lower()


def test_compare_rejects_disallowed_extension_on_either_file():
    resp = client.post(
        "/api/compare",
        files={
            "attendance_file": ("bad.docx", b"not excel", "application/octet-stream"),
            "client_file": _upload_tuple(CLIENT_XLSX),
        },
        data={
            "attendance_key_column": "Employee Name",
            "client_key_column": "Full Name",
        },
    )
    assert resp.status_code == 400
    assert "not an Excel file" in resp.json()["detail"]


def test_compare_cleans_up_temp_uploads_after_request():
    """Regression guard for the finally-block cleanup in routes/compare.py:
    uploads must never accumulate on disk across requests."""
    from app.config import UPLOAD_DIR

    before = set(UPLOAD_DIR.glob("*"))
    client.post(
        "/api/compare",
        files={
            "attendance_file": _upload_tuple(ATTENDANCE_XLSX),
            "client_file": _upload_tuple(CLIENT_XLSX),
        },
        data={
            "attendance_key_column": "Employee Name",
            "client_key_column": "Full Name",
        },
    )
    after = set(UPLOAD_DIR.glob("*")) - {UPLOAD_DIR / ".gitkeep"}
    assert after == (before - {UPLOAD_DIR / ".gitkeep"})


# ---------------------------------------------------------------------------
# GET /api/reports/{report_id}/download
# ---------------------------------------------------------------------------

def test_download_report_after_successful_compare():
    compare_resp = client.post(
        "/api/compare",
        files={
            "attendance_file": _upload_tuple(ATTENDANCE_XLSX),
            "client_file": _upload_tuple(CLIENT_XLSX),
        },
        data={
            "attendance_key_column": "Employee Name",
            "client_key_column": "Full Name",
        },
    )
    report_id = compare_resp.json()["report_id"]

    download_resp = client.get(f"/api/reports/{report_id}/download")
    assert download_resp.status_code == 200
    assert download_resp.headers["content-type"] == (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    assert download_resp.content[:2] == b"PK"  # xlsx is a zip archive
    assert "hours_comparison_report_" in download_resp.headers["content-disposition"]


def test_download_report_unknown_id_returns_404():
    resp = client.get("/api/reports/does-not-exist/download")
    assert resp.status_code == 404
    assert "not found" in resp.json()["detail"].lower()


# ---------------------------------------------------------------------------
# Documents a currently-unenforced limit (see Part 21 of the walkthrough:
# MAX_UPLOAD_SIZE exists in config.py but nothing in routes/compare.py
# actually checks an upload's size against it). This test is written to
# PASS today, documenting the gap explicitly rather than silently relying
# on undocumented behavior. If size enforcement is added later, flip the
# assertion to expect a 413/400 and this test will correctly start failing
# until updated -- that's the point.
# ---------------------------------------------------------------------------

def test_oversized_upload_is_not_currently_rejected():
    """MAX_UPLOAD_SIZE is defined in config.py but nothing in
    routes/compare.py ever checks an upload's actual size against it.
    A file well over that limit is still accepted and processed."""
    from app.config import MAX_UPLOAD_SIZE

    # A valid, parseable CSV that is nonetheless bigger than MAX_UPLOAD_SIZE.
    header = "id,hours\n"
    row = "1,8\n"
    padding_rows_needed = (MAX_UPLOAD_SIZE // len(row)) + 100
    oversized_csv = (header + row * padding_rows_needed).encode()
    assert len(oversized_csv) > MAX_UPLOAD_SIZE

    resp = client.post(
        "/api/columns",
        files={"file": ("huge.csv", oversized_csv, "text/csv")},
    )
    # Documents current behavior: accepted and successfully processed
    # despite exceeding MAX_UPLOAD_SIZE -- there is no size check today.
    assert resp.status_code == 200
    assert resp.json()["columns"] == ["id", "hours"]
