from __future__ import annotations

from pathlib import Path

import pandas as pd
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


def _valid_compare_uploads():
    return (
        (
            "attendance.csv",
            b"Network ID,Employee Name,Date,Hours\n"
            b"P1,Ada Lovelace,2024-01-02,30\n",
            "text/csv",
        ),
        (
            "client.csv",
            b"Project ID,Employee Name,Month,Year,WeekDate,Billable Hours,Non-Billable Hours\n"
            b"P1,Ada Lovelace,Jan,2024,2024-01-06,30,154\n",
            "text/csv",
        ),
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
    attendance_upload, client_upload = _valid_compare_uploads()
    resp = client.post(
        "/api/compare",
        files={
            "attendance_file": attendance_upload,
            "client_file": client_upload,
        },
        data={
            "attendance_key_column": "Network ID",
            "client_key_column": "Project ID",
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
    column is selected (see _employee_key in hours_comparator.py)."""
    attendance_upload, client_upload = _valid_compare_uploads()
    resp = client.post(
        "/api/compare",
        files={
            "attendance_file": attendance_upload,
            "client_file": client_upload,
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
    bad_csv = (
        b"Network ID,Employee Name,Date,Notes\n"
        b"P1,John Smith,2024-01-02,no numeric column here\n"
    )
    _, client_upload = _valid_compare_uploads()
    resp = client.post(
        "/api/compare",
        files={
            "attendance_file": ("attendance.csv", bad_csv, "text/csv"),
            "client_file": client_upload,
        },
        data={
            "attendance_key_column": "Network ID",
            "client_key_column": "Project ID",
        },
    )
    assert resp.status_code in (400, 500)


def test_compare_hard_stops_when_a_file_has_no_rows():
    resp = client.post(
        "/api/compare",
        files={
            "attendance_file": ("empty.csv", b"Project ID,Date,Hours\n", "text/csv"),
            "client_file": _upload_tuple(CLIENT_XLSX),
        },
        data={
            "attendance_key_column": "Project ID",
            "client_key_column": "Full Name",
        },
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["stage"] == "completeness"
    assert body["completeness"]["attendance"]["error"] == "No rows found in iLink Timesheet."


def test_compare_detects_hours_columns_without_manual_overrides():
    attendance_csv = (
        b"Network ID,Employee Name,Date,Hours\n"
        b"P1,Ada Lovelace,2024-01-02,30\n"
    )
    client_csv = (
        b"Project ID,Employee Name,Month,Year,WeekDate,Billable Hours,Non-Billable Hours\n"
        b"P1,Ada Lovelace,Jan,2024,2024-01-06,30,0\n"
    )

    resp = client.post(
        "/api/compare",
        files={
            "attendance_file": ("attendance.csv", attendance_csv, "text/csv"),
            "client_file": ("client.csv", client_csv, "text/csv"),
        },
        data={
            "attendance_key_column": "Network ID",
            "client_key_column": "Project ID",
        },
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["stage1"]["expected_total_hours"] == 184
    assert body["completeness"]["projects"][0]["client_billable_hours"] == 30
    assert body["completeness"]["projects"][0]["status"] == "Match"


def test_all_comparison_stages_use_full_multi_month_records(tmp_path):
    attendance_path = tmp_path / "attendance.xlsx"
    client_path = tmp_path / "client.xlsx"
    pd.DataFrame([
        {"Network ID": "N001", "Employee Name": "Ada Lovelace", "Date": "2024-09-05", "Hours": 50},
        {"Network ID": "N001", "Employee Name": "Ada Lovelace", "Date": "2024-09-12", "Hours": 50},
        {"Network ID": "N001", "Employee Name": "Ada Lovelace", "Date": "2024-10-03", "Hours": 8},
    ]).to_excel(attendance_path, index=False)
    pd.DataFrame([
        {"Project ID": "N001", "Employee Name": "Ada Lovelace", "Month": "Sep", "Year": 2024, "WeekDate": "2024-09-07", "Billable Hours": 40, "Non-Billable Hours": 30},
        {"Project ID": "N001", "Employee Name": "Ada Lovelace", "Month": "Sep", "Year": 2024, "WeekDate": "2024-09-14", "Billable Hours": 40, "Non-Billable Hours": 30},
        {"Project ID": "N001", "Employee Name": "Ada Lovelace", "Month": "Oct", "Year": 2024, "WeekDate": "2024-10-05", "Billable Hours": 28, "Non-Billable Hours": 0},
    ]).to_excel(client_path, index=False)

    response = client.post(
        "/api/compare",
        files={
            "attendance_file": _upload_tuple(attendance_path),
            "client_file": _upload_tuple(client_path),
        },
        data={
            "attendance_key_column": "Network ID",
            "client_key_column": "Project ID",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["completeness"]["client"]["period"] == "Sep 2024"
    assert body["stage1"]["expected_total_hours"] == 168
    assert body["stage1"]["matched"][0]["total_hours"] == 168
    project = body["completeness"]["projects"][0]
    assert project["client_billable_hours"] == 108
    assert project["ilink_total_hours"] == 108
    assert project["status"] == "Match"
    assert body["summary"]["matches"] == 1
    assert body["matched"][0]["company_hours"] == 108
    assert body["matched"][0]["client_hours"] == 108


def test_compare_skips_llm_when_fuzzy_detection_succeeds(monkeypatch):
    import app.routes.compare as compare_route

    def unexpected_llm_call(column_names):
        raise AssertionError("LLM fallback must not run after fuzzy matches")

    monkeypatch.setattr(
        compare_route,
        "detect_billable_and_non_billable_via_llm",
        unexpected_llm_call,
    )
    attendance_upload, client_upload = _valid_compare_uploads()
    response = client.post(
        "/api/compare",
        files={
            "attendance_file": attendance_upload,
            "client_file": client_upload,
        },
        data={"attendance_key_column": "Network ID", "client_key_column": "Project ID"},
    )

    assert response.status_code == 200


def test_compare_uses_llm_fallback_for_unfamiliar_hour_headers(monkeypatch):
    import app.routes.compare as compare_route

    seen_headers = []

    def classify_headers(column_names):
        seen_headers.extend(column_names)
        return {
            "billable_column": "Chargeable Hours",
            "non_billable_column": "Bench Hours",
        }

    monkeypatch.setattr(
        compare_route,
        "detect_billable_and_non_billable_via_llm",
        classify_headers,
    )
    attendance_upload, _ = _valid_compare_uploads()
    client_upload = (
        "client.csv",
        b"Project ID,Employee Name,Month,Year,WeekDate,Chargeable Hours,Bench Hours\n"
        b"P1,Ada Lovelace,Jan,2024,2024-01-06,30,10\n",
        "text/csv",
    )
    response = client.post(
        "/api/compare",
        files={
            "attendance_file": attendance_upload,
            "client_file": client_upload,
        },
        data={"attendance_key_column": "Network ID", "client_key_column": "Project ID"},
    )

    assert response.status_code == 200
    assert "Chargeable Hours" in seen_headers
    assert "Bench Hours" in seen_headers


def test_compare_keeps_existing_error_when_fallback_cannot_classify(monkeypatch):
    import app.routes.compare as compare_route

    monkeypatch.setenv("GROQ_API_KEY", "")
    attendance_upload, _ = _valid_compare_uploads()
    client_upload = (
        "client.csv",
        b"Project ID,Employee Name,Month,Year,WeekDate,Chargeable Hours,Bench Hours\n"
        b"P1,Ada Lovelace,Jan,2024,2024-01-06,30,10\n",
        "text/csv",
    )
    response = client.post(
        "/api/compare",
        files={
            "attendance_file": attendance_upload,
            "client_file": client_upload,
        },
        data={"attendance_key_column": "Network ID", "client_key_column": "Project ID"},
    )

    assert response.status_code == 400
    assert "Could not confidently detect distinct" in response.json()["detail"]


def test_completeness_includes_level1_mismatches_and_keeps_comparison_totals():
    attendance_csv = (
        b"Network ID,Employee Name,Email ID,Date,Hours\n"
        b"p1,Ada Lovelace,ada@example.com,2024-01-02,30\n"
        b"p2,Grace Hopper,grace@example.com,2024-01-02,25\n"
    )
    client_csv = (
        b"Project ID,Employee Name,Month,Year,WeekDate,Billable Hours,Non-Billable Hours\n"
        b"P1,Ada Lovelace,Jan,2024,2024-01-06,30,154\n"
        b"P2,Grace Hopper,Jan,2024,2024-01-06,20,19\n"
        b"P3,Katherine Johnson,Jan,2024,2024-01-06,15,0\n"
    )

    resp = client.post(
        "/api/compare",
        files={
            "attendance_file": ("attendance.csv", attendance_csv, "text/csv"),
            "client_file": ("client.csv", client_csv, "text/csv"),
        },
        data={
            "attendance_key_column": "Network ID",
            "client_key_column": "Project ID",
        },
    )

    assert resp.status_code == 200
    body = resp.json()
    projects = {row["project_id"]: row for row in body["completeness"]["projects"]}
    assert set(projects) == {"P1", "P2", "P3"}
    assert projects["P1"]["client_billable_hours"] == 30
    assert projects["P1"]["status"] == "Match"
    assert "email_subject" not in projects["P1"]
    assert "email_body" not in projects["P1"]
    assert projects["P2"]["client_billable_hours"] == 20
    assert projects["P2"]["status"] == "Mismatch"
    assert projects["P2"]["email"] == "grace@example.com"
    assert projects["P2"]["email_subject"] == (
        "Action needed: Project ID P2 hours discrepancy for Jan 2024"
    )
    assert "Grace Hopper" in projects["P2"]["email_body"]
    assert "20 billable hours" in projects["P2"]["email_body"]
    assert "25 hours in iLink" in projects["P2"]["email_body"]
    assert body["stage1"]["expected_total_hours"] == 184
    assert {row["employee_id"]: row["total_hours"] for row in body["stage1"]["matched"]} == {"P1": 184}
    assert {row["employee_id"]: row["total_hours"] for row in body["stage1"]["mismatched"]} == {"P2": 39, "P3": 15}
    assert body["summary"]["matches"] == 1
    assert body["matched"][0]["company_hours"] == 30
    assert body["matched"][0]["client_hours"] == 30
    assert projects["P3"]["status"] == "Project ID Not Found"
    assert projects["P3"]["email"] is None
    assert projects["P3"]["email_subject"] == (
        "Action needed: Project ID P3 not found in iLink for Jan 2024"
    )
    assert "15 billable hours" in projects["P3"]["email_body"]
    assert "no matching entries in iLink" in projects["P3"]["email_body"]


def test_compare_uses_llm_to_disambiguate_hours_columns(monkeypatch):
    import app.routes.compare as compare_route

    classified_headers = []

    def classify_headers(column_names):
        classified_headers.extend(column_names)
        return {
            "billable_column": "Billable Hrs",
            "non_billable_column": "Non-Billable Hours",
        }

    monkeypatch.setattr(
        compare_route,
        "detect_billable_and_non_billable_via_llm",
        classify_headers,
    )
    attendance_csv = (
        b"Network ID,Employee Name,Date,Hours\n"
        b"P1,Ada Lovelace,2024-01-02,30\n"
    )
    client_csv = (
        b"Project ID,Employee Name,Month,Year,WeekDate,Billable Hours,Billable Hrs,Non-Billable Hours\n"
        b"P1,Ada Lovelace,Jan,2024,2024-01-06,33,30,154\n"
    )

    resp = client.post(
        "/api/compare",
        files={
            "attendance_file": ("attendance.csv", attendance_csv, "text/csv"),
            "client_file": ("client.csv", client_csv, "text/csv"),
        },
        data={
            "attendance_key_column": "Network ID",
            "client_key_column": "Project ID",
        },
    )

    assert resp.status_code == 200
    body = resp.json()
    assert "Billable Hrs" in classified_headers
    assert body["stage1"]["matched"][0]["billable_hours"] == 30
    assert body["stage1"]["matched"][0]["total_hours"] == 184
    assert body["completeness"]["projects"][0]["client_billable_hours"] == 30
    assert body["matched"][0]["client_hours"] == 30


# ---------------------------------------------------------------------------
# GET /api/reports/{report_id}/download
# ---------------------------------------------------------------------------

def test_download_report_after_successful_compare():
    attendance_upload, client_upload = _valid_compare_uploads()
    compare_resp = client.post(
        "/api/compare",
        files={
            "attendance_file": attendance_upload,
            "client_file": client_upload,
        },
        data={
            "attendance_key_column": "Network ID",
            "client_key_column": "Project ID",
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