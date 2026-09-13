"""Real app integrations, same interface as mocks.apps.build_mock_suite()."""

def build_real_suite() -> dict:
    from .google_auth import GoogleToken
    from .gmail import GmailIntegration
    from .gcalendar import CalendarIntegration
    from .slack import SlackIntegration
    from .airtable import AirtableIntegration
    token = GoogleToken()
    return {"gmail": GmailIntegration(token), "calendar": CalendarIntegration(token),
            "slack": SlackIntegration(), "airtable": AirtableIntegration()}
