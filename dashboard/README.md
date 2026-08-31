# Timmy personal hours dashboard

Interactive hours dashboard with exec KPIs, pay-period ranges, and inline day-detail editing.

## Run locally

```bash
cd dashboard
npm install
npm run dev
```

Open http://localhost:4321

## Modes

| Env | Behavior |
|-----|----------|
| `NEXT_PUBLIC_DASHBOARD_DATA_SOURCE=mock` (default) | In-memory data; full edit/add UX, no Supabase |
| `supabase` | Live read/write on `time_entries_timmy_v2` only |

### Supabase env (pilot)

- `SUPABASE_URL`
- `SUPABASE_SERVICE_ROLE_KEY` or `SUPABASE_KEY`
- `DASHBOARD_STAFF_NAME` / `DASHBOARD_OFFICE`
- Optional: `SUPABASE_ENTRIES_TABLE`, `SUPABASE_CLIENTS_TABLE`, `SUPABASE_JOB_CODES_TABLE`

**Never writes** to `clients` or `job_codes` — read-only for combobox validation.

## Features

- Ranges: Today, Yesterday, This week (Sun–Sat), This/Last pay period (US Central)
- KPIs: Total, Billable, Admin (+ %), Clients
- Charts: Admin vs non-admin by day, top 8 clients, job codes
- Day detail: editable Client/Job Code (validated), free Notes/Times, Add entry
- Pay-period edit window matches Timmy plugin (`timeassist/pay_period.py`)

## Tests

```bash
npm test
```
