# import the required libraries
from googleapiclient.discovery import build
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from datetime import datetime, timedelta
from email_classifier import analyze_email
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


def normalize_datetime(raw_datetime):

    if not raw_datetime:
        return None

    raw_datetime = raw_datetime.strip().lower()
    now = datetime.now()

    # 1. RULE BASED (next Monday etc.)
    for day_name, target_weekday in WEEKDAYS.items():
        if day_name in raw_datetime:

            days_ahead = target_weekday - now.weekday()
            if days_ahead <= 0:
                days_ahead += 7

            result = now + timedelta(days=days_ahead)

            return result.replace(
                hour=DEFAULT_HOUR,
                minute=0,
                second=0,
                microsecond=0
            )

    # 2. DATEPARSER FALLBACK
    parsed = dateparser.parse(
        raw_datetime,
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


# Define the SCOPES. If modifying it, delete the token.json file.
SCOPES = ['https://www.googleapis.com/auth/gmail.modify']


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

    # We can also pass maxResults to get any number of emails. Like this:
    # result = service.users().messages().list(maxResults=200, userId='me').execute()
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

            # Look for Subject and Sender Email in the headers
            for d in headers:
                if d['name'] == 'Subject':
                    subject = d['value']
                if d['name'] == 'From':
                    sender = d['value']

            # The Body of the message is in Encrypted format. So, we have to decode it.
            # Get the data and decode it with base 64 decoder.

            body = "(No body found)"

            payload_body = payload.get("body", {})
            data = payload_body.get("data")

            if not data:
                parts = payload.get("parts", [])
                if parts:
                    data = parts[0]['body'].get('data')

            if data:
                data = data.replace("-", "+").replace("_", "/")
                decoded_data = base64.b64decode(data)
                body = decoded_data.decode('utf-8', errors='ignore')


            # Printing the subject, sender's email and message
            #print("Subject: ", subject)
            #print("From: ", sender)
            #print("Message: ", body)
            #print('\n')

            MAX_BODY_LENGTH = 3000

            clean_body = body[:MAX_BODY_LENGTH]
            analysis = analyze_email(subject, sender, clean_body)

            analysis = analyze_email(subject, sender, clean_body)

            if analysis and analysis.get("intent") != "error":

                dt = normalize_datetime(analysis.get("raw_datetime"))

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