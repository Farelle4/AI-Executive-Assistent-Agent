from mcp.server.fastmcp import FastMCP
from google_calendar import create_event, list_events

mcp = FastMCP("google-calendar")

# ---------------------------
# CREATE EVENT TOOL
# ---------------------------
@mcp.tool()
def create_calendar_event(
    title: str,
    start_iso: str,
    duration_minutes: int = 30
):
    """
    Create a Google Calendar event
    """
    try:
        return create_event(title, start_iso, duration_minutes)
    except Exception as e:
        return {
            "status": "error",
            "message": str(e)
        }


# ---------------------------
# LIST EVENTS TOOL
# ---------------------------
@mcp.tool()
def get_upcoming_events(limit: int = 5):
    """
    Get upcoming Google Calendar events
    """
    try:
        return list_events(limit)
    except Exception as e:
        return {
            "status": "error",
            "message": str(e)
        }


# ---------------------------
# HEALTH CHECK TOOL
# ---------------------------
@mcp.tool()
def ping():
    return {"status": "ok", "service": "google-calendar-mcp"}


if __name__ == "__main__":
    mcp.run()