-- Phase 0 hardening: optimistic locking, per-party halts, idempotent joint build,
-- and structured private memory. Run after 002_mediation_agents.sql.

-- New status while the joint pipeline runs, so two "ready" clicks can't both build it.
alter type session_status add value if not exists 'building_joint';

alter table public.sessions
  add column if not exists state_version int not null default 0,
  add column if not exists halted_for party_role,
  add column if not exists halt_kind text;

do $$ begin
  alter table public.sessions
    add constraint sessions_halted_for_chk check (halted_for in ('user_a', 'user_b'));
exception
  when duplicate_object then null;
end $$;

do $$ begin
  alter table public.sessions
    add constraint sessions_halt_kind_chk check (halt_kind in ('safety', 'referral', 'withdrawn'));
exception
  when duplicate_object then null;
end $$;

-- Positions, interests, hidden concerns and issues a party raised in private.
-- Previously these leaked into the shared mediation_state.
alter table public.private_memories
  add column if not exists profile jsonb not null default '{}'::jsonb;
