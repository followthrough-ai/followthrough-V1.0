#!/usr/bin/env python3
"""Followthrough CLI.

Engine (for the browser extension — autopilot + website, no browser opened):
  python run.py engine [port]              # default port 8765; runs until stopped
  python run.py package-extension          # zip the extension into dist/

Web UI:
  python run.py ui [port]                  # open the Followthrough website (default port 8765)

Benchmark (mock apps, sample calls, no keys needed):
  python run.py suite                      # run all fixtures + evaluate
  python run.py suite --faults             # same, with fault injection
  python run.py suite --no-llm             # rule-based extractor only (fast, deterministic)
  python run.py fixture fixture_001        # single fixture, verbose
  python run.py replay fixture_005         # restart-after-partial-execution proof
  python run.py history                    # score history by agent version

Real apps (keys in .env):
  python run.py check                      # test every connection (read-only)
  python run.py notes                      # recent Granola notes and their IDs
  python run.py live <note_id> --dry-run   # show planned actions, send nothing
  python run.py live <note_id>             # act for real (needs FOLLOWTHROUGH_MODE=real)
"""
import json, os, sys
if "--no-llm" in sys.argv:
    os.environ["GROQ_API_KEY"] = ""   # must be set before followthrough.config loads .env
from followthrough.pipeline import run_fixture
from followthrough.evaluation.evaluator import evaluate
from followthrough.evaluation.scorer import score
from followthrough.evaluation.regression_runner import run_suite
from followthrough.config import RUNS_DIR
from followthrough.integrations.base import ApiError

def _print_score(s):
    mark = "✅" if s["verdict"] == "PASS" else "❌"
    print(f"{mark} {s['fixture_id']:<14} {s['verdict']:<5} score={s['overall_score']:>5}  "
          f"F1={s['components']['commitment_f1']:.2f} "
          f"ent={s['components']['entity_accuracy']:.2f} "
          f"act={s['components']['action_accuracy']:.2f} "
          f"safety={s['components']['safety']:.0f}")
    for h in s["hard_failures"]:
        print(f"     HARD FAIL: {h}")
    for e in s["explanations"]:
        print(f"     - {e}")

def _check():
    from followthrough import config
    from followthrough.health import check_connections
    print(f"FOLLOWTHROUGH_MODE={config.MODE}  "
          f"({'live runs will act' if config.MODE == 'real' else 'live runs need --dry-run'})\n")
    rows = check_connections()
    for r in rows:
        print(f"{'✅' if r['ok'] else '❌'} {r['name']:<9} {r['detail']}")
    ok = sum(r["ok"] for r in rows)
    print(f"\n{ok}/{len(rows)} connections OK")
    return 0 if ok == len(rows) else 1

def _print_live(run, dry_run):
    icons = {"applied": "✅", "planned": "📝", "clarification_requested": "❓",
             "skipped_duplicate": "⏭️ ", "failed": "❌"}
    print(f"\n=== Followthrough live run {'(DRY RUN — nothing sent)' if dry_run else ''} ===")
    ex = run.get("extraction", {})
    how = {"llm": "Groq", "mixed": "Groq + rule-based fallback",
           "heuristic": "rule-based fallback only"}.get(ex.get("method"), "unknown")
    print(f"{len(run['commitments'])} commitment(s) found "
          f"(extracted with {how}, {ex.get('parts', 1)} part(s))")
    for w in ex.get("warnings", []):
        print(f"⚠️  {w}")
    print()
    for r in run["results"]:
        print(f"{icons.get(r['status'], '•')} {r['status']}: {r.get('commitment_text', '')}")
        if r["type"] == "action":
            print(f"     {r['app']}.{r['action']} {json.dumps(r['parameters'], default=str)}")
        else:
            print(f"     question: {r.get('question')}")
        if r.get("error"):
            print(f"     error: {r['error']}")
        if r.get("outcome_unknown"):
            print("     outcome unknown: check the app before re-running this note")
    print(f"\ntrace: {run['trace'].path}")

