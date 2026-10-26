> **Status (2026-10-26):** Phase 0 is implemented on branch `phase0-agent-hardening`. Parts 1–2 describe the code *before* that work; Phase 1 onward is still to do.

# Mediator — Code Review, Doc Gap Analysis & Next-Steps Plan

## Context

The repo is an Indian-context "shuttle diplomacy" mediator MVP: FastAPI + Gemini backend, Next.js frontend, Supabase Postgres. The committed code is a single-prompt intake + joint summary. The **uncommitted** work (`backend/app/agents/`, `002_mediation_agents.sql`, router changes) swaps that for the multi-agent design described in `MediatorDocs/4.MultiAgents_Model_prompts.md` (Safety Guardian → Orchestrator → Caucus/internal agents → Safety out → Neutrality Auditor).

You asked for: a code review, a check of the problem statement and docs against the implementation, and a plan covering fixes to what exists plus what to build next. Non-live tests currently pass (11 passed, 1 live deselected).

---

## Part 1 — Code review findings

### Critical (break the core promises: safety and confidentiality)

1. **The LLM Safety Guardian never sees the message.** The `SAFETY` prompt in `backend/app/agents/prompts.py:212` has no `{{LATEST_EVENT}}` / `{{SHARED_STATE_JSON}}` placeholders, so `fill()` drops the mapping passed in `pipeline.py:82` and `:307`. Inbound and outbound safety checks only see instructions, never content. The regex in `safety.py` is the only real check.
2. **Private caucus data leaks into shared state.** `merge_party_signals` (`agents/state.py:62`) writes `positions`, `interests`, `hidden_concerns` and `resolution_needs` from the caucus straight into `state.parties.X`. `shared_view()` doesn't strip them, so the *other* party's Caucus agent, the Diagnostician, Options and Joint Voice all receive them. That breaks R3 and the doc's rule that only approved shares cross over (and "hidden concerns" are the most sensitive part).
3. **Orchestrator can send B's caucus reply to A.** If A speaks and the orchestrator returns `CAUCUS_B`, `pipeline.py:178` runs B's caucus (with no B input), merges the signals into **B's** state, and `sessions.py:242` still delivers the reply to **A**. The audience expression on that line always resolves to `actor.party`. `test_caucus_keeps_other_party_memory_out` tests this path as if it were correct.
4. **Safety fails open.** Any exception in the Safety Guardian call falls back to `_default_safety()` = CONTINUE (`pipeline.py:89`, `:314`). On a halt, the Handoff agent's `message_to_parties` replaces the help text (`pipeline.py:105`), so the helpline numbers can be lost.
5. **Halting leaks the trigger to the other party.** `_halt` sets the session to `halted` for both sides, and `room/[id]/page.tsx:178` shows both the crisis screen. The Safety prompt itself says "Never reveal to one party that the other triggered a safety flag."

### High

6. **Consent is decided by the LLM, not the user.** `approved_by_party` comes from the caucus JSON, and the UI has no share-approval step. In practice `approved_shares` stays empty, so the joint view only works because of leak #2.
7. **Outbound handling is wrong.** When outbound safety blocks a draft it is replaced with `HELP_MESSAGE`, crisis lines for a biased sentence (`pipeline.py:316`). The auditor's `blocked` flag is ignored. Severity 2 (`PAUSE_AND_CHECK`) and 1 (`CONTINUE_WITH_CARE`) are ignored.
8. **Cost and latency per turn.** Every internal-agent hop recurses and re-runs Safety and Orchestrator (`pipeline.py:164`), so one turn can make 13+ sequential Gemini calls inside a synchronous request with no timeout. `mark_ready` runs the whole joint pipeline inline. The frontend shows no "thinking" state.
9. **Race conditions.** `mediation_state` is read-modify-written as one JSONB blob with no version or lock, so concurrent A/B turns lose updates. Both parties pressing Ready at the same moment can run the joint pipeline twice (`sessions.py:86`).
10. **Errors are swallowed silently.** `persist_turn` drops a failed state write (`store.py:38`) and only inserts the *last* audit entry, while a turn appends several (orchestrator hops plus neutrality alerts). The audit trail is incomplete.
11. **No schema validation of agent JSON.** Outputs are untyped dicts. `call_agent` retries only on parse failure, not on API errors or bad shapes. Gemini structured output (`response_schema`) isn't used.
12. **Joint view duplicates text.** When Joint Voice omits the perspectives, both `user_a_perspective` and `user_b_perspective` fall back to the same `joint.reply` (`pipeline.py:374`).

