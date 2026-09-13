"""Granola public API — meeting notes and transcripts (https://docs.granola.ai).
Needs GRANOLA_API_KEY (grn_..., Business/Enterprise plan, "Personal notes" access).
Only notes that already have an AI summary and transcript are returned."""
import urllib.parse
from .base import http
from ..config import GRANOLA_API_KEY, GRANOLA_API_URL

class GranolaIntegration:
    name = "granola"
    def _h(self): return {"Authorization": f"Bearer {GRANOLA_API_KEY}"}
    def list_notes(self, page_size: int = 10, updated_after: str | None = None,
                   created_after: str | None = None) -> list[dict]:
        qs = {"page_size": min(page_size, 30)}
        if updated_after:
            qs["updated_after"] = updated_after
        if created_after:
            qs["created_after"] = created_after
        res = http("GET", f"{GRANOLA_API_URL}/notes?{urllib.parse.urlencode(qs)}", self._h())
        return res.get("notes", [])
    def get_transcript(self, note_id: str) -> str:
        """The whole transcript as 'Speaker: text' lines, following pagination."""
        lines, cursor = [], None
        while True:
            qs = "page_size=100" + (f"&cursor={urllib.parse.quote(cursor)}" if cursor else "")
            res = http("GET", f"{GRANOLA_API_URL}/notes/{urllib.parse.quote(note_id)}/transcript?{qs}",
                       self._h())
            for seg in res.get("transcript", []):
                text = (seg.get("text") or "").strip()
                if text:
                    lines.append(f"{_speaker(seg.get('speaker') or {})}: {text}")
            cursor = res.get("cursor")
            if not res.get("hasMore") or not cursor:
                return "\n".join(lines)

def _speaker(s: dict) -> str:
    if s.get("name"):
        return s["name"]
    if s.get("attribution") == "me" or s.get("source") == "microphone":
        return "Me"
    return s.get("diarization_label") or "Them"
