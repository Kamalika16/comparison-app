from __future__ import annotations

from collections import Counter
import uuid

from .excel_loader import _as_number, _is_missing
from .llm_comparator import _employee_key


class ComparisonError(ValueError):
    """Raised when two datasets cannot be compared (e.g. missing key column)."""

def _display_identifier(record: dict, key_column: str) -> str:
    raw = record.get(key_column)
    if _is_missing(raw):
        return ""
    return str(raw).strip()


def _display_name(record: dict, label: str = "", key_column: str = "") -> str:
    """Get a display name without using it as a comparison key."""
    normalized_columns = {
        "".join(char for char in str(column).lower() if char.isalnum()): column
        for column in record
    }

    if label == "iLink Attendance":
        first_column = normalized_columns.get("firstname")
        last_column = normalized_columns.get("lastname")
        if first_column or last_column:
            parts = [
                record.get(column)
                for column in (first_column, last_column)
                if column and not _is_missing(record.get(column))
            ]
            if parts:
                return " ".join(str(part).strip() for part in parts)

    if label == "Client Worksheet":
        row_labels_column = normalized_columns.get("rowlabels")
        if row_labels_column and not _is_missing(record.get(row_labels_column)):
            return str(record[row_labels_column]).strip()

    for column in record:
        if column == key_column:
            continue
        if "name" in str(column).lower():
            raw = record.get(column)
            if not _is_missing(raw):
                return str(raw).strip()
    return ""


def _fmt(value) -> str:
    
    return f"{value:g}"

def _fold_provided_total(entry: dict, raw_hours, sum_mode: bool = False) -> None:
    
    if _is_missing(raw_hours):
        return
    try:
        number = _as_number(raw_hours)
    except (TypeError, ValueError):
        return

    if sum_mode:
        entry["provided_totals"].append((number, _plain(raw_hours)))
        entry["hours"] = (entry["hours"] or 0) + number
        entry["raw_hours"] = _fmt(entry["hours"])
        return

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

def _index_employees(records, key_column, hours_column, label, sum_hours: bool = False,
                     allowed_keys: set[str] | None = None,
                     skip_blank: bool = False) -> dict:
    
    employees: dict = {}
    for pos, record in enumerate(records, start=1):
        key = _employee_key(record, key_column)
        if skip_blank and not key:
            continue
        if allowed_keys is not None and key not in allowed_keys:
            continue
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
                "name": "",
                "name_counts": Counter(),
                "name_values": {},
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
        display_name = _display_name(record, label, key_column)
        if display_name:
            name_key = display_name.casefold()
            entry["name_counts"][name_key] += 1
            entry["name_values"][name_key] = display_name
        entry["rows"].append(pos)
        _fold_provided_total(entry, record.get(hours_column),sum_mode=sum_hours)

    for entry in employees.values():
        if entry["name_counts"]:
            name_key, _ = entry["name_counts"].most_common(1)[0]
            entry["name"] = entry["name_values"][name_key]
        rows = entry["rows"]
        entry["fallback_id"] = (
            f"(row {rows[0]})" if len(rows) == 1
            else f"(rows {', '.join(str(r) for r in rows)})"
        )
    return employees


def _result_row(employee_id, employee_name, file1_hours, file2_hours,
                status, severity, reason, recommendation) -> dict:
    difference = (
        round(file1_hours - file2_hours, 2)
        if file1_hours is not None and file2_hours is not None
        else None
    )
    return {
        "id": employee_id,
        "file1_total_hours": file1_hours,
        "file2_hours": file2_hours,
        "difference": difference,
        "status": status,
        "ID": employee_id,
        "File1_TotalHours": file1_hours,
        "File2_Hours": file2_hours,
        "Difference": difference,
        "Status": status,
        "employee_id": employee_id,
        "employee_name": employee_name,
        "company_hours": file1_hours,
        "client_hours": file2_hours,
        "company_attendance_status": "Present" if file1_hours is not None else "Missing",
        "classification": "MATCH" if status == "Match" else "MISMATCH",
        "severity": severity,
        "reason": reason,
        "recommendation": recommendation,
    }

