-- Share approval: each party reviews and approves the exact words the other
-- party will see. Drafts are private to their author until approved.

create table if not exists public.party_shares (
  session_id uuid not null references public.sessions (id) on delete cascade,
  party_role party_role not null,
  draft_text text,
  approved_text text,
  approved_at timestamptz,
  updated_at timestamptz not null default now(),
  primary key (session_id, party_role),
  constraint party_shares_party_chk check (party_role in ('user_a', 'user_b')),
  constraint party_shares_draft_len_chk check (draft_text is null or char_length(draft_text) <= 1200),
  constraint party_shares_approved_len_chk check (approved_text is null or char_length(approved_text) <= 1200)
);

alter table public.party_shares enable row level security;
revoke all on public.party_shares from anon, authenticated;
grant all on public.party_shares to service_role;

-- What the two approved accounts have in common, written for both parties.
alter table public.joint_summaries
  add column if not exists common_ground text;
