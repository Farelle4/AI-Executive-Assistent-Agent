import logging
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from googleapiclient.discovery import build
from src.google_calendar_auth import GoogleAuthClient

logger = logging.getLogger(__name__)


class GoogleCalendar:
    """Wrapper around the Google Calendar API for event management and free/busy queries."""

    TZ = ZoneInfo("Europe/Berlin")
    # Default padding added around in-person events so back-to-back meetings
    # aren't proposed/confirmed without time to travel between them.
    TRAVEL_BUFFER_MINUTES = 30

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

    def _is_in_person(self, event: dict) -> bool:
        """Return True if an event looks like a physical meeting that requires travel time.

        Events carrying a Google Meet/Hangout link or other conference data are
        treated as virtual regardless of their location text. Otherwise, any
        non-empty, non-URL location is treated as in-person.
        """
        if event.get("hangoutLink") or event.get("conferenceData"):
            return False
        location = (event.get("location") or "").strip()
        if not location:
            return False
        return "http" not in location.lower()

    def _get_busy_intervals(
        self, service, time_min: datetime, time_max: datetime, travel_buffer_minutes: int
    ) -> list[tuple[datetime, datetime]]:
        """Return busy (start, end) intervals overlapping [time_min, time_max].

        In-person events are padded by travel_buffer_minutes on both sides so a
        slot right before/after them isn't treated as free.
        """
        events = service.events().list(
            calendarId="primary",
            timeMin=time_min.isoformat(),
            timeMax=time_max.isoformat(),
            singleEvents=True,
            orderBy="startTime",
        ).execute().get("items", [])

        busy = []
        for e in events:
            if "dateTime" not in e["start"]:
                continue
            b_start = datetime.fromisoformat(e["start"]["dateTime"]).astimezone(self.TZ)
            b_end = datetime.fromisoformat(e["end"]["dateTime"]).astimezone(self.TZ)
            if self._is_in_person(e):
                b_start -= timedelta(minutes=travel_buffer_minutes)
                b_end += timedelta(minutes=travel_buffer_minutes)
            busy.append((b_start, b_end))
        return busy

    def is_time_free(
        self,
        start_iso: str,
        end_iso: str = "",
        duration_minutes: int = 30,
        travel_buffer_minutes: int = TRAVEL_BUFFER_MINUTES,
    ) -> bool:
        """Return True if the calendar has no events overlapping [start, end).

        end_iso takes precedence over duration_minutes when provided. A slot
        that starts in the past is never free. Events with a physical location
        are padded by travel_buffer_minutes on both sides so a slot right
        before/after an in-person meeting isn't marked free.
        """
        start = datetime.fromisoformat(start_iso).astimezone(self.TZ)
        end = datetime.fromisoformat(end_iso).astimezone(self.TZ) if end_iso else start + timedelta(minutes=duration_minutes)

        if start < datetime.now(self.TZ):
            logger.info("is_time_free: slot %s is in the past", start)
            return False

        service = self.get_service()
        busy = self._get_busy_intervals(
            service,
            start - timedelta(minutes=travel_buffer_minutes),
            end + timedelta(minutes=travel_buffer_minutes),
            travel_buffer_minutes,
        )
        conflicts = [(b_start, b_end) for b_start, b_end in busy if not (end <= b_start or start >= b_end)]

        if conflicts:
            logger.info("is_time_free: slot %s–%s is BUSY — conflicting events: %s", start, end, conflicts)
            return False
        logger.info("is_time_free: slot %s–%s is free", start, end)
        return True

    def get_free_slots_for_day(
        self,
        service,
        target_date: datetime,
        duration_minutes: int = 30,
        travel_buffer_minutes: int = TRAVEL_BUFFER_MINUTES,
    ) -> list[str]:
        """Return ISO strings of free 30-minute slots between 08:00 and 18:00 on target_date.

        Slots that start before the current time are excluded, so "today" never
        yields a slot in the past. Events with a physical location are padded
        by travel_buffer_minutes on both sides so back-to-back in-person
        meetings aren't proposed without travel time.
        """
        target_date = target_date.astimezone(self.TZ)
        start_day = target_date.replace(hour=8, minute=0, second=0, microsecond=0)
        end_day = target_date.replace(hour=18, minute=0, second=0, microsecond=0)
        now = datetime.now(self.TZ)

        busy = self._get_busy_intervals(
            service,
            start_day - timedelta(minutes=travel_buffer_minutes),
            end_day + timedelta(minutes=travel_buffer_minutes),
            travel_buffer_minutes,
        )

        # Walk through the day in 30-minute increments and collect free slots
        slots = []
        cursor = start_day
        while cursor < end_day:
            slot_end = cursor + timedelta(minutes=duration_minutes)
            if cursor >= now and not any(not (slot_end <= b_start or cursor >= b_end) for b_start, b_end in busy):
                slots.append(cursor.astimezone(self.TZ).isoformat())
            cursor += timedelta(minutes=30)

        return slots
