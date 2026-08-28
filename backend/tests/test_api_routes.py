"""
API-layer automation tests.

Unlike test_hours_comparator.py (which calls service functions directly),
these tests go through the real HTTP surface: FastAPI's TestClient drives
actual requests through CORS middleware, multipart parsing, routing, and
the route handlers in app/routes/compare.py exactly as a real client would.

/api/compare now always routes through compare_via_llm() (see
app/routes/compare.py). These tests mock that function rather than calling
the real Groq API, on purpose:

  * LLM output is not guaranteed identical between runs, so real calls make
    assertions flaky in a way that has nothing to do with whether our code
    is correct.
  * Real calls cost tokens and are subject to rate limits -- undesirable on
    every push/PR in CI (see .github/workflows/tests.yml, which does not
    provide a GROQ_API_KEY).
  * These tests exist to verify OUR code -- upload handling, validation,
    temp-file cleanup, report generation, the download endpoint -- not to
    verify Groq's model quality.

A small number of tests near the bottom are marked as live integration
tests and are skipped unless GROQ_API_KEY is set, so you can still run a
real end-to-end check by hand when you want one.

No live server or network access is required for the mocked tests. Run with:

    cd backend
    source .venv/bin/activate      # or your own venv
    pytest tests/test_api_routes.py -v
"""
from __future__ import annotations

import io
import os
from pathlib import Path
from unittest.mock import patch

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


# A fixed, known-good response standing in for whatever compare_via_llm()
# would normally return. Matches the schema report_writer.write_report()
# and the frontend both expect: summary + mismatches, each mismatch using
# company_hours / client_hours (never invented -- None when a side has no
# record, exactly like the real comparator's contract).
FAKE_LLM_RESULT = {
    "summary": {
        "total_records_compared": 3,
        "matches": 1,
        "mismatches": 2,
    },
    "mismatches": [
        {
            "id": "H285491",
            "name": "Abdul Hakeem Habeeb Rahman",
            "company_hours": 176,
            "client_hours": 72,
            "classification": "Hours mismatch",
            "severity": "HIGH",
            "reason": "iLink total 176 vs Client total 72 - difference 104",
            "recommendation": "Reconcile the logged hours with the client.",
        },
        {
            "id": "H324723",
            "name": "Abbas Ali Pathan",
            "company_hours": 29.7,
            "client_hours": None,
            "classification": "Only in iLink Attendance",
            "severity": "MEDIUM",
            "reason": "Employee present only in iLink Attendance (total 29.7).",
            "recommendation": "Confirm whether work was billed to the client.",
        },
    ],
}


def _mock_compare_via_llm(*args, **kwargs):
    return FAKE_LLM_RESULT


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
# POST /api/compare -- LLM path, compare_via_llm() mocked out (see module
# docstring for why). These tests verify OUR route/plumbing code: request
# handling, response shape, report generation, cleanup -- not the model.
# ---------------------------------------------------------------------------

@patch("app.routes.compare.compare_via_llm", side_effect=_mock_compare_via_llm)
def test_compare_happy_path_returns_report_id(mock_llm):
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
    summary = body["summary"]
    mismatch_count = len(body["mismatches"])
    assert summary["mismatches"] == mismatch_count
    if "total_records_compared" in summary:
        assert summary["matches"] + summary["mismatches"] == summary["total_records_compared"]

    for m in body["mismatches"]:
        assert m["severity"] in {"HIGH", "MEDIUM", "LOW"}

    # Confirm we actually went through the (mocked) LLM path, not some
    # other code path, and that the route passed the key columns through.
    mock_llm.assert_called_once()
    _, kwargs = mock_llm.call_args
    assert kwargs["attendance_key_column"] == "Employee Name"
    assert kwargs["client_key_column"] == "Full Name"


@patch("app.routes.compare.compare_via_llm", side_effect=_mock_compare_via_llm)
def test_compare_works_without_key_columns_too(mock_llm):
    """The LLM path doesn't require key columns to be pre-selected -- it can
    be called with neither, unlike the old deterministic path."""
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


@patch("app.routes.compare.compare_via_llm", side_effect=_mock_compare_via_llm)
def test_compare_rejects_disallowed_extension_on_either_file(mock_llm):
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
    mock_llm.assert_not_called()


@patch("app.routes.compare.compare_via_llm", side_effect=_mock_compare_via_llm)
def test_compare_cleans_up_temp_uploads_after_request(mock_llm):
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


@patch(
    "app.routes.compare.compare_via_llm",
    side_effect=lambda *a, **k: {"unexpected": "shape"},
)
def test_compare_rejects_malformed_llm_response(mock_llm):
    """If the LLM (or whatever's standing in for it) returns JSON that
    doesn't have the summary/mismatches shape we need, the route must fail
    loudly with a 502 rather than silently passing garbage to the report
    writer or the frontend."""
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
    assert resp.status_code == 502


# ---------------------------------------------------------------------------
# GET /api/reports/{report_id}/download
# ---------------------------------------------------------------------------

@patch("app.routes.compare.compare_via_llm", side_effect=_mock_compare_via_llm)
def test_download_report_after_successful_compare(mock_llm):
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


# ---------------------------------------------------------------------------
# Live integration test -- hits the REAL Groq API. Skipped by default; only
# runs if you explicitly set GROQ_API_KEY in your shell before running
# pytest. Use this by hand occasionally to sanity-check the real
# integration; do not rely on it in CI (costs tokens, rate-limited, and
# GROQ_API_KEY is intentionally not configured in
# .github/workflows/tests.yml).
# ---------------------------------------------------------------------------

@pytest.mark.skipif(
    not os.getenv("GROQ_API_KEY"),
    reason="GROQ_API_KEY not set -- skipping real Groq API call",
)
def test_compare_real_llm_integration_smoke_test():
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