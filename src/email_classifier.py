from pydantic import BaseModel, Field
from langchain_core.prompts import ChatPromptTemplate


class EmailClassification(BaseModel):
    """Pydantic schema for structured LLM output from email classification."""
    intent: str = Field(
        description="One of: meeting_request, meeting_confirmation, meeting_cancellation, information_request, other"
    )
    confidence: float = Field(description="Confidence score between 0 and 1")
    raw_date: str = Field(default="", description="Date as written in the email, e.g. 'next Monday', '14 juin'")
    start_raw_time: str = Field(default="", description="Start time as written, e.g. '2pm', '14:00'")
    end_raw_time: str = Field(default="", description="End time as written, e.g. '3pm', '15:00'")
    language: str = Field(default="English", description="Language of the email body, e.g. 'English', 'French'")


_PROMPT = ChatPromptTemplate.from_messages([
    ("system", "You are an email classifier. Analyze the email below and return structured output."),
    ("human", """Classify this email:

Subject: {subject}
From: {sender}
Body: {body}

Rules:
- Do NOT filter based on no-reply senders — meeting confirmations from Doctolib, Calendly, or Google Calendar often come from automated addresses.
- Copy date and time expressions exactly as written — do not calculate, convert, or interpret them.
- Detect the language from the email body (full name in English, e.g. "French", "German").
- If no date or time is mentioned, return empty strings for raw_date and start_raw_time."""),
])


class EmailClassifier:
    """Classifies email intent and extracts meeting date/time via a LangChain LCEL chain."""

    def __init__(self, model):
        # Bind structured output so the response is validated against EmailClassification
        self._chain = _PROMPT | model.with_structured_output(EmailClassification)

    def analyze_email(self, subject: str, sender: str, body: str) -> dict:
        """Return a dict with intent, confidence, raw_date, start_raw_time, end_raw_time, language."""
        result = self._chain.invoke({
            "subject": subject,
            "sender": sender,
            "body": body,
        })
        return result.model_dump()
