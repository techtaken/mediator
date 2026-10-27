# Mediator

Indian-context shuttle-diplomacy MVP: two private intake rooms, Gemini-mediated NVC summaries, then a joint compromise view.

## Stack

- `frontend/` — Next.js (App Router) + Tailwind
- `backend/` — FastAPI + Google GenAI SDK
- `supabase/migrations/` — Postgres schema (run in your Supabase project)

Person A signs in with email OTP. Person B joins from the invite link with no account. Chat updates by polling.

## How a turn works

Each private message runs through a small team of Gemini agents in `backend/app/agents/` (design in `MediatorDocs/4.MultiAgents_Model_prompts.md`):

1. **Keyword safety** (`app/safety.py`): crisis phrases stop the room immediately, with no model call.
2. **Safety Guardian**: checks the message. Severity 3 halts the room, 2 blocks the move to a joint session, 1 adds care. If the check itself fails, the turn continues *with care*, never as clean.
3. **Orchestrator**: picks the stage and agent. During intake the reply always goes to the speaker's own **Caucus** agent; any other routing is coerced and logged.
4. **Caucus**: replies privately. Positions, interests, hidden concerns and raised issues go to that party's `private_memories` row. Shared state keeps only process signals (intensity, willing, feels heard).
5. **Outbound Safety + Neutrality Auditor**: a blocked draft is regenerated once, then replaced with a neutral line (never with crisis text).

When a room halts, only the party who triggered it sees why, with helplines. The other party sees a neutral "paused" message. Shared state is saved with an optimistic `state_version` lock, and the joint view is built once by claiming the `building_joint` status.

## 1. Create a Supabase project

