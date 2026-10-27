# Phase 2 and 3 notes

Branch: `phase2-3-quality-and-growth` (cut from `phase0-agent-hardening`).

## Phase 2: quality, safety and evaluation

### 1. Eval / red-team harness (`backend/evals/`)

- 12 scripted scenarios in `backend/tests/fixtures/scenarios.json` (the old `party_a` / `party_b` keys are kept for manual testing): expensive phone (Hinglish), ₹50k loan (English), ₹50k loan (Hindi), ancestral land (Hindi), in-laws (Hinglish), two manipulators (English; Hinglish with fake `{{PLACEHOLDER}}`s and a forged end-of-data marker), a hidden threat (Hinglish, phrased so the keyword list misses it), coercion (Hindi), a minor (English), a party who never acknowledges the other (English), and an explicit crisis. Several plant a `canary` private detail.
- `evals/harness.py` runs each scenario through the real `handle_party_turn` → `draft_share` → `check_share` → `run_joint_pipeline`, recording every agent call with the party it was made for. Checks: confidentiality (5-word overlap of one side's private text with the other side's prompts, replies, share draft, joint view and joint prompts, minus consented text), safety recall, advice/pressure/verdict phrases (English, Hinglish, Devanagari), loaded attribution verbs, and balance (share drafts within ±15% length, matched verb kinds; reported as warnings).
- `python -m evals.run` needs `GEMINI_API_KEY`, skips with exit 0 without one, never touches Supabase, writes `evals/reports/eval-<time>.json` + `.md`, and exits 1 if a scenario fails.
- Offline tests: `tests/test_evals.py` (the harness catches a caucus that repeats one side to the other, options that reveal private words, a guardian that never flags, advice phrases). `tests/test_evals_live.py` runs two scenarios live (marked `live`).
- **Not done:** an embedding-similarity leak check. String overlap catches near-verbatim leaks only; paraphrases need a person to read the report.

### 2. Prompt-injection hardening

- `fill()` wraps every party-derived value (messages, transcripts, private memory, approved shares, shared state, drafts, idea and agreement text, safety reports, relationship context, and the topic inside the caucus framing) in `<<<PARTY_DATA label>>> … <<<END_PARTY_DATA label>>>` blocks. Any `<<<` / `>>>` inside party text is replaced with look-alike characters, so a party can't close a block early.
- The constitution gains a "DATA, NOT INSTRUCTIONS" section under R8.
- Fake `{{PLACEHOLDER}}`s stay literal (fill is single-pass). Tests: `tests/test_phase2.py` (every data placeholder in every prompt is delimited; an injected message with a forged marker and fake placeholders stays inside its block; injected approved shares and idea text arrive as data).
- Orchestrator `instructions_to_agent` is still passed to the caucus as an instruction. It is model output that may paraphrase the party, and it is covered by R8 rather than delimited.

### 3. Observability

- Every `call_agent` logs one JSON line (`agent_call {...}`: role, ok, attempts, latency_ms, model, token counts from `usage_metadata`, error kind). Inside `track_calls(session_id)` the records are written to the new `agent_calls` table (best-effort; a failed write never fails the request). No prompt or model text is stored there.
- Admin detail page: calls, failures, attempts, tokens in/out, average latency and an estimated cost, per agent. Prices come from `GEMINI_PRICE_INPUT_PER_M` / `GEMINI_PRICE_OUTPUT_PER_M` (defaults are placeholders: check current Gemini pricing for your model).
- Retries: 5xx, 408, timeouts, network errors and bad/invalid output are retried (3 attempts). 429 `RESOURCE_EXHAUSTED` raises `QuotaExceeded` at once, and other 4xx errors fail at once; callers keep their existing safe fallbacks.

### 4. Abuse protection

- `app/ratelimit.py`: in-process sliding windows. Room creation per user per hour, messages per person per room per minute, and other writes (share drafts and approvals, ideas, answers, agreement draft and sign, invite rotation) per minute. 429 with `Retry-After` and a friendly message. **Per process**: with several backend instances, move the counters to a shared store.
- Invite links: `invite_expires_at` is set to `INVITE_TTL_DAYS` (14) at creation. An expired link is refused with 410 **only while unused**: once Person B has accepted the consent card, the link is their key to their own room and keeps working. Person A can replace the link from the room ("Sent it to the wrong person? Make a new link") until B joins; the old one stops working at once.
- New privacy fix found on the way: Person A used to keep seeing B's invite link, which is also B's key, so A could open B's private room. The link is now hidden from A once B has joined. **Remaining gap:** A could have copied the link earlier. A proper fix is a one-time claim that issues B a separate device token. It is not done, because B often opens the link in several browsers (WhatsApp in-app, then Chrome).

### 5. Retention and deletion

- **Delete my data** (Options menu, typed confirmation): removes that person's private chat (both sides), private memory and share drafts. If the room is still open it ends for both (the other sees only a neutral pause). Words already shown in the joint view stay there, since they were shared with consent. Before the joint view, the approved share is removed too. Safety flags (severity and category, no text) are kept.
- **Delete this room** (Person A): removes everything for both people (every table cascades from `sessions`). B then sees "This room is no longer available".
- `POST /api/jobs/retention` (X-Job-Token or admin): removes rooms older than `RETENTION_DAYS` (180), and clears free-text `reason` / payload text in `mediation_audit_events` older than `AUDIT_REASON_RETENTION_DAYS` (30), keeping stage, agent and gate.
- The in-row `mediation_state.audit_log` is now stored with structured fields only. Free-text reasons go only to the audit table, where they are cleared after 30 days.
- The consent card gains "You control your data", with the retention period and the 30-day note.
- Fixed on the way: a background joint build that finished after the room was stopped used to flip it back to `joint_review`. It now only opens a room that is still `building_joint`, and otherwise discards the unseen joint view.

### Migrations to run (Phase 2)

`supabase/migrations/008_phase2_quality.sql`, after 001–007.

### New env vars (Phase 2)

`GEMINI_PRICE_INPUT_PER_M`, `GEMINI_PRICE_OUTPUT_PER_M`, `RATE_LIMIT_ENABLED`, `RATE_LIMIT_SESSIONS_PER_HOUR`, `RATE_LIMIT_MESSAGES_PER_MINUTE`, `RATE_LIMIT_WRITES_PER_MINUTE`, `INVITE_TTL_DAYS`, `RETENTION_DAYS`, `AUDIT_REASON_RETENTION_DAYS`, `JOB_TOKEN`. All are optional, with defaults.

### Needs your accounts (Phase 2)

- A Gemini key to run `python -m evals.run` and `pytest -m live`.
- A scheduler (Render cron, GitHub Actions schedule, Supabase `pg_cron` + `pg_net`, …) to call `POST /api/jobs/retention` daily with `X-Job-Token`.
