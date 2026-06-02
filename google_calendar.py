from googleapiclient.discovery import build
from google_calendar_auth import get_creds
from datetime import datetime, timedelta


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

    start = datetime.fromisoformat(start_iso)
    end = start + timedelta(minutes=duration_minutes)

    body = {
        "timeMin": start.isoformat() + "Z",
        "timeMax": end.isoformat() + "Z",
        "items": [{"id": "primary"}]
    }

    events_result = service.freebusy().query(body=body).execute()
    busy_times = events_result["calendars"]["primary"]["busy"]

    return len(busy_times) == 0