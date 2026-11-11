-- The invite link alone no longer opens the invited person's room. They choose
-- a PIN when they join; link + PIN gets a short-lived access token. Person A
-- has the link too (they sent it), and never learns the PIN.
-- Run after 009_phase3_growth.sql. Safe to re-run.

alter table public.sessions
  add column if not exists b_pin_hash text,
  add column if not exists b_pin_set_at timestamptz,
  add column if not exists b_pin_failed_attempts int not null default 0,
  add column if not exists b_pin_locked_until timestamptz;

-- Only a hash of each token is stored.
create table if not exists public.room_access_tokens (
  token_hash text primary key,
  session_id uuid not null references public.sessions (id) on delete cascade,
  expires_at timestamptz not null,
  created_at timestamptz not null default now()
);

create index if not exists room_access_tokens_session_idx on public.room_access_tokens (session_id);

alter table public.room_access_tokens enable row level security;
revoke all on public.room_access_tokens from anon, authenticated;
grant all on public.room_access_tokens to service_role;
