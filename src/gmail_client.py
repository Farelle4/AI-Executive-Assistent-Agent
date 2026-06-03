# import the required libraries
from googleapiclient.discovery import build
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from datetime import datetime, timedelta
from src.google_calendar import create_event, is_time_free
from src.email_classifier import analyze_email
import os
import os.path
import base64
import dateparser

WEEKDAYS = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6
}
DEFAULT_HOUR = 9

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



def normalize_datetime(raw_datetime):
    if not raw_datetime:
        return None

    now = datetime.now()
    text = raw_datetime.strip().lower()

    # 1. cleanup léger
    text = text.replace("den", "").replace("uhr", "").strip()

    # 2. dateparser (gère TOUT: relative + absolute)
    parsed = dateparser.parse(
        text,
        languages=["de", "fr", "en"],
        settings={
            "RELATIVE_BASE": now,
            "PREFER_DATES_FROM": "future",
            "DATE_ORDER": "DMY",
        }
    )

    if not parsed:
        return None

    # 3. fallback heure si absente
    if parsed.hour == 0 and parsed.minute == 0:
        parsed = parsed.replace(hour=9)

    return parsed

    # 2. DATEPARSER FALLBACK
    parsed = dateparser.parse(
        raw_datetime,
        languages=["fr", "de", "en"],
        settings={
            "RELATIVE_BASE": now,
            "PREFER_DATES_FROM": "future",
        }
    )

    if parsed:
        # If hour fails → fallback 09:00
        if parsed.hour == 0 and parsed.minute == 0:
            parsed = parsed.replace(hour=DEFAULT_HOUR)

        return parsed

    return None

def should_ignore_email(subject, sender, body, headers, label_ids):
    sender = sender.lower()
    subject = subject.lower()
    body_sample = body[:500].lower()

    # 1. Labels Gmail
    if set(label_ids).intersection(IGNORE_LABELS):
        return True

    # 2. Sender patterns
    if any(x in sender for x in ["no-reply", "noreply", "newsletter", "marketing"]):
        return True

    # 3. Keywords (subject + body)
    text = subject + " " + body_sample
    if any(word in text for word in MARKETING_KEYWORDS):
        return True

    # 4. Newsletter headers
    header_names = [h["name"].lower() for h in headers]
    if any(h in header_names for h in NEWSLETTER_HEADERS):
        return True

    return False

# return the body of the email, handling different formats (plain text, HTML, multipart)
import base64

def decode_base64(data):
    if not data:
        return None
    data = data.replace("-", "+").replace("_", "/")
    return base64.b64decode(data).decode("utf-8", errors="ignore")


def extract_body(payload):

    def walk(part):
        mime = part.get("mimeType", "")

        # 1. PRIORITY: text/plain
        if mime == "text/plain" and part.get("body", {}).get("data"):
            return decode_base64(part["body"]["data"])

        # 2. fallback: text/html
        if mime == "text/html" and part.get("body", {}).get("data"):
            return decode_base64(part["body"]["data"])

        # 3. recursion
        if "parts" in part:
            for sub in part["parts"]:
                result = walk(sub)
                if result:
                    return result

        return None

    # 1. direct body
    if payload.get("body", {}).get("data"):
        return decode_base64(payload["body"]["data"])

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


def getEmails():
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
            headers = payload['headers']

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

            body = extract_body(payload)

            if not body:
                body = "(No body found)"

            if data:
                data = data.replace("-", "+").replace("_", "/")
                decoded_data = base64.b64decode(data)
                body = decoded_data.decode('utf-8', errors='ignore')


            # Printing the subject, sender's email and message
            print("Subject: ", subject)
            print("From: ", sender)
            #print("Message: ", body)
            print('\n')


            MAX_BODY_LENGTH = 3000
            clean_body = body[:MAX_BODY_LENGTH]

            analysis = analyze_email(subject, sender, clean_body)

            raw = analysis.get("raw_datetime", "").strip()

            if raw:
                dt = normalize_datetime(raw)

                if dt:
                    analysis["datetime_iso"] = dt.isoformat()
                else:
                    analysis["datetime_iso"] = None
            else:
                analysis["datetime_iso"] = None

            valid_intents = {
                "meeting_request",
                "meeting_confirmation",
                "meeting_cancellation"
            }

            if not analysis or analysis.get("intent") == "error":
                print(" LLM error")

                service.users().messages().modify(
                    userId='me',
                    id=msg['id'],
                    body={'removeLabelIds': ['UNREAD']}
                ).execute()

                continue


            intent = analysis.get("intent")
            valid_intents = {"meeting_request", "meeting_confirmation"}

            if intent not in valid_intents:
                print("======= Ignored non-meeting email")

                service.users().messages().modify(
                    userId='me',
                    id=msg['id'],
                    body={'removeLabelIds': ['UNREAD']}
                ).execute()

                continue
            

            dt = normalize_datetime(analysis.get("raw_datetime"))

            if intent == "meeting_confirmation":
                if dt:
                    create_event(
                        title="Meeting confirmation",
                        start_iso=dt.isoformat(),
                        duration_minutes=30
                    )
                    print(" Event created")




            elif intent == "meeting_request":
                if dt:
                    available = is_time_free(dt.isoformat())

                    if available:
                        print("OK available → creating event")

                        result = create_event(
                            title=subject,
                            start_iso=dt.isoformat(),
                            duration_minutes=30
                        )

                        print(" EVENT CREATED:", result)

                    else:
                        print(" REJECT - busy time")




            if analysis and analysis.get("intent") != "error":

                if dt:
                    
                    analysis["datetime"] = dt.strftime("%Y-%m-%d %H:%M:%S")

                print("\n===== AI ANALYSIS =====")
                print(analysis)

                # Mark the email as read
                service.users().messages().modify(
                    userId='me',
                    id=msg['id'],
                    body={'removeLabelIds': ['UNREAD']}
                ).execute()
            else:
                print("Skipping email due to LLM error")

        except Exception as e:
            print("ERROR:", e)


getEmails()