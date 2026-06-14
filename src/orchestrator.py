from src.gmail_client import GmailClient
from src.email_classifier import EmailClassifier
from src.google_calendar import GoogleCalendar
from src.memory_client import MemoryClient
from src.draft_response import DraftResponse

from langchain_groq import ChatGroq
import os

llm = ChatGroq(
    api_key=os.getenv("GROQ_API_KEY"),
    model="llama3-70b-8192"
)

ORCHESTRATION_PROMPT = """
You are an AI email assistant orchestrator.

You decide the next action based on the email.

Possible actions:
- CLASSIFY
- CHECK_CALENDAR
- DRAFT_RESPONSE
- IGNORE

Rules:
- If email is about meeting → CHECK_CALENDAR
- If informational → CLASSIFY
- If spam/newsletter → IGNORE

Email:
{email}

Return only the action name.
"""

class AgentOrchestrator:

    def __init__(self):
        self.classifier = EmailClassifier()
        self.calendar = GoogleCalendar()
        self.responder = DraftResponse()
        self.memory = MemoryClient()

    def run(self, email):

        # 1. Skip if already processed
        if self.memory.is_processed(email["id"]):
            return

        # 2. LangChain decision
        decision = llm.invoke(
            ORCHESTRATION_PROMPT.format(email=email["body"])
        ).content

        print("Decision:", decision)


        if "IGNORE" in decision:
            return

        elif "CLASSIFY" in decision:
            intent = self.classifier.predict(email["body"])
            print("Intent:", intent)

        elif "CHECK_CALENDAR" in decision:
            availability = self.calendar.check_availability(email)
            print("Availability:", availability)

            response = self.responder.generate(email, availability)

        elif "DRAFT_RESPONSE" in decision:
            response = self.responder.generate(email)

        print("Final response:", response)

        self.memory.save_email(
            message_id=email["id"],
            subject=email["subject"],
            sender=email["from"],
            intent="unknown",
            status=decision
        )

        