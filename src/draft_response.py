import re
from datetime import datetime
from dateparser import parse as dateparse
from dateparser.search import search_dates
from zoneinfo import ZoneInfo
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from src.google_calendar import GoogleCalendar


_DRAFT_PROMPT = ChatPromptTemplate.from_messages([
    ("system", (
        "You are Farelle Tchoukwe. Write email replies as yourself — a real person, not an AI. "
        "You MUST write the entire reply in {language}. "
        "Structure: greeting with the sender's first name, body (1–3 sentences), "
        "a closing line, then your first name 'Farelle' on its own line. "
        "Match the tone and formality of the original email."
    )),
    ("human", "{message}"),
])


class DraftResponse:
    """Generates email draft replies via a LangChain LCEL chain."""

    def __init__(self, model):
        self.TZ = ZoneInfo("Europe/Berlin")
        self._calendar = GoogleCalendar()
        # Chain: prompt template → LLM → plain text
        self._chain = _DRAFT_PROMPT | model | StrOutputParser()

    def _extract_first_name(self, sender: str) -> str:
        """Parse first name from 'First Last <email@domain>' or fall back to local-part of email."""
        match = re.match(r'^([^<\s]+)', sender.strip())
        if match:
            name = match.group(1).strip(" \"'")
            if name and "@" not in name:
                return name
        email_match = re.search(r'([^@<\s]+)@', sender)
        if email_match:
            return email_match.group(1).capitalize()
        return ""

    def _format_daily_slots(self, slot_groups: list) -> str:
        """Format a list of {date, slots} groups into a human-readable string."""
        if not slot_groups:
            return "No available slots were found."
        lines = []
        for group in slot_groups:
            if group["slots"]:
                lines.append(f"{group['date']}: {', '.join(group['slots'])}")
            else:
                lines.append(f"{group['date']}: no slots available")
        return "\n".join(lines)

    def _build_start_iso(self, raw_date: str, start_time: str) -> str | None:
        """Parse a raw date + time string into an ISO 8601 datetime string (Europe/Berlin)."""
        if not raw_date or not start_time:
            return None
        combined = f"{raw_date} {start_time}"
        parsed = dateparse(
            combined,
            settings={"PREFER_DATES_FROM": "future", "TIMEZONE": "Europe/Berlin", "RETURN_AS_TIMEZONE_AWARE": True},
        )
        if parsed:
            return parsed.astimezone(self.TZ).isoformat()
        results = search_dates(
            combined,
            settings={"PREFER_DATES_FROM": "future", "TIMEZONE": "Europe/Berlin", "RETURN_AS_TIMEZONE_AWARE": True},
        )
        if results:
            _, parsed = results[0]
            if parsed:
                return parsed.astimezone(self.TZ).isoformat()
        return None

    def _call_llm(self, message: str, language: str = "English") -> str:
        """Invoke the LCEL draft chain with the given message and target language."""
        return self._chain.invoke({"language": language, "message": message})

    def generate_draft_response(self, sender: str, subject: str, analysis: dict, body: str = "") -> str:
        """Build a context-aware draft reply based on meeting analysis."""
        sender = sender or "Sender"
        subject = subject or "Meeting request"
        analysis = analysis or {}
        body = body or ""

        raw_date = analysis.get("raw_date") or ""
        start_time = analysis.get("start_raw_time") or ""
        start_iso = analysis.get("start_iso") or ""
        end_iso = analysis.get("end_iso") or ""
        language = analysis.get("language") or "English"

        if not start_iso and raw_date and start_time:
            start_iso = self._build_start_iso(raw_date, start_time)

        first_name = self._extract_first_name(sender)
        original_email = f"From: {sender}\nSubject: {subject}\n\n{body}".strip()

        structure_rule = (
            f'1. Greeting using the sender\'s first name: "{first_name}"\n'
            f"2. The message body (1–3 sentences max, natural and direct)\n"
            f"3. A closing line appropriate for {language}\n"
            f"4. Your first name on a new line: Farelle\n\n"
            f"Return only the email body — nothing else."
        )

        # Meeting confirmed: event was already added to the calendar in the orchestrator
        if analysis.get("event_created") and raw_date and start_time:
            return self._call_llm(f"""You received this email:
---
{original_email}
---

You just added the meeting to your calendar: {start_time} on {raw_date}.
Write a short reply confirming this works for you.

{structure_rule}""", language=language)

        # Date/time present: check calendar and either confirm or propose alternatives
        if start_iso and start_time and raw_date:
            try:
                is_free = self._calendar.is_time_free(start_iso)
            except Exception:
                is_free = None

            if is_free is False:
                try:
                    parsed_start = datetime.fromisoformat(start_iso).astimezone(self.TZ)
                except Exception:
                    parsed_start = datetime.now(self.TZ)

                service = self._calendar.get_service()
                slots = self._calendar.get_free_slots_for_day(
                    service, target_date=parsed_start, duration_minutes=30
                )
                available_slots_text = self._format_daily_slots(
                    [{"date": parsed_start.date().isoformat(), "slots": slots}]
                )
                return self._call_llm(f"""You received this email:
---
{original_email}
---

{start_time} on {raw_date} doesn't work for you. You're free at these times instead:
{available_slots_text}

Write a brief reply saying that time doesn't work and suggesting one of those alternatives.

{structure_rule}""", language=language)

            if is_free is True:
                self._calendar.create_event(title=subject, start_iso=start_iso, end_iso=end_iso)
                return self._call_llm(f"""You received this email:
---
{original_email}
---

You just added the meeting to your calendar: {start_time} on {raw_date}.
Write a short reply confirming this works for you.

{structure_rule}""", language=language)

        # No date or time: ask the sender when they're free
        return self._call_llm(f"""You received this email:
---
{original_email}
---

They want to meet but haven't given a specific date and/or time.
Write a short reply asking when they're free.

{structure_rule}""", language=language)
