import { getReportDownloadUrl } from "../api/compareApi.js";

/**
 * Shown only after a successful comparison produced a downloadable report.
 */
export default function DownloadReportButton({ reportId }) {
  if (!reportId) return null;

  return (
    <a
      className="download-report-btn"
      href={getReportDownloadUrl(reportId)}
      download
    >
      ↓ Download Excel Report
    </a>
  );
}
