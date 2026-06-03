from googleapiclient.discovery import build
from src.google_calendar_auth import get_creds
from zoneinfo import ZoneInfo
from datetime import datetime, timedelta, timezone

def get_service():
    creds = get_creds()
    return build("calendar", "v3", credentials=creds)


def create_event(title: str, start_iso: str, duration_minutes: int = 30):
    service = get_service()

    start = datetime.fromisoformat(start_iso)
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

    # 🔥 IMPORTANT: overlap check, pas juste len()
    for b in busy:
        b_start = datetime.fromisoformat(b["start"].replace("Z", "+00:00"))
        b_end = datetime.fromisoformat(b["end"].replace("Z", "+00:00"))

        if start < b_end and end > b_start:
            return False

    return True