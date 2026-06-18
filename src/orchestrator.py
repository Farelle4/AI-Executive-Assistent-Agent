import json
import logging
import os

from langchain.chat_models import init_chat_model
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

STEP 5 — Calendar (only if intent != "meeting_cancellation" AND raw_date and start_raw_time are not empty):
  → call book_calendar(subject, raw_date, start_raw_time, end_raw_time)
  → Note whether event_created is True or False.

STEP 6 — Draft: call generate_draft(sender, subject, body, intent, raw_date, start_raw_time, end_raw_time, language, event_created).
  → Use the preferred name from user_context in the greeting if available.

STEP 7 — Save draft: call save_draft(to=sender, subject=subject, draft_body=<text from step 6>).

STEP 8 — Update user memory: call save_user_memory with any new information learned about this contact
  (name, language, VIP status, or relevant notes). Only call this if you learned something new.

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
        _memory = MemoryClient()
        _classifier = EmailClassifier(classifier_model)
        _responder = DraftResponse(draft_model)
        _calendar = GoogleCalendar()

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
        def book_calendar(
            subject: str,
            raw_date: str,
            start_raw_time: str,
            end_raw_time: str = "",
        ) -> dict:
            """Parse date/time and create a calendar event if the slot is free.

            Returns {"event_created": bool, "start_iso": str}.
            """
            start_iso = _responder._build_start_iso(raw_date, start_raw_time)
            if not start_iso:
                return {"event_created": False, "start_iso": ""}
            end_iso = _responder._build_start_iso(raw_date, end_raw_time) if end_raw_time else ""
            if _calendar.is_time_free(start_iso):
                _calendar.create_event(title=subject, start_iso=start_iso, end_iso=end_iso)
                return {"event_created": True, "start_iso": start_iso}
            return {"event_created": False, "start_iso": start_iso}

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
                sender=sender, subject=subject, analysis=analysis, body=body
            )

        @tool
        def save_draft(to: str, subject: str, draft_body: str) -> str:
            """Save a reply draft to Gmail. Returns the draft ID."""
            return self._gmail.save_draft(to=to, subject=f"Re: {subject}", body=draft_body)

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
            name="AI Executive Assistant Agent",
            tools=[
                check_if_processed,
                get_user_context,
                classify_email,
                book_calendar,
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
