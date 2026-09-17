# QBO sync verify checklist (Phase 4)

Do these in order after code is in place. Agent cannot complete steps that need
your Intuit login or the Supabase SQL editor.

## Blocked until ops

As of last agent check: `public.qbo_tokens` was **missing** (PostgREST 404 /
`PGRST205`). Apply SQL before OAuth or sync.

1. [ ] Paste/run [`docs/supabase-qbo-tokens.sql`](supabase-qbo-tokens.sql) in
       Supabase SQL editor.
2. [ ] Confirm `.env` has `QBO_REDIRECT_URI`, `QBO_ENVIRONMENT`, client id/secret,
       `SUPABASE_SERVICE_ROLE_KEY`.
3. [ ] Intuit app redirect URI = `http://localhost:8000/callback`.
4. [ ] `python qbo_oauth_setup.py` for **GCD**, then again for **MH**.
5. [ ] `select office, realm_id, updated_at from qbo_tokens;` → 2 rows.

## Sync smoke

```bash
python scripts/sync_qbo_clients.py --dry-run
# Expect JSON counts; qbo_tokens.updated_at / refresh may change
python scripts/sync_qbo_clients.py
```

6. [ ] Dry-run exits 0 (or non-zero only if refresh needs re-auth — follow stderr).
7. [ ] Real sync: spot-check `clients` (`office`, `qbo_customer_id`, `active`).
8. [ ] Timmy / dashboard show new names (no redeploy needed for roster read).

## If refresh fails

Re-run `python qbo_oauth_setup.py` for **that office only**. Do not put
rotating tokens back into `.env` / `QBO_COMPANIES`.
