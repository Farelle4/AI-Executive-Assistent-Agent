"""Tests for AgentOrchestrator — LangChain ReAct agent pipeline."""
import json
from unittest.mock import MagicMock, patch


def _make_orchestrator():
    """Instantiate AgentOrchestrator with all external dependencies mocked."""
    with patch("src.orchestrator.init_chat_model", return_value=MagicMock()), \
         patch("src.orchestrator.create_agent", return_value=MagicMock()), \
         patch("src.orchestrator.MemoryClient"), \
         patch("src.orchestrator.EmailClassifier"), \
         patch("src.orchestrator.DraftResponse"), \
         patch("src.orchestrator.GmailClient"), \
         patch("src.orchestrator.GoogleCalendar"):
        from src.orchestrator import AgentOrchestrator
        return AgentOrchestrator()


def test_orchestrator_instantiates():
    orch = _make_orchestrator()
    assert hasattr(orch, "run")
    assert hasattr(orch, "run_batch")
    assert hasattr(orch, "run_sent_batch")


def test_orchestrator_builds_agent_with_correct_tools():
    with patch("src.orchestrator.init_chat_model", return_value=MagicMock()), \
         patch("src.orchestrator.create_agent", return_value=MagicMock()) as mock_build, \
         patch("src.orchestrator.MemoryClient"), \
         patch("src.orchestrator.EmailClassifier"), \
         patch("src.orchestrator.DraftResponse"), \
         patch("src.orchestrator.GmailClient"), \
         patch("src.orchestrator.GoogleCalendar"):
        from src.orchestrator import AgentOrchestrator
        AgentOrchestrator()

    _, kwargs = mock_build.call_args
    tool_names = {t.name for t in kwargs["tools"]}
    assert tool_names == {
        "check_if_processed",
        "get_user_context",
        "classify_email",
        "check_calendar",
        "generate_draft",
        "save_draft",
        "save_user_memory",
        "mark_as_read",
        "save_to_memory",
    }


def test_run_invokes_agent_with_email_json():
    orch = _make_orchestrator()
    email = {"id": "msg-001", "subject": "Meeting", "from": "a@b.com", "body": "Hi"}
    orch.run(email)

    orch._agent.invoke.assert_called_once()
    call_input = orch._agent.invoke.call_args[0][0]
    payload = json.loads(call_input["messages"][0]["content"])
    assert payload["id"] == "msg-001"
    assert payload["subject"] == "Meeting"


def test_run_does_not_raise_on_agent_exception():
    orch = _make_orchestrator()
    orch._agent.invoke.side_effect = Exception("LLM timeout")
    orch.run({"id": "e1", "subject": "Hi", "from": "x@y.com", "body": "Hello"})


def test_run_batch_calls_run_for_each_email():
    orch = _make_orchestrator()
    orch._gmail.get_unread_emails.return_value = [
        {"id": "e1", "subject": "S1", "from": "a@b.com", "body": "B1"},
        {"id": "e2", "subject": "S2", "from": "c@d.com", "body": "B2"},
    ]
    assert orch.run_batch() == 2
    assert orch._agent.invoke.call_count == 2


def test_run_batch_empty_inbox():
    orch = _make_orchestrator()
    orch._gmail.get_unread_emails.return_value = []
    assert orch.run_batch() == 0
    orch._agent.invoke.assert_not_called()


# ── run_sent_batch ─────────────────────────────────────────────────────────────

def test_run_sent_batch_creates_event_when_sent_after_pending():
    orch = _make_orchestrator()
    orch._gmail.get_recently_sent.return_value = [
        {"id": "msg1", "thread_id": "thread-abc", "subject": "Re: Meeting", "sent_at": 2_000_000_000.0},
    ]
    orch._memory.get_pending_event.return_value = {
        "id": "uuid1",
        "subject": "Meeting",
        "notes": json.dumps({"start_iso": "2026-07-10T10:00:00+02:00", "end_iso": "2026-07-10T10:30:00+02:00"}),
        "created_at": "2026-06-01T08:00:00+00:00",
    }
    assert orch.run_sent_batch() == 1
    orch._calendar.create_event.assert_called_once_with(
        title="Meeting",
        start_iso="2026-07-10T10:00:00+02:00",
        end_iso="2026-07-10T10:30:00+02:00",
    )
    orch._memory.mark_event_created.assert_called_once_with("thread-abc")


def test_run_sent_batch_skips_email_sent_before_pending_event():
    orch = _make_orchestrator()
    orch._gmail.get_recently_sent.return_value = [
        {"id": "msg1", "thread_id": "thread-abc", "subject": "Re: Meeting", "sent_at": 1000.0},
    ]
    orch._memory.get_pending_event.return_value = {
        "id": "uuid1",
        "subject": "Meeting",
        "notes": json.dumps({"start_iso": "2026-07-10T10:00:00+02:00", "end_iso": ""}),
        "created_at": "2026-06-01T08:00:00+00:00",
    }
    assert orch.run_sent_batch() == 0
    orch._calendar.create_event.assert_not_called()


def test_run_sent_batch_skips_thread_with_no_pending_event():
    orch = _make_orchestrator()
    orch._gmail.get_recently_sent.return_value = [
        {"id": "msg1", "thread_id": "thread-xyz", "subject": "Re: Hello", "sent_at": 2_000_000_000.0},
    ]
    orch._memory.get_pending_event.return_value = None
    assert orch.run_sent_batch() == 0
    orch._calendar.create_event.assert_not_called()


def test_run_sent_batch_returns_zero_on_empty_sent():
    orch = _make_orchestrator()
    orch._gmail.get_recently_sent.return_value = []
    assert orch.run_sent_batch() == 0
