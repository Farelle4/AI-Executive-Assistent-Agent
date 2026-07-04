import base64
import email.mime.text
import logging
from googleapiclient.discovery import build
from bs4 import BeautifulSoup
from src.google_calendar_auth import GoogleAuthClient

logger = logging.getLogger(__name__)

# Emails in these Gmail label categories are silently skipped (promotions, social, spam)
IGNORE_LABELS = {"CATEGORY_PROMOTIONS", "CATEGORY_SOCIAL", "SPAM"}


class GmailClient:
    """Thin wrapper around the Gmail API for fetching, reading, and drafting emails."""

    def __init__(self):
        self._auth = GoogleAuthClient()

    def get_service(self):
        """Return an authenticated Gmail API service client."""
        creds = self._auth.get_creds()
        return build("gmail", "v1", credentials=creds)

    def get_unread_emails(self, max_results: int = 10) -> list[dict]:
        """Fetch unread emails, skipping promotion/spam labels.

        Returns a list of dicts: {id, subject, from, body}.
        """
        service = self.get_service()
        result = service.users().messages().list(
            userId="me", labelIds=["UNREAD"], maxResults=max_results
        ).execute()

        emails = []
        for msg in result.get("messages", []):
            try:
                txt = service.users().messages().get(userId="me", id=msg["id"]).execute()
                payload = txt["payload"]
                headers = payload.get("headers", [])
                label_ids = set(txt.get("labelIds", []))

                # Skip emails in ignored label categories
                if label_ids & IGNORE_LABELS:
                    self.mark_as_read(msg["id"])
                    continue

                subject = next((h["value"] for h in headers if h["name"] == "Subject"), "")
                sender = next((h["value"] for h in headers if h["name"] == "From"), "")
                date = next((h["value"] for h in headers if h["name"] == "Date"), "")
                message_id = next((h["value"] for h in headers if h["name"] == "Message-ID"), "").strip()
                if message_id and not message_id.startswith("<"):
                    message_id = f"<{message_id}>"
                body = self.clean_email_body(self.extract_body(payload) or "")
                emails.append({
                    "id": msg["id"],
                    "thread_id": txt.get("threadId", ""),
                    "message_id": message_id,
                    "subject": subject,
                    "from": sender,
                    "date": date,
                    "body": body,
                })
            except Exception as e:
                logger.warning("Failed to parse message %s: %s", msg.get("id"), e)

        return emails

    def mark_as_read(self, msg_id: str) -> None:
        """Remove the UNREAD label from an email."""
        service = self.get_service()
        service.users().messages().modify(
            userId="me", id=msg_id, body={"removeLabelIds": ["UNREAD"]}
        ).execute()

    def save_draft(
        self,
        to: str,
        subject: str,
        body: str,
        thread_id: str = "",
        message_id: str = "",
    ) -> str:
        """Create a Gmail draft and return its draft ID.

        When thread_id and message_id are provided the draft is attached to the
        existing conversation thread so Gmail shows it as a reply, not a new message.
        """
        service = self.get_service()
        msg = email.mime.text.MIMEText(body, "plain", "utf-8")
        msg["To"] = to
        msg["Subject"] = subject
        if message_id:
            msg["In-Reply-To"] = message_id
            msg["References"] = message_id
        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("ascii")
        message_body: dict = {"raw": raw}
        if thread_id:
            message_body["threadId"] = thread_id
        draft = service.users().drafts().create(
            userId="me", body={"message": message_body}
        ).execute()
        return draft["id"]

    def get_recently_sent(self, max_results: int = 20) -> list[dict]:
        """Return recently sent messages as {id, thread_id, subject}."""
        service = self.get_service()
        result = service.users().messages().list(
            userId="me", labelIds=["SENT"], maxResults=max_results
        ).execute()
        msgs = []
        for msg in result.get("messages", []):
            try:
                txt = service.users().messages().get(
                    userId="me", id=msg["id"], format="metadata",
                    metadataHeaders=["Subject"],
                ).execute()
                subject = next(
                    (h["value"] for h in txt.get("payload", {}).get("headers", []) if h["name"] == "Subject"), ""
                )
                sent_at = int(txt.get("internalDate", 0)) / 1000  # ms → seconds (Unix timestamp)
                msgs.append({"id": msg["id"], "thread_id": txt.get("threadId", ""), "subject": subject, "sent_at": sent_at})
            except Exception as e:
                logger.warning("Failed to parse sent message %s: %s", msg.get("id"), e)
        return msgs

    # ── Body extraction helpers ────────────────────────────────────────────────

    def decode_base64(self, data: str) -> str | None:
        """Decode Gmail's URL-safe base64 body data into a UTF-8 string."""
        if not data:
            return None
        data = data.replace("-", "+").replace("_", "/")
        return base64.b64decode(data).decode("utf-8", errors="ignore")

    def extract_body(self, payload: dict) -> str | None:
        """Recursively extract plain-text (or HTML fallback) body from a Gmail message payload."""
        def walk(part):
            mime = part.get("mimeType", "")
            if mime == "text/plain" and part.get("body", {}).get("data"):
                return self.decode_base64(part["body"]["data"])
            if mime == "text/html" and part.get("body", {}).get("data"):
                return self.decode_base64(part["body"]["data"])
            for sub in part.get("parts", []):
                result = walk(sub)
                if result:
                    return result
            return None

        if payload.get("body", {}).get("data"):
            return self.decode_base64(payload["body"]["data"])
        for part in payload.get("parts", []):
            result = walk(part)
            if result:
                return result
        return None

    def clean_email_body(self, html: str) -> str:
        """Strip HTML tags and collapse whitespace into clean plain text."""
        if not html:
            return ""
        soup = BeautifulSoup(html, "html.parser")
        for tag in soup(["script", "style"]):
            tag.decompose()
        return " ".join(soup.get_text(" ").split())
