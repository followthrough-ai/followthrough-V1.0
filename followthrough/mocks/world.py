"""Seeded 'world' each fixture runs against: contacts, Slack users/channels,
calendars, Airtable records. This is the search space the agent may query.
Gold labels are NOT here — the agent never sees them."""
import json
from pathlib import Path

class World:
    def __init__(self, data: dict):
        self.gmail_contacts = data.get("gmail_contacts", [])     # {name, email}
        self.slack_users = data.get("slack_users", [])           # {name, id}
        self.slack_channels = data.get("slack_channels", [])     # {name, id}
        self.airtable_records = data.get("airtable_records", []) # {id, fields{Name,...}}

    @classmethod
    def load(cls, path: Path):
        return cls(json.loads(Path(path).read_text()))
