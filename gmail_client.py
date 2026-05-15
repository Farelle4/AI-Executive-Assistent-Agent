# import the required libraries
from googleapiclient.discovery import build
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
import os
import os.path
import base64
from bs4 import BeautifulSoup

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
            print("Subject: ", subject)
            print("From: ", sender)
            print("Message: ", body)
            print('\n')

            # Mark the email as read
            service.users().messages().modify(
                userId='me',
                id=msg['id'],
                body={
                    'removeLabelIds': ['UNREAD']
                }
            ).execute()
        except Exception as e:
            print("ERROR:", e)


getEmails()
print("All Emails have been fetched successfully!")