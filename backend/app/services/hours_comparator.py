"""
Deterministic Total Hours comparison.

Employees are matched on the normalized values of the user-selected primary
identifier columns (shared with the LLM path via llm_comparator), then each
employee's already-calculated Total Hours number is compared DIRECTLY.
No LLM is involved: hours are never identified, calculated, combined, or summed
by a model — values are read as-is from the detected numeric column, kept
unchanged, and compared numerically. Blank identifier rows never join anything;
each becomes its own record so every employee stays accounted for.

Duplicate identifiers are accepted, never rejected: every row sharing one
normalized identifier is folded into that ONE employee/entity. Identical
duplicate rows are copies of the same data and count once; if duplicate rows
disagree on the provided Total Hours, the conflict surfaces as a single
review record for that identifier — totals are never summed, averaged,
silently chosen, or otherwise altered.
"""
from __future__ import annotations

import uuid

from .excel_loader import _as_number, _is_missing
from .llm_comparator import _employee_key


class ComparisonError(ValueError):
    """Raised when the input structure cannot support a direct comparison."""


def _display_identifier(record: dict, key_column: str) -> str:
    raw = record.get(key_column)
    if _is_missing(raw):
        return ""
    return str(raw).strip()


def _display_name(record: dict) -> str:
    """Best-effort human name for reports (display only — never used to match)."""
    for col in record:
        if "name" in str(col).lower():
            raw = record.get(col)
            if not _is_missing(raw):
                return str(raw).strip()
    return ""


def _fmt(value) -> str:
    """Format a number without trailing zeros: 184 -> '184', 128.5 -> '128.5'."""
    return f"{value:g}"


def _fold_provided_total(entry: dict, raw_hours) -> None:
    """Accumulate one duplicate row's provided Total Hours into the single
    entity already indexed for its identifier.

    - Blank cells contribute nothing (and are never treated as zero).
    - A value numerically equal to one already recorded (so 40, '40' and
      40.0 all agree) is a duplicate COPY of the same data: ignored —
      nothing is ever summed.
    - A genuinely DIFFERENT value marks the entity's total as conflicted:
      the usable total is withdrawn (set to None) rather than picking a
      winner, and every distinct provided value is retained so results can
      show exactly what the source rows contain. No hour value is changed
      or invented here.
    """
    if _is_missing(raw_hours):
        return
    number = _as_number(raw_hours)
    for prior_number, _ in entry["provided_totals"]:
        if prior_number == number:
            return
    entry["provided_totals"].append((number, _plain(raw_hours)))
    if len(entry["provided_totals"]) == 1:
        entry["raw_hours"] = _plain(raw_hours)
        entry["hours"] = number
    else:
        entry["raw_hours"] = None
        entry["hours"] = None
        entry["hours_conflict"] = True


def _index_employees(records, key_column, hours_column, label) -> dict:
    """Group rows by normalized identifier into ONE entity per identifier.
    Rows repeating an identifier are folded together instead of being
    rejected: identical duplicate rows are copies of the same employee and
    count once, while conflicting duplicate totals blank the usable value
    and raise the ``hours_conflict`` flag for the caller to report. Each
    entity keeps its ORIGINAL hours value untouched plus a float view for
    arithmetic. Rows with a blank identifier keep a positional fallback so
    results can always identify them."""
    employees: dict = {}
    for pos, record in enumerate(records, start=1):
        key = _employee_key(record, key_column)
        if key:
            dict_key = key
        else:
            # Blank identifiers NEVER join anything — including other blank
            # rows in the opposite file — hence the unique synthetic key.
            dict_key = f"_blank_{label}_{pos}_{uuid.uuid4().hex}"
        entry = employees.get(dict_key)
        if entry is None:
            entry = {
                "id": _display_identifier(record, key_column),
                "fallback_id": "",
                "name": _display_name(record),
                "rows": [],
                "raw_hours": None,
                "hours": None,
                "hours_conflict": False,
                "provided_totals": [],
            }
            employees[dict_key] = entry
        else:
            # Same normalized identifier as an earlier row: still ONE
            # employee/entity — fold this row in rather than erroring.
            if not entry["id"]:
                entry["id"] = _display_identifier(record, key_column)
            if not entry["name"]:
                entry["name"] = _display_name(record)
        entry["rows"].append(pos)
        _fold_provided_total(entry, record.get(hours_column))

    for entry in employees.values():
        rows = entry["rows"]
        entry["fallback_id"] = (
            f"(row {rows[0]})" if len(rows) == 1
            else f"(rows {', '.join(str(r) for r in rows)})"
        )
    return employees


