# QuickBooks Online → Supabase client sync

Two separate jobs:

1. **OAuth setup (once per office)** — `qbo_oauth_setup.py` stores `realm_id` +
   `refresh_token` in Supabase `qbo_tokens`. Does **not** touch `clients`.
2. **Customer sync (cron / manual)** — `scripts/sync_qbo_clients.py` refreshes
   access tokens from `qbo_tokens`, **writes the rotated refresh token back
   immediately**, pulls QBO Customers, upserts Supabase `clients`.

Timmy and the dashboard only **read** `clients` — they never call QBO.
Webhooks and writing back to QuickBooks are out of scope.

## Mental model

| Piece | Role |
|-------|------|
| `qbo_tokens` | Source of truth for OAuth keys (rotating refresh) |
| `clients` | Roster Timmy/dashboard use |
| `QBO_COMPANIES` in `.env` | **Deprecated** — cannot hold rotated tokens across cron runs |

## Phase 0 — Ops (one-time)

### Preferred (Production): dashboard OAuth on Vercel

1. Intuit app **Production** Redirect URI (exact):
   `https://dashboard-gcd1.vercel.app/api/qbo/callback`
2. Vercel project env (Production) — server-only, not `NEXT_PUBLIC_`:
   - `QBO_CLIENT_ID`, `QBO_CLIENT_SECRET`
   - `QBO_REDIRECT_URI=https://dashboard-gcd1.vercel.app/api/qbo/callback`
   - `QBO_ENVIRONMENT=production`
   - `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY` (already used by the dashboard)
3. Run SQL: [`docs/supabase-qbo-tokens.sql`](supabase-qbo-tokens.sql)
4. Deploy dashboard with `/api/qbo/*` routes, then sign in as **admin** and open:
   `https://dashboard-gcd1.vercel.app/qbo-connect`
5. Click **Connect GCD**, then **Connect MH** (company switcher must match).

Verify two rows: `select office, realm_id, updated_at from qbo_tokens;`

### Alternate: local `qbo_oauth_setup.py`

Only if Intuit allows your redirect (Production often rejects `http://localhost`).
Kit `.env`: `QBO_*` + Supabase service role; `pip install intuit-oauth requests python-dotenv`;
run `python qbo_oauth_setup.py` twice.

**Security (conscious v1 choice):** refresh tokens are plaintext in `qbo_tokens`.
RLS blocks anon/authenticated; only the service role used by scripts can read them.
Same trust boundary as other service-role secrets in Supabase.

## Sync run

```bash
python scripts/sync_qbo_clients.py --dry-run
python scripts/sync_qbo_clients.py
```

### Dry-run behavior (important)

`--dry-run` skips **`clients`** inserts/updates only. It still:

1. Refreshes the Intuit access token (which **invalidates** the old refresh token).
2. Writes the **new** refresh token to `qbo_tokens` immediately.

If you refresh and do not save, the next run (dry or not) fails with a dead refresh.

### Concurrency

If an office’s `qbo_tokens.updated_at` is within the last **5 minutes**, that
office is skipped (`skipped_recent_refresh`) so a manual run and the GitHub
Action cannot race-invalidate the same refresh token.

### Refresh failure / re-auth

Refresh tokens also hit an absolute ~100-day window, and die on revoke /
password / security changes. If refresh fails for an office:

- Sync logs loudly which office failed and tells you to re-run
  `python qbo_oauth_setup.py` for that office.
- The other office still syncs when possible.
- Process exits **non-zero** (GitHub Action shows red).

No Slack/email in v1 — failed Actions + stderr are the alert.

### Clients missing from QBO

v1 does **not** mass-deactivate or delete `clients` rows that are absent from
the QBO pull (orphans stay until a later phase or manual cleanup). Customers
returned with QBO `Active=false` still upsert `active=false`.

Each successful run also seeds **Unassigned** for GCD and MH if missing.

Upsert rules: match by `qbo_customer_id` when present, else `(name, office)`.
An existing hit always counts as **update** (no field-diff skip). Duplicate
display names across offices are separate rows.

## GitHub Actions

Workflow: `.github/workflows/qbo-clients-sync.yml` (every 6 hours + manual).

Repo **Secrets** (not committed files):

- `QBO_CLIENT_ID`, `QBO_CLIENT_SECRET`
- `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`

Do **not** put `QBO_COMPANIES` or QBO secrets on Vercel. Tokens are read from
Supabase `qbo_tokens` at job runtime.

## Ops checklist

- [ ] `docs/supabase-qbo-tokens.sql` applied; RLS on; two rows (GCD + MH)
- [ ] Every active `employees.office` is `GCD` or `MH`
- [ ] Unassigned exists for GCD + MH after first sync
- [ ] Spot-check new QBO customers in `clients` with correct `office`
- [ ] On refresh failure: re-run `qbo_oauth_setup.py` for that office only
