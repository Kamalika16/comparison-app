import axios from "axios";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || "http://localhost:8000";

export { API_BASE_URL };

/** Ask the backend to read an uploaded Excel file and return its columns. */
export async function fetchColumns(file) {
  const formData = new FormData();
  formData.append("file", file);

  const response = await axios.post(`${API_BASE_URL}/api/columns`, formData);
  return response.data.columns;
}

export async function compareFiles(
  attendanceFile,
  clientFile,
  attendanceKeyColumn,
  clientKeyColumn
) {
  const formData = new FormData();
  formData.append("attendance_file", attendanceFile);
  formData.append("client_file", clientFile);
  if (attendanceKeyColumn) {
    formData.append("attendance_key_column", attendanceKeyColumn);
  }
  if (clientKeyColumn) {
    formData.append("client_key_column", clientKeyColumn);
  }

  const response = await axios.post(`${API_BASE_URL}/api/compare`, formData);
  return response.data;
}

export function getReportDownloadUrl(reportId) {
  return `${API_BASE_URL}/api/reports/${reportId}/download`;
}