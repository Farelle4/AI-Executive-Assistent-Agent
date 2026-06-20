import json
import logging
import os
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv
from langchain.chat_models import init_chat_model

load_dotenv()
from langchain_core.tools import tool
from langchain.agents import create_agent

from src.email_classifier import EmailClassifier
from src.draft_response import DraftResponse
from src.gmail_client import GmailClient
from src.google_calendar import GoogleCalendar
from src.memory_client import MemoryClient

logger = logging.getLogger(__name__)

# Agent instructions — prescriptive order so the LLM follows the pipeline reliably
_SYSTEM_PROMPT = """You are an email processing agent for Farelle Tchoukwe.

When you receive an email as JSON, process it by following these steps in order:

STEP 1 — Dedup: call check_if_processed(email_id).
  → If True: stop immediately, do nothing else.
  → If False: continue.

STEP 2 — User context: call get_user_context(sender).
  → Note is_vip, preferred name, preferred language, and notes.

STEP 3 — Classify: call classify_email(subject, sender, body).
  → Note the intent, raw_date, start_raw_time, end_raw_time, and language.
  → If user_context has a preferred language, use it instead of the detected language.

STEP 4 — Route:
  → If intent is NOT one of [meeting_request, meeting_confirmation, meeting_cancellation]:
      - If is_vip is True: continue to step 5 anyway (VIP always get a reply).
      - Otherwise: call mark_as_read(email_id), call save_to_memory(email_id, subject, sender, intent, "IGNORED"), STOP.
  → Otherwise continue to step 5.

STEP 5 — Check calendar (only if intent != "meeting_cancellation" AND raw_date and start_raw_time are not empty):
  → call check_calendar(subject, raw_date, start_raw_time, end_raw_time)
  → Note is_free, start_iso, end_iso.

STEP 6 — Draft: call generate_draft(sender, subject, body, intent, raw_date, start_raw_time, end_raw_time, language, event_created=<is_free from step 5>).
  → Use the preferred name from user_context in the greeting if available.

STEP 7 — Save draft: call save_draft(to=sender, subject=subject, draft_body=<text from step 6>, thread_id=<thread_id from the email>, message_id=<message_id from the email>, start_iso=<start_iso from step 5 if is_free was True, else "">, end_iso=<end_iso from step 5 if is_free was True, else "">).
  → Always pass thread_id and message_id. Pass start_iso and end_iso only when confirming a meeting (is_free=True).

STEP 8 — Update user memory: ALWAYS call save_user_memory for the sender, even if user_context was already known.
  Use the name extracted from the sender header, the language detected in step 3, the is_vip flag from user_context (default False), and any relevant notes.
  This ensures every contact has an up-to-date profile in memory.

STEP 9 — Mark read: call mark_as_read(email_id).

STEP 10 — Persist: call save_to_memory(email_id, subject, sender, intent, "DRAFTED").

Always complete every step. Never skip save_to_memory at the end.
"""


