import axios from "axios";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || "http://localhost:8000";

export async function compareFiles(attendanceFile, clientFile) {
  const formData = new FormData();
  formData.append("attendance_file", attendanceFile);
  formData.append("client_file", clientFile);

  const response = await axios.post(`${API_BASE_URL}/api/compare`, formData);
  return response.data;
}

export function getReportDownloadUrl(reportId) {
  return `${API_BASE_URL}/api/reports/${reportId}/download`;
}