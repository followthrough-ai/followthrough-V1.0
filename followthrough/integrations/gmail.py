"""Gmail send + Google Contacts lookup (People API), using the token from
token.json. Scopes: gmail.send, contacts.readonly."""
import base64, urllib.parse
from email.mime.text import MIMEText
from .base import http
from ..config import GMAIL_API_URL

PEOPLE_API_URL = "https://people.googleapis.com/v1"

class GmailIntegration:
    name = "gmail"
    def __init__(self, token):
        self.token = token            # GoogleToken
        self._warmed = False
    def _h(self): return {"Authorization": f"Bearer {self.token.access_token()}"}
    def find_contact(self, name: str):
        mask = "readMask=names,emailAddresses"
        if not self._warmed:
            # The People API wants an empty-query search first to warm its cache.
            http("GET", f"{PEOPLE_API_URL}/people:searchContacts?query=&{mask}", self._h())
            self._warmed = True
        q = urllib.parse.quote(name)
        res = http("GET", f"{PEOPLE_API_URL}/people:searchContacts?query={q}&{mask}", self._h())
        out = []
        for r in res.get("results", []):
            p = r.get("person", {})
            nm = (p.get("names") or [{}])[0].get("displayName", "")
            em = (p.get("emailAddresses") or [{}])[0].get("value")
            if em: out.append({"name": nm, "email": em})
        return out
    def execute(self, action, **p):
        assert action == "send_email"
        subject = p.get("subject", "Follow-up")
        body = p.get("body") or (f"Hi,\n\nAs promised on our call, following up on: {subject}.\n\n"
                                 "Best regards")
        msg = MIMEText(body)
        msg["to"], msg["subject"] = p["recipient"], subject
        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
        return http("POST", f"{GMAIL_API_URL}/users/me/messages/send",
                    self._h(), {"raw": raw})
