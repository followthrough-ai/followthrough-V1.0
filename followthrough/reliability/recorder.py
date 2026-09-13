"""Side-Effect Recorder — the source of truth for what actually happened.

The evaluator grades THIS log, never the agent's own claims.
"""
import json, time, uuid
from pathlib import Path

class ActionRecorder:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def record(self, *, run_id, fixture_id, commitment_id, app, action,
               target, parameters, idempotency_key, status="applied"):
        rec = {
            "action_id": f"a_{uuid.uuid4().hex[:8]}",
            "ts": time.time(),
            "run_id": run_id,
            "fixture_id": fixture_id,
            "commitment_id": commitment_id,
            "app": app,
            "action": action,
            "target": target,
            "parameters": parameters,
            "idempotency_key": idempotency_key,
            "status": status,
        }
        with open(self.path, "a") as f:
            f.write(json.dumps(rec, default=str) + "\n")
        return rec

    def read(self):
        return [json.loads(l) for l in open(self.path)] if self.path.exists() else []