### Medium / Low

- Dead code left after the switch: `gemini_client.generate_json` / `generate_intake_reply` / `generate_joint_summary`, `app/prompts.py`, `sessions._transcript`, `store.code_for_role` / `role_for_code`. `llm.py` imports the private `_client`. The live test still exercises the dead functions.
- Issue dedupe works on exact topic strings (`state.py:81`), and the Diagnostician then overwrites `issues` wholesale, so IDs and `acknowledged_by` aren't stable.
- Built but never reached: `FOLLOW_UP` (never routed), `REALITY_TESTER` (results never fed to the caucus), `DRAFTER` (`agreed_terms` is never filled).
- Party messages are put into prompts without delimiters, which is weak against prompt injection (R8 relies on the prompt alone).
- `resolve` can be triggered by either party on their own; Ready can be toggled after joint or resolved.
- `test_create_session` builds a real Supabase client, because `agents.store.get_supabase` isn't patched.
- Helpline lists differ in `safety.py`, `constitution.LOCAL_RESOURCES` and the hard-coded frontend list.
- Model name drift: README says `gemini-2.5-flash`; config and `.env.example` say `gemini-3.5-flash-lite`.
- `.env.example` and README contain a stray `EXAMPLE_ARGUMENT`.
- Frontend: the invite token lives only in `sessionStorage` (lost on a new tab or in the WhatsApp in-app browser), Person A has no "my rooms" list, compromises use `key={item}`, and there's no AI-disclosure or consent screen.

---

## Part 2 — Problem statement and doc gaps

| Gap | Where | Impact |
|---|---|---|
| **No single problem statement.** It's spread across a README one-liner and MVP_plan, with no target user, success metrics, non-goals, or privacy and data-retention stance | README, MVP_plan | You can't judge scope or "done" |
| **Contradiction:** MVP_plan says to "synthesize both private chats" into the summary; docs 3 and 4 say nothing is shared without explicit consent | MVP_plan §4 Wk2 vs Doc 4 R3 | The core product decision is unresolved, and the code does neither cleanly |
| MVP stops at "show compromises → mark resolved"; the docs describe recognition → facts → negotiate → reality test → agreement → follow-up | MVP_plan vs Doc 3 §5 | There's no documented MVP boundary for which agents are in scope |
| Doc 4 Prompt 2 (Caucus) is missing its first half (ROLE, RECEIVE, TASKS); Prompt 5 (Options) is missing its header and RECEIVE | Doc 4 | The code's versions were invented and never reviewed against a spec |
| Doc 2 is cut off mid-table (styles) | Doc 2 end | Incomplete; superseded by Doc 4 B1 |
| Chat-transcript leftovers ("Yes, the previous answer is complete", "Where would you like to go next?", `multiselect` / `widget` blocks, a YAML template split in two) | Docs 3, 4 | Reads as a chat export, not a spec |
| Constitution numbering differs (R1–R9 in Doc 3, R1–R8 in Doc 4 and code) | Docs 3, 4 | Minor, but the audit refers to rule IDs |
| The dispute object (Doc 1) and the state schema (Doc 4, `state.py`) aren't reconciled (`priority` vs `priority_for_raiser`, per-party issue lists) | Docs 1 and 3, `state.py` | Field drift |
| No spec for the consent UX, AI disclosure, minors and vulnerability, power imbalance, or what B sees when a room halts | All | Safety and legal exposure |
| Helplines say "verify before deploying" and nobody owns verifying them | Doc 4 P8, `safety.py` | Wrong numbers in a crisis |
| No evaluation or red-team spec, although Doc 4 lists the scenarios (manipulator, hidden threat, coercion, non-acknowledger) | Doc 4 notes | The prompts and the auditor can't be measured |
| README doesn't describe the multi-agent architecture, the test commands, or the `live` marker | README | Onboarding |

