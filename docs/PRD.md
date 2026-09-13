# Followthrough — Product Requirements Document

| | |
|---|---|
| **Product** | Followthrough — meeting commitments to completed work |
| **Document owner** | Andromeda team |
| **Status** | MVP implemented (hackathon build) · living document |
| **Agent version** | v1.0 |
| **Last updated** | 2026-09-14 |

---

## 1. Summary

Followthrough is an AI agent for customer-facing teams. It reads a meeting transcript from Granola, finds every explicit commitment, matches the people and records involved in the team's real apps, and completes the follow-up work — sending the email, booking the meeting, posting the update and updating the CRM record — **exactly once, only with human approval, and with a verifiable audit trail**.

## 2. Problem

- Sales and account teams make many small promises per call. Follow-ups are forgotten, delayed or sent to the wrong person.
- Manual follow-up means switching between Gmail, Calendar, Slack and the CRM after every call.
- Existing AI note-takers summarise calls but stop short of *doing* the work, and generic agents are not trusted to act: they guess when names are ambiguous and can repeat actions when something fails.

## 3. Target users

| Persona | Needs | Typical commitments |
|---|---|---|
| **Account executive** | Fast, accurate follow-up after every sales call | Send proposal, book next meeting, move deal stage |
| **Customer success manager** | Keep renewals on track and the team informed | Post renewal status, schedule QBR, email summary |
| **Sales engineer** | Deliver technical follow-ups | Share docs, book technical review |
| **Revenue operations** | Clean pipeline data | Deal stage updates in the CRM |
| **Hackathon judge / evaluator** | Evidence of multi-app reliability | Benchmark, traces, invariants |

## 4. Goals and non-goals

### Goals

| ID | Goal |
|---|---|
| G1 | Turn explicit meeting commitments into completed actions across at least three external apps |
| G2 | Never act on the wrong person or record — ask instead of guessing |
| G3 | Never duplicate a side effect, even on retries, failures or restarts |
| G4 | Keep a human in control: preview first, approve explicitly |
| G5 | Prove reliability with an independent, repeatable benchmark |
| G6 | Run locally with minimal setup and no required third-party Python packages |

### Non-goals (this release)

- Summarising meetings or drafting long-form content.
- Acting on hedged or hypothetical statements ("maybe we could…").
- Multi-user hosting, authentication or role-based access.
- Automatic execution without human approval.
- Replacing the CRM or task manager.

## 5. User stories

| ID | As a… | I want to… | So that… | Status |
|---|---|---|---|---|
| US-1 | Account executive | pick a recent Granola call and see every commitment found | I don't have to re-read the transcript | ✅ Implemented |
| US-2 | Account executive | preview the exact email, event, post and record change before anything happens | I stay in control | ✅ Implemented |
| US-3 | Account executive | untick actions I don't want and execute the rest in one click | follow-up takes seconds | ✅ Implemented |
| US-4 | CSM | be asked when a name is ambiguous | the wrong customer is never emailed | ✅ Implemented |
| US-5 | CSM | safely re-run a call after a failure | nothing is sent twice | ✅ Implemented |
| US-6 | Any user | paste a transcript from another tool | I can use calls not recorded in Granola | ✅ Implemented |
| US-7 | Evaluator | run a benchmark with fault injection and see scores | reliability is proven, not claimed | ✅ Implemented |
| US-8 | Admin | check every connection from one screen | setup problems are obvious | ✅ Implemented |
| US-9 | Any user | answer a clarification question in the UI and have the action re-planned | ambiguous items still get done | 🔜 Planned |
| US-10 | Account executive | have runs start automatically when a Granola note is ready | follow-up is ready when I open the app | ✅ Implemented (extension autopilot) |
| US-11 | Any user | install a browser extension, sign up with my email and choose allowed apps once | I never touch config files | ✅ Implemented |
| US-12 | Any user | get a notification and an activity feed after each meeting | I know what was done and what needs me | ✅ Implemented |

## 6. Functional requirements

| ID | Requirement | Priority | Status |
|---|---|---|---|
| **Ingestion** | | | |
| FR-1 | Fetch transcripts from the Granola public API, following pagination | P0 | ✅ |
| FR-2 | Accept pasted transcripts | P1 | ✅ |
| FR-3 | List recent Granola notes with title, date and id | P0 | ✅ |
| **Extraction** | | | |
| FR-4 | Extract explicit commitments with an LLM (Groq) | P0 | ✅ |
| FR-5 | Ignore hedged or hypothetical statements; merge duplicate mentions | P0 | ✅ |
| FR-6 | Split long transcripts and pace requests to the provider's tokens-per-minute limit | P0 | ✅ |
| FR-7 | Fall back to deterministic extraction per part, with a visible warning | P0 | ✅ |
| **Resolution and planning** | | | |
| FR-8 | Resolve recipients (Google Contacts), Slack members and channels, Airtable records | P0 | ✅ |
| FR-9 | Require confidence ≥ 0.85 and reject near-ties; otherwise request clarification | P0 | ✅ |
| FR-10 | Plan exactly one action or one clarification per commitment | P0 | ✅ |
| FR-11 | Support Gmail send, Calendar event, Slack post, Airtable record update | P0 | ✅ |
| FR-12 | Convert spoken times ("friday 10am", "tomorrow 3pm") to calendar times in the local time zone | P1 | ✅ |
| **Execution** | | | |
| FR-13 | Dry-run preview that performs read-only lookups only | P0 | ✅ |
| FR-14 | Execute only selected actions, only in real mode, only after confirmation | P0 | ✅ |
| FR-15 | Exactly-once execution via idempotency keys that persist across runs | P0 | ✅ |
| FR-16 | Retry rate limits and safe timeouts; never blindly retry writes with unknown outcome | P0 | ✅ |
| FR-17 | Report per-action status: Done, Failed (with reason), Already done | P0 | ✅ |
| **Evaluation and observability** | | | |
| FR-18 | Gold-labelled fixtures isolated from the agent | P0 | ✅ |
| FR-19 | Fault injection: timeout, 429, applied-but-lost | P0 | ✅ |
| FR-20 | Weighted scoring with hard-fail invariants and score history | P0 | ✅ |
| FR-21 | One JSONL trace and side-effect log per run | P0 | ✅ |
| **Interfaces** | | | |
| FR-22 | Local web UI: Live run, Benchmark, System | P0 | ✅ |
| FR-23 | CLI parity for check, notes, live, suite, replay, history | P1 | ✅ |
| **Extension and autopilot** | | | |
| FR-27 | Chrome/Edge extension with email sign-up, allowed-app selection and arming | P0 | ✅ |
| FR-28 | Engine polls Granola on an interval and processes each new meeting once | P0 | ✅ |
| FR-29 | Autopilot executes only in allowed apps; others are listed | P0 | ✅ |
| FR-30 | Activity feed, badge and notifications per meeting | P1 | ✅ |
| FR-31 | Engine starts at Windows sign-in (installer script) | P1 | ✅ |
| FR-32 | Hosted accounts (sign-in usable across devices) | P2 | 🔜 |
| FR-24 | Answer clarifications in the UI and re-plan | P1 | 🔜 |
| FR-25 | LLM-drafted email bodies and event titles | P2 | 🔜 |
| FR-26 | Granola webhooks for automatic previews | P2 | 🔜 |

