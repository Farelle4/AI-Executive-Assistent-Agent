from googleapiclient.discovery import build
from src.google_calendar_auth import get_creds
from zoneinfo import ZoneInfo
from datetime import datetime, timedelta, timezone

TZ = ZoneInfo("Europe/Berlin")

"""
    Creates and returns an authenticated Google Calendar API service client.

    This function:
    - Retrieves valid OAuth credentials
    - Builds a Google Calendar API v3 service object

    Returns:
        googleapiclient.discovery.Resource: Google Calendar service instance
"""
def get_service():
    creds = get_creds()
    return build("calendar", "v3", credentials=creds)


"""
    Creates a new event in Google Calendar.

    Args:
        title (str): Event title/summary
        start_iso (str): Start datetime in ISO format (must be timezone-aware or valid ISO string)
        end_iso (str, optional): End datetime in ISO format. If not provided, duration is used.
        duration_minutes (int): Default duration if end time is not provided

    Returns:
        dict: Status, event link, and event ID from Google Calendar
"""
def create_event(title: str, start_iso: str, end_iso: str = None, duration_minutes: int = 30):
    service = get_service()

    start = datetime.fromisoformat(start_iso)

    if end_iso:
        end = datetime.fromisoformat(end_iso)
    else:
        end = start + timedelta(minutes=duration_minutes)

    event = {
        "summary": title,
        "start": {
            "dateTime": start.isoformat(),
            "timeZone": "Europe/Berlin",
        },
        "end": {
            "dateTime": end.isoformat(),
            "timeZone": "Europe/Berlin",
        },
    }

    created = service.events().insert(
        calendarId="primary",
        body=event
    ).execute()

    return {
        "status": "success",
        "event_link": created.get("htmlLink"),
        "id": created.get("id")
    }


"""
    Retrieves upcoming events from the user's primary Google Calendar.

    Args:
        max_results (int): Maximum number of events to return

    Returns:
        list: List of upcoming calendar events
"""
def list_events(max_results: int = 5):
    service = get_service()

    now = datetime.utcnow().isoformat() + "Z"

    events = service.events().list(
        calendarId="primary",
        timeMin=now,
        maxResults=max_results,
        singleEvents=True,
        orderBy="startTime"
    ).execute()

    return events.get("items", [])


  
"""
    Checks if a time slot is available in Google Calendar.

    This function:
    - Converts input time to UTC
    - Queries Google Calendar FreeBusy API
    - Detects overlapping events

    Args:
        start_iso (str): Start time in ISO format
        duration_minutes (int): Duration of the meeting

    Returns:
        bool: True if slot is free, False if busy
"""
def is_time_free(start_iso: str, duration_minutes: int = 30):
    service = get_service()

    start = datetime.fromisoformat(start_iso).astimezone(timezone.utc)
    end = start + timedelta(minutes=duration_minutes)

    body = {
        "timeMin": start.isoformat().replace("+00:00", "Z"),
        "timeMax": end.isoformat().replace("+00:00", "Z"),
        "items": [{"id": "primary"}]
    }

    result = service.freebusy().query(body=body).execute()

    busy = result["calendars"]["primary"]["busy"]

    #  IMPORTANT: overlap check, not just len()
    for b in busy:
        b_start = datetime.fromisoformat(b["start"].replace("Z", "+00:00"))
        b_end = datetime.fromisoformat(b["end"].replace("Z", "+00:00"))

        if start < b_end and end > b_start:
            return False

    return True



"""
    Generates available time slots for a specific day.

    This function:
    - Fetches existing events for the day
    - Builds a working window (08:00–18:00)
    - Splits the day into slots
    - Removes conflicting slots

    Args:
        service: Google Calendar API service instance
        target_date (datetime): Date to analyze (timezone-aware)
        duration_minutes (int): Slot duration

    Returns:
        list[str]: List of available ISO datetime slots
"""
def get_free_slots_for_day(service, target_date, duration_minutes=30):
    """
    target_date = datetime (TZ aware)
    """

    target_date = target_date.astimezone(TZ)

    start_day = target_date.replace(hour=8, minute=0, second=0, microsecond=0)
    end_day = target_date.replace(hour=18, minute=0, second=0, microsecond=0)

    events = service.events().list(
        calendarId="primary",
        timeMin=start_day.isoformat(),
        timeMax=end_day.isoformat(),
        singleEvents=True,
        orderBy="startTime"
    ).execute().get("items", [])

    busy = []

    for e in events:
        if "dateTime" in e["start"]:
            busy.append((
                datetime.fromisoformat(e["start"]["dateTime"]).astimezone(TZ),
                datetime.fromisoformat(e["end"]["dateTime"]).astimezone(TZ)
            ))

    slots = []
    cursor = start_day

    while cursor < end_day:
        slot_end = cursor + timedelta(minutes=duration_minutes)

        conflict = any(
            not (slot_end <= b_start or cursor >= b_end)
            for b_start, b_end in busy
        )

        if not conflict:
            slots.append(cursor.astimezone(TZ).isoformat())

        cursor += timedelta(minutes=30)

    return slots