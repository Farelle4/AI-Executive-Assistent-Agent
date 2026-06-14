from openai import OpenAI
from datetime import datetime, timedelta
from dotenv import load_dotenv
from dateparser import parse as dateparse
from dateparser.search import search_dates
from zoneinfo import ZoneInfo
from src.google_calendar import (
    get_free_slots_for_day,
    is_time_free,
    create_event,
    get_service
)
import os

TZ = ZoneInfo("Europe/Berlin")

load_dotenv()
client = OpenAI(
    api_key=os.getenv("GROQ_API_KEY"),
    base_url="https://api.groq.com/openai/v1"
)


# -------------------------
# HELPERS
# -------------------------

def _format_daily_slots(slot_groups):
    if not slot_groups:
        return "No available slots were found."

    lines = []
    for group in slot_groups:
        if group["slots"]:
            lines.append(f"{group['date']}: {', '.join(group['slots'])}")
        else:
            lines.append(f"{group['date']}: no slots available")

    return "\n".join(lines)


def _build_start_iso(raw_date: str, start_time: str):
    if not raw_date or not start_time:
        return None

    combined = f"{raw_date} {start_time}"
    parsed = dateparse(
        combined,
        settings={
            "PREFER_DATES_FROM": "future",
            "TIMEZONE": "Europe/Berlin",
            "RETURN_AS_TIMEZONE_AWARE": True
        }
    )

    if parsed:
        return parsed.astimezone(TZ).isoformat()

    search_result = search_dates(
        combined,
        settings={
            "PREFER_DATES_FROM": "future",
            "TIMEZONE": "Europe/Berlin",
            "RETURN_AS_TIMEZONE_AWARE": True
        }
    )

    if search_result:
        _, parsed = search_result[0]
        if parsed:
            return parsed.astimezone(TZ).isoformat()

    return None


