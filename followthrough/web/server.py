"""Followthrough engine: a small local JSON API over the pipeline, the website in
./static, and (in engine mode) the autopilot loop used by the browser extension.
Stdlib only. Start with: python run.py ui   or   python run.py engine

Safety: binds to 127.0.0.1, only answers requests addressed to localhost, only
accepts JSON POST bodies, and only allows cross-origin calls from browser
extensions (chrome-extension:// / moz-extension://). Real sends require the
engine to be armed (extension switch, or FOLLOWTHROUGH_MODE=real)."""
import hashlib, json, threading, time, traceback, uuid, webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

from .. import config
from .. import settings as S
from ..agents import commitment_extractor
from ..agents.llm_client import llm_disabled
from ..integrations.base import ApiError

STATIC = Path(__file__).resolve().parent / "static"
MAX_BODY = 2_000_000
CONTENT_TYPES = {".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8",
                 ".js": "text/javascript; charset=utf-8", ".svg": "image/svg+xml",
                 ".png": "image/png"}
EXTENSION_ORIGINS = ("chrome-extension://", "moz-extension://")
ENGINE_VERSION = "1.0.0"

class Busy(Exception):
    pass

class HttpError(Exception):
    def __init__(self, code: int, message: str):
        super().__init__(message)
        self.code = code

class Job:
    def __init__(self, kind: str, label: str):
        self.id = uuid.uuid4().hex[:12]
        self.kind, self.label = kind, label
        self.status, self.log, self.result, self.error = "queued", [], None, None
        self.created, self.finished = time.time(), None
        self.state = None            # server-side only (planned run, app clients)
        self._lock = threading.Lock()

    def say(self, msg):
        with self._lock:
            self.log.append({"t": time.time(), "msg": str(msg)})

    def public(self) -> dict:
        with self._lock:
            return {"id": self.id, "kind": self.kind, "label": self.label,
                    "status": self.status, "log": list(self.log), "result": self.result,
                    "error": self.error, "created": self.created, "finished": self.finished}

class JobRunner:
    """One job at a time: the Groq rate-limit budget and the extractor's
    progress hook are shared by the whole process."""
    def __init__(self):
        self.jobs: dict[str, Job] = {}
        self._busy = threading.Lock()

    def active(self) -> Job | None:
        return next((j for j in self.jobs.values() if j.status in ("queued", "running")), None)

    def start(self, job: Job, fn) -> Job:
        if not self._busy.acquire(blocking=False):
            running = self.active()
            raise Busy(f"Busy with '{running.label if running else 'another job'}'. "
                       "Wait for it to finish.")
        self.jobs[job.id] = job

        def work():
            job.status = "running"
            commitment_extractor.progress_hook = job.say
            try:
                job.result = fn(job)
                job.status = "done"
            except ApiError as e:
                job.error, job.status = str(e), "error"
            except Exception as e:
                job.error, job.status = f"{type(e).__name__}: {e}", "error"
                traceback.print_exc()
            finally:
                commitment_extractor.progress_hook = None
                job.finished = time.time()
                self._busy.release()

        threading.Thread(target=work, daemon=True).start()
        return job

RUNNER = JobRunner()
AUTOPILOT = None     # set by serve(autopilot=True)

# --- job bodies ----------------------------------------------------------------

def _plan_view(planned: dict) -> dict:
    plans = planned["plans"]
    actions = sum(1 for p in plans if p["type"] == "action")
    return {"source_id": planned["source_id"], "commitments": planned["commitments"],
            "extraction": planned["extraction"], "plans": plans,
            "trace": str(planned["trace"].path),
            "counts": {"commitments": len(planned["commitments"]), "actions": actions,
                       "questions": len(plans) - actions}}

def _preview(job: Job, note_id: str | None, transcript: str | None) -> dict:
    from ..integrations import build_real_suite
    from ..integrations.granola import GranolaIntegration
    from ..pipeline import plan_live
    if note_id:
        job.say("Fetching transcript from Granola")
        transcript = GranolaIntegration().get_transcript(note_id)
        if not transcript.strip():
            raise ApiError("That note has no transcript yet.")
        source_id = note_id
    else:
        source_id = "text_" + hashlib.sha1(transcript.strip().encode()).hexdigest()[:10]
    job.say("Connecting to Gmail, Calendar, Slack and Airtable")
    apps = build_real_suite()
    planned = plan_live(source_id, transcript, apps, progress=job.say)
    job.state = {"planned": planned, "apps": apps}
    view = _plan_view(planned)
    job.say(f"Done: {view['counts']['actions']} action(s) planned, "
            f"{view['counts']['questions']} need your input")
    return view

