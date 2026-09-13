"""Airtable. Needs AIRTABLE_API_KEY (pat..., scopes data.records:read + write),
AIRTABLE_BASE_ID, AIRTABLE_TABLE_NAME. The table needs a "Name" and a "Stage" field."""
import urllib.parse
from .base import http
from ..config import AIRTABLE_API_KEY, AIRTABLE_API_URL, AIRTABLE_BASE_ID, AIRTABLE_TABLE_NAME

class AirtableIntegration:
    name = "airtable"
    def _h(self): return {"Authorization": f"Bearer {AIRTABLE_API_KEY}"}
    def _url(self, rid=""):
        return f"{AIRTABLE_API_URL}/{AIRTABLE_BASE_ID}/{urllib.parse.quote(AIRTABLE_TABLE_NAME)}" \
               + (f"/{rid}" if rid else "")
    def check(self):
        return http("GET", f"{self._url()}?maxRecords=1", self._h())
    def find_record(self, name: str):
        safe = name.replace("\\", "\\\\").replace("'", "\\'")
        formula = urllib.parse.quote(f"SEARCH(LOWER('{safe}'), LOWER({{Name}}))")
        res = http("GET", f"{self._url()}?filterByFormula={formula}", self._h())
        return [{"id": r["id"], "fields": r["fields"]} for r in res.get("records", [])]
    def execute(self, action, **p):
        assert action == "update_record"
        return http("PATCH", self._url(p["record_id"]), self._h(),
                    {"fields": p["fields"]})