def _duplicate_conflict_note(entry: dict, label: str) -> str:
    """Human explanation of one side's duplicated, conflicting totals."""
    rows = ", ".join(str(r) for r in entry["rows"])
    values = ", ".join(_fmt(number) for number, _ in entry["provided_totals"])
    return (
        f"{label} lists this identifier on rows {rows} with conflicting "
        f"Total Hours values ({values}); the rows are treated as ONE "
        f"employee and their totals were neither summed nor guessed."
    )

def _mismatch(employee_id, employee_name, company_hours, client_hours,
              status, severity, reason, recommendation) -> dict:
    return {
        "employee_id": employee_id,
        "employee_name": employee_name,
        "company_attendance_status": status,
        "company_hours": company_hours,
        "client_hours": client_hours,
        "classification": "MISMATCH",
        "severity": severity,
        "reason": reason,
        "recommendation": recommendation,
    }


def compare_records(att_records, cli_records, att_key_column, cli_key_column,
                    att_hours_column, cli_hours_column) -> dict:
    """Match employees via selected identifier columns and compare their
    provided Total Hours values directly. The response shape is identical to
    the previous LLM-based result, so downstream consumers are unaffected.
    Duplicate identifiers inside either input are ONE employee/entity (see
    ``_index_employees``): identical copies count once and conflicting
    totals surface as a single review record per identifier."""
    att = _index_employees(att_records, att_key_column, att_hours_column,
                           "iLink Attendance")
    cli = _index_employees(cli_records, cli_key_column, cli_hours_column,
                           "Client Worksheet")

    mismatches: list[dict] = []
    matches = 0
    high = 0

    for key, a in att.items():
        b = cli.get(key)

        # Duplicated identifier whose rows disagree on the provided Total
        # Hours: report it EXACTLY ONCE for manual reconciliation instead of
        # comparing an arbitrarily chosen value or creating extra records.
        if a["hours_conflict"] or (b is not None and b["hours_conflict"]):
            parts = []
            if a["hours_conflict"]:
                parts.append(_duplicate_conflict_note(a, "iLink Attendance"))
            elif a["hours"] is None:
                parts.append("iLink Attendance provides no Total Hours "
                             "value for this identifier.")
            else:
                parts.append(f"iLink Attendance reports a single total of "
                             f"{_fmt(a['hours'])}.")
            if b is not None and b["hours_conflict"]:
                parts.append(_duplicate_conflict_note(b, "Client Worksheet"))
            elif b is None:
                parts.append("No Client Worksheet record exists for this "
                             "identifier.")
            elif b["hours"] is None:
                parts.append("The Client Worksheet provides no Total Hours "
                             "value for this identifier.")
            else:
                parts.append(f"The Client Worksheet reports a single total "
                             f"of {_fmt(b['hours'])}.")
            high += 1
            mismatches.append(_mismatch(
                a["id"] or (b["id"] if b is not None else "") or a["fallback_id"],
                a["name"] or (b["name"] if b is not None else ""),
                None if a["hours_conflict"] else a["raw_hours"],
                None if (b is None or b["hours_conflict"]) else b["raw_hours"],
                "Present", "HIGH",
                "; ".join(parts) + " Manual reconciliation required.",
                "Reconcile the duplicated rows to a single Total Hours value "
                "in the source file, then re-run the comparison."))
            continue

        if b is None:
            total = (f"(total {_fmt(a['hours'])})" if a["hours"] is not None
                     else "(total hours value missing)")
            mismatches.append(_mismatch(
                a["id"] or a["fallback_id"], a["name"],
                a["raw_hours"], None, "Present", "MEDIUM",
                f"Employee present only in iLink Attendance {total}; "
                "no Client Worksheet record.",
                "Confirm whether work was performed but not recorded for the "
                "client."))
            continue

        if a["hours"] is None or b["hours"] is None:
            missing_side = ("iLink Attendance" if a["hours"] is None
                            else "Client Worksheet")
            mismatches.append(_mismatch(
                a["id"] or b["id"] or a["fallback_id"] or b["fallback_id"],
                a["name"] or b["name"],
                a["raw_hours"], b["raw_hours"], "Present", "LOW",
                f"Matched employee but the total-hours value is missing in "
                f"{missing_side}; treated as missing, not zero.",
                f"Obtain the missing {missing_side} total for this employee."))
            continue

        if a["hours"] == b["hours"]:
            matches += 1
            continue

        difference = abs(a["hours"] - b["hours"])
        higher = "Client Worksheet" if b["hours"] > a["hours"] else "iLink Attendance"
        severity = "HIGH" if b["hours"] > a["hours"] else "MEDIUM"
        if severity == "HIGH":
            high += 1
        mismatches.append(_mismatch(
            a["id"], a["name"], a["raw_hours"], b["raw_hours"], "Present",
            severity,
            f"iLink total {_fmt(a['hours'])} vs Client total "
            f"{_fmt(b['hours'])} - difference {_fmt(difference)} "
            f"({higher} higher).",
            "Reconcile the logged hours against the source records."))

    for key, b in cli.items():
        if key in att:
            continue
        if b["hours_conflict"]:
            # Conflicting duplicate rows on the client-only side: one review
            # record for this identifier — never separate employees.
            high += 1
            mismatches.append(_mismatch(
                b["id"] or b["fallback_id"], b["name"], None, None,
                "Missing", "HIGH",
                _duplicate_conflict_note(b, "Client Worksheet")
                + " No iLink Attendance record exists for this identifier.",
                "Reconcile the duplicated rows to a single Total Hours value, "
                "confirm the client time entry is authorised and the "
                "employee's iLink attendance is complete."))
            continue
        total = (f"(total {_fmt(b['hours'])})" if b["hours"] is not None
                 else "(total hours value missing)")
        high += 1
        mismatches.append(_mismatch(
            b["id"] or b["fallback_id"], b["name"], None, b["raw_hours"],
            "Missing", "HIGH",
            f"Employee present only in Client Worksheet {total}; "
            "no iLink Attendance record.",
            "Confirm whether the client time entry is authorised and the "
            "employee's iLink attendance is complete."))

    return {
        "summary": {
            "total_records_compared": matches + len(mismatches),
            "matches": matches,
            "mismatches": len(mismatches),
            "review_required": high,
        },
        "mismatches": mismatches,
    }


