"""End-to-end pipeline: transcript -> commitments -> entities -> plan ->
execute -> recorded side effects. One trace per run. Gold labels never enter."""
import hashlib, json
from .config import AGENT_VERSION, RUNS_DIR
from .fixtures_lib.manager import load_fixture
from .mocks.apps import build_mock_suite
from .reliability.trace import Trace
from .reliability.idempotency import IdempotencyStore
from .reliability.recorder import ActionRecorder
from .reliability.fault_injection import FaultInjector, FaultyIntegration
from .agents import commitment_extractor, entity_resolver, action_planner, executor

def run_fixture(fixture_id: str, run_id: str | None = None, inject_faults: bool = False,
                shared_state_dir=None, apps=None):
    fx = load_fixture(fixture_id)
    trace = Trace(fixture_id, run_id=run_id, agent_version=AGENT_VERSION)
    state_dir = shared_state_dir or trace.dir
    store = IdempotencyStore(state_dir / "idempotency.jsonl")
    recorder = ActionRecorder(state_dir / "actions.jsonl")

    if apps is None:
        apps = build_mock_suite(fx.world)
    if inject_faults and fx.fault_plan:
        injector = FaultInjector(fx.fault_plan)
        apps = {k: FaultyIntegration(v, injector, k) for k, v in apps.items()}
        trace.log("fault_injection_enabled", plan=fx.fault_plan)

    view = fx.agent_view()
    trace.log("ingest", chars=len(view["transcript"]))

    commitments, extraction = commitment_extractor.extract_detailed(view["transcript"])
    trace.log("commitments_extracted", count=len(commitments), commitments=commitments,
              **extraction)

    entities = entity_resolver.resolve(commitments, apps)
    trace.log("entities_resolved", entities=entities)

    plans = action_planner.plan(commitments, entities, apps)
    trace.log("actions_planned", plans=plans)

    results = executor.execute(plans, apps, store, recorder, trace, fixture_id)
    trace.log("run_complete", results=[{k: r.get(k) for k in
              ("commitment_id", "type", "status", "app", "action")} for r in results])
    return {"trace": trace, "commitments": commitments, "entities": entities,
            "plans": plans, "results": results, "recorder": recorder,
            "apps": apps, "fixture": fx, "store": store, "state_dir": state_dir}

def _stable_action_id(p: dict) -> str:
    """Commitment ids from the LLM can change between runs, so live idempotency
    keys are derived from what the action does (app, action, target)."""
    prm = p["parameters"]
    basis = [p["app"], p["action"], prm.get("recipient"), prm.get("subject"),
             prm.get("record_id"), prm.get("fields"), prm.get("channel"),
             prm.get("mention"), prm.get("time")]
    return "c_" + hashlib.sha1(json.dumps(basis, sort_keys=True, default=str).encode()).hexdigest()[:10]

def _summary(results: list[dict]) -> list[dict]:
    return [{k: r.get(k) for k in ("commitment_id", "type", "status", "app", "action", "error")}
            for r in results]

def plan_live(source_id: str, transcript: str, apps: dict, progress=None) -> dict:
    """Real mode, step 1: find commitments and plan actions. Only reads the apps
    (to resolve people, channels and records); sends nothing."""
    say = progress or (lambda msg: None)
    trace = Trace(source_id, agent_version=AGENT_VERSION)
    trace.log("ingest", source="live", chars=len(transcript))

    say(f"Extracting commitments from {len(transcript):,} characters")
    commitments, extraction = commitment_extractor.extract_detailed(transcript)
    trace.log("commitments_extracted", count=len(commitments), commitments=commitments,
              **extraction)

    say(f"Found {len(commitments)} commitment(s); resolving people, channels and records")
    entities = entity_resolver.resolve(commitments, apps)
    trace.log("entities_resolved", entities=entities)

    say("Planning one action per commitment")
    plans = action_planner.plan(commitments, entities, apps)
    text_by_id = {c["id"]: c["text"] for c in commitments}
    for p in plans:
        p["commitment_text"] = text_by_id.get(p["commitment_id"], "")
        if p["type"] == "action":
            p["commitment_id"] = _stable_action_id(p)
    trace.log("actions_planned", plans=plans)
    return {"source_id": source_id, "trace": trace, "commitments": commitments,
            "plans": plans, "extraction": extraction}

def execute_live(planned: dict, apps: dict, only: set | None = None) -> list[dict]:
    """Real mode, step 2: carry out the planned actions (all, or those whose ids
    are in `only`). The idempotency store is shared across live runs, so
    re-running the same source never repeats an action that already happened."""
    trace = planned["trace"]
    store = IdempotencyStore(RUNS_DIR / "live_idempotency.jsonl")
    recorder = ActionRecorder(trace.dir / "actions.jsonl")
    chosen = [p for p in planned["plans"]
              if p["type"] != "action" or only is None or p["commitment_id"] in only]
    results = executor.execute(chosen, apps, store, recorder, trace, planned["source_id"])
    trace.log("run_complete", dry_run=False, results=_summary(results))
    return results

def run_live(note_id: str, transcript: str, apps: dict, dry_run: bool = False):
    """Plan, then (unless dry_run) execute every planned action."""
    planned = plan_live(note_id, transcript, apps)
    if dry_run:
        results = [{**p, "status": "planned" if p["type"] == "action"
                    else "clarification_requested"} for p in planned["plans"]]
        planned["trace"].log("run_complete", dry_run=True, results=_summary(results))
    else:
        results = execute_live(planned, apps)
    return {**planned, "results": results}
