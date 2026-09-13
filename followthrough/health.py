"""Connection checks for the real apps (read-only), shared by `run.py check`
and the web UI."""
from . import config

def check_connections() -> list[dict]:
    from .agents.llm_client import complete_json
    from .integrations.base import ApiError, http
    from .integrations.granola import GranolaIntegration
    from .integrations.slack import SlackIntegration
    from .integrations.airtable import AirtableIntegration
    from .integrations.google_auth import GoogleToken

    def groq():
        if not config.GROQ_API_KEY:
            raise ApiError("GROQ_API_KEY is empty")
        complete_json('Return {"ok": true}.', "ping", max_tokens=1024)
        return f"model {config.GROQ_MODEL} answered"
    def granola():
        return f"{len(GranolaIntegration().list_notes(page_size=5))} recent note(s) visible"
    def slack():
        s = SlackIntegration()
        who = s.auth_test()
        ch = s.find_channel("updates") or s.find_channel("general")
        where = f"will post to #{ch[0]['name']}" if ch else "NO #updates or #general channel found"
        return f"bot '{who.get('user')}' in workspace '{who.get('team')}', {where}"
    def airtable():
        n = len(AirtableIntegration().check().get("records", []))
        return (f"base {config.AIRTABLE_BASE_ID}, table '{config.AIRTABLE_TABLE_NAME}' "
                f"reachable ({n} record read)")
    def google():
        h = {"Authorization": f"Bearer {GoogleToken().access_token()}"}
        http("GET", f"{config.GCAL_API_URL}/calendars/primary/events?maxResults=1", h)
        http("GET", "https://people.googleapis.com/v1/people:searchContacts?query=&readMask=names", h)
        return "token valid; Calendar and Contacts reachable (Gmail send is checked on first email)"

    rows = []
    for key, name, fn in [("groq", "Groq", groq), ("granola", "Granola", granola),
                          ("slack", "Slack", slack), ("airtable", "Airtable", airtable),
                          ("google", "Google", google)]:
        try:
            rows.append({"key": key, "name": name, "ok": True, "detail": fn()})
        except Exception as e:
            rows.append({"key": key, "name": name, "ok": False, "detail": str(e)})
    return rows
