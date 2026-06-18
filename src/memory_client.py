import os
from dotenv import load_dotenv
from supabase import create_client


class MemoryClient:
    """Supabase-backed store for processed email records.

    Used for deduplication: before processing an email, check is_processed().
    After processing, call save_email() to record the result.
    """

    def __init__(self):
        load_dotenv()
        url = os.getenv("SUPABASE_URL")
        key = os.getenv("SUPABASE_KEY")
        if not url or not key:
            raise ValueError("Missing SUPABASE_URL or SUPABASE_KEY environment variables")
        self.supabase = create_client(url, key)

    def save_email(self, message_id: str, subject: str, sender: str, intent: str, status: str) -> None:
        """Insert a processed email record into the email_memory table."""
        self.supabase.table("email_memory").insert({
            "message_id": message_id,
            "subject": subject,
            "sender": sender,
            "intent": intent,
            "status": status,
        }).execute()

    def is_processed(self, message_id: str) -> bool:
        """Return True if this email has already been processed (exists in email_memory)."""
        res = (
            self.supabase.table("email_memory")
            .select("id")
            .eq("message_id", message_id)
            .limit(1)
            .execute()
        )
        return bool(res.data)

    def get_memory(self) -> list:
        """Return all records from email_memory (useful for inspection/debugging)."""
        return self.supabase.table("email_memory").select("*").execute().data

    # ── User memory (preferences + VIP status) ────────────────────────────────

    def get_user(self, email: str) -> dict:
        """Return stored preferences for a contact, or {} if unknown.

        Returns keys: name, is_vip, language, notes.
        """
        res = (
            self.supabase.table("user_memory")
            .select("name, is_vip, language, notes")
            .eq("email", email)
            .limit(1)
            .execute()
        )
        return res.data[0] if res.data else {}

    def upsert_user(
        self,
        email: str,
        name: str = "",
        is_vip: bool = False,
        language: str = "",
        notes: str = "",
    ) -> None:
        """Insert or update a user's preferences (upsert on email)."""
        self.supabase.table("user_memory").upsert(
            {
                "email": email,
                "name": name,
                "is_vip": is_vip,
                "language": language,
                "notes": notes,
            },
            on_conflict="email",
        ).execute()
