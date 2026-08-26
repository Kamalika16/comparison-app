from pathlib import Path

import pandas as pd


def _read_table(path: str, sheet=0) -> pd.DataFrame:
    """Read an Excel sheet or a CSV file into a DataFrame."""
    if Path(path).suffix.lower() == ".csv":
        return pd.read_csv(path)
    return pd.read_excel(path, sheet_name=sheet, dtype=object)


def _clean_frame(df: pd.DataFrame) -> pd.DataFrame:
    df = df.dropna(how="all")                 # drop fully empty rows
    df = df.dropna(axis=1, how="all")          # drop fully empty columns
    df = df.loc[:, ~df.columns.astype(str).str.startswith("Unnamed")]
    for col in df.columns:
        df[col] = df[col].apply(
            lambda v: v.strftime("%Y-%m-%d") if hasattr(v, "strftime") else v
        )
    return df


def load_records(path: str, sheet=0) -> list[dict]:
    """Read an Excel sheet or a CSV file into a list of plain dicts, column
    names untouched. No interpretation happens here."""
    df = _clean_frame(_read_table(path, sheet))
    return df.to_dict(orient="records")


def get_columns(path: str, sheet=0) -> list[str]:
    """Return the column headers of an Excel sheet or CSV file, using the
    same cleaning rules as load_records (fully empty rows/columns and unnamed
    ghost columns are dropped) so callers see exactly the keys the loaded
    records will have."""
    df = _clean_frame(_read_table(path, sheet))
    return [str(col) for col in df.columns]


def _is_missing(value) -> bool:
    """True for None / NaN / NaT / blank-string cells."""
    if value is None:
        return True
    if isinstance(value, float) and value != value:  # NaN
        return True
    if isinstance(value, str) and not value.strip():
        return True
    try:
        return bool(pd.isna(value))
    except (TypeError, ValueError):
        return False


def _as_number(value) -> float:
    """Return the value as a float if it is a plain number or a cleanly
    parseable numeric string; raise ValueError otherwise."""
    if isinstance(value, bool):
        raise ValueError("boolean is not numeric")
    if isinstance(value, str):
        number = float(value.strip())
    else:
        # int/float and NumPy scalars (CSV type inference produces these)
        number = float(value)
    if number != number:  # NaN
        raise ValueError("NaN is not a usable number")
    return number


def find_numeric_columns(records: list[dict], exclude: list[str] | None = None) -> list[str]:
    """All columns (in sheet order) whose every non-blank cell is a number or
    a cleanly parseable numeric string, with at least one such cell. Column
    NAMES are never inspected."""
    excluded = set(exclude or [])
    candidates: list[str] = []
    if not records:
        return candidates
    for col in records[0].keys():
        if col in excluded:
            continue
        saw_value = False
        fully_numeric = True
        for record in records:
            value = record.get(col)
            if _is_missing(value):
                continue
            saw_value = True
            try:
                _as_number(value)
            except (ValueError, TypeError):
                fully_numeric = False
                break
        if saw_value and fully_numeric:
            candidates.append(col)
    return candidates


def detect_hours_column(records: list[dict], exclude: list[str] | None = None) -> str:
    """Detect the single fully numeric Total Hours column in a loaded sheet
    or CSV table.

    A column qualifies when every non-blank cell is a number (or a cleanly
    parseable numeric string) and at least one such cell exists. Column NAMES
    are never inspected, so any header works ('Total', 'Hrs', 'Grand Total',
    ...). ``exclude`` lets callers filter out the primary identifier column so
    a numeric ID column can never be mistaken for hours.

    Returns the column name. Raises ValueError when zero or more than one
    column qualifies, so callers never have to guess."""
    if not records:
        raise ValueError("Cannot detect a hours column: the dataset has no rows.")

    candidates = find_numeric_columns(records, exclude)

    if len(candidates) == 1:
        return candidates[0]
    if not candidates:
        raise ValueError(
            "No fully numeric Total Hours column was found "
            "(no column contains only numbers)."
        )
    raise ValueError(
        f"Expected exactly one numeric Total Hours column but found "
        f"{len(candidates)}: {', '.join(map(str, candidates))}."
    )