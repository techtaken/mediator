-- People's names. Person A's lives in their profile and is copied onto each room
-- they open; Person B's is given when they join and lives only on that room, so
-- deleting a room removes the names with it.
-- Run after 010_invite_pin.sql. Safe to re-run.

create table if not exists public.profiles (
  user_id uuid primary key references auth.users (id) on delete cascade,
  name text not null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

alter table public.profiles enable row level security;
revoke all on public.profiles from anon, authenticated;
grant all on public.profiles to service_role;

alter table public.sessions
  add column if not exists name_a text,
  add column if not exists name_b text;
