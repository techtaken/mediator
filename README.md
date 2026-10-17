# Mediator

Indian-context shuttle-diplomacy MVP: two private intake rooms, Gemini-mediated NVC summaries, then a joint compromise view.

## Stack

- `frontend/` — Next.js (App Router) + Tailwind
- `backend/` — FastAPI + Google GenAI SDK
- `supabase/migrations/` — Postgres schema (run in your Supabase project)

Person A signs in with email OTP. Person B joins from the invite link with no account. Chat updates by polling.

## 1. Create a Supabase project

1. Create a project at [supabase.com](https://supabase.com).
2. Enable **Email** auth. Turn on **Email OTP** (disable confirmations that require a click-through if you want the in-app code flow).
3. Run `supabase/migrations/001_init.sql` in the SQL editor.
4. Copy keys from **Project Settings → API**:
   - Project URL
   - Publishable key (`sb_publishable_…`) for the browser
   - Secret key (`sb_secret_…`) for FastAPI only
   - JWKS URL (`/auth/v1/.well-known/jwks.json`) so FastAPI can verify Person A’s session

Row Level Security is on and browser roles have no table grants. Next.js never talks to Postgres; FastAPI uses the secret key and isolates A/B chats in application code.

## 2. Environment files

Copy `backend/.env.example` → `backend/.env` and `frontend/.env.example` → `frontend/.env.local`. Put real keys only in those local files, never in the example templates.

If `gemini-2.5-flash` is unavailable on your key, set `GEMINI_MODEL` to another current Flash model.

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

## Flow to try

1. Sign in as Person A and start a session (optional relationship context).
2. Copy the invite or share via WhatsApp.
3. Open the invite in a private window as Person B (no login).
4. Each person vents in their private chat, then taps **Ready for joint session**.
5. When both are ready, the joint view shows neutralized perspectives and 2–3 compromises.

Crisis / severe-harm phrases halt the room and show Indian helpline numbers (iCall, Vandrevala, AASRA, 112).

## Out of scope for this local MVP

Cloud deploy (Vercel / Render), production rate limits, and a full legal/clinical safety review.


### EXAMPLE_ARGUMENT 
 "my 23 yr of child  still a student doing internship is demanding me to buy her a phone which is expensive for her"

Father -> hi , my daughter is demanding expensive phone ig its google10 a , an i am not able to make her understand the importance of simplisity, i dont want to telll her directly that u are 23 yr old now , buy on ur own 

Daughter -> i want a phone , all my friends have iphone , and i am stuck with this old oppo phone , my main motive is to get good , cemera , i am embaressaed ,to alway ask others to click pic of me asn then ask them later or beg them later
