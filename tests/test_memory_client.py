"""Unit tests for MemoryClient — Supabase interactions mocked."""
import json
from unittest.mock import MagicMock, call, patch

import pytest


@pytest.fixture
def memory():
    with patch.dict("os.environ", {"SUPABASE_URL": "https://fake.supabase.co", "SUPABASE_KEY": "fake-key"}), \
         patch("src.memory_client.create_client"):
        from src.memory_client import MemoryClient
        client = MemoryClient()
        client.supabase = MagicMock()
        return client


# ── is_processed ──────────────────────────────────────────────────────────────

def test_is_processed_returns_true_when_found(memory):
    memory.supabase.table.return_value.select.return_value \
        .in_.return_value.eq.return_value.limit.return_value \
        .execute.return_value.data = [{"id": "abc"}]
    assert memory.is_processed("msg-123") is True


def test_is_processed_returns_false_when_not_found(memory):
    memory.supabase.table.return_value.select.return_value \
        .in_.return_value.eq.return_value.limit.return_value \
        .execute.return_value.data = []
    assert memory.is_processed("msg-unknown") is False


# ── save_email ─────────────────────────────────────────────────────────────────

def test_save_email_inserts_correct_record_type(memory):
    # Simulate dedup check finding no existing record (.in_ is used, not .eq, for record_type)
    memory.supabase.table.return_value.select.return_value \
        .in_.return_value.eq.return_value.limit.return_value \
        .execute.return_value.data = []
    memory.save_email("mid", "Subject", "sender@x.com", "DRAFTED", language="Italian", intent="meeting_request")
    insert_call = memory.supabase.table.return_value.insert
    payload = insert_call.call_args[0][0]
    assert payload["record_type"] == "email"
    assert payload["message_id"] == "mid"
    assert payload["sender"] == "sender@x.com"
    assert payload["language"] == "Italian"
    assert payload["intent"] == "meeting_request"
    assert payload["status"] == "DRAFTED"
    assert "id" in payload


# ── get_user ──────────────────────────────────────────────────────────────────

def test_get_user_returns_dict_when_found(memory):
    expected = {"name": "Alice", "is_vip": True, "language": "French", "notes": ""}
    memory.supabase.table.return_value.select.return_value \
        .eq.return_value.eq.return_value.limit.return_value \
        .execute.return_value.data = [expected]
    assert memory.get_user("alice@x.com") == expected


def test_get_user_returns_empty_dict_when_not_found(memory):
    memory.supabase.table.return_value.select.return_value \
        .eq.return_value.eq.return_value.limit.return_value \
        .execute.return_value.data = []
    assert memory.get_user("unknown@x.com") == {}


# ── upsert_user ───────────────────────────────────────────────────────────────

def test_upsert_user_inserts_when_contact_is_new(memory):
    memory.supabase.table.return_value.select.return_value \
        .eq.return_value.eq.return_value.limit.return_value \
        .execute.return_value.data = []
    memory.upsert_user("new@x.com", name="Bob", language="German")
    memory.supabase.table.return_value.insert.assert_called_once()
    payload = memory.supabase.table.return_value.insert.call_args[0][0]
    assert payload["record_type"] == "user"
    assert payload["sender"] == "new@x.com"
    assert payload["name"] == "Bob"


def test_upsert_user_updates_when_contact_exists(memory):
    memory.supabase.table.return_value.select.return_value \
        .eq.return_value.eq.return_value.limit.return_value \
        .execute.return_value.data = [{"id": "existing-uuid"}]
    memory.upsert_user("known@x.com", name="Bob", is_vip=True)
    memory.supabase.table.return_value.update.assert_called_once()
    memory.supabase.table.return_value.insert.assert_not_called()


# ── save_pending_event ────────────────────────────────────────────────────────

def test_save_pending_event_stores_isos_as_json(memory):
    # UPDATE returns no rows → fallback INSERT is triggered
    memory.supabase.table.return_value.update.return_value \
        .eq.return_value.eq.return_value.execute.return_value.data = []
    memory.save_pending_event("thread-1", "Meeting", "2026-07-10T10:00:00+02:00", "2026-07-10T10:30:00+02:00")
    payload = memory.supabase.table.return_value.insert.call_args[0][0]
    assert payload["record_type"] == "pending_event"
    assert payload["message_id"] == "thread-1"
    assert payload["status"] == "pending"
    notes = json.loads(payload["notes"])
    assert notes["start_iso"] == "2026-07-10T10:00:00+02:00"
    assert notes["end_iso"] == "2026-07-10T10:30:00+02:00"


# ── get_pending_event ─────────────────────────────────────────────────────────

def test_get_pending_event_returns_dict_when_found(memory):
    row = {"id": "uuid", "subject": "Meeting", "notes": "{}", "created_at": "2026-06-01T00:00:00+00:00"}
    memory.supabase.table.return_value.select.return_value \
        .eq.return_value.eq.return_value.eq.return_value.limit.return_value \
        .execute.return_value.data = [row]
    assert memory.get_pending_event("thread-1") == row


def test_get_pending_event_returns_none_when_not_found(memory):
    memory.supabase.table.return_value.select.return_value \
        .eq.return_value.eq.return_value.eq.return_value.limit.return_value \
        .execute.return_value.data = []
    assert memory.get_pending_event("thread-missing") is None


# ── mark_event_created ────────────────────────────────────────────────────────

def test_mark_event_created_sets_status_to_done(memory):
    memory.mark_event_created("thread-1")
    memory.supabase.table.return_value.update.assert_called_once_with({"status": "done"})
