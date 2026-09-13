"""Deterministic in-memory mock integrations. Same interface as real ones:
   find_*() for read/lookup, execute(action, **params) for side effects."""
from .world import World

class MockBase:
    name = "base"
    def __init__(self, world: World, recorder_hook=None):
        self.world = world
        self.effects: list[dict] = []      # actual side effects that "happened"

    def _apply(self, action, target, params):
        eff = {"app": self.name, "action": action, "target": target, "parameters": params}
        self.effects.append(eff)
        return eff

class MockGmail(MockBase):
    name = "gmail"
    def find_contact(self, name: str):
        n = name.lower()
        return [c for c in self.world.gmail_contacts
                if n in c["name"].lower() or c["name"].lower() in n]
    def execute(self, action, **p):
        assert action == "send_email", f"unsupported gmail action {action}"
        assert p.get("recipient"), "recipient required"
        return self._apply(action, p["recipient"], p)

class MockCalendar(MockBase):
    name = "calendar"
    def execute(self, action, **p):
        assert action == "create_event", f"unsupported calendar action {action}"
        assert p.get("title") and p.get("time"), "title+time required"
        return self._apply(action, p.get("time"), p)

class MockSlack(MockBase):
    name = "slack"
    def find_user(self, name: str):
        n = name.lower()
        return [u for u in self.world.slack_users
                if n in u["name"].lower() or u["name"].lower() in n]
    def find_channel(self, name: str):
        n = name.lower().lstrip("#")
        return [c for c in self.world.slack_channels if n in c["name"].lower()]
    def execute(self, action, **p):
        assert action == "send_message", f"unsupported slack action {action}"
        assert p.get("channel"), "channel required"
        return self._apply(action, p["channel"], p)

class MockAirtable(MockBase):
    name = "airtable"
    def find_record(self, name: str):
        n = name.lower()
        return [r for r in self.world.airtable_records
                if n in r["fields"].get("Name", "").lower()
                or r["fields"].get("Name", "").lower() in n]
    def execute(self, action, **p):
        assert action == "update_record", f"unsupported airtable action {action}"
        assert p.get("record_id"), "record_id required"
        return self._apply(action, p["record_id"], p)

def build_mock_suite(world: World) -> dict:
    return {"gmail": MockGmail(world), "calendar": MockCalendar(world),
            "slack": MockSlack(world), "airtable": MockAirtable(world)}
