-- What the dispute is about, in the words of the person who opened the room.
-- Shown verbatim to the invited person, so they know who started it and why.
alter table public.sessions
  add column if not exists topic text;

do $$ begin
  alter table public.sessions
    add constraint sessions_topic_len_chk check (topic is null or char_length(topic) <= 300);
exception
  when duplicate_object then null;
end $$;