def _execute(job: Job, preview: Job, ids: list[str]) -> dict:
    from ..pipeline import execute_live
    planned, apps = preview.state["planned"], preview.state["apps"]
    job.say(f"Executing {len(ids)} action(s) for real")
    results = execute_live(planned, apps, only=set(ids))
    for r in results:
        if r["type"] == "action":
            job.say(f"{r['app']}.{r['action']}: {r['status']}"
                    + (f" ({r['error']})" if r.get("error") else ""))
    return {"results": results, "trace": str(planned["trace"].path)}

def _suite(job: Job, faults: bool, use_llm: bool) -> dict:
    from ..evaluation.regression_runner import run_suite
    job.say(f"Running benchmark ({'Groq' if use_llm else 'rule-based'} extractor, "
            f"{'with' if faults else 'no'} fault injection)")
    def on_result(r):
        job.say(f"{r['fixture_id']}: {r['verdict']} (score {r['overall_score']})")
    if use_llm:
        return run_suite(inject_faults=faults, on_result=on_result)
    with llm_disabled():
        return run_suite(inject_faults=faults, on_result=on_result)

# --- read-only endpoints -----------------------------------------------------------

def _status() -> dict:
    active = RUNNER.active()
    s = S.load()
    return {"engine": "followthrough", "version": ENGINE_VERSION,
            "mode": config.MODE, "armed": S.is_armed(s), "onboarded": s["onboarded"],
            "agent_version": config.AGENT_VERSION,
            "groq_model": config.GROQ_MODEL, "groq_enabled": bool(config.GROQ_API_KEY),
            "autopilot": AUTOPILOT.status() if AUTOPILOT else None,
            "active_job": active.public() if active else None}

def _notes() -> list[dict]:
    from ..integrations.granola import GranolaIntegration
    return [{"id": n["id"], "title": n.get("title") or "", "created_at": n.get("created_at"),
             "owner": (n.get("owner") or {}).get("name"),
             "owner_email": (n.get("owner") or {}).get("email")}
            for n in GranolaIntegration().list_notes(page_size=30)]

def _history() -> list[dict]:
    path = config.RUNS_DIR / "score_history.jsonl"
    if not path.exists():
        return []
    rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    return list(reversed(rows[-20:]))

def _public_settings(s: dict) -> dict:
    return {**s, "armed_effective": S.is_armed(s), "mode": config.MODE}

# --- HTTP ----------------------------------------------------------------------

