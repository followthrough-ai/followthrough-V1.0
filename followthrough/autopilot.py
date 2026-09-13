"""Autopilot: watches Granola for finished meetings and runs the pipeline on each
new one automatically — only for the apps the user allowed, and only sending
for real when the engine is armed. Every meeting becomes one activity entry
(runs/activity.jsonl) that the extension and website show."""
import json, threading, time, traceback, uuid
from datetime import datetime, timedelta, timezone
from . import settings as S
from .config import RUNS_DIR

ACTIVITY_PATH = RUNS_DIR / "activity.jsonl"
STATE_PATH = RUNS_DIR / "autopilot_state.json"
MAX_ACTIVITY = 200
ICON_STATUS = {"applied": "done", "planned": "preview", "failed": "failed",
               "skipped_duplicate": "already_done", "clarification_requested": "question",
               "skipped_not_allowed": "not_allowed"}

def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

class Autopilot:
    def __init__(self, runner):
        self.runner = runner          # web.server.JobRunner (shared busy lock)
        self.state = self._load_state()
        self.activity = self._load_activity()
        self.last_poll = None
        self.last_error = None
        self.next_poll = None
        self._wake = threading.Event()
        self._lock = threading.Lock()
        self._thread = None

    # ----- persistence -----------------------------------------------------------
    def _load_state(self) -> dict:
        if STATE_PATH.exists():
            try:
                return json.loads(STATE_PATH.read_text(encoding="utf-8"))
            except ValueError:
                pass
        return {"processed": {}, "attempts": {}}

    def _save_state(self):
        STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        STATE_PATH.write_text(json.dumps(self.state), encoding="utf-8")

    def _load_activity(self) -> list[dict]:
        if not ACTIVITY_PATH.exists():
            return []
        rows = []
        for line in ACTIVITY_PATH.read_text(encoding="utf-8").splitlines():
            if line.strip():
                try:
                    rows.append(json.loads(line))
                except ValueError:
                    pass
        return rows[-MAX_ACTIVITY:]

    def _record(self, entry: dict):
        with self._lock:
            self.activity.append(entry)
            self.activity = self.activity[-MAX_ACTIVITY:]
            ACTIVITY_PATH.parent.mkdir(parents=True, exist_ok=True)
            with open(ACTIVITY_PATH, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, default=str) + "\n")

    # ----- public ----------------------------------------------------------------
    def start(self):
        if self._thread:
            return
        self._thread = threading.Thread(target=self._loop, name="autopilot", daemon=True)
        self._thread.start()

    def run_now(self):
        """Poll immediately (called from the extension's 'Run now')."""
        self._wake.set()

    def status(self) -> dict:
        s = S.load()
        ap = s["autopilot"]
        return {"enabled": ap["enabled"], "armed": S.is_armed(s),
                "armed_by_env": S.MODE == "real", "poll_minutes": ap["poll_minutes"],
                "only_my_meetings": ap["only_my_meetings"], "enabled_at": ap["enabled_at"],
                "allowed_apps": s["allowed_apps"], "running": bool(self._thread),
                "last_poll": self.last_poll, "next_poll": self.next_poll,
                "last_error": self.last_error, "processed": len(self.state["processed"]),
                "pending_questions": sum(e.get("counts", {}).get("questions", 0)
                                         for e in self.activity[-20:])}

    def recent(self, limit: int = 20, since_id: str | None = None) -> list[dict]:
        with self._lock:
            rows = list(reversed(self.activity))
        if since_id:
            out = []
            for r in rows:
                if r["id"] == since_id:
                    break
                out.append(r)
            return out[:limit]
        return rows[:limit]

    # ----- loop ------------------------------------------------------------------
    def _loop(self):
        while True:
            s = S.load()
            wait = max(1, s["autopilot"]["poll_minutes"]) * 60
            if s["autopilot"]["enabled"]:
                try:
                    self.tick(s)
                    self.last_error = None
                except Exception as e:
                    self.last_error = f"{type(e).__name__}: {e}"
                    traceback.print_exc()
            self.next_poll = _iso(datetime.now(timezone.utc) + timedelta(seconds=wait))
            self._wake.wait(wait)
            self._wake.clear()

    def tick(self, s: dict | None = None):
        """One poll: find finished meetings we haven't handled and process them."""
        from .integrations.granola import GranolaIntegration
        s = s or S.load()
        ap = s["autopilot"]
        self.last_poll = _now()
        enabled_at = ap.get("enabled_at") or self.last_poll
        # A note can finish processing a while after the meeting started, so look
        # a few hours back from the moment autopilot was switched on.
        floor = _iso(datetime.strptime(enabled_at, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
                     - timedelta(hours=6))
        granola = GranolaIntegration()
        notes = granola.list_notes(page_size=30, updated_after=floor)
        notes = [n for n in notes if (n.get("created_at") or "") >= floor]
        for n in sorted(notes, key=lambda x: x.get("created_at") or ""):
            nid = n["id"]
            if nid in self.state["processed"]:
                continue
            if self.state["attempts"].get(nid, 0) >= 5:
                continue
            self._handle(n, s, granola)

    def _handle(self, note: dict, s: dict, granola):
        from .web.server import Job, Busy
        nid, title = note["id"], note.get("title") or "(untitled)"
        owner = ((note.get("owner") or {}).get("email") or "").lower()
        me = (s["profile"].get("email") or "").lower()
        if s["autopilot"]["only_my_meetings"] and me and owner and owner != me:
            self._done(nid)
            self._record(self._entry(note, mode="skipped_owner", items=[],
                                     counts={"commitments": 0, "actions": 0, "questions": 0},
                                     note_text=f"Owned by {owner}, not {me}"))
            return
        job = Job("autopilot", f"Autopilot: {title}")
        try:
            self.runner.start(job, lambda j: self._process(j, note, s, granola))
        except Busy:
            return  # try again next poll
        while job.status in ("queued", "running"):
            time.sleep(0.5)
        if job.status == "error":
            self.state["attempts"][nid] = self.state["attempts"].get(nid, 0) + 1
            self._save_state()
            self._record(self._entry(note, mode="error", items=[],
                                     counts={"commitments": 0, "actions": 0, "questions": 0},
                                     note_text=job.error))

    def _done(self, nid: str):
        self.state["processed"][nid] = _now()
        self.state["attempts"].pop(nid, None)
        self._save_state()

    def _entry(self, note, mode, items, counts, note_text=None, extraction=None, trace=None):
        return {"id": uuid.uuid4().hex[:10], "ts": _now(), "note_id": note["id"],
                "title": note.get("title") or "(untitled)",
                "owner": (note.get("owner") or {}).get("email"), "mode": mode,
                "counts": counts, "items": items, "note": note_text,
                "extraction": extraction, "trace": trace}

    def _process(self, job, note: dict, s: dict, granola):
        from .integrations import build_real_suite
        from .integrations.base import ApiError
        from .pipeline import plan_live, execute_live
        nid = note["id"]
        job.say("Fetching transcript from Granola")
        transcript = granola.get_transcript(nid)
        if not transcript.strip():
            raise ApiError("No transcript yet; will retry next poll")
        allowed = set(s["allowed_apps"])
        armed = S.is_armed(s)
        apps = build_real_suite()
        planned = plan_live(nid, transcript, apps, progress=job.say)
        plans = planned["plans"]
        allowed_ids = {p["commitment_id"] for p in plans if p["type"] == "action" and p["app"] in allowed}
        if armed and allowed_ids:
            job.say(f"Executing {len(allowed_ids)} action(s) for real")
            results = execute_live(planned, apps, only=allowed_ids)
        else:
            results = [{**p, "status": "planned" if p["type"] == "action" else "clarification_requested"}
                       for p in plans if p["type"] != "action" or p["commitment_id"] in allowed_ids]
            planned["trace"].log("run_complete", dry_run=True, autopilot=True)
        by_id = {r["commitment_id"]: r for r in results}
        items, counts = [], {"commitments": len(planned["commitments"]), "actions": 0,
                             "done": 0, "failed": 0, "questions": 0, "not_allowed": 0}
        for p in plans:
            r = by_id.get(p["commitment_id"], p)
            if p["type"] == "action":
                status = r.get("status") if p["commitment_id"] in allowed_ids else "skipped_not_allowed"
                counts["actions" if status != "skipped_not_allowed" else "not_allowed"] += 1
                if status in ("applied", "skipped_duplicate"):
                    counts["done"] += 1
                elif status == "failed":
                    counts["failed"] += 1
                items.append({"type": "action", "app": p["app"], "action": p["action"],
                              "status": status, "text": p.get("commitment_text", ""),
                              "params": p["parameters"], "error": r.get("error"),
                              "outcome_unknown": r.get("outcome_unknown", False)})
            else:
                counts["questions"] += 1
                items.append({"type": "question", "status": "clarification_requested",
                              "text": p.get("commitment_text", ""), "question": p.get("question")})
        mode = "executed" if armed and allowed_ids else "preview"
        self._done(nid)
        self._record(self._entry(note, mode=mode, items=items, counts=counts,
                                 extraction=planned["extraction"], trace=str(planned["trace"].path)))
        job.say(f"Done: {counts['done']} done, {counts['failed']} failed, {counts['questions']} need you")
        return {"note_id": nid, "mode": mode, "counts": counts}
