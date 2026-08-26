/**
 * Dropdown listing the columns detected in one uploaded Excel file.
 * The selected column becomes that dataset's primary matching attribute.
 */
export default function ColumnSelector({
  id,
  label = "Primary Identifier",
  columns = [],
  value = "",
  onChange,
  disabled = false,
  loading = false,
  error = null,
}) {
  return (
    <div className="column-selector">
      <label className="column-selector__label" htmlFor={`${id}-key-column`}>
        {label}
      </label>
      <select
        id={`${id}-key-column`}
        value={value}
        disabled={disabled || loading || columns.length === 0}
        onChange={(event) => onChange(event.target.value)}
      >
        <option value="">Select Column</option>
        {columns.map((column) => (
          <option key={column} value={column}>
            {column}
          </option>
        ))}
      </select>
      {loading && <div className="column-selector__hint">Reading columns…</div>}
      {!loading && !disabled && columns.length === 0 && !error && (
        <div className="column-selector__hint">No columns detected.</div>
      )}
      {error && <div className="column-selector__error">{error}</div>}
    </div>
  );
}