def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "suite"
    if cmd == "suite":
        agg = run_suite(inject_faults="--faults" in sys.argv)
        print(f"\n=== Followthrough regression suite "
              f"({'FAULT-INJECTED' if agg['fault_injection'] else 'clean'}) ===")
        for r in agg["results"]:
            _print_score(r)
        print(f"\nPASS {agg['passed']}/{agg['fixtures']}  "
              f"pass_rate={agg['pass_rate']}%  mean_score={agg['mean_score']}")
    elif cmd == "fixture":
        fid = sys.argv[2]
        run = run_fixture(fid, inject_faults="--faults" in sys.argv)
        rep = evaluate(run["fixture"], run)
        _print_score(score(rep))
        print(f"trace: {run['trace'].path}")
    elif cmd == "replay":
        fid = sys.argv[2]
        # First pass with faults, then restart the workflow against the SAME
        # state dir + same app instances: exactly-once must hold.
        run1 = run_fixture(fid, inject_faults=True)
        run2 = run_fixture(fid, shared_state_dir=run1["state_dir"], apps=run1["apps"])
        rep = evaluate(run1["fixture"], {**run2, "apps": run1["apps"],
                                          "recorder": run1["recorder"]})
        s = score(rep)
        _print_score(s)
        skipped = [r for r in run2["results"] if r["status"] == "skipped_duplicate"]
        print(f"restart skipped {len(skipped)} already-applied action(s) via idempotency keys")
        print(f"traces: {run1['trace'].path}  |  {run2['trace'].path}")
    elif cmd == "history":
        hist = RUNS_DIR / "score_history.jsonl"
        if hist.exists():
            for line in open(hist):
                print(json.dumps(json.loads(line)))
        else:
            print("no history yet")
    elif cmd in ("ui", "engine"):
        from followthrough.web.server import serve
        port = int(sys.argv[2]) if len(sys.argv) > 2 and sys.argv[2].isdigit() else 8765
        if cmd == "engine":
            if sys.stdout is None or sys.stderr is None:   # started by pythonw / at logon
                RUNS_DIR.mkdir(exist_ok=True)
                log = open(RUNS_DIR / "engine.log", "a", buffering=1, encoding="utf-8")
                sys.stdout = sys.stderr = log
            serve(port, open_browser="--browser" in sys.argv, autopilot=True)
        else:
            serve(port, open_browser="--no-browser" not in sys.argv)
    elif cmd == "package-extension":
        import zipfile
        from pathlib import Path
        src = Path(__file__).resolve().parent / "extension"
        out = Path(__file__).resolve().parent / "dist" / "followthrough-extension.zip"
        out.parent.mkdir(exist_ok=True)
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
            for f in sorted(src.rglob("*")):
                if f.is_file() and "__pycache__" not in f.parts:
                    z.write(f, f.relative_to(src).as_posix())
        print(f"packaged {out} ({out.stat().st_size:,} bytes)")
    elif cmd == "check":
        sys.exit(_check())
    elif cmd == "notes":
        from followthrough.integrations.granola import GranolaIntegration
        notes = GranolaIntegration().list_notes(page_size=int(sys.argv[2]) if len(sys.argv) > 2 else 10)
        if not notes:
            print("No notes returned. Only notes with a finished AI summary + transcript are listed.")
        for n in notes:
            when = (n.get("created_at") or "")[:16].replace("T", " ")
            print(f"{n['id']}  {when}  {n.get('title') or '(untitled)'}")
    elif cmd == "live":
        if len(sys.argv) < 3 or sys.argv[2].startswith("--"):
            print("usage: python run.py live <note_id> [--dry-run]   (find IDs with: python run.py notes)")
            sys.exit(2)
        from followthrough.settings import is_armed
        from followthrough.integrations import build_real_suite
        from followthrough.integrations.granola import GranolaIntegration
        from followthrough.pipeline import run_live
        note_id, dry_run = sys.argv[2], "--dry-run" in sys.argv
        if not dry_run and not is_armed():
            print("Not sending anything: the engine is not armed.\n"
                  "Preview first with --dry-run, then arm autopilot in the extension "
                  "(or set FOLLOWTHROUGH_MODE=real in .env) to act.")
            sys.exit(1)
        transcript = GranolaIntegration().get_transcript(note_id)
        if not transcript.strip():
            print("That note has no transcript yet.")
            sys.exit(1)
        run = run_live(note_id, transcript, build_real_suite(), dry_run=dry_run)
        _print_live(run, dry_run)
    else:
        print(__doc__)

if __name__ == "__main__":
    try:
        main()
    except ApiError as e:
        print(f"❌ {e}")
        sys.exit(1)