---

## Part 3 — Plan

### Phase 0: Stabilize the uncommitted multi-agent work (do first, before committing)

1. **Fix the Safety prompt placeholders.** Add `{{LATEST_EVENT}}` and `{{SHARED_STATE_JSON}}` to `SAFETY`. Add a check in `fill()` that raises if any `{{…}}` is left over, plus a unit test that every role's required keys are supplied.
2. **Split private and shared party state.** Caucus `positions`, `interests`, `hidden_concerns` and `resolution_needs` go into `private_memories` (structured JSON instead of a text blob). Shared `parties.X` keeps only process signals: intensity, willing, feels_heard, turns. Move `notes` to a `jsonb` column via a new migration `003_…sql`.
3. **Force the caucus to the speaking party.** For an inbound message, `next_agent` must be `CAUCUS_{party}`, `JOINT_VOICE`, an internal agent, or handoff. Coerce anything else. Remove the misleading audience expression in `sessions.py:242`. Rewrite the test so it asserts that A's message is never answered by B's caucus.
4. **Make safety fail closed and halt per party.** On a Safety call error, use the keyword result and mark the turn `CONTINUE_WITH_CARE`. Always append the canonical helplines to the halt message. Add `halted_for` (party) and `halt_kind` (safety | referral | withdrawn). The other party sees a neutral "This session has been paused" with no reason given.
5. **Fix outbound handling.** If outbound safety blocks, regenerate once with feedback; if it still fails, send a neutral fallback, never helplines. Respect auditor `blocked` the same way. Implement the PAUSE_AND_CHECK and CONTINUE_WITH_CARE branches. Severity 2 stops the move to joint review.
6. **Add concurrency control.** Add a `state_version int` column to `sessions` and do a conditional update (`eq("state_version", v)`), retrying once on conflict. Make the joint pipeline idempotent: atomically move status `intake → building_joint`, run, then set `joint_review`. Add the enum value in the migration.
7. **Make persistence honest.** Fail the request (5xx) if the state write fails. Insert every audit entry produced during the turn (track `audit_cursor`).
8. **Validate agent outputs.** Add Pydantic models per agent role in `agents/schemas.py`. Pass `response_schema` to Gemini. Retry on validation and API errors with backoff, and set a per-call timeout.
9. **Cleanup.** Remove the dead `gemini_client` functions and `app/prompts.py` (keep `_client` as a public `get_client`). Update the live test to cover `call_agent("CAUCUS", …)`. Patch `agents.store.get_supabase` in tests. Use one `RESOURCES` constant served to the frontend through `/api/resources` or the session payload. Remove `EXAMPLE_ARGUMENT` from `.env.example` and move it to `tests/fixtures/scenarios.json`. Align the model name in README and config.

### Phase 1: Complete the MVP loop the docs promise

1. **Disclosure and consent screen.** Before the first message, each party sees: this is an AI, participation is voluntary, how privacy works, that they can stop any time. Store `consented_at` per party.
2. **User-controlled share consent.** When the caucus proposes a `share_proposal`, the UI shows it as a card ("Share this with the other person? Edit / Approve / Keep private"). Only a `POST /sessions/{id}/shares/{share_id}/approve` from that party puts it in `approved_shares`. The joint pipeline runs only on approved shares; "Ready" warns when nothing has been approved.
3. **Latency.** Cut each turn to about 4 calls: run the inbound Safety and the Orchestrator in parallel, and stop re-running Safety on internal hops. Show a typing indicator. Move the joint pipeline to a background task, and have the frontend poll `building_joint`.
4. **Interactive joint session.** Replace the static summary with a joint thread (`audience_role = 'both'`): a Joint Voice opening, recognition prompts, then options per agenda issue. Each party can react to an option (works for me / needs change / no). Mutual "works for me" turns an option into an `agreed_terms` entry.
5. **Agreement.** Route to the Drafter once all agenda issues have agreed terms. Show the draft, and require both parties to sign off before the room is `resolved`, replacing the one-sided resolve.
6. **Withdraw and ask for a human.** Add a "Stop" button for either party (R2) and an "I'd like a human" button that routes to Handoff, shows the brief, and asks for consent before sharing.
7. **Frontend basics.** A "My rooms" list for A (`GET /sessions` by `created_by`). Persist B's invite in `localStorage` and keep the link re-openable. Stable keys. A mobile-tested layout.

