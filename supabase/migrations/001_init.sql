-- Mediator MVP schema
-- Run this in the Supabase SQL editor (or via CLI) on a fresh project.

create extension if not exists "pgcrypto";

do $$ begin
  create type session_status as enum (
    'intake',
    'joint_review',
    'resolved',
    'halted'
  );
exception
  when duplicate_object then null;
end $$;

do $$ begin
  create type party_role as enum ('user_a', 'user_b', 'ai');
exception
  when duplicate_object then null;
end $$;

create table if not exists public.sessions (
  id uuid primary key default gen_random_uuid(),
  created_by uuid references auth.users (id) on delete set null,
  status session_status not null default 'intake',
  relationship_context text,
  invite_token_b text not null unique default encode(gen_random_bytes(24), 'hex'),
  user_a_ready boolean not null default false,
  user_b_ready boolean not null default false,
  halted_reason text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.messages (
  id uuid primary key default gen_random_uuid(),
  session_id uuid not null references public.sessions (id) on delete cascade,
  sender_role party_role not null,
  audience_role party_role not null,
  content text not null,
  is_private boolean not null default true,
  created_at timestamptz not null default now()
);

create table if not exists public.joint_summaries (
  id uuid primary key default gen_random_uuid(),
  session_id uuid not null unique references public.sessions (id) on delete cascade,
  user_a_perspective text not null,
  user_b_perspective text not null,
  compromises jsonb not null default '[]'::jsonb,
  created_at timestamptz not null default now()
);

create index if not exists messages_session_created_idx
  on public.messages (session_id, created_at);

create or replace function public.set_updated_at()
returns trigger
language plpgsql
as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

drop trigger if exists sessions_set_updated_at on public.sessions;
create trigger sessions_set_updated_at
  before update on public.sessions
  for each row execute procedure public.set_updated_at();

alter table public.sessions enable row level security;
alter table public.messages enable row level security;
alter table public.joint_summaries enable row level security;

-- Browser clients never talk to these tables directly.
-- FastAPI uses the service-role key and enforces isolation in application code.
-- Keep RLS on with no anon/authenticated policies so leaked keys cannot read chats.

revoke all on public.sessions from anon, authenticated;
revoke all on public.messages from anon, authenticated;
revoke all on public.joint_summaries from anon, authenticated;

grant all on public.sessions to service_role;
grant all on public.messages to service_role;
grant all on public.joint_summaries to service_role;
