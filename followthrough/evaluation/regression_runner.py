"""Runs the whole fixture suite, aggregates, appends score history per agent version."""
import json, time
from pathlib import Path
from ..config import RUNS_DIR, AGENT_VERSION
from ..fixtures_lib.manager import list_fixtures, load_fixture
from ..pipeline import run_fixture
from .evaluator import evaluate
from .scorer import score

def run_suite(inject_faults: bool = False, on_result=None) -> dict:
    """on_result: optional callable(score) invoked as each fixture finishes."""
    results = []
    for fid in list_fixtures():
        run = run_fixture(fid, inject_faults=inject_faults)
        report = evaluate(run["fixture"], run)
        results.append(score(report) | {"run_id": run["trace"].run_id})
        if on_result:
            on_result(results[-1])
    passed = sum(1 for r in results if r["verdict"] == "PASS")
    agg = {"ts": time.strftime("%Y-%m-%d %H:%M:%S"), "agent_version": AGENT_VERSION,
           "fault_injection": inject_faults,
           "fixtures": len(results), "passed": passed,
           "pass_rate": round(100 * passed / len(results), 1) if results else 0,
           "mean_score": round(sum(r["overall_score"] for r in results) / len(results), 1)
                         if results else 0,
           "results": results}
    hist = Path(RUNS_DIR) / "score_history.jsonl"
    hist.parent.mkdir(exist_ok=True)
    with open(hist, "a") as f:
        f.write(json.dumps({k: agg[k] for k in
                ("ts", "agent_version", "fault_injection", "pass_rate", "mean_score")}) + "\n")
    return agg
