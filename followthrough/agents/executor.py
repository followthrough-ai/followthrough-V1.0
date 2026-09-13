"""Execution Agent — validate, idempotency-check, execute with retries,
record every side effect. Exactly-once semantics even under
'applied-but-response-lost' faults, because the idempotency key is committed
optimistically BEFORE the integration call: a retry after an ambiguous
failure re-checks the store instead of re-firing the side effect."""
import time
from ..config import MAX_RETRIES, RETRY_BACKOFF_S
from ..reliability.idempotency import IdempotencyStore
from ..reliability.fault_injection import TransientError

def execute(plans, apps, store: IdempotencyStore, recorder, trace, fixture_id):
    results = []
    for p in plans:
        if p["type"] == "clarification":
            trace.log("clarification_requested", commitment_id=p["commitment_id"],
                      question=p["question"])
            results.append({**p, "status": "clarification_requested"})
            continue
        app, action = p["app"], p["action"]
        key = IdempotencyStore.make_key(fixture_id, p["commitment_id"], app, action)
        if store.seen(key):
            trace.log("idempotent_skip", commitment_id=p["commitment_id"], key=key)
            results.append({**p, "status": "skipped_duplicate", "idempotency_key": key})
            continue
        # Optimistic commit: claim the key, then fire. If the response is lost
        # after the write applied, a restart sees the key and does NOT re-fire.
        store.record(key, action_id="pending")
        integration = apps[app]
        status, attempt, error, release_key = "failed", 0, None, True
        while attempt < MAX_RETRIES:
            attempt += 1
            try:
                integration.execute(action, **{k: v for k, v in p["parameters"].items()
                                               if v is not None})
                status = "applied"
                break
            except TransientError as e:
                trace.log("transient_error", status="retry", commitment_id=p["commitment_id"],
                          fault=e.kind, attempt=attempt)
                if e.kind == "applied_but_lost":
                    # Side effect DID apply; the key is already committed, so we
                    # must NOT retry the write. Mark applied and move on.
                    status = "applied"
                    break
                time.sleep(RETRY_BACKOFF_S * attempt)
            except Exception as e:
                # Permanent failure (bad token, missing permission, invalid input).
                # If the write may still have applied, keep the key claimed.
                error = str(e)
                release_key = not getattr(e, "outcome_unknown", False)
                trace.log("action_error", status="error", commitment_id=p["commitment_id"],
                          error=error, outcome_unknown=not release_key, attempt=attempt)
                break
        if status == "failed" and release_key:
            # Nothing was applied: free the key so a later re-run can try again.
            store.record(key, action_id="failed")
        target = (p["parameters"].get("recipient") or p["parameters"].get("record_id")
                  or p["parameters"].get("channel") or p["parameters"].get("time"))
        rec = recorder.record(run_id=trace.run_id, fixture_id=fixture_id,
                              commitment_id=p["commitment_id"], app=app, action=action,
                              target=target, parameters=p["parameters"],
                              idempotency_key=key, status=status)
        trace.log("action_executed", commitment_id=p["commitment_id"], app=app,
                  action=action, target=target, attempts=attempt,
                  action_status=status, action_id=rec["action_id"])
        results.append({**p, "status": status, "idempotency_key": key,
                        "attempts": attempt, "error": error,
                        "outcome_unknown": status == "failed" and not release_key})
    return results
