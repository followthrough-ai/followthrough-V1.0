"""One trace per run: append-only JSONL, replayable, every step recorded."""
import json, time, uuid
from pathlib import Path
from ..config import RUNS_DIR

class Trace:
    def __init__(self, fixture_id: str, run_id: str | None = None, agent_version: str = "v1.0"):
        self.run_id = run_id or f"run_{time.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
        self.fixture_id = fixture_id
        self.agent_version = agent_version
        self.dir = Path(RUNS_DIR) / self.run_id
        self.dir.mkdir(parents=True, exist_ok=True)
        self.path = self.dir / "trace.jsonl"

    def log(self, step: str, status: str = "ok", **payload):
        rec = {
            "ts": time.time(),
            "run_id": self.run_id,
            "fixture_id": self.fixture_id,
            "agent_version": self.agent_version,
            "step": step,
            "status": status,
            **payload,
        }
        with open(self.path, "a") as f:
            f.write(json.dumps(rec, default=str) + "\n")
        return rec

    def read(self):
        return [json.loads(l) for l in open(self.path)] if self.path.exists() else []
