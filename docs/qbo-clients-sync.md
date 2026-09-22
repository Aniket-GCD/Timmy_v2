# QuickBooks Online → Supabase client sync

Three pieces:

1. **OAuth setup (once per office)** — dashboard `/qbo-connect` (or `qbo_oauth_setup.py`)
   stores `realm_id` + `refresh_token` in Supabase `qbo_tokens`. Does **not** touch `clients`.
2. **Customer sync (cron / manual)** — `scripts/sync_qbo_clients.py` refreshes
   access tokens from `qbo_tokens`, **writes the rotated refresh token back
   immediately**, pulls QBO Customers, upserts Supabase `clients`.
3. **Webhooks (near real-time)** — Intuit POSTs to
   `https://dashboard-gcd1.vercel.app/api/qbo/webhook` → verify signature →
   fetch Customer (or soft-deactivate on Delete) → update `clients`.

Timmy and the dashboard only **read** `clients` — they never call QBO.
Writing back to QuickBooks is out of scope.

## Mental model

| Piece | Role |
|-------|------|
| `qbo_tokens` | Source of truth for OAuth keys (rotating refresh) |
| `clients` | Roster Timmy/dashboard use |
| `/api/qbo/webhook` | Near real-time Customer create/update/delete/merge |
| GH Action every 6h | Full pull catch-up if a webhook was missed |
| `QBO_COMPANIES` in `.env` | **Deprecated** |

```text
QBO Customer change
  → Intuit POST /api/qbo/webhook (Vercel)
  → verify QBO_WEBHOOK_VERIFIER_TOKEN (HMAC)
  → realmId → office via qbo_tokens
  → Create/Update/Merge: refresh + fetch Customer → upsert clients
  → Delete: set active=false
```

**Do not** set Intuit’s webhook endpoint to `https://….supabase.co/rest/v1/`.
That is the database API, not a webhook handler. GitHub Actions also cannot
listen for Intuit POSTs.

## Phase 0 — Ops (one-time)

### Preferred (Production): dashboard OAuth on Vercel

1. Intuit app **Production** Redirect URI (exact):
   `https://dashboard-gcd1.vercel.app/api/qbo/callback`
2. Vercel project env (Production) — server-only, not `NEXT_PUBLIC_`:
   - `QBO_CLIENT_ID`, `QBO_CLIENT_SECRET`
   - `QBO_REDIRECT_URI=https://dashboard-gcd1.vercel.app/api/qbo/callback`
   - `QBO_ENVIRONMENT=production`
   - `QBO_WEBHOOK_VERIFIER_TOKEN` (from Intuit Webhooks → Verifier Token)
   - `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY` (already used by the dashboard)
3. Run SQL: [`docs/supabase-qbo-tokens.sql`](supabase-qbo-tokens.sql)
4. Deploy dashboard with `/api/qbo/*` routes, then sign in as **admin** and open:
   `https://dashboard-gcd1.vercel.app/qbo-connect`
5. Click **Connect GCD**, then **Connect MH** (company switcher must match).

Verify two rows: `select office, realm_id, updated_at from qbo_tokens;`

### Webhooks (Production)

1. Intuit → app → Webhooks (Production):
   - **Endpoint URL:** `https://dashboard-gcd1.vercel.app/api/qbo/webhook`
   - **Customer:** Create, Update, Delete, Merge
2. Copy Verifier Token into Vercel `QBO_WEBHOOK_VERIFIER_TOKEN` and redeploy.
3. Smoke-test: create/rename/delete a Customer in QBO → check Supabase `clients`
   and Vercel function logs.

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

If an office’s `qbo_tokens.updated_at` is within the last **5 minutes**, the
**full sync** skips that office (`skipped_recent_refresh`) so a manual run and
the GitHub Action cannot race-invalidate the same refresh token. Webhooks still
refresh when they need to fetch a Customer (and persist the new refresh).

### Refresh failure / re-auth

Refresh tokens also hit an absolute ~100-day window, and die on revoke /
password / security changes. If refresh fails for an office:

- Sync logs loudly which office failed and tells you to re-run
  `/qbo-connect` (or `python qbo_oauth_setup.py`) for that office.
- The other office still syncs when possible.
- Process exits **non-zero** (GitHub Action shows red).

No Slack/email in v1 — failed Actions + stderr / Vercel logs are the alert.

### Clients missing from QBO

v1 full sync does **not** mass-deactivate or delete `clients` rows that are
absent from the QBO pull (orphans stay until a later phase or manual cleanup).
Webhook **Delete** events still set `active=false` for that `qbo_customer_id`.
Customers returned with QBO `Active=false` still upsert `active=false`.

Each successful full sync also seeds **Unassigned** for GCD and MH if missing.

Upsert rules: match by `qbo_customer_id` when present, else `(name, office)`.
An existing hit always counts as **update** (no field-diff skip). Duplicate
display names across offices are separate rows.

## GitHub Actions

Workflow: `.github/workflows/qbo-clients-sync.yml` (every 6 hours + manual).

Repo **Secrets** (not committed files):

- `QBO_CLIENT_ID`, `QBO_CLIENT_SECRET`
- `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`

Do **not** put rotating refresh tokens in GitHub secrets; they live in `qbo_tokens`.
QBO client id/secret + webhook verifier belong on **Vercel** for the dashboard
OAuth + webhook routes.

## Ops checklist

- [ ] `docs/supabase-qbo-tokens.sql` applied; RLS on; two rows (GCD + MH)
- [ ] Vercel has `QBO_*` + `QBO_WEBHOOK_VERIFIER_TOKEN` + service role
- [ ] Intuit webhook endpoint = `/api/qbo/webhook`
- [ ] Every active `employees.office` is `GCD` or `MH`
- [ ] Unassigned exists for GCD + MH after first sync
- [ ] Spot-check new QBO customers in `clients` with correct `office`
- [ ] On refresh failure: re-auth that office on `/qbo-connect`
