export function formatHours(value) {
  if (value === null || value === undefined) return "—";
  return `${Number(value).toFixed(2)}h`;
}

export function formatDate(isoDate) {
  if (!isoDate) return "—";
  const d = new Date(`${isoDate}T00:00:00`);
  if (Number.isNaN(d.getTime())) return isoDate;
  return d.toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

export const SEVERITY_LABELS = {
  match: "Match",
  minor: "Minor Mismatch",
  major: "Major Mismatch",
  missing_attendance: "Missing Attendance",
  missing_client_work: "Missing Client Work",
  review: "Needs Review",
};
