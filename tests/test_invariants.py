"""Invariant tests: run with  python -m pytest tests/ -q  (or plain python)."""
import os
# These tests check reliability logic, not LLM quality: always use the deterministic
# rule-based extractor, even when .env contains a GROQ_API_KEY.
os.environ["GROQ_API_KEY"] = ""
from followthrough.pipeline import run_fixture
from followthrough.evaluation.evaluator import evaluate
from followthrough.evaluation.scorer import score

def _run(fid, **kw):
    run = run_fixture(fid, **kw)
    return run, score(evaluate(run["fixture"], run))

def test_basic_multi_app_passes():
    _, s = _run("fixture_001")
    assert s["verdict"] == "PASS", s

def test_four_apps_pass():
    _, s = _run("fixture_002")
    assert s["verdict"] == "PASS", s

def test_ambiguity_clarifies_not_guesses():
    run, s = _run("fixture_003")
    assert s["verdict"] == "PASS", s
    assert not run["recorder"].read(), "no side effects allowed under ambiguity"

def test_negatives_and_duplicate_mentions():
    run, s = _run("fixture_004")
    assert s["verdict"] == "PASS", s
    assert len([e for e in run["recorder"].read() if e["status"] == "applied"]) == 1

def test_fault_injection_exactly_once():
    run, s = _run("fixture_005", inject_faults=True)
    assert s["verdict"] == "PASS", s
    # slack applied_but_lost: app ledger must still show exactly one message
    slack = run["apps"]["slack"]
    inner = getattr(slack, "inner", slack)
    assert len(inner.effects) == 1, inner.effects

def test_restart_produces_zero_new_side_effects():
    run1 = run_fixture("fixture_005", inject_faults=True)
    n1 = sum(len(getattr(getattr(a, "inner", a), "effects", []))
             for a in run1["apps"].values())
    run2 = run_fixture("fixture_005", shared_state_dir=run1["state_dir"],
                       apps=run1["apps"])
    n2 = sum(len(getattr(getattr(a, "inner", a), "effects", []))
             for a in run1["apps"].values())
    assert n1 == n2, "restart created duplicate side effects"
    assert all(r["status"] in ("skipped_duplicate", "clarification_requested")
               for r in run2["results"])

if __name__ == "__main__":
    import sys, traceback
    fns = [v for k, v in list(globals().items()) if k.startswith("test_")]
    failed = 0
    for fn in fns:
        try:
            fn(); print(f"PASS {fn.__name__}")
        except Exception:
            failed += 1; print(f"FAIL {fn.__name__}"); traceback.print_exc()
    sys.exit(1 if failed else 0)
