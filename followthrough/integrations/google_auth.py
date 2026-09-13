"""Google OAuth access token from token.json (created by get_google_token.py).
Renews it with the stored refresh_token when it expires. Stdlib only."""
import json, urllib.error, urllib.parse, urllib.request
from datetime import datetime, timedelta, timezone
from .base import ApiError
from ..config import GOOGLE_TOKEN_JSON

class GoogleToken:
    def __init__(self, path=GOOGLE_TOKEN_JSON):
        self.path = path
        if not path.exists():
            raise ApiError(f"{path} not found. Run: python get_google_token.py")
        self.data = json.loads(path.read_text())

    def _expired(self) -> bool:
        exp = self.data.get("expiry")
        if not exp or not self.data.get("token"):
            return True
        dt = datetime.fromisoformat(exp.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return (dt - datetime.now(timezone.utc)).total_seconds() < 60

    def access_token(self) -> str:
        if self._expired():
            self._refresh()
        return self.data["token"]

    def _refresh(self):
        d = self.data
        if not d.get("refresh_token"):
            raise ApiError("token.json has no refresh_token. Run: python get_google_token.py")
        body = urllib.parse.urlencode({
            "client_id": d["client_id"], "client_secret": d["client_secret"],
            "refresh_token": d["refresh_token"], "grant_type": "refresh_token"}).encode()
        req = urllib.request.Request(d.get("token_uri", "https://oauth2.googleapis.com/token"),
                                     data=body, method="POST",
                                     headers={"Content-Type": "application/x-www-form-urlencoded"})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                res = json.loads(r.read())
        except urllib.error.HTTPError as e:
            detail = e.read().decode(errors="replace")[:200]
            raise ApiError(f"Google token renewal failed (HTTP {e.code}): {detail}. "
                           "If it says invalid_grant, run: python get_google_token.py") from e
        expiry = datetime.now(timezone.utc) + timedelta(seconds=res.get("expires_in", 3600))
        d["token"] = res["access_token"]
        d["expiry"] = expiry.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        self.path.write_text(json.dumps(d))
