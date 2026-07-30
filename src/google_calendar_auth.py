import os
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request


class GoogleAuthClient:
    """Handles OAuth 2.0 authentication for Google APIs (Gmail + Calendar).

    Loads a saved token from token.json if available, refreshes it when expired,
    or runs the OAuth browser flow to create a new one.
    """

    # Scopes required for Gmail read/write and Calendar read/write
    SCOPES = [
        "https://www.googleapis.com/auth/gmail.modify",
        "https://www.googleapis.com/auth/calendar",
    ]

    def __init__(self, token_path: str = "token.json", credentials_path: str = "credentials.json"):
        self.token_path = token_path
        self.credentials_path = credentials_path

    def get_creds(self) -> Credentials:
        """Return valid Google credentials, refreshing or re-authenticating as needed."""
        creds = None

        # Load existing token if available
        if os.path.exists(self.token_path):
            creds = Credentials.from_authorized_user_file(self.token_path, self.SCOPES)

        # Refresh expired token or start a new OAuth flow
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file(self.credentials_path, self.SCOPES)
                creds = flow.run_local_server(port=0)

            # Persist the token for future runs
            with open(self.token_path, "w") as f:
                f.write(creds.to_json())

        return creds
