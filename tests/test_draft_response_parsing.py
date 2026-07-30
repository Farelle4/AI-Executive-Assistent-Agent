"""Unit tests for DraftResponse pure parsing helpers.

These tests require no LLM, no Google credentials, and no network access.
The LLM model and GoogleCalendar are mocked at instantiation time.
"""
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from src.draft_response import DraftResponse


@pytest.fixture
def parser():
    """DraftResponse with LLM and GoogleCalendar mocked out."""
    with patch("src.draft_response.GoogleCalendar"):
        return DraftResponse(model=MagicMock())


# ── _extract_first_name ────────────────────────────────────────────────────────

class TestExtractFirstName:
    def test_display_name_with_angle_brackets(self, parser):
        assert parser._extract_first_name("John Doe <john@example.com>") == "John"

    def test_email_only_capitalises_local_part(self, parser):
        assert parser._extract_first_name("john@example.com") == "John"

    def test_quoted_display_name(self, parser):
        assert parser._extract_first_name('"Jane Smith" <jane@example.com>') == "Jane"

    def test_single_name_no_email(self, parser):
        assert parser._extract_first_name("Alice") == "Alice"

    def test_empty_string(self, parser):
        assert parser._extract_first_name("") == ""


# ── _normalize_time ────────────────────────────────────────────────────────────

class TestNormalizeTime:
    def test_french_hour_only(self, parser):
        assert parser._normalize_time("14h") == "14:00"

    def test_french_hour_and_minutes(self, parser):
        assert parser._normalize_time("10h30") == "10:30"

    def test_single_digit_hour(self, parser):
        assert parser._normalize_time("9h") == "9:00"

    def test_already_colon_format(self, parser):
        assert parser._normalize_time("14:00") == "14:00"

    def test_am_pm_passthrough(self, parser):
        assert parser._normalize_time("10am") == "10am"

    def test_strips_surrounding_whitespace(self, parser):
        assert parser._normalize_time("  8h  ") == "8:00"


# ── _build_start_iso ───────────────────────────────────────────────────────────

class TestBuildStartIso:
    def test_empty_date_returns_none(self, parser):
        assert parser._build_start_iso("", "10:00") is None

    def test_empty_time_returns_none(self, parser):
        assert parser._build_start_iso("next Monday", "") is None

    def test_both_empty_returns_none(self, parser):
        assert parser._build_start_iso("", "") is None

    def test_returns_timezone_aware_iso(self, parser):
        result = parser._build_start_iso("next Friday", "10:00")
        assert result is not None
        dt = datetime.fromisoformat(result)
        assert dt.tzinfo is not None

    def test_french_time_format_parsed_correctly(self, parser):
        result = parser._build_start_iso("next Monday", "14h")
        assert result is not None
        dt = datetime.fromisoformat(result)
        assert dt.hour == 14
        assert dt.minute == 0

    def test_french_time_with_minutes(self, parser):
        result = parser._build_start_iso("next Monday", "9h30")
        assert result is not None
        dt = datetime.fromisoformat(result)
        assert dt.hour == 9
        assert dt.minute == 30

    def test_relative_word_prochain_still_parses(self, parser):
        result = parser._build_start_iso("lundi prochain", "10h")
        assert result is not None
        dt = datetime.fromisoformat(result)
        assert dt.hour == 10

    def test_result_is_in_future(self, parser):
        from datetime import timezone
        result = parser._build_start_iso("next Monday", "10:00")
        assert result is not None
        dt = datetime.fromisoformat(result)
        assert dt > datetime.now(timezone.utc)
