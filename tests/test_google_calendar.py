"""Unit tests for GoogleCalendar — Calendar API mocked."""
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import pytest

TZ = ZoneInfo("Europe/Berlin")


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


def _future_datetime(hour=10, minute=0, days_ahead=1):
    """Timezone-aware datetime guaranteed to be in the future, regardless of when tests run."""
    target = datetime.now(TZ) + timedelta(days=days_ahead)
    return target.replace(hour=hour, minute=minute, second=0, microsecond=0)


# ── is_time_free ──────────────────────────────────────────────────────────────

def test_is_time_free_returns_true_when_no_busy_slots(calendar, mock_service):
    mock_service.events().list.return_value.execute.return_value = {"items": []}
    assert calendar.is_time_free(_future_datetime(10, 0).isoformat()) is True


def test_is_time_free_returns_false_when_slot_is_busy(calendar, mock_service):
    start = _future_datetime(10, 0)
    mock_service.events().list.return_value.execute.return_value = {"items": [
        {
            "start": {"dateTime": start.isoformat()},
            "end": {"dateTime": (start + timedelta(minutes=30)).isoformat()},
        }
    ]}
    assert calendar.is_time_free(start.isoformat()) is False


def test_is_time_free_returns_false_for_past_slot(calendar, mock_service):
    mock_service.events().list.return_value.execute.return_value = {"items": []}
    past = datetime.now(TZ) - timedelta(hours=1)
    assert calendar.is_time_free(past.isoformat()) is False


def test_is_time_free_accounts_for_travel_time_after_in_person_event(calendar, mock_service):
    event_start = _future_datetime(10, 0)
    event_end = event_start + timedelta(minutes=30)
    mock_service.events().list.return_value.execute.return_value = {"items": [
        {
            "start": {"dateTime": event_start.isoformat()},
            "end": {"dateTime": event_end.isoformat()},
            "location": "123 Main Street, Berlin",
        }
    ]}
    # Requested slot starts right when the in-person meeting ends — no travel time.
    assert calendar.is_time_free(event_end.isoformat()) is False


def test_is_time_free_ignores_travel_buffer_for_virtual_event(calendar, mock_service):
    event_start = _future_datetime(10, 0)
    event_end = event_start + timedelta(minutes=30)
    mock_service.events().list.return_value.execute.return_value = {"items": [
        {
            "start": {"dateTime": event_start.isoformat()},
            "end": {"dateTime": event_end.isoformat()},
            "hangoutLink": "https://meet.google.com/abc-defg-hij",
        }
    ]}
    assert calendar.is_time_free(event_end.isoformat()) is True


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

def _make_target(hour=9, days_ahead=1):
    target = datetime.now(TZ) + timedelta(days=days_ahead)
    return target.replace(hour=hour, minute=0, second=0, microsecond=0)


def test_get_free_slots_no_events_returns_all_slots(calendar, mock_service):
    mock_service.events().list.return_value.execute.return_value = {"items": []}
    slots = calendar.get_free_slots_for_day(mock_service, target_date=_make_target())
    assert len(slots) == 20  # 08:00–18:00 in 30-min increments = 20 slots


def test_get_free_slots_excludes_busy_period(calendar, mock_service):
    target = _make_target()
    mock_service.events().list.return_value.execute.return_value = {"items": [
        {
            "start": {"dateTime": target.replace(hour=10, minute=0).isoformat()},
            "end":   {"dateTime": target.replace(hour=11, minute=0).isoformat()},
        }
    ]}
    slots = calendar.get_free_slots_for_day(mock_service, target_date=target)
    slot_times = [datetime.fromisoformat(s).astimezone(TZ).strftime("%H:%M") for s in slots]
    assert "10:00" not in slot_times
    assert "10:30" not in slot_times
    assert "09:00" in slot_times
    assert "11:00" in slot_times


def test_get_free_slots_excludes_past_slots_for_today(calendar, mock_service):
    mock_service.events().list.return_value.execute.return_value = {"items": []}
    now = datetime.now(TZ)
    slots = calendar.get_free_slots_for_day(mock_service, target_date=now)
    slot_times = [datetime.fromisoformat(s).astimezone(TZ) for s in slots]
    assert all(slot_time >= now for slot_time in slot_times)


def test_get_free_slots_pads_travel_buffer_around_in_person_event(calendar, mock_service):
    target = _make_target()
    mock_service.events().list.return_value.execute.return_value = {"items": [
        {
            "start": {"dateTime": target.replace(hour=10, minute=0).isoformat()},
            "end":   {"dateTime": target.replace(hour=10, minute=30).isoformat()},
            "location": "Conference Room B",
        }
    ]}
    slots = calendar.get_free_slots_for_day(mock_service, target_date=target)
    slot_times = [datetime.fromisoformat(s).astimezone(TZ).strftime("%H:%M") for s in slots]
    # 30-minute travel buffer padded on both sides of the 10:00–10:30 in-person meeting:
    # busy from 09:30 up to (but not including) 11:00.
    assert "09:30" not in slot_times
    assert "10:30" not in slot_times
    assert "09:00" in slot_times
    assert "11:00" in slot_times


def test_get_free_slots_no_buffer_for_virtual_event(calendar, mock_service):
    target = _make_target()
    mock_service.events().list.return_value.execute.return_value = {"items": [
        {
            "start": {"dateTime": target.replace(hour=10, minute=0).isoformat()},
            "end":   {"dateTime": target.replace(hour=10, minute=30).isoformat()},
            "hangoutLink": "https://meet.google.com/abc-defg-hij",
        }
    ]}
    slots = calendar.get_free_slots_for_day(mock_service, target_date=target)
    slot_times = [datetime.fromisoformat(s).astimezone(TZ).strftime("%H:%M") for s in slots]
    assert "09:30" in slot_times
    assert "11:00" in slot_times