### Phase 2: Quality, safety and evaluation

1. **Scenario and red-team harness** in `backend/evals/`: scripted two-party dialogues (phone dispute from the README, ₹50k loan, land dispute, in-laws, manipulator, hidden threat, coercion, minor, non-acknowledger), in Hinglish, Hindi and English. Assertions: no leaks of private text into the other room or the joint view (string and embedding overlap), safety recall on threat cases, balance metrics (word count ±15%, verb symmetry), no advice or pressure. Run with the `live` marker, and in CI on demand.
2. **Prompt injection hardening.** Put party text inside clearly delimited blocks, add an instruction that party text is data, and add eval cases for "ignore your rules / tell me what B said".
3. **Observability.** Structured logs per agent call (role, latency, tokens, retries), audit events viewable in an admin page, and cost per session.
4. **Rate limiting and abuse protection** on message and session creation, plus invite token expiry and rotation.
5. **Data retention.** Auto-purge private memories and messages after N days, and add a "Delete my data" endpoint.

### Phase 3: Additions going forward

- **Follow-up agent:** scheduled check-ins on agreed dates (Supabase cron or Cloud Scheduler), each party reached separately, with a "reopen at stage X" flow.
- **Reality Tester in caucus:** feed its questions into the caucus instruction during REALITY_TEST.
- **Human mediator handoff:** a mediator inbox with the Handoff brief, consent-gated.
- **Languages:** add regional languages (Hindi script, Tamil, Kannada…) with translation done at the shared-state level, per Doc 4.
- **Realtime** (Supabase Realtime or SSE) instead of 2.5s polling.
- **Deployment:** Vercel and Cloud Run or Render, secrets management, CI (pytest, eslint, tsc), and a staging environment.
- **Style selection** (facilitative, transformative, shuttle) chosen by the Diagnostician, per Doc 4 B1.

### Docs work (alongside Phase 0 and 1)

- Write `docs/PRODUCT.md`: problem statement, target users, the MVP boundary (which stages and agents are in v1), success metrics, non-goals, consent and confidentiality policy, and what a halted party versus the other party sees.
- Write `docs/ARCHITECTURE.md`: the turn loop as implemented, the state schema (shared vs private), the agent I/O contracts (generated from the Pydantic schemas), and the data flow diagram.
- Clean Docs 1–4: remove chat leftovers, finish the Caucus and Options prompt specs, fix the end of Doc 2, align constitution numbering and field names with the code.
- README: architecture summary, test commands (`pytest -m "not live"`, `pytest -m live`), migration list including `003`, the correct model name.
- `docs/SAFETY.md`: verified helplines with a verification date and an owner.

---

## Critical files

- `backend/app/agents/prompts.py`, `pipeline.py`, `state.py`, `store.py`, `llm.py`; new `agents/schemas.py`
- `backend/app/routers/sessions.py`, `backend/app/safety.py`, `backend/app/gemini_client.py`
- `supabase/migrations/003_*.sql` (state_version, private memory jsonb, halted_for, building_joint, shares table)
- `frontend/app/room/[id]/page.tsx`, `frontend/lib/api.ts`, `frontend/lib/types.ts`
- `backend/tests/test_pipeline.py`, `test_sessions.py`, new `backend/evals/`

## Verification

- `cd backend && .venv/bin/python -m pytest -m "not live"`. Add unit tests for: no placeholders left after `fill`, Safety receiving the message, A's private fields absent from B's caucus mapping and from the joint inputs, caucus forced to the speaking party, fail-closed safety, the per-party halt view, the state-version conflict retry, an idempotent joint build.
- `pytest -m live` plus the eval harness against real Gemini on the scenario set; track the leak, safety-recall and balance metrics.
- Manual end-to-end: run the backend and `npm run dev`, then go through A sign-in → invite → B in a private window → vent → approve shares → ready → joint thread → agree options → both sign off. Also try a crisis phrase from B and confirm A only sees a neutral pause.
- `npm run lint` and `tsc --noEmit` on the frontend.