def compare_records(att_records, cli_records, att_key_column, cli_key_column,
                    att_hours_column, cli_hours_column,
                    file1_label="iLink Timesheet", file2_label="Client") -> dict:
    """Aggregate File 1 by its selected ID, then join the result to File 2."""
    client_ids = {
        key for record in cli_records
        if (key := _employee_key(record, cli_key_column))
    }
    att = _index_employees(
        att_records,
        att_key_column,
        att_hours_column,
        "iLink Attendance",
        sum_hours=True,
        allowed_keys=client_ids,
        skip_blank=True,
    )
    cli = _index_employees(
        cli_records,
        cli_key_column,
        cli_hours_column,
        "Client Worksheet",
        sum_hours=True,
        skip_blank=True,
    )

    mismatches: list[dict] = []
    matched: list[dict] = []
    matches = 0
    high = 0

    for key in list(att) + [key for key in cli if key not in att]:
        a = att.get(key)
        b = cli.get(key)
        entry = a or b
        employee_id = entry["id"] or entry["fallback_id"]
        employee_name = (a or {}).get("name") or (b or {}).get("name", "")
        file1_hours = None if a is None or a["hours_conflict"] else a["hours"]
        file2_hours = None if b is None or b["hours_conflict"] else b["hours"]

        if a is None:
            high += 1
            mismatches.append(_result_row(
                employee_id, employee_name, None, file2_hours,
                f"Missing in {file1_label}", "HIGH",
                f"ID exists in {file2_label} but not in {file1_label}.",
                f"Confirm the {file2_label} entry and the source attendance records."))
            continue
        if b is None:
            mismatches.append(_result_row(
                employee_id, employee_name, file1_hours, None,
                f"Missing in {file2_label}", "MEDIUM",
                f"ID exists in {file1_label} but not in {file2_label}.",
                f"Confirm whether the {file2_label} entry is missing."))
            continue
        if a["hours_conflict"] or b["hours_conflict"] or file1_hours is None or file2_hours is None:
            high += 1
            mismatches.append(_result_row(
                employee_id, employee_name, file1_hours, file2_hours,
                "Mismatch", "HIGH",
                "Hours could not be compared because a selected hours value is conflicting or missing.",
                "Reconcile the hours values in the source files."))
            continue
        if file1_hours == file2_hours:
            matches += 1
            matched.append(_result_row(
                employee_id, employee_name, file1_hours, file2_hours,
                "Match", "MATCH", "Hours match.", ""))
            continue

        difference = abs(file1_hours - file2_hours)
        severity = "HIGH" if file2_hours > file1_hours else "MEDIUM"
        if severity == "HIGH":
            high += 1
        higher_side = file2_label if file2_hours > file1_hours else file1_label
        mismatches.append(_result_row(
            employee_id, employee_name, file1_hours, file2_hours,
            "Mismatch", severity,
            f"{file1_label} total {_fmt(file1_hours)} vs {file2_label} total {_fmt(file2_hours)} - "
            f"difference {_fmt(difference)} ({higher_side} higher).",
            "Reconcile the logged hours against the source records."))

    only_attendance = set(att) - set(cli)
    only_client = set(cli) - set(att)
    print(
        "Comparison counts: "
        f"raw File 1 rows={len(att_records)}, "
        f"valid common IDs={len(set(att) & set(cli))}, "
        f"aggregated File 1 IDs={len(att)}, "
        f"File 2 IDs={len(cli)}, "
        f"matched IDs={matches}, "
        f"mismatched IDs={len(mismatches)}, "
        f"only in File 1={len(only_attendance)}, "
        f"only in File 2={len(only_client)}"
    )

    return {
        "summary": {
            "total_records_compared": matches + len(mismatches),
            "matches": matches,
            "mismatches": len(mismatches),
            "review_required": high,
        },
        "mismatches": mismatches,
        "matched": matched,
    }

def _plain(value):
    """Convert NumPy scalars (CSV type inference) to plain Python numbers so
    downstream JSON/Excel serialization keeps working."""
    return value.item() if hasattr(value, "item") else value


def datasets_equivalent(att_records, cli_records, att_key_column, cli_key_column) -> bool:
    
    if len(att_records) != len(cli_records):
        return False
    att_keys = [_employee_key(r, att_key_column) for r in att_records]
    cli_keys = [_employee_key(r, cli_key_column) for r in cli_records]
    return sorted(att_keys) == sorted(cli_keys)


def compare_within_file(records, key_column, hours_col1, hours_col2) -> dict:
    
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