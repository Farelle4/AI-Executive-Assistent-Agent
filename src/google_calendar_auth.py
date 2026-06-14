import os
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request


class GoogleAuthClient:

    SCOPES = [
        "https://www.googleapis.com/auth/gmail.modify",
        "https://www.googleapis.com/auth/calendar"
    ]

    def __init__(self, token_path="token.json", credentials_path="credentials.json"):
        self.token_path = token_path
        self.credentials_path = credentials_path

    # -------------------------
    # MAIN METHOD
    # -------------------------

    def get_creds(self):

        creds = None

        # Step 1: load existing token
        if os.path.exists(self.token_path):
            creds = Credentials.from_authorized_user_file(
                self.token_path,
                self.SCOPES
            )

        # Step 2: refresh or re-auth
        if not creds or not creds.valid:

            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())

            else:
                flow = InstalledAppFlow.from_client_secrets_file(
                    self.credentials_path,
                    self.SCOPES
                )
                creds = flow.run_local_server(port=0)

            # Step 3: save token
            with open(self.token_path, "w") as f:
                f.write(creds.to_json())

        return creds