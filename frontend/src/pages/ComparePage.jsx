import { useState } from "react";
import FileUploader from "../components/FileUploader";
import SummaryCards from "../components/SummaryCards";
import MismatchTable from "../components/MismatchTable";
import DownloadReportButton from "../components/DownloadReportButton";
import { compareFiles } from "../api/compareApi";

export default function ComparePage() {
  const [attendanceFile, setAttendanceFile] = useState(null);
  const [clientFile, setClientFile] = useState(null);
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const canCompare = attendanceFile && clientFile && !loading;

  async function handleCompare() {
    console.log("Files being sent:", attendanceFile, clientFile);
    setLoading(true);
    setError(null);
    try {
      const data = await compareFiles(attendanceFile, clientFile);
      setResult(data);
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
      setLoading(false);
    }
  }

  return (
    <div className="page">
      <h1>Attendance vs Client Work Comparison</h1>

      <div className="upload-row">
        <FileUploader
          label="Company Attendance Sheet"
          file={attendanceFile}
          onFileSelected={setAttendanceFile}
        />
        <FileUploader
          label="Client Work Sheet"
          file={clientFile}
          onFileSelected={setClientFile}
        />
      </div>

      <button className="compare-btn" disabled={!canCompare} onClick={handleCompare}>
        {loading ? "Comparing…" : "Compare Files"}
      </button>

      {error && <p className="error-text">{error}</p>}

      {result && (
        <>
          <SummaryCards summary={result.summary} />
          <DownloadReportButton filename={result.report_id} />
          <MismatchTable mismatches={result.mismatches} />
        </>
      )}
    </div>
  );
}