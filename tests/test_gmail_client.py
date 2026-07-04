"""Unit tests for GmailClient — Gmail API mocked."""
import base64
import email.message
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def gmail():
    with patch("src.gmail_client.GoogleAuthClient"):
        from src.gmail_client import GmailClient
        return GmailClient()


@pytest.fixture
def mock_service(gmail):
    svc = MagicMock()
    gmail.get_service = MagicMock(return_value=svc)
    return svc


# ── mark_as_read ──────────────────────────────────────────────────────────────

def test_mark_as_read_removes_unread_label(gmail, mock_service):
    gmail.mark_as_read("msg-abc")
    mock_service.users().messages().modify.assert_called_once_with(
        userId="me", id="msg-abc", body={"removeLabelIds": ["UNREAD"]}
    )


# ── save_draft ────────────────────────────────────────────────────────────────

def _decode_draft_msg(mock_service):
    """Decode the raw MIME message passed to drafts().create()."""
    raw = mock_service.users().drafts().create.call_args[1]["body"]["message"]["raw"]
    return base64.urlsafe_b64decode(raw).decode("utf-8")


def test_save_draft_minimal(gmail, mock_service):
    mock_service.users().drafts().create.return_value.execute.return_value = {"id": "draft-1"}
    draft_id = gmail.save_draft(to="bob@x.com", subject="Hello", body="Hi there")
    assert draft_id == "draft-1"
    raw_msg = _decode_draft_msg(mock_service)
    assert "To: bob@x.com" in raw_msg
    assert "Subject: Hello" in raw_msg


def test_save_draft_with_thread_id_sets_thread_in_payload(gmail, mock_service):
    mock_service.users().drafts().create.return_value.execute.return_value = {"id": "draft-2"}
    gmail.save_draft(to="a@b.com", subject="Re: Meet", body="Sure!", thread_id="thread-xyz")
    body_arg = mock_service.users().drafts().create.call_args[1]["body"]
    assert body_arg["message"]["threadId"] == "thread-xyz"


def test_save_draft_with_message_id_sets_reply_headers(gmail, mock_service):
    mock_service.users().drafts().create.return_value.execute.return_value = {"id": "draft-3"}
    gmail.save_draft(to="a@b.com", subject="Re: Meet", body="Sure!", message_id="<orig@mail.com>")
    raw_msg = _decode_draft_msg(mock_service)
    assert "In-Reply-To: <orig@mail.com>" in raw_msg
    assert "References: <orig@mail.com>" in raw_msg


def test_save_draft_without_thread_id_no_thread_key(gmail, mock_service):
    mock_service.users().drafts().create.return_value.execute.return_value = {"id": "draft-4"}
    gmail.save_draft(to="a@b.com", subject="New", body="Hello")
    body_arg = mock_service.users().drafts().create.call_args[1]["body"]
    assert "threadId" not in body_arg["message"]


# ── get_recently_sent ─────────────────────────────────────────────────────────

def test_get_recently_sent_converts_ms_to_seconds(gmail, mock_service):
    mock_service.users().messages().list.return_value.execute.return_value = {
        "messages": [{"id": "sent-1"}]
    }
    mock_service.users().messages().get.return_value.execute.return_value = {
        "threadId": "thread-1",
        "internalDate": "1750000000000",  # milliseconds
        "payload": {"headers": [{"name": "Subject", "value": "Re: Hello"}]},
    }
    result = gmail.get_recently_sent(max_results=1)
    assert len(result) == 1
    assert result[0]["thread_id"] == "thread-1"
    assert result[0]["sent_at"] == pytest.approx(1750000000.0)


def test_get_recently_sent_returns_empty_on_no_messages(gmail, mock_service):
    mock_service.users().messages().list.return_value.execute.return_value = {"messages": []}
    assert gmail.get_recently_sent() == []
