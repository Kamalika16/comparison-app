import { getReportDownloadUrl } from "../api/compareApi.js";

export default function DownloadReportButton({ filename }) {
  if (!filename) return null;

  return (
    <a className="download-report-btn" href={getReportDownloadUrl(filename)} download>
      Download Excel Report
    </a>
  );
}
