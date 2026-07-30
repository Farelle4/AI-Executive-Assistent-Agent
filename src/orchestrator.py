import json
import logging
import os
from datetime import datetime, timedelta, timezone

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

IMPORTANT: thread_id = "thread_id" field of the email JSON. message_id = "message_id" field.
email_id = "id" field (used only for mark_as_read).

STEP 1 — Dedup + mark read: call check_processed_and_mark_read(thread_id, email_id).
  → If True (already processed): stop immediately, do nothing else.
  → If False: the email was just marked as read to prevent re-processing — continue.

STEP 2 — User context + classify: call get_context_and_classify(sender, subject, body).
  → Note is_vip, preferred name, and notes from user_context.
  → Note the intent, raw_date, start_raw_time, end_raw_time, and language.
  → Always use the language detected from the email body. Never override it.

STEP 3 — Route:
  → If intent is NOT one of [meeting_request, meeting_confirmation, meeting_cancellation]:
      - If is_vip is True: continue to step 4 anyway (VIP always get a reply).
      - Otherwise: call save_to_memory(thread_id, subject, sender, language, intent, "IGNORED"), STOP.
  → Otherwise continue to step 4.

STEP 4 — Check calendar + draft: call check_calendar_and_generate_draft(sender, subject, body, intent, raw_date, start_raw_time, end_raw_time, language).
  → Internally checks calendar availability (only if intent != "meeting_cancellation" AND raw_date
    and start_raw_time are not empty) before generating the draft.
  → Note is_free, start_iso, end_iso, and draft_body.
  → Use the preferred name from user_context in the greeting if available.

STEP 5 — Persist: call save_to_memory(thread_id, subject, sender, language, intent, "DRAFTED").
  → Must happen BEFORE step 6 so the row exists when the pending event is saved.

STEP 6 — Save draft + update user memory: call save_draft_and_update_contact(to=sender, subject=subject, draft_body=<draft_body from step 4>, thread_id=<thread_id from the email>, message_id=<message_id from the email>, start_iso=<start_iso from step 4 if is_free was True, else "">, end_iso=<end_iso from step 4 if is_free was True, else "">, name=<name extracted from the sender header>, is_vip=<is_vip from step 2, default False>, language=language, notes=<any relevant notes>).
  → Always pass thread_id and message_id. Pass start_iso and end_iso only when confirming a meeting (is_free=True).
  → This always updates the contact's stored preferences too, even if user_context was already known.

