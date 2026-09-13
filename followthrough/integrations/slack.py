"""Slack Web API. Needs SLACK_BOT_TOKEN (xoxb-...), bot scopes:
chat:write, chat:write.public, users:read, channels:read."""
from .base import http, ApiError
from ..config import SLACK_BOT_TOKEN, SLACK_API_URL

class SlackIntegration:
    name = "slack"
    def _h(self): return {"Authorization": f"Bearer {SLACK_BOT_TOKEN}"}
    def _call(self, method: str, path: str, body: dict | None = None):
        # Slack reports most failures as HTTP 200 with {"ok": false, "error": "..."}.
        res = http(method, f"{SLACK_API_URL}/{path}", self._h(), body)
        if not res.get("ok"):
            raise ApiError(f"Slack {path.split('?')[0]} failed: {res.get('error', 'unknown_error')}")
        return res
    def auth_test(self):
        return self._call("GET", "auth.test")
    def find_user(self, name: str):
        res = self._call("GET", "users.list?limit=1000")
        n = name.lower()
        out = []
        for m in res.get("members", []):
            if m.get("deleted") or m.get("is_bot"):
                continue
            full = m.get("real_name") or m.get("profile", {}).get("real_name") or m["name"]
            if n in full.lower():
                out.append({"name": full, "id": m["id"]})
        return out
    def find_channel(self, name: str):
        res = self._call("GET", "conversations.list?types=public_channel&exclude_archived=true&limit=1000")
        n = name.lower().lstrip("#")
        # New workspaces name the default channel "#all-<workspace>", not "#general".
        return [{"name": c["name"], "id": c["id"]}
                for c in res.get("channels", [])
                if n in c["name"].lower() or (n == "general" and c.get("is_general"))]
    def execute(self, action, **p):
        assert action == "send_message"
        text = p.get("message", "")
        if p.get("mention"):
            text = f"<@{p['mention']}> {text}"
        return self._call("POST", "chat.postMessage", {"channel": p["channel"], "text": text})
