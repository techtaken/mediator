-- Each party explicitly accepts how Mediator works before their first message.
alter table public.sessions
  add column if not exists consented_a_at timestamptz,
  add column if not exists consented_b_at timestamptz;

-- "My rooms" lists a signed-in person's rooms, newest first.
create index if not exists sessions_created_by_idx
  on public.sessions (created_by, created_at desc);
