import difflib
import re
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


# Phrases that genuinely mean "this is the hours total we want". Matched
# fuzzily (see _hours_name_score) so real-world typos and casing variants
# ("Bilable Hours", "TOTAL HRS") still hit, without hardcoding exact strings.
_HOURS_POSITIVE_HINTS = [
    "billable hours", "total hours", "hours worked", "worked hours",
    "hours", "hrs", "total hrs",
]

# Standalone words that mark a column as hour-shaped but NOT the one we
# want by default (non-billable/overtime hours, etc). Checked as whole
# words (not substrings) so it still catches misspelled neighbors --
# "Non-Bilable Hours" is flagged by the word "non" alone, regardless of
# how "billable" itself is spelled.
_HOURS_NEGATIVE_WORDS = {"non", "unbillable", "overtime", "ot"}


def _hours_name_score(column_name) -> float:
    """Fuzzy 0-1 score for how likely this column name refers to the hours
    total we want, tolerant of typos/casing/extra words ('Bilable Hours'
    still scores high against 'billable hours'). Column names unrelated to
    hours (dates, IDs, costs, per-weekday breakdowns) score near 0."""
    normalized = re.sub(r"[^a-z0-9]+", " ", str(column_name).lower()).strip()
    if not normalized:
        return 0.0

    best = 0.0
    for hint in _HOURS_POSITIVE_HINTS:
        ratio = difflib.SequenceMatcher(None, normalized, hint).ratio()
        best = max(best, ratio)
    # Reward a direct "hour(s)"/"hrs" substring even inside a longer/odd
    # header (e.g. "Total Work Hours (Approved)").
    if re.search(r"\bhours?\b|\bhrs\b", normalized):
        best = max(best, 0.7)

    if set(normalized.split()) & _HOURS_NEGATIVE_WORDS:
        best *= 0.5

    return best


# A name match needs at least this much fuzzy confidence to be trusted...
_HOURS_NAME_MIN_SCORE = 0.6
# ...and needs to lead the next-best candidate by at least this much, so a
# genuine tie (two equally hour-ish names) still falls through to asking
# the user rather than guessing between them.
_HOURS_NAME_MIN_LEAD = 0.15


def detect_hours_column(records: list[dict], exclude: list[str] | None = None) -> str:
    """Detect the Total Hours column in a loaded sheet or CSV table.

    A column is a numeric CANDIDATE when every non-blank cell is a number
    (or a cleanly parseable numeric string) and at least one such cell
    exists. ``exclude`` lets callers filter out the primary identifier
    column so a numeric ID column can never be mistaken for hours.

    - Exactly one numeric candidate: use it (column name is irrelevant --
      any header works, e.g. a lone "Grand Total" column).
    - Multiple numeric candidates (common on real client files: per-weekday
      totals, rate, cost, billable/non-billable splits, etc.): fall back to
      fuzzy-matching each candidate's NAME against known "hours" phrasing
      and pick the clear winner, if there is one.
    - Zero candidates, or multiple candidates with no confident/clear
      name match: raise ValueError so the caller surfaces this to the user
      to choose manually, rather than silently guessing."""
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

    scored = sorted(
        ((col, _hours_name_score(col)) for col in candidates),
        key=lambda pair: pair[1],
        reverse=True,
    )
    best_col, best_score = scored[0]
    runner_up_score = scored[1][1] if len(scored) > 1 else 0.0

    if (
        best_score >= _HOURS_NAME_MIN_SCORE
        and best_score - runner_up_score >= _HOURS_NAME_MIN_LEAD
    ):
        return best_col

    raise ValueError(
        f"Expected exactly one numeric Total Hours column but found "
        f"{len(candidates)}: {', '.join(map(str, candidates))}."
    )