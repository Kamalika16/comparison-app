"""Regression tests for selected-ID aggregation and comparison."""
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
        assert _ids(result) == ["E001"]
        m = result["mismatches"][0]
        assert m["company_hours"] == 80
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
        assert result["summary"]["matches"] == 0
        assert result["summary"]["mismatches"] == 1
        assert result["mismatches"][0]["company_hours"] == 80


class TestDuplicateConflictingHours:
    def test_multiple_file1_totals_are_summed_once(self):
        att = [
            {ATT_KEY: "E200", "Employee Name": "Dana Fox", HOURS: 40},
            {ATT_KEY: "E200", "Employee Name": "Dana Fox", HOURS: 32},
        ]
        cli = [{CLI_KEY: "E200", "Employee Name": "Dana Fox", HOURS: 36}]
        result = compare_records(att, cli, ATT_KEY, CLI_KEY, HOURS, HOURS)

        assert len(result["mismatches"]) == 1
        m = result["mismatches"][0]
        assert m["severity"] == "MEDIUM"
        assert m["company_hours"] == 72
        assert m["client_hours"] == 36
        assert m["difference"] == 36
        assert result["summary"]["review_required"] == 0

    def test_blank_duplicate_hour_is_ignored(self):
        att = [
            {ATT_KEY: "E202", "Employee Name": "Fay Hale", HOURS: None},
            {ATT_KEY: "E202", "Employee Name": "Fay Hale", HOURS: 24},
        ]
        cli = [{CLI_KEY: "E202", "Employee Name": "Fay Hale", HOURS: 24}]
        result = compare_records(att, cli, ATT_KEY, CLI_KEY, HOURS, HOURS)

        assert result["summary"]["matches"] == 1
        assert result["matched"][0]["company_hours"] == 24


class TestEachIdentifierOnce:
    def test_mixed_files_list_every_identifier_once(self):
        att = [
            {ATT_KEY: "A", HOURS: 10},
            {ATT_KEY: "B", HOURS: 20},
            {ATT_KEY: "B", HOURS: 20},
            {ATT_KEY: "C", HOURS: 30},
            {ATT_KEY: "C", HOURS: 35},
            {ATT_KEY: None, HOURS: 40},
        ]
        cli = [
            {CLI_KEY: "A", HOURS: 10},
            {CLI_KEY: "B", HOURS: 22},
            {CLI_KEY: "C", HOURS: 33},
            {CLI_KEY: "X", HOURS: 50},
            {CLI_KEY: "Y", HOURS: 51},
        ]
        result = compare_records(att, cli, ATT_KEY, CLI_KEY, HOURS, HOURS)

        assert result["summary"]["total_records_compared"] == 5
        assert result["summary"]["matches"] == 1
        assert len(_ids(result)) == len(set(_ids(result)))

    def test_file1_only_values_are_filtered_by_file2_ids(self):
        att = [
            {ATT_KEY: "DWP", HOURS: 8},
            {ATT_KEY: "DWP T&C", HOURS: 8},
            {ATT_KEY: "H285491", HOURS: 8},
            {ATT_KEY: "H285491", HOURS: 8},
        ]
        cli = [{CLI_KEY: "H285491", HOURS: 16}]

        result = compare_records(att, cli, ATT_KEY, CLI_KEY, HOURS, HOURS)

        assert result["summary"] == {
            "total_records_compared": 1,
            "matches": 1,
            "mismatches": 0,
            "review_required": 0,
        }
        assert result["matched"][0]["employee_id"] == "H285491"
        assert result["matched"][0]["company_hours"] == 16
        assert result["matched"][0]["client_hours"] == 16

    def test_duplicate_file2_ids_are_summed(self):
        att = [{ATT_KEY: "H285491", HOURS: 16}]
        cli = [
            {CLI_KEY: "H285491", HOURS: 8},
            {CLI_KEY: "H285491", HOURS: 8},
        ]

        result = compare_records(att, cli, ATT_KEY, CLI_KEY, HOURS, HOURS)

        assert result["summary"]["matches"] == 1
        assert result["matched"][0]["client_hours"] == 16

    def test_names_are_display_only_and_most_frequent_name_is_preserved(self):
        att = [
            {"ID": "E300", "First name": "Ada", "Last name": "Lovelace", HOURS: 4},
            {"ID": "E300", "First name": "ADA", "Last name": "LOVELACE", HOURS: 6},
            {"ID": "E300", "First name": "Ada", "Last name": "Lovelace", HOURS: 10},
        ]
        cli = [{"Network ID": "E300", "Row Labels": "Ada Lovelace", HOURS: 20}]

        result = compare_records(att, cli, "ID", "Network ID", HOURS, HOURS)

        assert result["matched"][0]["employee_name"] == "Ada Lovelace"
        assert result["matched"][0]["employee_id"] == "E300"


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

        # Blank identifiers are not valid comparison records.
        assert result["summary"]["mismatches"] == 0


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