# -------------------------
# GENERATE DRAFT RESPONSE
# -------------------------
def generate_draft_response(sender, subject, analysis):
    sender = sender or "Sender"
    subject = subject or "Meeting request"
    analysis = analysis or {}

    raw_date = analysis.get("raw_date")
    start_time = analysis.get("start_raw_time")
    start_iso = analysis.get("start_iso")
    end_iso = analysis.get("end_iso")

    if not start_iso and raw_date and start_time:
        start_iso = _build_start_iso(raw_date, start_time)

    prompt = None

    # =========================================================
    # EVENT CONFIRMED — TRUST PRIOR EVENT CREATION
    # =========================================================
    if analysis.get("event_created") and start_time and raw_date:
        prompt = f"""
You are Farelle Tchoukwe, responding to {sender} to confirm a meeting.

The meeting has been scheduled for: {start_time} on {raw_date}

Write a short, professional email response in the same language as the sender that:
- Confirms the meeting date and time
- Is brief and professional (like a real person responding)
- Does NOT invent or assume what the meeting is about
- Does NOT add opinions or enthusiasm about projects/opportunities not mentioned
- Maintains CONSISTENT formality level throughout (use either formal or informal, NOT MIXED)
- Ends with your name: Farelle Tchoukwe

Return ONLY the email body.
"""

    # =========================================================
    # NEW COMBINED CASE — INCOMPLETE DATE/TIME (CLARIFICATION ONLY)
    # =========================================================
    elif not raw_date or not start_time or not start_iso:
        prompt = f"""
You are Farelle Tchoukwe, responding to an email from {sender}.

The sender's message is about scheduling, but they haven't provided a specific date and/or time that can be resolved.

Write a short, friendly email response in the same language as the sender that:
- Thanks them for reaching out
- Politely asks for a specific date and time to schedule
- Keeps it brief and natural (like a real person responding)
- Does NOT invent or assume what the meeting is about
- Does NOT add opinions or enthusiasm about projects/opportunities not mentioned
- Maintains CONSISTENT formality level throughout (use either formal or informal, NOT MIXED)
- Ends with your name: Farelle Tchoukwe

Return ONLY the email body.
"""

    # =========================================================
    # PRECISE DATE + TIME PROVIDED
    # =========================================================
    elif start_time and raw_date and start_iso:

        service = get_service()
        if start_iso:
            try:
                is_free = is_time_free(start_iso)
            except Exception:
                is_free = None

            if is_free is False:
                parsed_start = None
                try:
                    parsed_start = datetime.fromisoformat(start_iso).astimezone(TZ)
                except Exception:
                    parsed_start = datetime.now(TZ)

                slots = get_free_slots_for_day(
                    service,
                    target_date=parsed_start,
                    duration_minutes=30
                )
                available_slots_text = _format_daily_slots([
                    {"date": parsed_start.date().isoformat(), "slots": slots}
                ])

                prompt = f"""
You are Farelle Tchoukwe, responding to {sender} about a scheduling conflict.

The requested time {start_time} is not available. Here are alternative times on that day:
{available_slots_text}

Write a short, professional email response in the same language as the sender that:
- Politely explains the requested time is not available
- Suggests the alternative times
- Asks them to pick one that works
- Is brief and friendly (like a real person responding)
- Does NOT invent or assume what the meeting is about
- Maintains CONSISTENT formality level throughout (use either formal or informal, NOT MIXED)
- Ends with your name: Farelle Tchoukwe

Return ONLY the email body.
"""
            elif is_free is True:
                create_event(
                    title=subject,
                    start_iso=start_iso,
                    end_iso=end_iso
                )
                prompt = f"""
You are Farelle Tchoukwe, responding to {sender} to confirm a meeting.

The meeting has been scheduled for: {start_time} on {raw_date}

Write a short, professional email response in the same language as the sender that:
- Confirms the meeting date and time
- Does NOT express enthusiasm or excitement about the meeting
- Is brief and professional (like a real person responding)
- Does NOT invent or assume what the meeting is about
- Does NOT add opinions or enthusiasm about projects/opportunities not mentioned
- Maintains CONSISTENT formality level throughout (use either formal or informal, NOT MIXED)
- Ends with your name: Farelle Tchoukwe

Return ONLY the email body.
"""
            else:
                prompt = f"""
You are Farelle Tchoukwe, responding to an email from {sender}.

The message is about scheduling, but something is unclear.

Write a short, professional email response in the same language as the sender that:
- Thanks them for reaching out
- Politely asks for clarification on the date or time
- Is brief and friendly (like a real person responding)
- Does NOT invent or assume what the meeting is about
- Maintains CONSISTENT formality level throughout (use either formal or informal, NOT MIXED)
- Ends with your name: Farelle Tchoukwe

Return ONLY the email body.
"""

    # =========================================================
    # FALLBACK
    # =========================================================
    else:
        prompt = f"""
You are Farelle Tchoukwe, responding to an email from {sender}.

The message is about scheduling.

Write a short, professional email response in the same language as the sender that:
- Thanks them for reaching out
- Politely asks for a date and time to schedule
- Is brief and friendly (like a real person responding)
- Does NOT invent or assume what the meeting is about
- Maintains CONSISTENT formality level throughout (use either formal or informal, NOT MIXED)
- Ends with your name: Farelle Tchoukwe

Return ONLY the email body.
"""

    if prompt is None:
        prompt = f"""
You are Farelle Tchoukwe, responding to an email from {sender}.

The message is about scheduling.

Write a short, professional email response in the same language as the sender that:
- Thanks them for reaching out
- Politely asks for a date and time
- Is brief and friendly (like a real person responding)
- Does NOT invent or assume what the meeting is about
- Maintains CONSISTENT formality level throughout (use either formal or informal, NOT MIXED)
- Ends with your name: Farelle Tchoukwe

Return ONLY the email body.
"""

    response = client.chat.completions.create(
        model="llama-3.1-8b-instant",
        messages=[
            {"role": "system", "content": "You are a scheduling assistant."},
            {"role": "user", "content": prompt}
        ],
        temperature=0.4
    )

    return response.choices[0].message.content
