"""Regression tests for detect_hours_column()'s name-based disambiguation.

Real client files frequently have MORE than one fully-numeric column (per
weekday totals, rate, cost, billable/non-billable splits, ...), so picking
"the one numeric column" no longer works once there's more than one. These
tests lock in the fuzzy name-matching fallback that disambiguates by column
NAME in that case -- including typos, since end users type headers however
they type them.
"""
from app.services.excel_loader import detect_hours_column


def _records(columns: dict) -> list[dict]:
    """Build a single-row dataset from {column_name: value}."""
    return [columns]


class TestSingleNumericColumnUnaffected:
    """The common case (exactly one numeric column) must still work
    regardless of its name -- name matching only kicks in when there's
    more than one candidate."""

    def test_lone_numeric_column_with_unrelated_name(self):
        assert detect_hours_column(_records({"Grand Total": 40})) == "Grand Total"


class TestNameDisambiguation:
    def test_real_client_file_with_typo_in_billable_hours(self):
        """Reproduces a real reported case: 12 fully-numeric columns
        (per-weekday totals, cost center, rate, cost...) including a
        misspelled 'Bilable Hours' and a 'Non-Bilable Hours' column. Must
        resolve to the plain billable-hours column, not any of the others."""
        row = {
            "CostCenter": 101, "Year": 2026,
            "Sat": 0, "Sun": 0, "Mon": 8, "Tue": 8, "Wed": 8, "Fri": 8,
            "Bilable Hours": 32, "Non-Bilable Hours": 4,
            "Effective Rate": 55, "Cost": 1760,
        }
        assert detect_hours_column(_records(row)) == "Bilable Hours"

    def test_prefers_billable_over_non_billable_when_both_present(self):
        row = {"Billable Hours": 40, "Non-Billable Hours": 2, "Rate": 50}
        assert detect_hours_column(_records(row)) == "Billable Hours"

    def test_case_and_wording_variants_still_match(self):
        row = {"TOTAL HRS": 40, "Employee ID": 1001}
        assert detect_hours_column(_records(row)) == "TOTAL HRS"


class TestFallsBackToErrorWhenGenuinelyAmbiguous:
    """When no column name confidently points to 'hours', or two columns
    are equally hour-ish, the function must raise (so the caller asks the
    user to choose) rather than silently guess."""

    def test_no_hours_like_name_among_candidates(self):
        try:
            detect_hours_column(_records({"A": 1, "B": 2}))
            assert False, "expected ValueError"
        except ValueError as e:
            assert "found 2" in str(e)

    def test_genuine_tie_between_two_equally_hour_like_names(self):
        row = {"Billable Hours": 8, "Total Hours": 8}
        try:
            detect_hours_column(_records(row))
            assert False, "expected ValueError"
        except ValueError as e:
            assert "found 2" in str(e)

    def test_only_a_non_billable_style_column_present(self):
        """Without a plain 'billable'/'total hours' column to prefer, a
        lone 'Non-Billable Hours' next to an unrelated numeric column is
        genuinely ambiguous -- must ask rather than assume it's the one
        wanted."""
        row = {"Non-Billable Hours": 4, "Rate": 50}
        try:
            detect_hours_column(_records(row))
            assert False, "expected ValueError"
        except ValueError as e:
            assert "found 2" in str(e)