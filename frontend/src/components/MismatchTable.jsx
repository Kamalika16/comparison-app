import { formatHours } from "../utils/formatters.js";

/**
 * Results detail view.
 *
 * Displays the already-computed ID join result without recomputing totals.
 */

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
        <tr key={`${m.id}-${i}`}>
          <td>{m.employee_name || ""}</td>
          <td>{m.id}</td>
          <td className="num">{formatHours(m.file1_total_hours)}</td>
          <td className="num">{formatHours(m.file2_hours)}</td>
          <td className="num">{formatHours(m.difference)}</td>
          <td>{m.status}</td>
          <td>{m.reason || ""}</td>
        </tr>
      ))}
    </tbody>
  );
}

export default function MismatchTable({ rows, summary, clientName = "Client" }) {
  if (!rows) return null;

  // Polished success state when everything reconciles.
  if (rows.length === 0) {
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
    <section className="result-group">
      <div className="result-group__head">
        <h3 className="result-group__title">Comparison</h3>
        <span className="result-group__count">{rows.length} records</span>
      </div>
      <div className="table-scroll">
        <table className="mismatch-table">
          <thead>
            <tr>
              <th>Employee Name</th>
              <th>ID</th>
              <th className="num">iLink Timesheet Hours</th>
              <th className="num">{clientName} Hours</th>
              <th className="num">Difference</th>
              <th>Status</th>
              <th>Reason</th>
            </tr>
          </thead>
          <ResultRows rows={rows} />
        </table>
      </div>
    </section>
  );
}