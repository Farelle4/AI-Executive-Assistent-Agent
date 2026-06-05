import os
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request

SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/calendar"
]

"""
    Handles Google OAuth authentication and returns valid credentials.

    This function:
    - Loads existing credentials from token.json if available
    - Refreshes the token if it is expired
    - Runs full OAuth login flow if no valid credentials exist
    - Saves updated credentials back to token.json for future use

    Returns:
        creds (google.oauth2.credentials.Credentials): Valid Google API credentials
"""

def get_creds():

    # Initialize credentials variable
    creds = None

    # Step 1: Check if a saved token already exists from a previous session
    if os.path.exists("token.json"):
        creds = Credentials.from_authorized_user_file("token.json", SCOPES)

    # Step 2: If credentials are missing or invalid, re-authenticate
    if not creds or not creds.valid:

        # Case 1: Token exists but is expired → try refreshing it
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())

        # Case 2: No valid token → run full OAuth login flow
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                "credentials.json",
                SCOPES
            )
            creds = flow.run_local_server(port=0)

        # Step 3: Save refreshed or newly created credentials
        # This avoids re-authentication on next execution
        with open("token.json", "w") as f:
            f.write(creds.to_json())

    return creds