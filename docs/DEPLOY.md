# Deploying Mediator

Nothing here has been deployed. These are ready-to-use configs and the steps
that need your accounts.

| Part | Where | Config |
|---|---|---|
| Database + auth | Supabase | `supabase/migrations/001…014` |
| API (FastAPI) | Render (Docker) | `render.yaml`, `backend/Dockerfile` |
| Scheduled jobs | Render cron (or any scheduler) | `render.yaml` |
| Web app (Next.js) | Vercel | notes below |
| CI | GitHub Actions | `.github/workflows/ci.yml` |

## 1. Supabase

1. Create a project, enable Email auth with Email OTP.
2. Run every migration in `supabase/migrations/` in order in the SQL editor (001 to 009). All are idempotent.
3. Add your web app's URL (e.g. `https://mediator.vercel.app`) under **Authentication → URL configuration**.
4. Keep the project URL, publishable key, secret key and JWKS URL for the steps below.

## 2. API on Render

1. In Render, **New → Blueprint**, pick this repo. `render.yaml` creates:
   - `mediator-api`: a Docker web service from `backend/`, health check `/health`, one instance.
   - `mediator-retention`: a daily cron calling `POST /api/jobs/retention`.
   - `mediator-followups`: an hourly cron calling `POST /api/jobs/followups`.
2. Fill in the `sync: false` values in the dashboard (table below). `JOB_TOKEN` is generated and shared with the crons. Set each cron's `API_URL` to the API's public URL.
3. Keep **one instance**. Rate limits and live-update streams are in-process; with several instances each counts separately. Scale up by moving the limiter to Redis first.

Fly.io or Cloud Run work the same way with the Dockerfile. The container listens on `$PORT` (default 8000).

```bash
docker build -t mediator-api backend
docker run -p 8000:8000 --env-file backend/.env mediator-api
```

## 3. Web app on Vercel

1. **New project**, import the repo, set **Root Directory** to `frontend` (framework: Next.js, defaults are fine).
2. Environment variables (Production and Preview):
   - `NEXT_PUBLIC_SUPABASE_URL`
   - `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY`
   - `NEXT_PUBLIC_API_URL`: the Render API URL, e.g. `https://mediator-api.onrender.com`
3. Set the API's `CORS_ORIGINS` and `FRONTEND_BASE_URL` to the Vercel URL. Invite links are built from `FRONTEND_BASE_URL`.
4. Live updates are streamed straight from the API to the browser (not through Vercel), so no Vercel streaming settings are needed. Render passes server-sent events through; the API sends `X-Accel-Buffering: no` for proxies that buffer.

## 4. Scheduled jobs without Render

Any scheduler can call the jobs with the `X-Job-Token` header:

```bash
curl -fsS -X POST -H "X-Job-Token: $JOB_TOKEN" "$API_URL/api/jobs/retention"   # daily
curl -fsS -X POST -H "X-Job-Token: $JOB_TOKEN" "$API_URL/api/jobs/followups"   # hourly
```

For example, a GitHub Actions workflow with `on: schedule`, `JOB_TOKEN` and `API_URL` as repository secrets, or Supabase `pg_cron` with `pg_net`. Both jobs are idempotent.

## 5. CI

`.github/workflows/ci.yml` runs on every push and pull request:

- backend: `pytest -m "not live"` with placeholder settings (no secrets needed);
- frontend: `npm ci`, `next typegen`, `tsc --noEmit`, `eslint`, `next build` with placeholder public env values.

To run the live evals in CI, add a `GEMINI_API_KEY` repository secret and start the workflow by hand (**Actions → CI → Run workflow**, tick "Also run the live Gemini evals"). The report is uploaded as an artifact.

## Environment variables

### Backend (`backend/.env` locally, Render dashboard in production)

| Variable | Required | Default | Notes |
|---|---|---|---|
| `SUPABASE_URL` | yes | — | Project URL |
| `SUPABASE_SECRET_KEY` | yes | — | `sb_secret_…`, backend only, never in the browser |
| `SUPABASE_PUBLISHABLE_KEY` | no | — | Not used by the backend today |
| `SUPABASE_JWKS_URL` | no | `<SUPABASE_URL>/auth/v1/.well-known/jwks.json` | Verifies Person A's sign-in |
| `GEMINI_API_KEY` | yes | — | Google AI Studio key |
| `DATA_ENCRYPTION_KEY` | yes | — | Encrypts private chats at rest; the API won't start without it. 32 random bytes, base64 (command in `backend/.env.example`). **Back it up**: losing it loses every private chat. Use a different key from local dev |
| `DATA_ENCRYPTION_OLD_KEYS` | no | empty | Comma-separated previous keys, after a rotation |
| `GEMINI_MODEL` | no | `gemini-3.5-flash-lite` | |
| `GEMINI_TIMEOUT_MS` | no | 30000 | Per agent call |
| `GEMINI_PRICE_INPUT_PER_M` / `GEMINI_PRICE_OUTPUT_PER_M` | no | 0.10 / 0.40 | USD per 1M tokens, admin cost estimate only |
| `CORS_ORIGINS` | yes in prod | `http://localhost:3000` | Comma-separated web origins |
| `FRONTEND_BASE_URL` | yes in prod | `http://localhost:3000` | Used in invite links |
| `ADMIN_EMAILS` | no | empty (no admins) | Comma-separated |
| `RATE_LIMIT_ENABLED` | no | true | |
| `RATE_LIMIT_SESSIONS_PER_HOUR` | no | 10 | Per signed-in person |
| `RATE_LIMIT_MESSAGES_PER_MINUTE` | no | 12 | Per person per room |
| `RATE_LIMIT_WRITES_PER_MINUTE` | no | 30 | Per person per room |
| `INVITE_TTL_DAYS` | no | 14 | Unused invite links expire |
| `PIN_ACCESS_TTL_MINUTES` | no | 120 | How long a correct PIN opens the invited person's room |
| `PIN_MAX_ATTEMPTS` | no | 5 | Wrong PINs before entry locks |
| `PIN_LOCK_MINUTES` | no | 15 | How long entry stays locked |
| `PRIVATE_ORCHESTRATOR` | no | false | Ask the orchestrator model in private chat (adds a call per reply) |
| `RETENTION_DAYS` | no | 180 | Rooms older than this are removed (0 = never) |
| `AUDIT_REASON_RETENTION_DAYS` | no | 30 | Free-text audit reasoning cleared after this |
| `JOB_TOKEN` | yes for cron | empty | Secret for `/api/jobs/*` |
| `FOLLOWUP_DEFAULT_DAYS` | no | 14 | Check-in delay when a signer doesn't pick one |
| `SSE_MAX_SECONDS` | no | 300 | Live-update streams reconnect after this |

### Frontend (`frontend/.env.local` locally, Vercel in production)

| Variable | Required | Notes |
|---|---|---|
| `NEXT_PUBLIC_SUPABASE_URL` | yes | Same project URL |
| `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY` | yes | `sb_publishable_…` |
| `NEXT_PUBLIC_API_URL` | yes in prod | Defaults to `http://localhost:8000` |

## Before a public launch

- Re-verify the helpline numbers in `backend/app/safety.py`.
- Set real Gemini prices for the cost estimate.
- Run `python -m evals.run` against the production model and read the report.
- Decide the retention period with whoever owns privacy, and update `RETENTION_DAYS`. The consent card shows it.
