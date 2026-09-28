"""Wording tests: what recipients read. Run with  python -m pytest tests/ -q  (or plain python)."""
import os
os.environ["GROQ_API_KEY"] = ""
from followthrough.fixtures_lib.manager import load_fixture
from followthrough.mocks.apps import build_mock_suite
from followthrough.agents import commitment_extractor, entity_resolver, action_planner
from followthrough.agents.action_planner import _event_title
from followthrough.pipeline import _stable_action_id

CTX = {"meeting": "Acme renewal sync", "sender": "Alex"}

def _plans(fid, context=CTX):
    fx = load_fixture(fid)
    apps = build_mock_suite(fx.world)
    cs, _ = commitment_extractor.extract_detailed(fx.agent_view()["transcript"])
    return {p["app"]: p for p in action_planner.plan(cs, entity_resolver.resolve(cs, apps), apps, context)
            if p["type"] == "action"}

def test_event_title_comes_from_the_sentence():
    assert _event_title("Let's put Friday at 10am on the calendar for the pricing review.", {}) == "Pricing review"
    assert _event_title("Schedule the QBR on Tuesday at 3pm", {}) == "QBR"
    assert _event_title("Let's book a call with Daniel for Friday at 2pm", {}) == "Call with Daniel"
    assert _event_title("Let's put Friday at 10am on the calendar", CTX) == "Follow-up: Acme renewal sync"
    assert _event_title("Let's put Friday at 10am on the calendar", {}) == "Follow-up meeting"

def test_slack_post_is_a_recap_not_the_instruction():
    msg = _plans("fixture_002")["slack"]["parameters"]["message"]
    assert "Please post" not in msg
    for part in ("Acme renewal sync", "Renewal summary emailed to Daniel Cho",
                 "Acme deal moved to Negotiation", "Pricing review, Friday at 10am"):
        assert part in msg, msg

def test_email_greets_by_name_and_keeps_internal_details_out():
    body = _plans("fixture_002")["gmail"]["parameters"]["body"]
    assert body.startswith("Hi Daniel,")
    assert "renewal summary" in body and "Pricing review, Friday at 10am" in body
    assert body.rstrip().endswith("Alex")
    # Deal stages and Slack posts are internal; they never go to the customer.
    assert "Negotiation" not in body and "Slack" not in body

def test_wording_works_without_context():
    p = _plans("fixture_002", context=None)
    assert p["calendar"]["parameters"]["title"] == "Pricing review"
    assert p["gmail"]["parameters"]["body"].rstrip().endswith("Best,")

def test_wording_never_changes_the_idempotency_key():
    for p in _plans("fixture_002").values():
        key = _stable_action_id(p)
        prm = p["parameters"]
        for k in ("title", "message", "body"):
            if k in prm:
                prm[k] = "something else"
        assert _stable_action_id(p) == key, p["app"]

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
