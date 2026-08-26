import SeverityBadge from "./SeverityBadge.jsx";
import { formatHours } from "../utils/formatters.js";

/**
 * Results detail view.
 *
 * Rows are GROUPED for scannability — hour differences, missing employees on
 * either side, and records needing manual review — using only fields the
 * comparison already produced (company_hours / client_hours presence). No
 * data is recomputed or changed here.
 */

function categoryOf(m) {
  const hasAtt = m.company_hours !== null && m.company_hours !== undefined;
  const hasCli = m.client_hours !== null && m.client_hours !== undefined;
  if (hasAtt && hasCli) return "hours";
  if (hasAtt) return "missing-client"; // attendance exists, client record absent
  if (hasCli) return "missing-attendance"; // client record exists, attendance absent
  return "review"; // neither side usable (e.g. conflicting duplicate totals)
}

const GROUPS = [
  {
    key: "hours",
    title: "Hour differences",
    description: "Found in both files with different Total Hours",
  },
  {
    key: "missing-attendance",
    title: "Missing from iLink Attendance",
    description: "In the Client Worksheet only",
  },
  {
    key: "missing-client",
    title: "Missing from Client Worksheet",
    description: "In iLink Attendance only",
  },
  {
    key: "review",
    title: "Needs manual review",
    description: "Could not be compared automatically",
  },
];

const CheckIcon = () => (
  <svg
    width="22"
    height="22"
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    strokeWidth="2"
    strokeLinecap="round"
    strokeLinejoin="round"
    aria-hidden="true"
  >
    <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14" />
    <polyline points="22 4 12 14.01 9 11.01" />
  </svg>
);

function ResultRows({ rows }) {
  return (
    <tbody>
      {rows.map((m, i) => (
        <tr key={`${m.employee_id}-${i}`}>
          <td>
            <div className="cell-main">{m.employee_name || "—"}</div>
            <div className="cell-sub">{m.employee_id}</div>
          </td>
          <td className="num">{formatHours(m.company_hours)}</td>
          <td className="num">{formatHours(m.client_hours)}</td>
          <td>
            <SeverityBadge severity={m.severity} />
          </td>
          <td className="reason-cell">{m.reason}</td>
        </tr>
      ))}
    </tbody>
  );
}

export default function MismatchTable({ mismatches, summary }) {
  if (!mismatches) return null;

  // Polished success state when everything reconciles.
  if (mismatches.length === 0) {
    return (
      <div className="empty-state" role="status">
        <div className="empty-state__icon" aria-hidden="true">
          <CheckIcon />
        </div>
        <h3>All records reconciled</h3>
        <p>No mismatches found — every employee's hours match across both files.</p>
        {summary && (
          <p className="empty-state__meta">
            {summary.total_records_compared} records compared · {summary.matches} matched
          </p>
        )}
      </div>
    );
  }

  return (
    <div>
      {GROUPS.map((group) => {
        const rows = mismatches.filter((m) => categoryOf(m) === group.key);
        if (rows.length === 0) return null; // only show groups that have records

        return (
          <section key={group.key} className="result-group">
            <div className="result-group__head">
              <h3 className="result-group__title">{group.title}</h3>
              <span className="result-group__count">
                {rows.length} {rows.length === 1 ? "record" : "records"}
              </span>
              <span className="result-group__desc">{group.description}</span>
            </div>
            {/* Scroll container keeps large datasets manageable while the
                header row stays visible. */}
            <div className="table-scroll">
              <table className="mismatch-table">
                <thead>
                  <tr>
                    <th>Employee</th>
                    <th className="num">Company Hrs</th>
                    <th className="num">Client Hrs</th>
                    <th>Severity</th>
                    <th>Reason</th>
                  </tr>
                </thead>
                <ResultRows rows={rows} />
              </table>
            </div>
          </section>
        );
      })}
    </div>
  );
}