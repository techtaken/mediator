-- Joint session: both parties react to ideas, agree on terms, and sign one
-- agreement. Run after 005_share_approval.sql.

create table if not exists public.joint_ideas (
  id uuid primary key default gen_random_uuid(),
  session_id uuid not null references public.sessions (id) on delete cascade,
  text text not null,
  -- 'mediator' for generated options, otherwise the party who suggested it.
  source text not null,
  position int not null default 0,
  created_at timestamptz not null default now(),
  constraint joint_ideas_text_len_chk check (char_length(text) between 1 and 300),
  constraint joint_ideas_source_chk check (source in ('mediator', 'user_a', 'user_b'))
);

create index if not exists joint_ideas_session_idx on public.joint_ideas (session_id, position);

create table if not exists public.idea_responses (
  idea_id uuid not null references public.joint_ideas (id) on delete cascade,
  session_id uuid not null references public.sessions (id) on delete cascade,
  party_role party_role not null,
  response text not null,
  note text,
  updated_at timestamptz not null default now(),
  primary key (idea_id, party_role),
  constraint idea_responses_party_chk check (party_role in ('user_a', 'user_b')),
  constraint idea_responses_response_chk check (response in ('yes', 'change', 'no')),
  constraint idea_responses_note_len_chk check (note is null or char_length(note) <= 300)
);

create index if not exists idea_responses_session_idx on public.idea_responses (session_id);

-- One live agreement per session. Redrafting bumps the version and clears
-- both signatures, so nobody can be held to text they didn't sign.
create table if not exists public.agreements (
  session_id uuid primary key references public.sessions (id) on delete cascade,
  version int not null default 1,
  summary text,
  terms jsonb not null default '[]'::jsonb,
  flags jsonb not null default '[]'::jsonb,
  created_by party_role,
  created_at timestamptz not null default now(),
  signed_a_at timestamptz,
  signed_b_at timestamptz
);

alter table public.joint_ideas enable row level security;
alter table public.idea_responses enable row level security;
alter table public.agreements enable row level security;

revoke all on public.joint_ideas from anon, authenticated;
revoke all on public.idea_responses from anon, authenticated;
revoke all on public.agreements from anon, authenticated;

grant all on public.joint_ideas to service_role;
grant all on public.idea_responses to service_role;
grant all on public.agreements to service_role;
