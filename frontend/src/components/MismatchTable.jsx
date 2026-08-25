export default function MismatchTable({ mismatches }) {
  if (!mismatches || mismatches.length === 0) {
    return <p className="empty-state">No mismatches found — everything reconciles.</p>;
  }

  return (
    <table className="mismatch-table">
      <thead>
        <tr>
          <th>Employee</th>
          <th>Company Hrs</th>
          <th>Client Hrs</th>
          <th>Reason</th>
        </tr>
      </thead>
      <tbody>
        {mismatches.map((m, i) => (
          <tr key={`${m.employee_id}-${i}`}>
            <td>
              <div>{m.employee_name}</div>
              <div className="muted">{m.employee_id}</div>
            </td>
            <td>{m.company_hours ?? "—"}</td>
            <td>{m.client_hours ?? "—"}</td>
            <td className="reason-cell">{m.reason}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}