from app.models.schemas import Severity
from app.services.rules_engine import NormalizedRecord, evaluate_pair


def make_record(name="john smith", date="2024-01-08", hours=8.0):
    # 2024-01-08 is a Monday, safely a non-weekend fixture date.
    return NormalizedRecord(employee_name=name, date=date, hours=hours)


class TestRulesEngine:
    def test_rule1_exact_match(self):
        result = evaluate_pair(make_record(hours=8.0), make_record(hours=8.1))
        assert result.severity == Severity.MATCH
        assert result.rule_triggered == "Rule 1"

    def test_rule2_minor_variance(self):
        result = evaluate_pair(make_record(hours=8.0), make_record(hours=8.5))
        assert result.severity == Severity.MINOR
        assert result.rule_triggered == "Rule 2"

    def test_rule3_major_variance(self):
        result = evaluate_pair(make_record(hours=8.0), make_record(hours=10.5))
        assert result.severity == Severity.MAJOR
        assert result.rule_triggered == "Rule 3"

    def test_rule4_missing_client_work(self):
        result = evaluate_pair(make_record(), None)
        assert result.severity == Severity.MISSING_CLIENT_WORK
        assert result.rule_triggered == "Rule 4"

    def test_rule5_missing_attendance(self):
        result = evaluate_pair(None, make_record())
        assert result.severity == Severity.MISSING_ATTENDANCE
        assert result.rule_triggered == "Rule 5"

    def test_rule6_zero_vs_nonzero(self):
        result = evaluate_pair(make_record(hours=0.0), make_record(hours=6.0))
        assert result.severity == Severity.MAJOR
        assert result.rule_triggered == "Rule 6"

    def test_rule7_duplicate_flagged_for_review(self):
        result = evaluate_pair(
            make_record(), make_record(), attendance_duplicate=True
        )
        assert result.severity == Severity.REVIEW
        assert result.rule_triggered == "Rule 7"

    def test_rule8_weekend_work_flagged(self):
        # 2024-01-06 is a Saturday
        result = evaluate_pair(
            make_record(date="2024-01-06", hours=4.0),
            make_record(date="2024-01-06", hours=4.0),
        )
        assert result.severity == Severity.REVIEW
        assert result.rule_triggered == "Rule 8"

    def test_rule9_malformed_row(self):
        bad_record = NormalizedRecord(employee_name="", date=None, hours=None)
        result = evaluate_pair(bad_record, make_record())
        assert result.severity == Severity.REVIEW
        assert result.rule_triggered == "Rule 9"
