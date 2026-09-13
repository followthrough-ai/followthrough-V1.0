"""Google Calendar, using the token from token.json (scope calendar.events).
The planner gives a spoken time ("friday 10am", "tomorrow 3pm"); this turns it
into a real start/end on the primary calendar in the computer's time zone."""
import re
from datetime import datetime, timedelta
from .base import http, ApiError
from ..config import GCAL_API_URL, EVENT_MINUTES

DAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]

def start_time(expr: str, now: datetime | None = None) -> datetime:
    now = now or datetime.now().astimezone()
    t = expr.lower()
    m = re.search(r"(\d{1,2})(?::(\d{2}))?\s?(am|pm)", t)
    if not m:
        raise ApiError(f"Can't read a time from '{expr}'")
    hour = int(m.group(1)) % 12 + (12 if m.group(3) == "pm" else 0)
    day, named = now.date(), False
    if "tomorrow" in t:
        day, named = day + timedelta(days=1), True
    elif "today" in t:
        named = True
    else:
        for i, d in enumerate(DAYS):
            if d in t:
                day, named = day + timedelta(days=(i - now.weekday()) % 7 or 7), True
                break
    start = datetime(day.year, day.month, day.day, hour, int(m.group(2) or 0), tzinfo=now.tzinfo)
    if not named and start <= now:
        start += timedelta(days=1)        # bare time that already passed today
    return start

class CalendarIntegration:
    name = "calendar"
    def __init__(self, token):
        self.token = token            # GoogleToken
    def execute(self, action, **p):
        assert action == "create_event"
        start = start_time(p["time"])
        body = {"summary": p.get("title", "Meeting"),
                "start": {"dateTime": start.isoformat()},
                "end": {"dateTime": (start + timedelta(minutes=EVENT_MINUTES)).isoformat()}}
        return http("POST", f"{GCAL_API_URL}/calendars/primary/events",
                    {"Authorization": f"Bearer {self.token.access_token()}"}, body)
