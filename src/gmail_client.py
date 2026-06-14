from googleapiclient.discovery import build
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from config import SCOPES
from datetime import time
from dateutil import parser
from dateparser import parse
from bs4 import BeautifulSoup
from src.google_calendar import GoogleCalendar
from src.google_calendar_auth import GoogleAuthClient
from src.email_classifier import EmailClassifier
from src.draft_response import DraftResponse

calendar = GoogleCalendar()
calendar_auth = GoogleAuthClient()
classifier = EmailClassifier()
draft_response = DraftResponse()

import json
import re
import os
import os.path
import base64


class GmailClient:

    DEFAULT_HOUR = 9

    WEEKDAYS = {
        "monday": 0,
        "tuesday": 1,
        "wednesday": 2,
        "thursday": 3,
        "friday": 4,
        "saturday": 5,
        "sunday": 6
    }

    NEWSLETTER_HEADERS = {
        "list-unsubscribe",
        "precedence",
        "x-mailer",
    }

    IGNORE_LABELS = {
        "CATEGORY_PROMOTIONS",
        "CATEGORY_SOCIAL",
        "SPAM",
    }

    MARKETING_KEYWORDS = [
        "unsubscribe",
        "newsletter",
        "marketing",
        "promotion",
        "offer",
        "discount",
        "sale",
        "no-reply",
        "noreply",
    ]

    TZ = ZoneInfo("Europe/Berlin")

   
    # =========================================================
    # INIT
    # =========================================================
    def __init__(self):
        pass

    # =========================================================
    # ALL YOUR FUNCTIONS (UNCHANGED LOGIC)
    # =========================================================

    def parse_time_only(self, text):
        if not text:
            return None

        parsed = parse(text)

        if not parsed:
            return None

        return parsed.time()

    def normalize_datetime(self, raw_datetime):
        if not raw_datetime:
            return None

        raw_datetime = raw_datetime.strip().lower()
        now = datetime.now(self.TZ)

        for day_name, target_weekday in self.WEEKDAYS.items():
            if day_name in raw_datetime:

                days_ahead = target_weekday - now.weekday()
                if days_ahead <= 0:
                    days_ahead += 7

                result = now + timedelta(days=days_ahead)

                return result.replace(
                    hour=self.DEFAULT_HOUR,
                    minute=0,
                    second=0,
                    microsecond=0
                )

        parsed = parse(
            raw_datetime,
            settings={
                "RELATIVE_BASE": now,
                "PREFER_DATES_FROM": "future",
                "TIMEZONE": "Europe/Berlin"
            }
        )

        if not parsed:
            return None

        if parsed.hour == 0 and parsed.minute == 0:
            parsed = parsed.replace(hour=self.DEFAULT_HOUR)

        return parsed

    def resolve_datetime(self, date_text, time_text):
        if not date_text or not time_text:
            return None

        base = datetime.now(self.TZ)

        dt = parse(
            f"{date_text} {time_text}",
            languages=["en", "de"],
            settings={
                "RELATIVE_BASE": base,
                "TIMEZONE": "Europe/Berlin",
                "RETURN_AS_TIMEZONE_AWARE": True,
                "PREFER_DATES_FROM": "future"
            }
        )

        return dt

    def clean_date(self, text: str):
        if not text:
            return None

        text = text.lower()
        text = text.replace("den", "")
        text = text.replace(",", " ")
        text = re.sub(r"\s+", " ", text).strip()

        return text

    def parse_time_only_regex(self, text: str):
        if not text:
            return None

        text = text.lower().strip()
        text = text.replace("uhr", "").strip()

        import re
        from datetime import time

        am_pm_match = re.search(r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)", text)
        if am_pm_match:
            hour = int(am_pm_match.group(1))
            minute = int(am_pm_match.group(2) or 0)
            period = am_pm_match.group(3)

            if period == "pm" and hour != 12:
                hour += 12
            if period == "am" and hour == 12:
                hour = 0

            return time(hour=hour, minute=minute)

        match = re.search(r"(\d{1,2})[:.](\d{2})", text)
        if match:
            return time(int(match.group(1)), int(match.group(2)))

        match = re.search(r"(\d{1,2})\s*h", text)
        if match:
            return time(int(match.group(1)), 0)

        return None

    def build_datetime_range(self, analysis):
        raw_date = analysis.get("raw_date")
        start_time = analysis.get("start_raw_time")
        end_time = analysis.get("end_raw_time")

        if not raw_date or not start_time:
            return None, None

        date_part = self.normalize_datetime(self.clean_date(raw_date))
        time_part = self.parse_time_only_regex(start_time)

        if not date_part or not time_part:
            return None, None

        start = datetime.combine(date_part.date(), time_part).replace(tzinfo=self.TZ)

        if end_time:
            end_time_part = self.parse_time_only_regex(end_time)
            if end_time_part:
                end = datetime.combine(date_part.date(), end_time_part).replace(tzinfo=self.TZ)
            else:
                end = start + timedelta(minutes=30)
        else:
            end = start + timedelta(minutes=30)

        return start, end

    def should_ignore_email(self, subject, sender, body, headers, label_ids):
        sender = sender.lower()
        subject = subject.lower()
        body_sample = body[:500].lower()

        if set(label_ids).intersection(self.IGNORE_LABELS):
            return True

        if any(x in sender for x in ["no-reply", "noreply", "newsletter", "marketing"]):
            return True

        text = subject + " " + body_sample
        if any(word in text for word in self.MARKETING_KEYWORDS):
            return True

        header_names = [h["name"].lower() for h in headers]
        if any(h in header_names for h in self.NEWSLETTER_HEADERS):
            return True

        return False

    # return the body of the email, handling different formats (plain text, HTML, multipart)
    def decode_base64(self, data):
        if not data:
            return None
        data = data.replace("-", "+").replace("_", "/")
        return base64.b64decode(data).decode("utf-8", errors="ignore")
    
    # Extract the email body, handling multipart emails and different MIME types
    def extract_body(self, payload):

        def walk(part):
            mime = part.get("mimeType", "")

            # 1. PRIORITY: text/plain
            if mime == "text/plain" and part.get("body", {}).get("data"):
                return self.decode_base64(part["body"]["data"])

            # 2. fallback: text/html
            if mime == "text/html" and part.get("body", {}).get("data"):
                return self.decode_base64(part["body"]["data"])

            # 3. recursion
            if "parts" in part:
                for sub in part["parts"]:
                    result = walk(sub)
                    if result:
                        return result

            return None

        # 1. direct body
        if payload.get("body", {}).get("data"):
            return self.decode_base64(payload["body"]["data"])

        # 2. recursive parts
        if "parts" in payload:
            for part in payload["parts"]:
                result = walk(part)
                if result:
                    return result

        return None

    # Define the SCOPES. If modifying it, delete the token.json file.
    SCOPES = [
        "https://www.googleapis.com/auth/gmail.modify",
        "https://www.googleapis.com/auth/calendar"
    ]


    def clean_email_body(self, html):
        if not html:
            return ""

        soup = BeautifulSoup(html, "html.parser")

        for tag in soup(["script", "style"]):
            tag.decompose()

        text = soup.get_text(" ")

        return " ".join(text.split())

    def extract_event_data(self, text):
        DATE_PATTERNS = [
            r"(\d{2}\.\d{2}\.\d{4})\D*(\d{2}:\d{2})\s*-\s*(\d{2}:\d{2})",
            r"(\d{4}-\d{2}-\d{2})\D*(\d{2}:\d{2})\s*-\s*(\d{2}:\d{2})",
            r"(next\s+\w+.*?\d{1,2}:\d{2})",
        ]

        for pattern in DATE_PATTERNS:
            match = re.search(pattern, text, re.IGNORECASE)
            if not match:
                continue

            groups = match.groups()

            if len(groups) == 3:
                return {
                    "raw_date": groups[0],
                    "start_raw_time": groups[1],
                    "end_raw_time": groups[2],
                }

            if len(groups) == 1:
                return {
                    "raw_date": groups[0],
                    "start_raw_time": None,
                    "end_raw_time": None,
                }

        return None

    # =========================================================
    # MAIN ENTRY (your original pipeline)
    # =========================================================

    # get emails, analyze them with the LLM, and create calendar events for meeting requests and confirmations
    def getEmails(self):
        # Variable creds will store the user access token.
        # If no valid token found, we will create one.
        creds = None

        # The file token.pickle contains the user access token.
        # Check if it exists
        if os.path.exists('token.json'):

            # Read the token from the file and store it in the variable creds
            creds = Credentials.from_authorized_user_file('token.json', SCOPES)

        # If credentials are not available or are invalid, ask the user to log in.
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file('credentials.json', SCOPES)
                creds = flow.run_local_server(port=0)

            # Save the access token in token.json file for the next run
            
            with open('token.json', 'w') as token:
                token.write(creds.to_json())

        # Connect to the Gmail API
        service = build('gmail', 'v1', credentials=creds)

        # request a list of all the messages
        result = service.users().messages().list(
            userId='me',
            labelIds=['UNREAD'],
            maxResults=1
            ).execute()

        messages = result.get('messages', [])

        # A list to store the results
        results = []

        # messages is a list of dictionaries where each dictionary contains a message id.
        # iterate through all the messages
        for msg in messages:
            # Get the message from its id
            txt = service.users().messages().get(userId='me', id=msg['id']).execute()

            subject = ""
            sender = ""
            # Use try-except to avoid any Errors
            try:
                # Get value of 'payload' from dictionary 'txt'
                payload = txt['payload']

                label_ids = txt.get("labelIds", [])
                headers = payload.get("headers", [])

                # Look for Subject and Sender Email in the headers
                for d in headers:
                    if d['name'] == 'Subject':
                        subject = d['value']
                    if d['name'] == 'From':
                        sender = d['value']

                # The Body of the message is in Encrypted format. So, we have to decode it.

                body = "(No body found)"

                payload_body = payload.get("body", {})
                data = payload_body.get("data")

                body = self.extract_body(payload)

                if not body:
                    body = "(No body found)"

                # Add the subject, sender and body to the results list
                results.append({
                    "subject": subject,
                    "from": sender,
                    "body": body
                })

                # Printing the subject, sender's email and message
                print("Subject: ", subject)
                print("From: ", sender)
                #print("Message: ", body)
                print('\n')


                clean_text = self.clean_email_body(body)

                event_data = self.extract_event_data(clean_text)

                analysis = classifier.analyze_email(subject, sender, clean_text)

                if not analysis or analysis.get("intent") == "error":
                    print("Ignored (LLM error)")
                    service.users().messages().modify(
                        userId='me',
                        id=msg['id'],
                        body={'removeLabelIds': ['UNREAD']}
                    ).execute()
                    continue

                valid_intents = {
                    "meeting_request",
                    "meeting_confirmation",
                    "meeting_cancellation"
                }

                intent = analysis.get("intent")
                
                if intent not in valid_intents:
                    print("Ignored non-meeting email")

                    service.users().messages().modify(
                        userId='me',
                        id=msg['id'],
                        body={'removeLabelIds': ['UNREAD']}
                    ).execute()
                    continue

                # MERGE LLM + RULE ENGINE (IMPORTANT)
                if event_data:
                    analysis.update(event_data)

                start, end = self.build_datetime_range(analysis)

                # ---------------- LOGIC ----------------
                
                if intent == "meeting_confirmation":

                    if start:

                        # fallback si end manquant
                        if not end:
                            end = start + timedelta(minutes=30)

                        event_title = analysis.get("title") or subject or "Meeting"

                        if calendar.is_time_free(start.isoformat(), duration_minutes=30):

                            calendar.create_event(
                                title=event_title,
                                start_iso=start.isoformat(),
                                end_iso=end.isoformat()
                            )
                            analysis["event_created"] = True
                            service.users().messages().modify(
                                userId='me',
                                id=msg['id'],
                                body={'removeLabelIds': ['UNREAD']}
                            ).execute()
                            print("+++++++++++ Available → event created ++++++++++++")

                        else:
                            print("------------ BUSY → rejected ------------")

                        print("\n============ AI ANALYSIS ============")
                        print(analysis)
                        print("START:", start)
                        print("END:", end)         


                elif intent == "meeting_request":

                        if start:


                            # override end if absent
                            if not end:
                                end = start + timedelta(minutes=30)

                            if calendar.is_time_free(start.isoformat(), duration_minutes=30):

                                calendar.create_event(
                                    title=subject,
                                    start_iso=start.isoformat(),
                                    end_iso=end.isoformat()
                                )
                                analysis["event_created"] = True

                                service.users().messages().modify(
                                    userId='me',
                                    id=msg['id'],
                                    body={'removeLabelIds': ['UNREAD']}
                                ).execute()

                                print("+++++++++++ Available → event created ++++++++++++")

                            else:
                                print("------------ BUSY → rejected ------------")


                        print("\n============ AI ANALYSIS ============")
                        print(analysis)
                        print("START:", start)
                        print("END:", end)

                        service.users().messages().modify(
                            userId='me',
                            id=msg['id'],
                            body={'removeLabelIds': ['UNREAD']}
                        ).execute()

            except Exception as e:
                print("ERROR:", e)

            draft = draft_response.generate_draft_response(
                sender=analysis.get("sender"),
                subject=subject,
                analysis=analysis
            )

            print("\n========== DRAFT RESPONSE ==========")
            print(draft)
    



# =========================================================
# RUN
# =========================================================

if __name__ == "__main__":
    client = GmailClient()
    client.getEmails()