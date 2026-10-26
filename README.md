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
4. Copy keys from **Project Settings → API**:
   - Project URL
   - Publishable key (`sb_publishable_…`) for the browser
   - Secret key (`sb_secret_…`) for FastAPI only
   - JWKS URL (`/auth/v1/.well-known/jwks.json`) so FastAPI can verify Person A’s session

Row Level Security is on and browser roles have no table grants. Next.js never talks to Postgres; FastAPI uses the secret key and isolates A/B chats in application code.

## 2. Environment files

Copy `backend/.env.example` → `backend/.env` and `frontend/.env.example` → `frontend/.env.local`. Put real keys only in those local files, never in the example templates.

The default model is `gemini-3.5-flash-lite`. If it is unavailable on your key, set `GEMINI_MODEL` to another current Flash model. `GEMINI_TIMEOUT_MS` (default 30000) caps each agent call; failed calls are retried up to 3 times.

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

### Tests

```bash
cd backend
.venv/bin/python -m pytest -m "not live"   # offline: scripted agents + in-memory Supabase fake
.venv/bin/python -m pytest -m live         # calls the real Gemini API (uses GEMINI_API_KEY)
```

## Flow to try

1. Sign in as Person A and start a session (optional relationship context).
2. Copy the invite or share via WhatsApp.
3. Open the invite in a private window as Person B (no login).
4. Each person vents in their private chat, then taps **Ready for joint session**.
5. When both are ready, the joint view shows neutralized perspectives and 2–3 compromises.

Crisis / severe-harm phrases halt the room. The person who wrote them sees Indian helpline numbers (the single list lives in `backend/app/safety.py`; re-verify it before any public launch). The other person only sees that the session is paused.

## Out of scope for this local MVP

Cloud deploy (Vercel / Render), production rate limits, and a full legal/clinical safety review.

Example dispute scripts for manual testing live in `backend/tests/fixtures/scenarios.json`.
