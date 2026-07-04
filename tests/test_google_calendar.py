"""Unit tests for GoogleCalendar — Calendar API mocked."""
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def calendar():
    with patch("src.google_calendar.GoogleAuthClient"):
        from src.google_calendar import GoogleCalendar
        cal = GoogleCalendar()
        cal.get_service = MagicMock()
        return cal


@pytest.fixture
def mock_service(calendar):
    svc = MagicMock()
    calendar.get_service.return_value = svc
    return svc


# ── is_time_free ──────────────────────────────────────────────────────────────

def test_is_time_free_returns_true_when_no_busy_slots(calendar, mock_service):
    mock_service.freebusy().query.return_value.execute.return_value = {
        "calendars": {"primary": {"busy": []}}
    }
    assert calendar.is_time_free("2026-07-10T10:00:00+02:00") is True


def test_is_time_free_returns_false_when_slot_is_busy(calendar, mock_service):
    mock_service.freebusy().query.return_value.execute.return_value = {
        "calendars": {"primary": {"busy": [
            {"start": "2026-07-10T10:00:00Z", "end": "2026-07-10T10:30:00Z"}
        ]}}
    }
    assert calendar.is_time_free("2026-07-10T10:00:00+02:00") is False


# ── create_event ──────────────────────────────────────────────────────────────

def test_create_event_calls_insert_with_summary(calendar, mock_service):
    mock_service.events().insert.return_value.execute.return_value = {
        "htmlLink": "http://cal.google.com/event/1", "id": "evt-1"
    }
    result = calendar.create_event("Team Sync", "2026-07-10T10:00:00+02:00", "2026-07-10T10:30:00+02:00")
    body = mock_service.events().insert.call_args[1]["body"]
    assert body["summary"] == "Team Sync"
    assert result["id"] == "evt-1"


def test_create_event_defaults_end_to_30_minutes(calendar, mock_service):
    mock_service.events().insert.return_value.execute.return_value = {"htmlLink": "", "id": "evt-2"}
    calendar.create_event("Quick Call", "2026-07-10T10:00:00+02:00")
    body = mock_service.events().insert.call_args[1]["body"]
    start = datetime.fromisoformat(body["start"]["dateTime"])
    end = datetime.fromisoformat(body["end"]["dateTime"])
    assert (end - start).seconds == 1800  # 30 minutes


# ── get_free_slots_for_day ────────────────────────────────────────────────────

def _make_target(hour=9):
    from zoneinfo import ZoneInfo
    return datetime(2026, 7, 10, hour, 0, tzinfo=ZoneInfo("Europe/Berlin"))


def test_get_free_slots_no_events_returns_all_slots(calendar, mock_service):
    mock_service.events().list.return_value.execute.return_value = {"items": []}
    slots = calendar.get_free_slots_for_day(mock_service, target_date=_make_target())
    assert len(slots) == 20  # 08:00–18:00 in 30-min increments = 20 slots


def test_get_free_slots_excludes_busy_period(calendar, mock_service):
    from zoneinfo import ZoneInfo
    tz = ZoneInfo("Europe/Berlin")
    mock_service.events().list.return_value.execute.return_value = {"items": [
        {
            "start": {"dateTime": "2026-07-10T10:00:00+02:00"},
            "end":   {"dateTime": "2026-07-10T11:00:00+02:00"},
        }
    ]}
    slots = calendar.get_free_slots_for_day(mock_service, target_date=_make_target())
    slot_times = [datetime.fromisoformat(s).astimezone(tz).strftime("%H:%M") for s in slots]
    assert "10:00" not in slot_times
    assert "10:30" not in slot_times
    assert "09:00" in slot_times
    assert "11:00" in slot_times
