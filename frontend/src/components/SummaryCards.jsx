export default function SummaryCards({ summary }) {
  if (!summary) return null;

  const cards = [
    { label: "Total Compared", value: summary.total_records_compared },
    { label: "Matches", value: summary.matches, tone: "good" },
    { label: "Mismatches", value: summary.mismatches, tone: "bad" },
  ];

  return (
    <div className="summary-cards">
      {cards.map((c) => (
        <div key={c.label} className={`summary-card summary-card--${c.tone || "neutral"}`}>
          <div className="summary-card__value">{c.value}</div>
          <div className="summary-card__label">{c.label}</div>
        </div>
      ))}
    </div>
  );
}