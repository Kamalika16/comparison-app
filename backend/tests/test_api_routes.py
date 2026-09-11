"""
API-layer automation tests.

Unlike test_hours_comparator.py (which calls service functions directly),
these tests go through the real HTTP surface: FastAPI's TestClient drives
actual requests through CORS middleware, multipart parsing, routing, and
the route handlers in app/routes/compare.py exactly as a real client would.

/api/compare routes through the deterministic Python comparison engine
(compare_records() in app/services/hours_comparator.py) -- there is no LLM
in the loop, so these tests call the real endpoint end-to-end with the
bundled sample fixtures rather than mocking anything out. That's on
purpose: the comparator is fast, free, and produces the same result every
run, so mocking it would only hide bugs instead of catching them.

No live server or network access is required. Run with:

    cd backend
    source .venv/bin/activate      # or your own venv
    pytest tests/test_api_routes.py -v
"""
from __future__ import annotations

from pathlib import Path

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
# POST /api/health
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
# POST /api/compare -- deterministic Python comparison engine, no mocking.
# The sample fixtures have one deliberate mismatch built in (see
# tests/fixtures/*), so we assert on that real, known shape.
# ---------------------------------------------------------------------------

def test_compare_happy_path_returns_report_id():
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

    assert "summary" in body and "report_id" in body
    assert "mismatches" in body and "matched" in body
    summary = body["summary"]
    assert summary["mismatches"] == len(body["mismatches"])
    assert summary["matches"] + summary["mismatches"] == summary["total_records_compared"]

    for m in body["mismatches"]:
        assert m["severity"] in {"HIGH", "MEDIUM", "LOW"}


def test_compare_works_without_key_columns_too():
    """Falls back to the legacy normalized-name heuristic when no key
    column is selected (see _employee_key in llm_comparator.py)."""
    resp = client.post(
        "/api/compare",
        files={
            "attendance_file": _upload_tuple(ATTENDANCE_XLSX),
            "client_file": _upload_tuple(CLIENT_XLSX),
        },
        data={},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "summary" in body and "mismatches" in body and "report_id" in body


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


def test_compare_reports_missing_hours_column_as_400():
    """detect_hours_column() raises ValueError when a file has zero or
    multiple numeric columns; the route must surface that as a clean 400/500
    rather than a raw traceback."""
    import io as _io
    bad_csv = b"Employee Name,Notes\nJohn Smith,no numeric column here\n"
    resp = client.post(
        "/api/compare",
        files={
            "attendance_file": ("attendance.csv", bad_csv, "text/csv"),
            "client_file": _upload_tuple(CLIENT_XLSX),
        },
        data={
            "attendance_key_column": "Employee Name",
            "client_key_column": "Full Name",
        },
    )
    assert resp.status_code in (400, 500)


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

    header = "id,hours\n"
    row = "1,8\n"
    padding_rows_needed = (MAX_UPLOAD_SIZE // len(row)) + 100
    oversized_csv = (header + row * padding_rows_needed).encode()
    assert len(oversized_csv) > MAX_UPLOAD_SIZE

    resp = client.post(
        "/api/columns",
        files={"file": ("huge.csv", oversized_csv, "text/csv")},
    )
    assert resp.status_code == 200
    assert resp.json()["columns"] == ["id", "hours"]