import datetime

from app.services.normalizers import normalize_date, normalize_hours, normalize_name


class TestNormalizeName:
    def test_simple_name(self):
        assert normalize_name("John Smith") == "john smith"

    def test_last_first_format(self):
        assert normalize_name("Smith, John") == "john smith"

    def test_extra_whitespace(self):
        assert normalize_name("  John   Smith  ") == "john smith"

    def test_punctuation_removed(self):
        assert normalize_name("O'Neil, Mary-Jane") == "maryjane oneil"

    def test_none_returns_empty(self):
        assert normalize_name(None) == ""


class TestNormalizeDate:
    def test_iso_string(self):
        assert normalize_date("2024-01-05") == "2024-01-05"

    def test_us_format(self):
        assert normalize_date("1/5/2024") == "2024-01-05"

    def test_datetime_object(self):
        dt = datetime.datetime(2024, 1, 5, 9, 30)
        assert normalize_date(dt) == "2024-01-05"

    def test_invalid_date_returns_none(self):
        assert normalize_date("not a date") is None

    def test_none_returns_none(self):
        assert normalize_date(None) is None


class TestNormalizeHours:
    def test_plain_number(self):
        assert normalize_hours(8) == 8.0

    def test_numeric_string(self):
        assert normalize_hours("7.5") == 7.5

    def test_hours_minutes_string(self):
        assert normalize_hours("8h 30m") == 8.5

    def test_hh_mm_duration(self):
        assert normalize_hours("08:30") == 8.5

    def test_time_range(self):
        assert normalize_hours("09:00-17:30") == 8.5

    def test_none_returns_none(self):
        assert normalize_hours(None) is None

    def test_garbage_returns_none(self):
        assert normalize_hours("not hours") is None
