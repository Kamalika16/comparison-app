"""Regression tests for duplicate-identifier handling in the deterministic
Total Hours comparison.

Every row sharing one normalized selected primary identifier must be treated
as ONE employee/entity: represented at most once in the comparison results,
never rejected with a duplicate error, and its provided Total Hours values
must never be summed or replaced with invented ones.
"""
import pandas as pd

from app.services.excel_loader import detect_hours_column, load_records
from app.services.hours_comparator import compare_records, compare_within_file


ATT_KEY = "Emp ID"
CLI_KEY = "Client ID"
HOURS = "Total Hours"


def _ids(result) -> list:
    return [m["employee_id"] for m in result["mismatches"]]


class TestDuplicateIdenticalData:
    def test_duplicate_rows_are_one_employee(self):
        att = [
            {ATT_KEY: "E001", "Employee Name": "Ann Lee", HOURS: 40},
            {ATT_KEY: "E001", "Employee Name": "Ann Lee", HOURS: 40},
            {ATT_KEY: "E002", "Employee Name": "Ben Ortiz", HOURS: 35},
        ]
        cli = [
            {CLI_KEY: "E001", "Employee Name": "Ann Lee", HOURS: 38},
            {CLI_KEY: "E002", "Employee Name": "Ben Ortiz", HOURS: 35},
        ]
        result = compare_records(att, cli, ATT_KEY, CLI_KEY, HOURS, HOURS)

        assert result["summary"] == {
            "total_records_compared": 2,
            "matches": 1,
            "mismatches": 1,
            "review_required": 0,
        }
        assert _ids(result) == ["E001"]  # E001 appears exactly once
        m = result["mismatches"][0]
        assert m["company_hours"] == 40  # original value, unmodified
        assert m["client_hours"] == 38
        assert m["severity"] == "MEDIUM"


class TestDuplicateSameHours:
    def test_identical_duplicates_match_cleanly(self):
        att = [
            {ATT_KEY: "E100", "Employee Name": "Cara Cole", HOURS: 40},
            {ATT_KEY: "e100", "Employee Name": "CARA COLE", HOURS: 40.0},
        ]
        cli = [{CLI_KEY: "E100", "Employee Name": "Cara Cole", HOURS: "40"}]
        result = compare_records(att, cli, ATT_KEY, CLI_KEY, HOURS, HOURS)

        assert result["summary"]["total_records_compared"] == 1
        assert result["summary"]["matches"] == 1
        assert result["summary"]["mismatches"] == 0
        assert result["mismatches"] == []


class TestDuplicateConflictingHours:
    def test_conflicting_totals_yield_single_review_record(self):
        att = [
            {ATT_KEY: "E200", "Employee Name": "Dana Fox", HOURS: 40},
            {ATT_KEY: "E200", "Employee Name": "Dana Fox", HOURS: 32},
        ]
        cli = [{CLI_KEY: "E200", "Employee Name": "Dana Fox", HOURS: 36}]
        result = compare_records(att, cli, ATT_KEY, CLI_KEY, HOURS, HOURS)

        assert len(result["mismatches"]) == 1  # one record, not two
        m = result["mismatches"][0]
        assert m["severity"] == "HIGH"
        assert m["company_hours"] is None  # no value silently chosen
        assert m["client_hours"] == 36
        assert "40" in m["reason"] and "32" in m["reason"]
        assert "72" not in m["reason"]  # totals were NOT summed
        assert result["summary"]["mismatches"] == 1
        assert result["summary"]["review_required"] == 1

    def test_conflicts_on_both_sides_reported_once(self):
        att = [
            {ATT_KEY: "E201", "Employee Name": "Evan Gray", HOURS: 40},
            {ATT_KEY: "E201", "Employee Name": "Evan Gray", HOURS: 32},
        ]
        cli = [
            {CLI_KEY: "E201", "Employee Name": "Evan Gray", HOURS: 36},
            {CLI_KEY: "E201", "Employee Name": "Evan Gray", HOURS: 30},
        ]
        result = compare_records(att, cli, ATT_KEY, CLI_KEY, HOURS, HOURS)

        assert len(result["mismatches"]) == 1
        m = result["mismatches"][0]
        assert m["company_hours"] is None and m["client_hours"] is None
        for value in ("40", "32", "36", "30"):
            assert value in m["reason"]
        assert result["summary"]["mismatches"] == 1

    def test_blank_duplicate_row_uses_the_provided_value(self):
        # A blank Total Hours cell adds no information: it is neither a
        # conflict nor a zero, so the single provided value stands.
        att = [
            {ATT_KEY: "E202", "Employee Name": "Fay Hale", HOURS: None},
            {ATT_KEY: "E202", "Employee Name": "Fay Hale", HOURS: 24},
        ]
        cli = [{CLI_KEY: "E202", "Employee Name": "Fay Hale", HOURS: 24}]
        result = compare_records(att, cli, ATT_KEY, CLI_KEY, HOURS, HOURS)

        assert result["summary"]["matches"] == 1
        assert result["mismatches"] == []


