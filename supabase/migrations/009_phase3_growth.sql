-- Phase 3: check-ins after an agreement, the referral inbox, language
-- preference, translations of shared text, and private "think it through"
-- questions. Run after 008_phase2_quality.sql. Safe to re-run.

-- Check-ins. Each person is asked separately, privately, on the schedule they
-- picked when signing. `answers` holds only that person's own answers.
create table if not exists public.followups (
  id uuid primary key default gen_random_uuid(),
  session_id uuid not null references public.sessions (id) on delete cascade,
  party_role party_role not null,
  round int not null default 1,
  due_at timestamptz not null,
  status text not null default 'scheduled',
  answers jsonb,
  reply text,
  opened_at timestamptz,
  answered_at timestamptz,
  created_at timestamptz not null default now(),
  constraint followups_party_chk check (party_role in ('user_a', 'user_b')),
  constraint followups_status_chk check (status in ('scheduled', 'open', 'answered')),
  unique (session_id, party_role, round)
);

create index if not exists followups_due_idx on public.followups (status, due_at);

alter table public.sessions
  -- Days until each person's check-in, picked when they sign (0 = none).
  add column if not exists followup_days_a int,
  add column if not exists followup_days_b int,
  -- Referral inbox: a neutral brief from shared content only, and who handled it.
  add column if not exists referral_brief jsonb,
  add column if not exists referral_brief_at timestamptz,
  add column if not exists referral_handled_at timestamptz,
  add column if not exists referral_handled_by text,
  -- Each person's language for the mediator's replies.
  add column if not exists language_a text,
  add column if not exists language_b text;

do $$ begin
  alter table public.sessions
    add constraint sessions_language_chk check (
      (language_a is null or language_a in ('en', 'hinglish', 'hi'))
      and (language_b is null or language_b in ('en', 'hinglish', 'hi'))
    );
exception
  when duplicate_object then null;
end $$;

-- A translation of one person's approved text, shown to the other labelled as
-- a translation next to the original.
create table if not exists public.share_translations (
  session_id uuid not null references public.sessions (id) on delete cascade,
  source_party party_role not null,
  language text not null,
  source_text text not null,
  text text not null,
  created_at timestamptz not null default now(),
  primary key (session_id, source_party, language),
  constraint share_translations_language_chk check (language in ('en', 'hinglish', 'hi'))
);

-- Private "think it through" questions about one idea, for one person.
create table if not exists public.reality_checks (
  idea_id uuid not null references public.joint_ideas (id) on delete cascade,
  session_id uuid not null references public.sessions (id) on delete cascade,
  party_role party_role not null,
  questions jsonb not null default '[]'::jsonb,
  created_at timestamptz not null default now(),
  primary key (idea_id, party_role),
  constraint reality_checks_party_chk check (party_role in ('user_a', 'user_b'))
);

alter table public.followups enable row level security;
alter table public.share_translations enable row level security;
alter table public.reality_checks enable row level security;

revoke all on public.followups from anon, authenticated;
revoke all on public.share_translations from anon, authenticated;
revoke all on public.reality_checks from anon, authenticated;

grant all on public.followups to service_role;
grant all on public.share_translations to service_role;
grant all on public.reality_checks to service_role;

-- Referral inbox lists halted rooms by kind.
create index if not exists sessions_halt_kind_idx on public.sessions (halt_kind, created_at desc);
