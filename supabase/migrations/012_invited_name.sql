-- What Person A calls the person they're inviting. Used until that person joins
-- and gives their own name (sessions.name_b), which then takes over.
-- Run after 011_names.sql. Safe to re-run.

alter table public.sessions
  add column if not exists invited_as text;