class Handler(BaseHTTPRequestHandler):
    server_version = "Followthrough"
    allowed_hosts: set[str] = set()

    def log_message(self, fmt, *args):
        pass

    def _cors(self):
        origin = self.headers.get("Origin", "")
        if origin.startswith(EXTENSION_ORIGINS):
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.send_header("Access-Control-Max-Age", "600")
            self.send_header("Vary", "Origin")

    def _send(self, code: int, body: bytes, ctype: str):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self._cors()
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code: int, payload):
        self._send(code, json.dumps(payload, default=str).encode(), "application/json")

    def _guard(self):
        if self.headers.get("Host", "") not in self.allowed_hosts:
            raise HttpError(403, "Requests must be addressed to localhost.")
        origin = self.headers.get("Origin")
        if origin and not origin.startswith(EXTENSION_ORIGINS) and \
                origin not in {f"http://{h}" for h in self.allowed_hosts}:
            raise HttpError(403, "Cross-origin requests are only allowed from the extension.")

    def _body(self) -> dict:
        if not self.headers.get("Content-Type", "").startswith("application/json"):
            raise HttpError(415, "Send a JSON body.")
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_BODY:
            raise HttpError(413, "Request is too large.")
        data = json.loads(self.rfile.read(length) or b"{}")
        if not isinstance(data, dict):
            raise HttpError(400, "Expected a JSON object.")
        return data

    def _handle(self, route):
        try:
            self._guard()
            route()
        except ConnectionError:
            pass    # the browser closed the connection (tab closed, page reloaded)
        except HttpError as e:
            self._json(e.code, {"error": str(e)})
        except Busy as e:
            self._json(409, {"error": str(e)})
        except ApiError as e:
            self._json(502, {"error": str(e)})
        except Exception as e:
            traceback.print_exc()
            self._json(500, {"error": f"{type(e).__name__}: {e}"})

    def do_OPTIONS(self):
        def route():
            if not self.headers.get("Origin", "").startswith(EXTENSION_ORIGINS):
                raise HttpError(403, "Cross-origin requests are only allowed from the extension.")
            self.send_response(204)
            self._cors()
            self.send_header("Content-Length", "0")
            self.end_headers()
        self._handle(route)

    def do_GET(self):
        self._handle(self._get)

    def do_POST(self):
        self._handle(self._post)

    def _get(self):
        url = urlparse(self.path)
        path, qs = url.path, parse_qs(url.query)
        if path == "/api/status":
            return self._json(200, _status())
        if path == "/api/settings":
            return self._json(200, {"settings": _public_settings(S.load())})
        if path == "/api/check":
            from ..health import check_connections
            return self._json(200, {"connections": check_connections()})
        if path == "/api/notes":
            return self._json(200, {"notes": _notes()})
        if path == "/api/history":
            return self._json(200, {"history": _history()})
        if path == "/api/autopilot":
            if not AUTOPILOT:
                return self._json(200, {"autopilot": None,
                                        "error": "Autopilot runs only in engine mode (python run.py engine)."})
            return self._json(200, {"autopilot": AUTOPILOT.status()})
        if path == "/api/activity":
            if not AUTOPILOT:
                return self._json(200, {"activity": []})
            limit = min(100, max(1, int((qs.get("limit") or ["20"])[0])))
            since = (qs.get("since") or [None])[0]
            return self._json(200, {"activity": AUTOPILOT.recent(limit, since)})
        if path.startswith("/api/jobs/"):
            job = RUNNER.jobs.get(path.rsplit("/", 1)[-1])
            if not job:
                raise HttpError(404, "No such job.")
            return self._json(200, job.public())
        if path.startswith("/api/"):
            raise HttpError(404, "Unknown endpoint.")
        self._static(path)

    def _post(self):
        path = urlparse(self.path).path
        data = self._body()
        if path == "/api/settings":
            return self._json(200, {"settings": _public_settings(S.update(data))})
        if path == "/api/autopilot/run-now":
            if not AUTOPILOT:
                raise HttpError(409, "Autopilot runs only in engine mode (python run.py engine).")
            AUTOPILOT.run_now()
            return self._json(202, {"ok": True})
        if path == "/api/preview":
            note_id = str(data.get("note_id") or "").strip() or None
            transcript = str(data.get("transcript") or "")
            if not note_id and not transcript.strip():
                raise HttpError(400, "Choose a Granola note or paste a transcript.")
            label = str(data.get("title") or "").strip() or ("Granola note" if note_id else "Pasted transcript")
            job = RUNNER.start(Job("preview", label),
                               lambda j: _preview(j, note_id, None if note_id else transcript))
            return self._json(202, {"job": job.public()})
        if path == "/api/execute":
            if not S.is_armed():
                raise HttpError(403, "The engine is not armed. Arm autopilot in the extension "
                                     "(or set FOLLOWTHROUGH_MODE=real in .env and restart).")
            preview = RUNNER.jobs.get(str(data.get("preview_job_id") or ""))
            if not preview or preview.kind != "preview" or preview.status != "done" or not preview.state:
                raise HttpError(400, "Run a preview first.")
            valid = {p["commitment_id"] for p in preview.state["planned"]["plans"] if p["type"] == "action"}
            ids = [i for i in dict.fromkeys(data.get("action_ids") or []) if i in valid]
            if not ids:
                raise HttpError(400, "Select at least one planned action.")
            job = RUNNER.start(Job("execute", f"Execute: {preview.label}"),
                               lambda j: _execute(j, preview, ids))
            return self._json(202, {"job": job.public()})
        if path == "/api/suite":
            faults, use_llm = bool(data.get("faults")), bool(data.get("llm"))
            label = f"Benchmark ({'Groq' if use_llm else 'rules'}{', faults' if faults else ''})"
            job = RUNNER.start(Job("suite", label), lambda j: _suite(j, faults, use_llm))
            return self._json(202, {"job": job.public()})
        raise HttpError(404, "Unknown endpoint.")

    def _static(self, path: str):
        name = "index.html" if path in ("", "/") else path.lstrip("/")
        file = (STATIC / name).resolve()
        if STATIC not in file.parents or not file.is_file():
            raise HttpError(404, "Not found.")
        self._send(200, file.read_bytes(),
                   CONTENT_TYPES.get(file.suffix, "application/octet-stream"))

def serve(port: int = 8765, open_browser: bool = True, autopilot: bool = False):
    global AUTOPILOT
    Handler.allowed_hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
    try:
        httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    except OSError as e:
        print(f"Can't start on port {port} ({e}). Is the engine already running? "
              f"Try: python run.py ui {port + 1}")
        return
    if autopilot:
        from ..autopilot import Autopilot
        AUTOPILOT = Autopilot(RUNNER)
        AUTOPILOT.start()
    url = f"http://127.0.0.1:{port}"
    print(f"Followthrough {'engine' if autopilot else 'UI'} running at {url}   "
          f"(armed: {S.is_armed()}; autopilot: {'on' if autopilot and S.load()['autopilot']['enabled'] else 'off'}; "
          f"Ctrl+C to stop)", flush=True)
    if open_browser:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        httpd.server_close()