class AgentOrchestrator:
    """Email processing agent built with LangGraph create_react_agent.

    The LLM decides which tools to call and in what order at runtime,
    guided by the system prompt above.
    """

    def __init__(self):
        llm_model = os.getenv("LLM_MODEL", "groq:llama-3.3-70b-versatile")

        # Separate instances so temperature settings don't bleed between uses
        agent_model = init_chat_model(llm_model, temperature=0)
        classifier_model = init_chat_model(llm_model, temperature=0)
        draft_model = init_chat_model(llm_model, temperature=0.5)

        # Service instances used inside the tool closures below
        self._gmail = GmailClient()
        self._memory = MemoryClient()
        self._calendar = GoogleCalendar()
        _memory = self._memory
        _calendar = self._calendar
        _classifier = EmailClassifier(classifier_model)
        _responder = DraftResponse(draft_model)

        # ── Tool definitions ───────────────────────────────────────────────────
        # Each tool is a closure over the service singletons above.

        @tool
        def check_if_processed(email_id: str) -> bool:
            """Return True if this email was already processed (Supabase dedup)."""
            return _memory.is_processed(email_id)

        @tool
        def classify_email(subject: str, sender: str, body: str) -> dict:
            """Classify the email intent and extract date, time, and language."""
            return _classifier.analyze_email(subject, sender, body)

        @tool
        def check_calendar(
            subject: str,
            raw_date: str,
            start_raw_time: str,
            end_raw_time: str = "",
        ) -> dict:
            """Check calendar availability for a requested time slot.

            Returns {"is_free": bool, "start_iso": str, "end_iso": str}.
            Does NOT create any event.
            """
            start_iso = _responder._build_start_iso(raw_date, start_raw_time)
            if not start_iso:
                logger.warning("check_calendar: could not parse date/time — raw_date=%r start_raw_time=%r", raw_date, start_raw_time)
                return {"is_free": False, "start_iso": "", "end_iso": ""}
            end_iso = _responder._build_start_iso(raw_date, end_raw_time) if end_raw_time else ""
            is_free = _calendar.is_time_free(start_iso)
            logger.info("check_calendar: start_iso=%s is_free=%s", start_iso, is_free)
            return {"is_free": is_free, "start_iso": start_iso, "end_iso": end_iso}

        @tool
        def generate_draft(
            sender: str,
            subject: str,
            body: str,
            intent: str,
            raw_date: str = "",
            start_raw_time: str = "",
            end_raw_time: str = "",
            language: str = "English",
            event_created: bool = False,
        ) -> str:
            """Generate a draft email reply. Returns the email body as plain text."""
            analysis = {
                "intent": intent,
                "raw_date": raw_date,
                "start_raw_time": start_raw_time,
                "end_raw_time": end_raw_time,
                "language": language,
                "event_created": event_created,
            }
            return _responder.generate_draft_response(
                sender=sender, subject=subject, analysis=analysis, body=body,
            )

        @tool
        def save_draft(
            to: str,
            subject: str,
            draft_body: str,
            thread_id: str = "",
            message_id: str = "",
            start_iso: str = "",
            end_iso: str = "",
        ) -> str:
            """Save a reply draft to Gmail inside the original conversation thread.

            Pass thread_id and message_id so the draft appears as a reply.
            Pass start_iso (and optionally end_iso) when confirming a meeting —
            the pending calendar event is saved automatically so it can be created
            once the human sends the email.
            Returns the draft ID.
            """
            draft_id = self._gmail.save_draft(
                to=to,
                subject=f"Re: {subject}",
                body=draft_body,
                thread_id=thread_id,
                message_id=message_id,
            )
            if thread_id and start_iso:
                if not end_iso:
                    end_iso = (datetime.fromisoformat(start_iso) + timedelta(minutes=30)).isoformat()
                _memory.save_pending_event(
                    thread_id=thread_id,
                    subject=subject,
                    start_iso=start_iso,
                    end_iso=end_iso,
                )
                logger.info("save_draft: pending event stored for thread=%s at %s", thread_id, start_iso)
            return draft_id

        @tool
        def mark_as_read(email_id: str) -> str:
            """Remove the UNREAD label from a Gmail message."""
            self._gmail.mark_as_read(email_id)
            return "marked as read"

        @tool
        def save_to_memory(
            email_id: str, subject: str, sender: str, intent: str, status: str
        ) -> str:
            """Persist the processing result to Supabase. status: DRAFTED, IGNORED, or ERROR."""
            _memory.save_email(email_id, subject, sender, intent, status)
            return f"saved with status={status}"

        @tool
        def get_user_context(sender_email: str) -> dict:
            """Return stored preferences and VIP status for a contact.

            Returns {"name": str, "is_vip": bool, "language": str, "notes": str}
            or {} if this contact is unknown.
            """
            return _memory.get_user(sender_email)

        @tool
        def save_user_memory(
            sender_email: str,
            name: str = "",
            is_vip: bool = False,
            language: str = "",
            notes: str = "",
        ) -> str:
            """Store or update preferences for a contact (name, VIP status, language, notes)."""
            _memory.upsert_user(sender_email, name=name, is_vip=is_vip, language=language, notes=notes)
            return f"user memory updated for {sender_email}"

        # Build the ReAct agent: model + tools + system prompt
        self._agent = create_agent(
            model=agent_model,
            name="AI_Executive_Assistant_Agent",
            tools=[
                check_if_processed,
                get_user_context,
                classify_email,
                check_calendar,
                generate_draft,
                save_draft,
                save_user_memory,
                mark_as_read,
                save_to_memory,
            ],
            system_prompt=_SYSTEM_PROMPT,
        )

    def run(self, email: dict) -> None:
        """Process a single email using the LangGraph ReAct agent."""
        logger.info("Processing email id=%s subject='%s'", email.get("id"), email.get("subject"))
        try:
            self._agent.invoke({
                "messages": [{"role": "user", "content": json.dumps(email, ensure_ascii=False)}]
            })
        except Exception as e:
            logger.error("Agent failed for email %s: %s", email.get("id"), e)

    def run_batch(self) -> int:
        """Fetch all unread emails and process each one. Returns number fetched."""
        emails = self._gmail.get_unread_emails(max_results=10)
        logger.info("run_batch: found %d unread emails.", len(emails))
        for email in emails:
            self.run(email)
        return len(emails)

    def run_sent_batch(self) -> int:
        """Scan recently sent emails and create calendar events for confirmed meetings.

        When the human sends a draft reply, Gmail places it in Sent. This method
        checks each sent thread against pending_event records and creates the
        calendar event if a match is found.
        Returns the number of events created.
        """
        sent = self._gmail.get_recently_sent(max_results=20)
        logger.info("run_sent_batch: scanning %d sent messages", len(sent))
        created = 0
        for msg in sent:
            thread_id = msg.get("thread_id", "")
            logger.debug("run_sent_batch: checking thread_id=%s subject=%r", thread_id, msg.get("subject"))
            if not thread_id:
                continue
            pending = self._memory.get_pending_event(thread_id)
            if not pending:
                logger.debug("run_sent_batch: no pending event for thread_id=%s", thread_id)
                continue

            # Only proceed if the sent email was sent AFTER the pending event was created
            pending_created_at = pending.get("created_at", "")
            sent_at = msg.get("sent_at", 0)
            if pending_created_at and sent_at:
                pending_ts = datetime.fromisoformat(pending_created_at).astimezone(timezone.utc).timestamp()
                if sent_at < pending_ts:
                    logger.debug("run_sent_batch: sent email predates pending event, skipping thread_id=%s", thread_id)
                    continue

            logger.info("run_sent_batch: found pending event for thread_id=%s — %s", thread_id, pending)
            try:
                details = json.loads(pending["notes"])
                start_iso = details.get("start_iso", "")
                end_iso = details.get("end_iso", "")
                if not start_iso:
                    logger.warning("run_sent_batch: pending event for thread=%s has no start_iso", thread_id)
                    continue
                self._calendar.create_event(
                    title=pending["subject"],
                    start_iso=start_iso,
                    end_iso=end_iso,
                )
                self._memory.mark_event_created(thread_id)
                logger.info("run_sent_batch: calendar event created for thread=%s ('%s')", thread_id, pending["subject"])
                created += 1
            except Exception as e:
                logger.error("run_sent_batch: failed for thread=%s: %s", thread_id, e)
        return created
