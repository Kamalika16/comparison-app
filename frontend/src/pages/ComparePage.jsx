import { useRef, useState } from "react";
import FileUploader from "../components/FileUploader";
import ColumnSelector from "../components/ColumnSelector";
import SummaryCards from "../components/SummaryCards";
import MismatchTable from "../components/MismatchTable";
import DownloadReportButton from "../components/DownloadReportButton";
import {
  API_BASE_URL,
  compareFiles,
  fetchColumns,
} from "../api/compareApi";

export default function ComparePage() {
  const [attendanceFile, setAttendanceFile] = useState(null);
  const [clientFile, setClientFile] = useState(null);
  const [attendanceColumns, setAttendanceColumns] = useState([]);
  const [clientColumns, setClientColumns] = useState([]);
  const [attendanceKeyColumn, setAttendanceKeyColumn] = useState("");
  const [clientKeyColumn, setClientKeyColumn] = useState("");
  const [readingColumns, setReadingColumns] = useState({
    attendance: false,
    client: false,
  });
  const [columnsError, setColumnsError] = useState({
    attendance: null,
    client: null,
  });
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  // Latest selected file per side; lets the async column reader detect
  // when a file was replaced while its request was still in flight.
  const attendanceFileRef = useRef(null);
  const clientFileRef = useRef(null);

  // Synchronous guards: block duplicate Compare clicks before state updates
  // propagate, and let us discard responses whose inputs changed mid-run.
  const comparingRef = useRef(false);
  const inputsRef = useRef({});
  inputsRef.current = {
    attendanceFile,
    clientFile,
    attendanceKeyColumn,
    clientKeyColumn,
  };

  // Columns must be detected on both sides before comparing is possible.
  const columnsDetected =
    attendanceColumns.length > 0 && clientColumns.length > 0;

  // Compare stays disabled until both files are uploaded, their columns
  // are detected, and one matching column is selected for each file.
  const canCompare =
    Boolean(attendanceFile) &&
    Boolean(clientFile) &&
    columnsDetected &&
    Boolean(attendanceKeyColumn) &&
    Boolean(clientKeyColumn) &&
    !loading;

  async function detectColumns(file, side) {
    const setColumns =
      side === "attendance" ? setAttendanceColumns : setClientColumns;
    const fileRef = side === "attendance" ? attendanceFileRef : clientFileRef;

    setReadingColumns((prev) => ({ ...prev, [side]: true }));
    setColumnsError((prev) => ({ ...prev, [side]: null }));

    try {
      const columns = await fetchColumns(file);
      if (fileRef.current !== file) return; // file replaced mid-request; discard
      setColumns(columns);
    } catch (err) {
      if (fileRef.current !== file) return; // file replaced mid-request; discard
      let detail = err.response?.data?.detail;
      if (!err.response) {
        // No HTTP response at all: the backend is unreachable.
        detail =
          `Cannot reach the comparison service at ${API_BASE_URL}. ` +
          "Start the backend (uvicorn app.main:app) and try again.";
      }
      setColumnsError((prev) => ({
        ...prev,
        [side]:
          typeof detail === "string"
            ? detail
            : `Could not read columns from "${file.name}".`,
      }));
      setColumns([]);
    } finally {
      setReadingColumns((prev) => ({ ...prev, [side]: false }));
    }
  }

  function handleFileSelected(side, file) {
    const setFile = side === "attendance" ? setAttendanceFile : setClientFile;
    const setColumns =
      side === "attendance" ? setAttendanceColumns : setClientColumns;
    const setKeyColumn =
      side === "attendance" ? setAttendanceKeyColumn : setClientKeyColumn;
    const fileRef = side === "attendance" ? attendanceFileRef : clientFileRef;

    fileRef.current = file;
    setFile(file);
    setColumns([]); // re-read columns for the newly selected file
    setKeyColumn(""); // reset stale/invalid selection
    setResult(null); // previous results no longer apply to the new file
    setError(null);

    detectColumns(file, side);
  }

  async function handleCompare() {
    if (comparingRef.current || !canCompare) return; // prevent duplicate processing
    comparingRef.current = true;

    setLoading(true);
    setError(null);

    const snapshot = { ...inputsRef.current };

    try {
      const data = await compareFiles(
        attendanceFile,
        clientFile,
        attendanceKeyColumn,
        clientKeyColumn
      );
      // Discard the response if any input changed while we were running.
      const now = inputsRef.current;
      const stale =
        now.attendanceFile !== snapshot.attendanceFile ||
        now.clientFile !== snapshot.clientFile ||
        now.attendanceKeyColumn !== snapshot.attendanceKeyColumn ||
        now.clientKeyColumn !== snapshot.clientKeyColumn;
      if (!stale) setResult(data);
    } catch (err) {
      const detail = err.response?.data?.detail;
      let message = "Something went wrong comparing the files.";
      if (typeof detail === "string") {
        message = detail;
      } else if (Array.isArray(detail)) {
        message = detail.map((d) => d.msg).join("; ");
      }
      setError(message);
    } finally {
      comparingRef.current = false;
      setLoading(false);
    }
  }

  // Human-readable list of everything still missing before Compare can run.
  function validationMessage() {
    const items = [];
    if (!attendanceFile) items.push("upload the iLink Attendance file");
    else if (attendanceColumns.length > 0 && !attendanceKeyColumn)
      items.push("select the primary identifier column for iLink Attendance");
    if (!clientFile) items.push("upload the Client Worksheet file");
    else if (clientColumns.length > 0 && !clientKeyColumn)
      items.push("select the primary identifier column for Client Worksheet");
    if (columnsError.attendance)
      items.push("iLink Attendance columns could not be read - choose the file again");
    if (columnsError.client)
      items.push("Client Worksheet columns could not be read - choose the file again");
    if (!items.length) return "";
    return `To run the comparison: ${items.join("; ")}.`;
  }

  return (
    <div className="app-shell">
      <header className="app-header">
        <h1>iLink Attendance vs Client Worksheet</h1>
        <p>
          Upload both Excel files, pick the column that identifies employees in
          each, then compare working hours.
        </p>
      </header>

      {/* One card per input source: each file's uploader and its primary
          identifier dropdown stay together — side by side on desktop,
          stacked vertically on smaller screens. */}
      <section className="upload-section" aria-label="Input files">
        <div className="upload-panel">
          <FileUploader
            label="iLink Attendance"
            file={attendanceFile}
            onFileSelected={(file) => handleFileSelected("attendance", file)}
          />
          <div className="upload-panel__divider" aria-hidden="true" />
          <ColumnSelector
            id="attendance"
            columns={attendanceColumns}
            value={attendanceKeyColumn}
            onChange={(value) => {
              setAttendanceKeyColumn(value);
              setResult(null); // results no longer match the new selection
              setError(null);
            }}
            disabled={!attendanceFile}
            loading={readingColumns.attendance}
            error={columnsError.attendance}
          />
        </div>

        <div className="upload-panel">
          <FileUploader
            label="Client Worksheet"
            file={clientFile}
            onFileSelected={(file) => handleFileSelected("client", file)}
          />
          <div className="upload-panel__divider" aria-hidden="true" />
          <ColumnSelector
            id="client"
            columns={clientColumns}
            value={clientKeyColumn}
            onChange={(value) => {
              setClientKeyColumn(value);
              setResult(null); // results no longer match the new selection
              setError(null);
            }}
            disabled={!clientFile}
            loading={readingColumns.client}
            error={columnsError.client}
          />
        </div>
      </section>

      {/* Single prominent action directly below the input cards */}
      <div className="compare-actions">
        <button
          className="btn btn--primary btn--lg"
          disabled={!canCompare}
          onClick={handleCompare}
          aria-busy={loading}
        >
          {loading && <span className="spinner" aria-hidden="true" />}
          {loading ? "Comparing…" : "Compare Files"}
        </button>
      </div>

      {loading && (
        <div className="alert alert--info" role="status">
          <span className="spinner" aria-hidden="true" />
          <span>Processing both datasets using the selected identifiers…</span>
        </div>
      )}

      {!loading && !canCompare && validationMessage() && (
        <div className="alert alert--warning" role="status">
          {validationMessage()}
        </div>
      )}

      {error && (
        <div className="alert alert--error" role="alert">
          <strong>Error:</strong>&nbsp;{error}
        </div>
      )}

      {result && (
        <section className="results-section" aria-label="Comparison results">
          {!loading && (
            <div className="alert alert--success" role="status">
              Comparison completed successfully.
            </div>
          )}

          <div className="results-header">
            <div>
              <h2>Results</h2>
              <p className="results-subtitle">
                {result.summary.total_records_compared} employee records compared ·{" "}
                {result.summary.matches} matched ·{" "}
                {result.summary.mismatches} need attention
              </p>
            </div>
            {/* Download sits beside the results heading as a secondary action */}
            <DownloadReportButton reportId={result.report_id} />
          </div>

          <SummaryCards summary={result.summary} />
          <MismatchTable mismatches={result.mismatches} summary={result.summary} />
        </section>
      )}
    </div>
  );
}