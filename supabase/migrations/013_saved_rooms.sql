-- Person B can save a room to their account, so it shows in their chats and
-- they can reopen it from any device with their PIN instead of the link.
-- Run after 012_invited_name.sql. Safe to re-run.

alter table public.sessions
  add column if not exists user_b_id uuid references auth.users (id) on delete set null,
  add column if not exists b_saved_at timestamptz;

create index if not exists sessions_user_b_idx on public.sessions (user_b_id);
