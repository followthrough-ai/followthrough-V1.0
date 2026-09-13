"""Fixture Manager. A fixture directory contains:
   transcript.txt   - the meeting transcript (agent input)
   world.json       - seeded entity directory  (agent may search)
   gold.json        - gold labels             (agent NEVER sees)
   faults.json      - optional fault-injection plan
The loader enforces isolation: agent_view() excludes gold labels."""
import json, hashlib
from pathlib import Path
from ..config import FIXTURES_DIR
from ..mocks.world import World

class Fixture:
    def __init__(self, fixture_id: str, path: Path):
        self.fixture_id = fixture_id
        self.path = path
        self.transcript = (path / "transcript.txt").read_text()
        self.world = World.load(path / "world.json")
        self._gold_path = path / "gold.json"
        fplan = path / "faults.json"
        self.fault_plan = json.loads(fplan.read_text()) if fplan.exists() else None
        self.version_hash = hashlib.sha256(
            (self.transcript + (path / "world.json").read_text()
             + self._gold_path.read_text()).encode()).hexdigest()[:12]

    def agent_view(self) -> dict:
        """Everything the agent under test is allowed to see."""
        return {"fixture_id": self.fixture_id, "transcript": self.transcript}

    def gold(self) -> dict:
        """Only the evaluator calls this."""
        return json.loads(self._gold_path.read_text())

def load_fixture(fixture_id: str) -> Fixture:
    return Fixture(fixture_id, Path(FIXTURES_DIR) / fixture_id)

def list_fixtures() -> list[str]:
    return sorted(p.name for p in Path(FIXTURES_DIR).iterdir()
                  if (p / "gold.json").exists())
