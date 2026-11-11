-- Shared dispute state + isolated private memory for the multi-agent mediator.
-- FastAPI is the only client (service_role). Browser roles stay revoked.

alter table public.sessions
  add column if not exists mediation_state jsonb not null default '{}'::jsonb;

create table if not exists public.private_memories (
  session_id uuid not null references public.sessions (id) on delete cascade,
  party_role party_role not null,
  notes text not null default '',
  updated_at timestamptz not null default now(),
  primary key (session_id, party_role),
  constraint private_memories_party_chk check (party_role in ('user_a', 'user_b'))
);

create table if not exists public.mediation_audit_events (
  id bigint generated always as identity primary key,
  session_id uuid not null references public.sessions (id) on delete cascade,
  stage text,
  agent text,
  gate int,
  reason text,
  payload jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create index if not exists mediation_audit_session_idx
  on public.mediation_audit_events (session_id, created_at);

alter table public.private_memories enable row level security;
alter table public.mediation_audit_events enable row level security;

revoke all on public.private_memories from anon, authenticated;
revoke all on public.mediation_audit_events from anon, authenticated;

grant all on public.private_memories to service_role;
grant all on public.mediation_audit_events to service_role;