Always complete every step. Never skip save_to_memory before stopping or before step 6.
"""


class AgentOrchestrator:
    """Email processing agent built with create_agent.

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
        def check_processed_and_mark_read(thread_id: str, email_id: str) -> bool:
            """Dedup-check the thread, then mark the email as read if it's new.

            Combines check_if_processed + mark_as_read, in that order.
            Returns True if this thread was already processed (Supabase dedup) — in that
            case mark_as_read was NOT called and the pipeline must stop.
            """
            if _memory.is_processed(thread_id):
                return True
            self._gmail.mark_as_read(email_id)
            return False

        @tool
        def get_context_and_classify(sender: str, subject: str, body: str) -> dict:
            """Fetch stored contact context, then classify the email intent/date/time/language.

            Combines get_user_context + classify_email, in that order.

            Returns {"user_context": {"name": str, "is_vip": bool, "language": str, "notes": str}
            (or {} if unknown), plus intent, confidence, raw_date, start_raw_time, end_raw_time,
            language from the classification}.
            """
            user_context = _memory.get_user(sender)
            classification = _classifier.analyze_email(subject, sender, body)
            return {"user_context": user_context, **classification}

        @tool
        def check_calendar_and_generate_draft(
            sender: str,
            subject: str,
            body: str,
            intent: str,
            raw_date: str = "",
            start_raw_time: str = "",
            end_raw_time: str = "",
            language: str = "English",
        ) -> dict:
            """Check calendar availability for the requested slot, then generate a draft reply.

            Combines check_calendar + generate_draft, in that order. Calendar availability is only
            checked when intent != "meeting_cancellation" and raw_date/start_raw_time are present
            (same condition as before). Does NOT create any event or save anything.

            Returns {"is_free": bool, "start_iso": str, "end_iso": str, "draft_body": str}.
            """
            # check_calendar
            is_free, start_iso, end_iso = False, "", ""
            if intent != "meeting_cancellation" and raw_date and start_raw_time:
                start_iso = _responder._build_start_iso(raw_date, start_raw_time)
                if not start_iso:
                    logger.warning("check_calendar: could not parse date/time — raw_date=%r start_raw_time=%r", raw_date, start_raw_time)
                    start_iso = ""
                else:
                    end_iso = _responder._build_start_iso(raw_date, end_raw_time) if end_raw_time else ""
                    is_free = _calendar.is_time_free(start_iso, end_iso=end_iso)
                    logger.info("check_calendar: start_iso=%s is_free=%s", start_iso, is_free)

            # generate_draft
            analysis = {
                "intent": intent,
                "raw_date": raw_date if start_iso else "",
                "start_raw_time": start_raw_time if start_iso else "",
                "end_raw_time": end_raw_time,
                "language": language,
                "event_created": is_free,
                "start_iso": start_iso,
            }
            draft_body = _responder.generate_draft_response(
                sender=sender, subject=subject, analysis=analysis, body=body,
            )

            return {"is_free": is_free, "start_iso": start_iso, "end_iso": end_iso, "draft_body": draft_body}

        @tool
        def save_to_memory(
            thread_id: str, subject: str, sender: str, language: str, intent: str, status: str
        ) -> str:
            """Persist the processing result to Supabase. status: DRAFTED, IGNORED, or ERROR.

            thread_id must be the 'thread_id' field from the email JSON.
            """
            if not thread_id:
                logger.warning("save_to_memory called with empty thread_id — skipping")
                return "skipped: empty thread_id"
            _memory.save_email(thread_id, subject, sender, status, language=language, intent=intent)
            return f"saved with status={status}"

        @tool
        def save_draft_and_update_contact(
            to: str,
            subject: str,
            draft_body: str,
            thread_id: str = "",
            message_id: str = "",
            start_iso: str = "",
            end_iso: str = "",
            name: str = "",
            is_vip: bool = False,
            language: str = "",
            notes: str = "",
        ) -> dict:
            """Save a reply draft to Gmail, then update the contact's stored preferences.

            Combines save_draft + save_user_memory, in that order.

            Pass thread_id and message_id so the draft appears as a reply. Pass start_iso (and
            optionally end_iso) when confirming a meeting — the pending calendar event is saved
            automatically so it can be created once the human sends the email.

            Returns {"draft_id": str, "save_user_memory": str}.
            """
            # save_draft
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

            # save_user_memory
            _memory.upsert_user(to, name=name, is_vip=is_vip, language=language, notes=notes)

            return {"draft_id": draft_id, "save_user_memory": f"user memory updated for {to}"}

        # Build the ReAct agent: model + tools + system prompt
        self._agent = create_agent(
            model=agent_model,
            name="AI_Executive_Assistant_Agent",
            tools=[
                check_processed_and_mark_read,
                get_context_and_classify,
                check_calendar_and_generate_draft,
                save_to_memory,
                save_draft_and_update_contact,
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
        finally:
            # Safety net: the LLM is instructed to call mark_as_read as its first
            # tool call, but tool-calling order/completeness isn't enforced — it can
            # skip straight to save_to_memory. If the thread ended up recorded as
            # processed, the email must not be left UNREAD, so enforce it here
            # regardless of whether the LLM actually called mark_as_read itself. A
            # genuine failure before save_to_memory leaves is_processed False, so
            # the email stays unread and gets retried on the next pass.
            thread_id = email.get("thread_id", "")
            if thread_id and self._memory.is_processed(thread_id):
                try:
                    self._gmail.mark_as_read(email["id"])
                except Exception as e:
                    logger.error("Failed to mark email %s as read: %s", email.get("id"), e)

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
        sent = self._gmail.get_recently_sent(max_results=50)
        logger.info("run_sent_batch: scanning %d sent messages", len(sent))

        # Deduplicate by thread_id — keep the most recent message per thread
        seen_threads: dict[str, dict] = {}
        for msg in sent:
            tid = msg.get("thread_id", "")
            if tid and tid not in seen_threads:
                seen_threads[tid] = msg
        logger.debug("run_sent_batch: %d unique threads to check", len(seen_threads))

        created = 0
        for thread_id, msg in seen_threads.items():
            logger.debug("run_sent_batch: checking thread_id=%s subject=%r", thread_id, msg.get("subject"))
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
