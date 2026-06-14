from mcp.server.fastmcp import FastMCP
from src.google_calendar import GoogleCalendar
calendar = GoogleCalendar()


class GoogleCalendarMCPServer:

    def __init__(self, name: str = "google-calendar"):
        self.mcp = FastMCP(name)
        self._register_tools()

    # -------------------------
    # TOOL REGISTRATION
    # -------------------------

    def _register_tools(self):

        @self.mcp.tool()
        def create_calendar_event(
            title: str,
            start_iso: str,
            duration_minutes: int = 30
        ):
            """
            Create a Google Calendar event
            """
            try:
                return calendar.create_event(title, start_iso, None, duration_minutes)
            except Exception as e:
                return {
                    "status": "error",
                    "message": str(e)
                }

        @self.mcp.tool()
        def get_upcoming_events(limit: int = 5):
            """
            Get upcoming Google Calendar events
            """
            try:
                return calendar.list_events(limit)
            except Exception as e:
                return {
                    "status": "error",
                    "message": str(e)
                }

        @self.mcp.tool()
        def ping():
            return {"status": "ok", "service": "google-calendar-mcp"}

    # -------------------------
    # RUN SERVER
    # -------------------------

    def run(self):
        self.mcp.run()


# -------------------------
# ENTRYPOINT
# -------------------------

if __name__ == "__main__":
    server = GoogleCalendarMCPServer()
    server.run()