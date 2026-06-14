from supabase import create_client
import os
from dotenv import load_dotenv


class MemoryClient:

    def __init__(self):
        load_dotenv()

        self.SUPABASE_URL = os.getenv("SUPABASE_URL")
        self.SUPABASE_KEY = os.getenv("SUPABASE_KEY")

        if not self.SUPABASE_URL or not self.SUPABASE_KEY:
            raise ValueError("Missing Supabase environment variables")

        self.supabase = create_client(self.SUPABASE_URL, self.SUPABASE_KEY)

    # -------------------------
    # SAVE EMAIL MEMORY
    # -------------------------

    def save_email(self, message_id, subject, sender, intent, status):
        self.supabase.table("email_memory").insert({
            "message_id": message_id,
            "subject": subject,
            "sender": sender,
            "intent": intent,
            "status": status
        }).execute()

    # -------------------------
    # CHECK IF PROCESSED
    # -------------------------

    def is_processed(self, message_id):
        res = self.supabase.table("email_memory") \
            .select("id") \
            .eq("message_id", message_id) \
            .limit(1) \
            .execute()

        return bool(res.data)

    # -------------------------
    # GET FULL MEMORY
    # -------------------------

    def get_memory(self):
        return self.supabase.table("email_memory").select("*").execute().data