import { SEVERITY_LABELS } from "../utils/formatters.js";

export default function SeverityBadge({ severity }) {
  return (
    <span className={`severity-badge severity-badge--${severity}`}>
      {SEVERITY_LABELS[severity] || severity}
    </span>
  );
}
