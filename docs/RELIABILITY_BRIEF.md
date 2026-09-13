# Followthrough — System & Reliability Brief

## What it does
A multi-step agent that converts a Granola call transcript into completed, verified
work across four external apps (Gmail, Google Calendar, Slack, Airtable): extract
explicit commitments → resolve entities against the connected apps → plan one
structured action per commitment → execute idempotently → record every side effect.

## How we know it works
**Fixture-based, gold-labeled, agent-blind evaluation.** Each of the 5 seeded
fixtures pairs a transcript + seeded world directory with independently authored
gold labels (expected commitments, entities, actions, parameters, and expected
clarifications). `Fixture.agent_view()` structurally prevents gold labels from
ever entering the agent's context. The evaluator grades the **side-effect log**
(what actually happened), never the agent's natural-language claims.

## Invariants (hard failures, regardless of weighted score)
1. **One action per commitment** — multiple applied effects for one commitment fail the run.
2. **No action without a confidently resolved entity** — resolution below the 0.85
   confidence gate or with near-tied candidates yields a clarification request;
   any wrong-entity side effect is a hard fail (fixture_003).
3. **Zero duplicate side effects** — idempotency keys
   (`fixture:commitment:app:action`) are file-backed and committed *optimistically
   before* the integration call, so a restart after partial execution re-checks
   the store instead of re-firing (fixture_005 replay: restart produces 0 new effects).
4. **Clarify-don't-guess** — expected-clarification fixtures fail if the agent acts.
5. **No hallucinated actions** — every applied effect must map to a gold commitment.

## Fault injection
A replay mode wraps integrations and injects, per a fixture-level plan:
`timeout` and `rate_limit_429` (raised before the effect applies; executor retries
with backoff) and `applied_but_lost` (effect applies, response is lost — the classic
exactly-once killer). Because the idempotency key is claimed before the call, the
agent never re-fires an applied-but-lost write; the mock apps' own effect ledger is
independently checked for double-fires. All three fault types fire in fixture_005
and the suite still passes 5/5 with zero duplicates.

## Observability
One append-only JSONL trace per run (`runs/<run_id>/trace.jsonl`) recording every
step — ingest, extraction, resolution, plans, per-attempt transient errors,
idempotent skips, executed actions — keyed by run_id / fixture_id / commitment_id /
agent_version, enabling "why did it email the wrong person?" style replay debugging.
A regression runner aggregates pass rate and mean score into
`runs/score_history.jsonl` per agent version.

## Scoring
Weighted: 25% commitment F1, 20% entity accuracy, 20% action planning, 20% execution
correctness, 15% side-effect safety — with the five invariants as unconditional
hard-fail gates. Current agent (v1.0): **5/5 fixtures PASS, clean and fault-injected,
6/6 invariant tests green.**

## Safety posture
Mock integrations are the default; real mode requires explicit env opt-in with
separate sandbox credentials; every action is validated before execution; there is
no hidden execution — the recorder is written on every applied effect.
