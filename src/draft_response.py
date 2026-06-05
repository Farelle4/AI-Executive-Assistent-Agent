from openai import OpenAI
from datetime import datetime
from dotenv import load_dotenv
from src.google_calendar import (
    get_free_slots_for_day,
    is_time_free,
    create_event,
    get_service
)
import os

load_dotenv()
client = OpenAI(
    api_key=os.getenv("GROQ_API_KEY"),
    base_url="https://api.groq.com/openai/v1"
)


# -------------------------
# FUZZY DATE DETECTION
# -------------------------
def is_fuzzy_date(text: str):
    if not text:
        return True

    text = text.lower()
    return any(k in text for k in [
        "next week", "weeks", "month", "weekend", "la semaine",
        "prochaine", "in "
    ])


# -------------------------
# GENERATE DRAFT RESPONSE
# -------------------------
def generate_draft_response(sender, subject, analysis):

    raw_date = analysis.get("raw_date")
    start_time = analysis.get("start_raw_time")
    intent = analysis.get("intent")

    service = get_service()
    slots = []

    date_fuzzy = is_fuzzy_date(raw_date)

    # =========================================================
    # CASE 1 — FUZZY DATE (multi-day planning)
    # =========================================================
    if raw_date and date_fuzzy and not start_time:

        slots = get_free_slots_for_day(
            service,
            target_date=datetime.now(),
            duration_minutes=30
        )

        print("fuzzy date, proposing multiple slots")
        prompt = f"""
You are a professional scheduling assistant.

Write an email reply in the same language as the sender.

CASE: FUZZY DATE (e.g. next week, in 2 weeks)

Context:
Sender: {sender}
Subject: {subject}
Requested date: {raw_date}

Available time slots:
{slots}

Rules:
- The date is vague, so offer flexible options
- Present available slots clearly
- Ask the sender to choose one
- Do NOT invent times
- Be concise and professional
- End the message with this name: Farelle Tchoukwe

Return ONLY the email body.
"""

    # =========================================================
    # CASE 2 — EXACT DATE BUT NO TIME
    # =========================================================
    elif raw_date and not date_fuzzy and not start_time:

        slots = get_free_slots_for_day(
            service,
            target_date=datetime.now(),
            duration_minutes=30
        )

        print("exact date but no time, proposing slots")
        prompt = f"""
You are a professional scheduling assistant.

Write an email reply in the same language as the sender.

CASE: MISSING TIME (exact date provided)

Context:
Sender: {sender}
Subject: {subject}
Date: {raw_date}

Available time slots for this day:
{slots}

Rules:
- The date is precise but time is missing
- Offer only slots for that exact date
- Ask the sender to pick one
- Be concise and professional
- Do NOT invent times
- End the message with this name: Farelle Tchoukwe

Return ONLY the email body.
"""

    # =========================================================
    # If Meeting request
    # =========================================================
    
    elif start_time:
        # =========================================================
        # CASE 3 — BUSY SLOT (REJECT + ALTERNATIVES)
        # =========================================================

        start_iso = analysis.get("start_iso")

        if start_iso and not is_time_free(start_iso):

            slots = get_free_slots_for_day(
                service,
                target_date=datetime.now(),
                duration_minutes=30
            )
            print("busy slot, proposing alternatives")

            prompt = f"""
    You are a professional scheduling assistant.

    Write an email reply in the same language as the sender.

    CASE: REQUESTED SLOT NOT AVAILABLE

    Context:
    Sender: {sender}
    Subject: {subject}
    Requested time: {start_time}

    Alternative available slots:
    {slots}

    Rules:
    - Politely say the requested time is unavailable
    - Suggest alternative slots
    - Ask the sender to choose another time
    - Be concise and professional
    - End the message with this name: Farelle Tchoukwe

    Return ONLY the email body.
    """

        # =========================================================
        # CASE 4 — AVAILABLE SLOT (CONFIRM)
        # =========================================================
        elif start_iso and is_time_free(start_iso):


            create_event(
                title=subject,
                start_iso=analysis.get("start_iso"),
                end_iso=analysis.get("end_iso")
            )

            print("Meeting confirmed at", start_time)
            prompt = f"""
    You are a professional scheduling assistant.

    Write an email reply in the same language as the sender.

    CASE: MEETING CONFIRMED

    Context:
    Sender: {sender}
    Subject: {subject}
    Confirmed time: {start_time}

    Rules:
    - Confirm the meeting politely
    - Be concise and professional
    - Do NOT propose alternatives
    - End the message with this name: Farelle Tchoukwe

    Return ONLY the email body.
    """

    # =========================================================
    # FALLBACK
    # =========================================================
    else:

        print(" asking for details")
        prompt = f"""
You are a professional scheduling assistant. 

Write an email reply in the same language as the sender.

CASE: MISSING INFORMATION

Context:
Sender: {sender}
Subject: {subject}

Rules:
- Ask for missing date and time
- Be polite and concise
- Do NOT propose slots
- End the message with this name: Farelle Tchoukwe

Return ONLY the email body.
"""

    # -------------------------
    # LLM CALL (SINGLE POINT)
    # -------------------------
    response = client.chat.completions.create(
        model="llama-3.1-8b-instant",  
        messages=[
            {"role": "system", "content": "You are a scheduling assistant."},
            {"role": "user", "content": prompt}
        ],
        temperature=0.4
    )

    return response.choices[0].message.content