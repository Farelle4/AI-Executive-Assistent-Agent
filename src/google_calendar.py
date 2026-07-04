import logging
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from googleapiclient.discovery import build
from src.google_calendar_auth import GoogleAuthClient

logger = logging.getLogger(__name__)


class GoogleCalendar:
    """Wrapper around the Google Calendar API for event management and free/busy queries."""

    TZ = ZoneInfo("Europe/Berlin")

    def __init__(self):
        self._auth = GoogleAuthClient()

    def get_service(self):
        """Return an authenticated Google Calendar API service client."""
        return build("calendar", "v3", credentials=self._auth.get_creds())

    def create_event(self, title: str, start_iso: str, end_iso: str | None = None, duration_minutes: int = 30) -> dict:
        """Create a calendar event. If end_iso is omitted, defaults to start + duration_minutes."""
        service = self.get_service()
        start = datetime.fromisoformat(start_iso)
        end = datetime.fromisoformat(end_iso) if end_iso else start + timedelta(minutes=duration_minutes)

        event = {
            "summary": title,
            "start": {"dateTime": start.isoformat(), "timeZone": "Europe/Berlin"},
            "end": {"dateTime": end.isoformat(), "timeZone": "Europe/Berlin"},
        }
        created = service.events().insert(calendarId="primary", body=event).execute()
        return {"status": "success", "event_link": created.get("htmlLink"), "id": created.get("id")}

    def list_events(self, max_results: int = 5) -> list:
        """Return upcoming calendar events ordered by start time."""
        service = self.get_service()
        now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        events = service.events().list(
            calendarId="primary",
            timeMin=now,
            maxResults=max_results,
            singleEvents=True,
            orderBy="startTime",
        ).execute()
        return events.get("items", [])

    def is_time_free(self, start_iso: str, end_iso: str = "", duration_minutes: int = 30) -> bool:
        """Return True if the calendar has no events overlapping [start, end).

        end_iso takes precedence over duration_minutes when provided.
        """
        service = self.get_service()
        start = datetime.fromisoformat(start_iso).astimezone(timezone.utc)
        end = datetime.fromisoformat(end_iso).astimezone(timezone.utc) if end_iso else start + timedelta(minutes=duration_minutes)

        body = {
            "timeMin": start.isoformat().replace("+00:00", "Z"),
            "timeMax": end.isoformat().replace("+00:00", "Z"),
            "items": [{"id": "primary"}],
        }
        result = service.freebusy().query(body=body).execute()
        busy = result["calendars"]["primary"]["busy"]

        if busy:
            logger.info("is_time_free: slot %s–%s is BUSY — conflicting events: %s", start, end, busy)
            return False
        logger.info("is_time_free: slot %s–%s is free", start, end)
        return True

    def get_free_slots_for_day(self, service, target_date: datetime, duration_minutes: int = 30) -> list[str]:
        """Return ISO strings of free 30-minute slots between 08:00 and 18:00 on target_date."""
        target_date = target_date.astimezone(self.TZ)
        start_day = target_date.replace(hour=8, minute=0, second=0, microsecond=0)
        end_day = target_date.replace(hour=18, minute=0, second=0, microsecond=0)

        events = service.events().list(
            calendarId="primary",
            timeMin=start_day.isoformat(),
            timeMax=end_day.isoformat(),
            singleEvents=True,
            orderBy="startTime",
        ).execute().get("items", [])

        # Build list of busy intervals
        busy = [
            (
                datetime.fromisoformat(e["start"]["dateTime"]).astimezone(self.TZ),
                datetime.fromisoformat(e["end"]["dateTime"]).astimezone(self.TZ),
            )
            for e in events
            if "dateTime" in e["start"]
        ]

        # Walk through the day in 30-minute increments and collect free slots
        slots = []
        cursor = start_day
        while cursor < end_day:
            slot_end = cursor + timedelta(minutes=duration_minutes)
            if not any(not (slot_end <= b_start or cursor >= b_end) for b_start, b_end in busy):
                slots.append(cursor.astimezone(self.TZ).isoformat())
            cursor += timedelta(minutes=30)

        return slots