def _plain(value):
    """Convert NumPy scalars (CSV type inference) to plain Python numbers so
    downstream JSON/Excel serialization keeps working."""
    return value.item() if hasattr(value, "item") else value


def datasets_equivalent(att_records, cli_records, att_key_column, cli_key_column) -> bool:
    """True when both uploads carry the SAME employee records — same row
    count and an identical multiset of normalized identifier values — i.e.
    two copies of one dataset rather than two independent sources."""
    if len(att_records) != len(cli_records):
        return False
    att_keys = [_employee_key(r, att_key_column) for r in att_records]
    cli_keys = [_employee_key(r, cli_key_column) for r in cli_records]
    return sorted(att_keys) == sorted(cli_keys)


def compare_within_file(records, key_column, hours_col1, hours_col2) -> dict:
    """Same-dataset mode: the two uploads are copies of ONE dataset whose
    table carries TWO Total Hours columns. Compare those two columns against
    each other for every record of the single dataset — the files are not
    treated as separate employee sources. Duplicate identifiers are folded
    into ONE record here as well: identical duplicate rows evaluate once,
    and rows disagreeing on a Total Hours column produce a single review
    record instead of multiple entries (values are never summed or
    invented). Identifier/name information is preserved so any difference is
    clearly attributable."""
    # Group rows by normalized identifier, preserving sheet order. Rows with
    # a blank identifier stay singleton groups (they never join anything).
    groups: dict = {}
    for pos, record in enumerate(records, start=1):
        key = _employee_key(record, key_column)
        if key:
            dict_key = key
        else:
            dict_key = f"_blank_row_{pos}_{uuid.uuid4().hex}"
        group = groups.get(dict_key)
        if group is None:
            group = {"id": "", "name": "", "rows": [], "records": []}
            groups[dict_key] = group
        if not group["id"]:
            group["id"] = _display_identifier(record, key_column)
        if not group["name"]:
            group["name"] = _display_name(record)
        group["rows"].append(pos)
        group["records"].append(record)

    mismatches: list[dict] = []
    matches = 0
    high = 0

    for group in groups.values():
        rows = group["rows"]
        employee_id = group["id"] or (
            f"(row {rows[0]})" if len(rows) == 1
            else f"(rows {', '.join(str(r) for r in rows)})"
        )
        employee_name = group["name"]

        # Fold each Total Hours column across the group's rows: identical
        # copies collapse into one value; genuinely different values withdraw
        # to None and get flagged — never summed, averaged or replaced.
        states: list[dict] = []
        for col in (hours_col1, hours_col2):
            provided: list = []
            for record in group["records"]:
                raw = record.get(col)
                if _is_missing(raw):
                    continue  # blank contributes nothing; never treated as zero
                number = _as_number(raw)
                if any(prior == number for prior, _ in provided):
                    continue  # duplicate copy of an already-recorded value
                provided.append((number, _plain(raw)))
            if len(provided) == 1:
                states.append({"raw": provided[0][1], "value": provided[0][0],
                               "conflict": False})
            elif len(provided) > 1:
                states.append({"raw": None, "value": None, "conflict": True,
                               "values": [n for n, _ in provided]})
            else:
                states.append({"raw": None, "value": None, "conflict": False})
        s1, s2 = states
        raws = [s["raw"] for s in states]
        v1, v2 = s1["value"], s2["value"]

        if s1["conflict"] or s2["conflict"]:
            detail = "; ".join(
                f"'{col}' has conflicting values "
                f"({', '.join(_fmt(n) for n in s['values'])})"
                for col, s in zip((hours_col1, hours_col2), states)
                if s["conflict"]
            )
            conflicted_cols = ", ".join(
                str(col) for col, s in zip((hours_col1, hours_col2), states)
                if s["conflict"]
            )
            high += 1
            mismatches.append({
                "employee_id": employee_id,
                "employee_name": employee_name,
                "company_attendance_status": "Present",
                "company_hours": raws[0],
                "client_hours": raws[1],
                "classification": "MISMATCH",
                "severity": "HIGH",
                "reason": f"Duplicate rows share this identifier ({detail}); "
                          f"they were evaluated once as a single record with "
                          f"no values summed or invented.",
                "recommendation": f"Reconcile the duplicated rows to one value "
                                  f"per column ({conflicted_cols}).",
            })
            continue

        if v1 is None or v2 is None:
            missing_col = hours_col1 if v1 is None else hours_col2
            mismatches.append({
                "employee_id": employee_id,
                "employee_name": employee_name,
                "company_attendance_status": "Present",
                "company_hours": raws[0],
                "reason": f"Record matched, but the total-hours value is "
                          f"missing in column '{missing_col}'.",
                "recommendation": f"Fill in the missing '{missing_col}' value.",
            })
            continue

        if v1 == v2:
            matches += 1
            continue

        difference = abs(v1 - v2)
        higher = hours_col2 if v2 > v1 else hours_col1
        severity = "HIGH" if v2 > v1 else "MEDIUM"
        if severity == "HIGH":
            high += 1
        mismatches.append({
            "employee_id": employee_id,
            "employee_name": employee_name,
            "company_attendance_status": "Present",
            "company_hours": raws[0],
            "client_hours": raws[1],
            "classification": "MISMATCH",
            "severity": severity,
            "reason": f"'{hours_col1}' {_fmt(v1)} vs '{hours_col2}' "
                      f"{_fmt(v2)} - difference {_fmt(difference)} "
                      f"('{higher}' higher).",
            "recommendation": "Reconcile the two total-hours values against "
                              "the source records.",
        })

    return {
        "summary": {
            "total_records_compared": matches + len(mismatches),
            "matches": matches,
            "mismatches": len(mismatches),
            "review_required": high,
        },
        "mismatches": mismatches,
    }