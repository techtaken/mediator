-- Private text is now stored encrypted by the backend (backend/app/crypto.py).
-- Encrypted text is longer than the original, so the character limits on share
-- text move to the API (it still accepts at most 1200 characters).
alter table public.party_shares drop constraint if exists party_shares_draft_len_chk;
alter table public.party_shares drop constraint if exists party_shares_approved_len_chk;

-- After running this, encrypt rows written before this change:
--   cd backend && .venv/bin/python -m app.encrypt_existing
