from openai import OpenAI

client = OpenAI()


def generate_draft_response(
    sender,
    subject,
    analysis,
    slots
):
    """
    slots = [
        "2026-06-07 09:00",
        "2026-06-07 10:30",
        ...
    ]
    """

    slots_text = "\n".join(f"- {s}" for s in slots)

    prompt = f"""
You are an assistant that helps scheduling meetings.

Write a professional email reply in the same language as the sender.

Context:
Sender: {sender}
Subject: {subject}

Extracted info:
- Intent: {analysis.get("intent")}
- Date: {analysis.get("raw_date")}
- Time: {analysis.get("start_raw_time")}

Available time slots from calendar:
{slots_text}

Rules:
- Be polite and concise
- If a date is known, mention it
- Suggest the available slots clearly
- Ask the sender to choose one slot
- Do NOT invent new times

Return ONLY the email body.
"""

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": "You are a scheduling assistant."},
            {"role": "user", "content": prompt}
        ],
        temperature=0.4
    )

    return response.choices[0].message.content