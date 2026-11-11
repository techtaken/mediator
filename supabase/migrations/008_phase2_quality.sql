-- Phase 2: agent call stats, expiring invite links, retention support.
-- Run after 007_consent.sql. Safe to re-run.

-- One row per agent (model) call: role, latency, attempts and token usage.
-- No prompt or model text is stored here.
create table if not exists public.agent_calls (
  id bigint generated always as identity primary key,
  session_id uuid not null references public.sessions (id) on delete cascade,
  role text not null,
  ok boolean not null,
  attempts int not null default 1,
  latency_ms int not null default 0,
  model text,
  prompt_tokens int,
  output_tokens int,
  total_tokens int,
  error text,
  created_at timestamptz not null default now()
);

create index if not exists agent_calls_session_idx on public.agent_calls (session_id, created_at);

alter table public.agent_calls enable row level security;
revoke all on public.agent_calls from anon, authenticated;
grant all on public.agent_calls to service_role;

-- Invite links stop working after a while if nobody has joined with them,
-- and Person A can replace the link before the other person joins.
alter table public.sessions
  add column if not exists invite_expires_at timestamptz,
  add column if not exists invite_rotated_at timestamptz;

-- Existing unused invites get the default 14 days from when the room opened.
update public.sessions
  set invite_expires_at = created_at + interval '14 days'
  where invite_expires_at is null and consented_b_at is null;

-- The retention jobs look rooms and audit rows up by age.
create index if not exists sessions_created_at_idx on public.sessions (created_at);
create index if not exists mediation_audit_created_idx on public.mediation_audit_events (created_at);

-- "Delete my data": when each person deleted their private chat and notes.
alter table public.sessions
  add column if not exists data_deleted_a_at timestamptz,
  add column if not exists data_deleted_b_at timestamptz;

-- Free-text agent reasoning in audit rows is cleared after a retention period
-- (AUDIT_REASON_RETENTION_DAYS); stage, agent and gate are kept.
alter table public.mediation_audit_events
  add column if not exists reason_scrubbed boolean not null default false;