class TestEachIdentifierOnce:
    def test_mixed_files_list_every_identifier_exactly_once(self):
        att = [
            {ATT_KEY: "A", "Employee Name": "A", HOURS: 10},
            {ATT_KEY: "B", "Employee Name": "B", HOURS: 20},
            {ATT_KEY: "B", "Employee Name": "B", HOURS: 20},  # identical copy
            {ATT_KEY: "C", "Employee Name": "C", HOURS: 30},
            {ATT_KEY: "C", "Employee Name": "C", HOURS: 35},  # conflicting copy
            {ATT_KEY: None, "Employee Name": "No ID", HOURS: 40},
        ]
        cli = [
            {CLI_KEY: "A", "Employee Name": "A", HOURS: 10},
            {CLI_KEY: "B", "Employee Name": "B", HOURS: 22},
            {CLI_KEY: "C", "Employee Name": "C", HOURS: 33},
            {CLI_KEY: "X", "Employee Name": "X", HOURS: 50},
            {CLI_KEY: "Y", "Employee Name": "Y", HOURS: 51},
        ]
        result = compare_records(att, cli, ATT_KEY, CLI_KEY, HOURS, HOURS)
        s = result["summary"]

        # Six entities: A, B, C, the blank-ID row, X and Y — regardless of
        # how many physical rows produced them.
        assert s["total_records_compared"] == 6
        assert s["matches"] == 1  # only A reconciles
        assert s["mismatches"] == 5  # B, C, blank-ID row, X, Y
        assert s["review_required"] == 4  # B & C (client higher / conflict), X, Y

        ids = _ids(result)
        named = sorted(i for i in ids if not i.startswith("(row"))
        assert named == ["B", "C", "X", "Y"]
        assert len(ids) == len(set(ids))  # no identifier repeats
        assert sum(i.startswith("(row") for i in ids) == 1


class TestBlankIdentifiersNeverJoin:
    def test_blank_ids_remain_separate_records(self):
        att = [
            {ATT_KEY: None, "Employee Name": "R1", HOURS: 10},
            {ATT_KEY: None, "Employee Name": "R2", HOURS: 20},
        ]
        cli = [
            {CLI_KEY: None, "Employee Name": "S1", HOURS: 30},
            {CLI_KEY: None, "Employee Name": "S2", HOURS: 40},
        ]
        result = compare_records(att, cli, ATT_KEY, CLI_KEY, HOURS, HOURS)

        # Blank identifiers still never join anything: four separate records.
        assert result["summary"]["mismatches"] == 4
        severities = sorted(m["severity"] for m in result["mismatches"])
        assert severities == ["HIGH", "HIGH", "MEDIUM", "MEDIUM"]


class TestWithinFileDuplicates:
    def test_identical_duplicates_evaluate_once(self):
        records = [
            {"ID": "E1", "Total A": 40, "Total B": 40},
            {"ID": "E1", "Total A": 40, "Total B": 40},
            {"ID": "E2", "Total A": 8, "Total B": 9},
        ]
        result = compare_within_file(records, "ID", "Total A", "Total B")

        # E2's second column is higher, which this path classifies as HIGH
        # severity (existing rule), hence review_required == 1.
        assert result["summary"] == {
            "total_records_compared": 2,
            "matches": 1,
            "mismatches": 1,
            "review_required": 1,
        }
        assert _ids(result) == ["E2"]

    def test_conflicting_duplicates_yield_one_record(self):
        records = [
            {"ID": "E1", "Total A": 40, "Total B": 40},
            {"ID": "E1", "Total A": 32, "Total B": 40},
        ]
        result = compare_within_file(records, "ID", "Total A", "Total B")

        assert len(result["mismatches"]) == 1
        m = result["mismatches"][0]
        assert m["severity"] == "HIGH"
        assert m["company_hours"] is None
        assert m["client_hours"] == 40
        assert "40" in m["reason"] and "32" in m["reason"]
        assert result["summary"]["review_required"] == 1


class TestEndToEndWithFiles:
    def test_loaded_workbooks_keep_duplicates_as_one_employee(self, tmp_path):
        att_path = tmp_path / "att.xlsx"
        cli_path = tmp_path / "cli.xlsx"
        pd.DataFrame([
            {"Emp ID": "E001", "Employee Name": "Ann", "Total Hours": 40},
            {"Emp ID": "E001", "Employee Name": "Ann", "Total Hours": 40},
            {"Emp ID": "E002", "Employee Name": "Ben", "Total Hours": 35},
        ]).to_excel(att_path, index=False)
        pd.DataFrame([
            {"Client ID": "E001", "Employee Name": "Ann", "Total Hours": 38},
            {"Client ID": "E002", "Employee Name": "Ben", "Total Hours": 35},
        ]).to_excel(cli_path, index=False)

        att_records = load_records(str(att_path))
        cli_records = load_records(str(cli_path))
        att_hours = detect_hours_column(att_records, exclude=["Emp ID"])
        cli_hours = detect_hours_column(cli_records, exclude=["Client ID"])

        result = compare_records(
            att_records, cli_records,
            "Emp ID", "Client ID", att_hours, cli_hours,
        )

        assert result["summary"]["total_records_compared"] == 2
        assert result["summary"]["mismatches"] == 1
        assert _ids(result) == ["E001"]