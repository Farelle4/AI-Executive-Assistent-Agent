import json
import os
import uuid
from dotenv import load_dotenv
from supabase import create_client

_TABLE = "memory"


class MemoryClient:
    """Supabase-backed store using a single 'memory' table.

    record_type='email' — one row per processed email (dedup + audit)
    record_type='user'  — one row per contact (preferences, VIP status)
    """

    def __init__(self):
        load_dotenv()
        url = os.getenv("SUPABASE_URL")
        key = os.getenv("SUPABASE_KEY")
        if not url or not key:
            raise ValueError("Missing SUPABASE_URL or SUPABASE_KEY environment variables")
        self.supabase = create_client(url, key)

    # ── Email records (dedup + audit) ─────────────────────────────────────────

    def save_email(self, message_id: str, subject: str, sender: str, intent: str, status: str) -> None:
        """Insert a processed-email record."""
        self.supabase.table(_TABLE).insert({
            "id": str(uuid.uuid4()),
            "record_type": "email",
            "message_id": message_id,
            "subject": subject,
            "sender": sender,
            "intent": intent,
            "status": status,
        }).execute()

    def is_processed(self, message_id: str) -> bool:
        """Return True if this email has already been processed."""
        res = (
            self.supabase.table(_TABLE)
            .select("id")
            .eq("record_type", "email")
            .eq("message_id", message_id)
            .limit(1)
            .execute()
        )
        return bool(res.data)

    def get_memory(self) -> list:
        """Return all records (useful for inspection/debugging)."""
        return self.supabase.table(_TABLE).select("*").execute().data

    # ── Pending calendar events ────────────────────────────────────────────────

    def save_pending_event(self, thread_id: str, subject: str, start_iso: str, end_iso: str = "") -> None:
        """Store meeting details to create after the human sends the confirmation email."""
        self.supabase.table(_TABLE).insert({
            "id": str(uuid.uuid4()),
            "record_type": "pending_event",
            "message_id": thread_id,
            "subject": subject,
            "notes": json.dumps({"start_iso": start_iso, "end_iso": end_iso}),
            "status": "pending",
        }).execute()

    def get_pending_event(self, thread_id: str) -> dict | None:
        """Return a pending event for this thread, or None if not found."""
        res = (
            self.supabase.table(_TABLE)
            .select("id, subject, notes, created_at")
            .eq("record_type", "pending_event")
            .eq("message_id", thread_id)
            .eq("status", "pending")
            .limit(1)
            .execute()
        )
        return res.data[0] if res.data else None

    def mark_event_created(self, thread_id: str) -> None:
        """Mark a pending event as done after the calendar event is created."""
        self.supabase.table(_TABLE).update({"status": "done"}).eq(
            "record_type", "pending_event"
        ).eq("message_id", thread_id).execute()

    # ── User records (preferences + VIP) ──────────────────────────────────────

    def get_user(self, email: str) -> dict:
        """Return stored preferences for a contact, or {} if unknown.

        Returns keys: name, is_vip, language, notes.
        """
        res = (
            self.supabase.table(_TABLE)
            .select("name, is_vip, language, notes")
            .eq("record_type", "user")
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
        """Insert or update a contact's preferences."""
        exists = (
            self.supabase.table(_TABLE)
            .select("id")
            .eq("record_type", "user")
            .eq("email", email)
            .limit(1)
            .execute()
        ).data

        payload = {
            "name": name,
            "is_vip": is_vip,
            "language": language,
            "notes": notes,
        }

        if exists:
            self.supabase.table(_TABLE).update(payload).eq("record_type", "user").eq("email", email).execute()
        else:
            self.supabase.table(_TABLE).insert({
                "id": str(uuid.uuid4()),
                "record_type": "user",
                "email": email,
                **payload,
            }).execute()
