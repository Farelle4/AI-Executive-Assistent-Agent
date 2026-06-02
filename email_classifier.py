from openai import OpenAI
from dotenv import load_dotenv
import os
import json


load_dotenv()
client = OpenAI(
    api_key=os.getenv("GROQ_API_KEY"),
    base_url="https://api.groq.com/openai/v1"
)

IGNORE_SENDERS = [
    "tiktok",
    "newsletter",
    "no-reply",
    "marketing",
    "testflight"
]


def analyze_email(subject, sender, body):

    # Mark email as suspicious if sender matches common patterns of unwanted emails
    is_suspicious_sender = any(
        word in sender.lower() for word in IGNORE_SENDERS
    )
    
    # Try to extract important informations from the email
    prompt = f"""
You are an AI assistant.

Analyze this email and return ONLY valid JSON.

TASK:
1. Classify intent
2. If it's a meeting, extract date and time

INTENTS:
- meeting_request
- meeting_confirmation
- meeting_cancellation
- information_request
- other

IMPORTANT:
Do NOT classify emails as irrelevant only because the sender contains:
- no-reply
- noreply
- automated systems

Many important meeting confirmations come from such senders (Doctolib, Calendly, Google Calendar).

CRITICAL RULE:
- DO NOT calculate dates
- DO NOT convert dates
- DO NOT interpret dates
- ONLY copy the exact text that refers to time
- Return temporal expressions in English only (e.g. "next Monday", "tomorrow", "Friday 3pm")

Examples:
- "next Monday"
- "tomorrow at 3pm"
- "Friday morning"

If no time is mentioned, return an empty string "".

Return format:
{{
  "intent": "",
  "confidence": 0-1,
  "raw_datetime": "",
  "sender": ""
}}

EMAIL:
Subject: {subject}
From: {sender}
Body: {body}
"""

    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[
            {"role": "system", "content": "Return ONLY JSON."},
            {"role": "user", "content": prompt}
        ],
        temperature=0
    )

    result = response.choices[0].message.content

    # remove markdown fences
    result = result.replace("```json", "").replace("```", "").strip()

    try:
        return json.loads(result)
    except:
        return {
            "intent": "error",
            "raw": result
        }
