# Attendance Comparison App

Compares an **attendance export** against a **client work log** (both Excel/CSV),
automatically maps mismatched column headers between the two files, normalizes
names/dates/hours, and flags discrepancies using a 9-rule engine. Produces both
an interactive results table in the browser and a downloadable, color-coded
Excel report.

## Project layout

```
attendance-comparison-app/
├── backend/    FastAPI service (comparison engine, Excel report generation)
└── frontend/   React + Vite single-page app
```

## Prerequisites

- Python 3.10+
- Node.js 18+
- npm

## Backend setup

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env             # adjust values if needed
uvicorn app.main:app --reload --port 8000
```

The API will be available at `http://localhost:8000`. Interactive docs at
`http://localhost:8000/docs`.

Run the test suite:

```bash
pytest
```

## Frontend setup

In a separate terminal:

```bash
cd frontend
npm install
cp .env.example .env             # points VITE_API_BASE_URL at the backend
npm run dev
```

The app will be available at `http://localhost:5173`.

## How the comparison works

1. **Upload** — user provides an attendance file and a client-work file
   (`.xlsx`, `.xls`, or `.csv`).
2. **Column mapping** (`app/services/column_mapper.py`) — fuzzy-matches each
   file's headers to canonical fields (`employee_name`, `date`, `hours`, ...)
   so the two files don't need identical column names.
3. **Normalization** (`app/services/normalizers.py`) — standardizes employee
   names, dates (→ ISO `YYYY-MM-DD`), and hours (→ decimal hours), handling
   formats like `"Last, First"`, `"1/5/2024"`, `"8h 30m"`, and time ranges.
4. **Rule engine** (`app/services/rules_engine.py`) — for every
   `(employee, date)` pair found in either file, applies Rules 1–9 in order
   (exact match, minor/major variance, missing records on either side,
   zero-vs-nonzero anomalies, duplicate entries, weekend work, malformed
   rows) to assign a severity and explanation.
5. **Report** (`app/services/report_writer.py`) — writes a two-sheet,
   color-coded `.xlsx` report (Summary + Details) to `backend/outputs/`,
   available for download via `GET /api/reports/{filename}`.

## API

### `POST /api/compare`

Multipart form fields: `attendance_file`, `client_work_file`.

Returns JSON: `{ summary, rows[], report_filename }` (see
`backend/app/models/schemas.py` for the full shape).

### `GET /api/reports/{filename}`

Downloads the generated Excel report.

## Configuration

See `backend/.env.example` and `frontend/.env.example` for tunable settings
(upload size limits, CORS origins, column-matching threshold, hour
discrepancy tolerances, API base URL).

## Sample data

`backend/tests/fixtures/sample_attendance.xlsx` and
`sample_client_work.xlsx` contain small sample datasets (with deliberately
mismatched column headers) you can use to try the app end-to-end.