1. Create a project at [supabase.com](https://supabase.com).
2. Enable **Email** auth. Turn on **Email OTP** (disable confirmations that require a click-through if you want the in-app code flow).
3. Run the migrations in order in the SQL editor:
   - `001_init.sql`: sessions, messages, joint summaries
   - `002_mediation_agents.sql`: shared dispute state, per-party private memory, audit log
   - `003_phase0_hardening.sql`: state versioning, per-party halts, `building_joint` status, structured private memory
   - `004_session_topic.sql`: the "what is this about" line Person A writes, shown to Person B
   - `005_share_approval.sql`: each person's draft and approved share, and the joint "where you overlap" note
   - `006_joint_session.sql`: ideas, each person's answers, and the agreement both sign
   - `007_consent.sql`: each person's "how Mediator works" acceptance, and an index for "Your rooms"
   - `008_phase2_quality.sql`: per-call agent stats, expiring invite links, "delete my data" markers, audit-reason retention
4. Copy keys from **Project Settings → API**:
   - Project URL
   - Publishable key (`sb_publishable_…`) for the browser
   - Secret key (`sb_secret_…`) for FastAPI only
   - JWKS URL (`/auth/v1/.well-known/jwks.json`) so FastAPI can verify Person A’s session

Row Level Security is on and browser roles have no table grants. Next.js never talks to Postgres; FastAPI uses the secret key and isolates A/B chats in application code.

## 2. Environment files

Copy `backend/.env.example` → `backend/.env` and `frontend/.env.example` → `frontend/.env.local`. Put real keys only in those local files, never in the example templates.

The default model is `gemini-3.5-flash-lite`. If it is unavailable on your key, set `GEMINI_MODEL` to another current Flash model. `GEMINI_TIMEOUT_MS` (default 30000) caps each agent call. Server errors, timeouts and bad output are retried up to 3 times; a quota error (429 `RESOURCE_EXHAUSTED`) fails at once.

Other backend settings (all optional, defaults in `backend/app/config.py` and `backend/.env.example`):

| Variable | Default | What it does |
|---|---|---|
| `GEMINI_PRICE_INPUT_PER_M` / `GEMINI_PRICE_OUTPUT_PER_M` | 0.10 / 0.40 | USD per million tokens, only for the admin cost estimate |
| `RATE_LIMIT_ENABLED` | true | In-process limits, counted per backend instance |
| `RATE_LIMIT_SESSIONS_PER_HOUR` | 10 | New rooms per signed-in person |
| `RATE_LIMIT_MESSAGES_PER_MINUTE` | 12 | Private messages per person per room |
| `RATE_LIMIT_WRITES_PER_MINUTE` | 30 | Share drafts/approvals, ideas, answers, agreements per person per room |
| `INVITE_TTL_DAYS` | 14 | An invite link nobody has joined with stops working after this |
| `RETENTION_DAYS` | 180 | The retention job removes rooms older than this (0 = never) |
| `AUDIT_REASON_RETENTION_DAYS` | 30 | Free-text agent reasoning in the audit table is cleared after this |
| `JOB_TOKEN` | empty | Secret a scheduler sends as `X-Job-Token` to `/api/jobs/*` (empty = admins only) |

## 3. Run locally

Terminal 1:

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

Terminal 2:

```bash
cd frontend
npm install
npm run dev
```

Open [http://localhost:3000](http://localhost:3000).

### Admin portal

`/admin` lists every session and `/admin/<id>` shows both private rooms, private memory, safety flags, the joint summary and the audit trail. It is read-only.

To give someone access, add their sign-in email to `ADMIN_EMAILS` in `backend/.env` (comma-separated) and restart the backend. With it empty, nobody is an admin. Every time an admin opens a session, an `ADMIN` entry with their email is written to that session's audit trail; if that write fails, the page is refused.

Each session's detail page also shows its agent calls: count, failures, tokens in/out, average latency and an estimated cost (from the price settings above). Every agent call is also logged as one `agent_call {...}` JSON line.

### Jobs (cron)

`POST /api/jobs/retention` removes rooms older than `RETENTION_DAYS` and clears audit reasoning older than `AUDIT_REASON_RETENTION_DAYS`. It is idempotent; run it daily from any scheduler:

```bash
curl -X POST -H "X-Job-Token: $JOB_TOKEN" https://your-backend/api/jobs/retention
```

A signed-in admin can call it too (with their `Authorization` header).

### Tests

```bash
cd backend
.venv/bin/python -m pytest -m "not live"   # offline: scripted agents + in-memory Supabase fake
.venv/bin/python -m pytest -m live         # calls the real Gemini API (uses GEMINI_API_KEY)
```

The offline tests set harmless placeholder Supabase/Gemini values if none are configured; live tests skip without a real key.

### Evals

`backend/evals/` runs scripted two-party disputes (English, Hinglish, Hindi; including a manipulator, a hidden threat, coercion, a minor and a party who never acknowledges the other) through the real pipeline and checks for leaks between the two sides, safety recall, neutral language and balance. See `backend/evals/README.md`.

```bash
cd backend
python -m evals.run            # needs GEMINI_API_KEY; skips cleanly without one
```

## Flow to try

1. Sign in as Person A and start a session (optional relationship context).
2. Copy the invite or share via WhatsApp.
3. Open the invite in a private window as Person B (no login).
4. Before their first message, each person reads a short "How Mediator works" card (AI, privacy, the team can see rooms, stop anytime, not for emergencies) and accepts it. Each person talks in their private chat, then taps **I'm ready to share**. The mediator drafts a short summary of their side from their own chat; they edit it and approve the exact words the other person will read. Approved text is safety-checked before it is released.
5. When both have shared, the joint view shows each side in its own approved words, a "where you overlap" note, and ideas drawn only from those two texts. Nothing else from either private chat is shared.
6. Each person answers every idea privately (*Works for me* / *Needs a change* / *Not for me*) and can suggest their own. You only see the other person's answer once you've given yours. Ideas both accept become agreed.
7. Either person drafts the agreement: the agreed ideas word for word, plus a neutral summary and notes on anything vague. Changing an answer clears an unsigned draft. The room is resolved only when **both** sign the same version.

Either person can use **Options → Leave this session**, **Talk to a person** or **Delete my data** at any time; Person A can also delete the whole room. Person A's invite link works for `INVITE_TTL_DAYS` if unused, can be replaced from the room until the other person joins, and is hidden from Person A once they have joined. Both pause the room; only the person who stopped it sees why, and a *Talk to a person* request shows up as a `referral` in the admin portal. Signed-in people see **Your rooms** on the home page; invited people's links are remembered on their device.

Crisis / severe-harm phrases halt the room. The person who wrote them sees Indian helpline numbers (the single list lives in `backend/app/safety.py`; re-verify it before any public launch). The other person only sees that the session is paused.

## Out of scope for this local MVP

A full legal/clinical safety review, and rate limits shared across several backend instances (the built-in limits are per process).

Example dispute scripts for manual testing live in `backend/tests/fixtures/scenarios.json`.
