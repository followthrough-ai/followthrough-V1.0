"""Idempotency store: exactly-once side effects.

Key format: {fixture_id}:{commitment_id}:{app}:{action}
The store persists across retries AND across workflow restarts (file-backed),
so a re-run of the same fixture in the same run-suite produces zero new
side effects.
"""
import json
from pathlib import Path

class IdempotencyStore:
    def __init__(self, path: Path):
        self.path = Path(path)
        self._keys: dict[str, dict] = {}
        if self.path.exists():
            for line in open(self.path):
                rec = json.loads(line)
                self._keys[rec["key"]] = rec

    @staticmethod
    def make_key(fixture_id: str, commitment_id: str, app: str, action: str) -> str:
        return f"{fixture_id}:{commitment_id}:{app}:{action}"

    def seen(self, key: str) -> bool:
        # A key released as "failed" (nothing was applied) may be tried again.
        rec = self._keys.get(key)
        return rec is not None and rec.get("action_id") != "failed"

    def record(self, key: str, action_id: str):
        rec = {"key": key, "action_id": action_id}
        self._keys[key] = rec
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "a") as f:
            f.write(json.dumps(rec) + "\n")

    def get(self, key: str):
        return self._keys.get(key)