## 7. Non-functional requirements

| Category | Requirement | Current |
|---|---|---|
| **Reliability** | Invariants I1–I5 hold on every benchmark run, clean and fault-injected | 5/5 fixtures pass |
| **Safety** | No real side effect without `FOLLOWTHROUGH_MODE=real` and explicit confirmation | Enforced server- and client-side |
| **Correctness** | Zero wrong-entity, duplicate or hallucinated actions in the benchmark | 0 / 0 / 0 |
| **Performance** | Rule-based benchmark in seconds; short call (< 5 min) preview in under 30 s | ~2 s benchmark; ~10 s demo preview |
| **Scalability (LLM)** | Long calls succeed within Groq free-tier limits | ~1 minute per 16k characters |
| **Security** | Local-only server; localhost Host check; JSON-only writes; least-privilege scopes | Implemented |
| **Privacy** | Data leaves the machine only to configured APIs; secrets never exposed by the API | Implemented |
| **Portability** | Python 3.10+, standard library core, Windows/macOS/Linux | Tested on Windows, Python 3.11 |
| **Observability** | Every step, retry and error traceable per run | JSONL traces |
| **Accessibility** | Keyboard focus states, sufficient contrast, reduced-motion support | Implemented |

## 8. Success metrics

| Metric | Definition | Target |
|---|---|---|
| Benchmark pass rate | Fixtures passing / total | 100% |
| Duplicate side effects | Repeated effects across runs and restarts | 0 |
| Wrong-entity actions | Actions on an unintended person or record | 0 |
| Commitment recall (live) | Commitments found / commitments a reviewer identifies | ≥ 90% |
| Action acceptance rate | Executed actions / planned actions | ≥ 80% |
| Clarification rate | Questions / commitments on sales calls | ≤ 20% |
| Time to follow-up | Call end → actions executed | < 2 minutes of user time |

## 9. Release plan

| Phase | Scope | Status |
|---|---|---|
| **MVP** | Pipeline, 4 action types, 5 integrations, benchmark, CLI, web UI, safety lock, exactly-once | ✅ Done |
| **Next** | Clarification answering, LLM-drafted content, Slack channel names, Granola webhooks | 🔜 |
| **Later** | CRM integrations (HubSpot, Salesforce), Drive attachments, hosted team deployment with auth and audit export | 💡 |

## 10. Dependencies and constraints

| Dependency | Constraint |
|---|---|
| Granola API | Business or Enterprise plan; only notes with a finished AI summary are available |
| Groq | Free tier 8,000 tokens/minute; reasoning tokens count toward output |
| Google OAuth | Testing-mode sign-ins expire after 7 days; test users must be listed |
| Slack | Bot must have 4 scopes; mentions require matching member full names |
| Airtable | Table must have `Name` and single-select `Stage` with one-word options |

## 11. Risks and mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| LLM misses or invents commitments | Wrong or missing follow-up | Strict prompt, low temperature, verbatim sentences, human preview, benchmark |
| Ambiguous names | Email to the wrong person | Confidence gate, near-tie rejection, clarification |
| Duplicate sends on retry or restart | Customer receives repeats | Idempotency keys claimed before calls; persistent live store |
| Unknown outcome after timeout | Silent duplicate or loss | Key kept, user told to check the app |
| Accidental real execution | Unwanted emails or edits | Two-key execution (mode + confirmation); sandbox accounts recommended |
| Provider rate limits | Slow or failed extraction | Chunking, pacing, retries, per-part fallback with warnings |
| Sensitive call content sent to LLM | Privacy exposure | Local-only app, documented data flow, sandbox use |

## 12. Open questions

1. Should clarifications be answerable inline, or escalated to Slack for the call owner?
2. Which CRM should replace or complement Airtable first — HubSpot or Salesforce?
3. Should email bodies be drafted by the LLM, and if so, always require editing before send?
4. What approval policy fits teams: per-user confirmation, or auto-approve low-risk actions (e.g. internal Slack posts)?
5. What retention policy should apply to traces that contain transcript excerpts?
