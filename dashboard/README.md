# Timmy firm hours dashboard

Next.js dashboard for GCD hours. Employees use Timmy in Claude; this app shows submitted hours (and live “on the clock” in the header). With Supabase mode, staff sign in via **magic link** (Outlook).

## Run locally

```bash
cd dashboard
cp .env.example .env.local   # then fill keys (or copy from plugin Timmy MCP)
npm install
npm run dev
```

Open http://localhost:4321

```bash
npm test
```

**Restart `npm run dev` after any `NEXT_PUBLIC_*` change.** Env lives in `dashboard/.env.local` (gitignored), not the kit root `.env`.

## Modes

| Env | Behavior |
|-----|----------|
| `NEXT_PUBLIC_DASHBOARD_DATA_SOURCE=mock` (default) | In-memory seed; **no login** (dev bypass — mock admin user) |
| `supabase` | Live data + **magic-link login** required; create/edit → `POST`/`PATCH` `/api/entries` → `time_entries_timmy_v2` |

Polling: entries + currently-working every **30s** while the tab is visible.

### Go-live (flip off mock)

1. Set in `dashboard/.env.local` (and the same keys in **Vercel → Project → Settings → Environment Variables**, then redeploy):

```env
NEXT_PUBLIC_DASHBOARD_DATA_SOURCE=supabase
NEXT_PUBLIC_SUPABASE_URL=...
NEXT_PUBLIC_SUPABASE_ANON_KEY=...          # Auth only (anon / publishable)
SUPABASE_URL=...
SUPABASE_SERVICE_ROLE_KEY=...            # REQUIRED for create/edit (service_role or sb_secret_)
```

Do **not** use the publishable/`sb_publishable_` key as the server write key. That often makes PostgREST `PATCH` update 0 rows (RLS); the UI reloads old data and Supabase looks unchanged.

2. Confirm Network tab shows `/api/entries` with `200` on save (not silent in-memory mock refreshes).
3. Confirm Supabase Table Editor → `time_entries_timmy_v2` updates within seconds (`source_file` = `timmy-dashboard` on dashboard writes).
4. If Save shows `…` then reverts with no change: check the server terminal for the `SUPABASE_SERVICE_ROLE_KEY` warning and set the service role key, then restart.

### Live write smoke checklist

With Table Editor open on `time_entries_timmy_v2`:

1. Magic-link login as admin (`is_admin=true`).
2. **Edit** an existing row (table or calendar) → row updates in Supabase.
3. **Create** from calendar blank click → new row with correct staff/times/client/job/account.
4. Non-admin → only self; out-of-window Edit disabled; create on locked date ignored.
5. Admin out-of-window edit → confirm dialog → save succeeds.
6. Non-admin spoof via API (wrong `staff_name`) → 403.
7. Admin **Office** filter GCD/MH → entries and client picker narrow; create on MH client stores `office=MH`.
8. Calendar client search finds names beyond the first 12; **Clear times** + duration-only save works.
9. After MH CSV import, MH clients appear in the picker when Office=MH.
10. **Remap Unassigned** updates placeholder rows to the real client name.

### Hydration warning (Grammarly)

Console hydration mismatches that add `data-gr-ext-installed` / `data-new-gr-c-s-check-loaded` on `<body>` come from the **Grammarly** browser extension, not app code. Safe to ignore. The root layout sets `suppressHydrationWarning` on `<body>` to quiet that noise.

## Auth (magic link)

1. User opens the dashboard → `/login`
2. Enters work Outlook email → Supabase emails a one-time link
3. Click link → session cookie → app loads `employees` by `lower(email)`
4. **`is_admin`** → firm view + Employee + Office dropdowns; otherwise only that person’s hours

Staff never need Supabase console access. You maintain `employees.email` / `is_admin` / `office` via CSV sync (below).

### Supabase Auth setup (you)

1. Authentication → Providers → **Email** enabled (magic link)
2. URL configuration → Redirect URLs include:
   - `http://localhost:4321/auth/callback`
   - `https://dashboard-gcd1.vercel.app/auth/callback`
3. Site URL = your production dashboard URL (`https://dashboard-gcd1.vercel.app`)

### Magic link email branding (not in app code)

Emails say “Supabase” until you change them in the Supabase project:

1. Authentication → Email Templates → Magic Link — edit **Subject** and body (e.g. “Sign in to Timmy Dashboard”).
2. Project Settings → Authentication → SMTP (or custom SMTP) — set **Sender name** to `Timmy` / `GCD` and a from-address you own (e.g. `noreply@gcd.cpa`).

### Multi-office roster sync (operators)

From the **kit root** (uses `dashboard/.env.local` service role):

```bash
python scripts/sync_employees_from_csv.py --dry-run
python scripts/sync_employees_from_csv.py

python scripts/import_mh_clients_csv.py --dry-run
python scripts/import_mh_clients_csv.py
```

Then in Supabase Table Editor: confirm `employees` has GCD + MH rows, and `clients` has MH names plus `Unassigned` for both offices.

QBO read-only client refresh (optional, after OAuth secrets are set):

```bash
python scripts/sync_qbo_clients.py --dry-run
python scripts/sync_qbo_clients.py
```

## Env var names

| Variable | Role |
|----------|------|
| `NEXT_PUBLIC_DASHBOARD_DATA_SOURCE` | `mock` (default) or `supabase` |
| `NEXT_PUBLIC_SUPABASE_URL` | Same project URL (browser Auth) |
| `NEXT_PUBLIC_SUPABASE_ANON_KEY` | Anon/publishable key (**Auth cookies only** — not for writes) |
| `SUPABASE_URL` | Project URL (server PostgREST) |
| `SUPABASE_SERVICE_ROLE_KEY` | Prefer legacy **service_role JWT** (`eyJ…`) for full access. New `sb_secret_…` keys need table GRANTs or reads will 403/500; dashboard falls back to publishable for reads/writes when `sb_secret_` is set |
| `SUPABASE_KEY` | Fallback only if it is a secret/service key with table grants (avoid publishable) |
| `SUPABASE_ENTRIES_TABLE` | Default `time_entries_timmy_v2` |
| `SUPABASE_CLIENTS_TABLE` | Default `clients` |
| `SUPABASE_JOB_CODES_TABLE` | Default `job_codes` |
| `SUPABASE_EMPLOYEES_TABLE` | Default `employees` |
| `SUPABASE_CURRENTLY_WORKING_TABLE` | Default `currently_working` |

## Features

- Header: Timmy logo; name / Updated / Currently working (one person)
- Admin-only **Office** dropdown (All / GCD / MH) and **Employee** dropdown; others locked to self
- Admin **Remap Unassigned** tool after QBO/CSV adds the real client name
- Ranges: Today, Yesterday, This week, This/Last pay period (US Central)
- Charts filter Time Entry Detail (day / client / job)
- Table View / Calendar View (client search returns up to 100 matches; duration-only saves supported)
- **Edits** write to `time_entries_timmy_v2` (client, job_code, notes/task, entry_date, start/end, hours, billable, account from job roster, `office` from client, `source_file=timmy-dashboard`)

### QBO client sync (kit root, read-only)

```bash
# In kit .env or environment (never NEXT_PUBLIC_):
# QBO_CLIENT_ID=...
# QBO_CLIENT_SECRET=...
# QBO_COMPANIES=[{"office":"GCD","realm_id":"...","refresh_token":"..."}]

python scripts/sync_qbo_clients.py --dry-run
python scripts/sync_qbo_clients.py
```

Vercel dashboard env does not need QBO secrets for v1 (CLI sync). Add them later only if you schedule a server job.

### Who can edit

| Actor | Own entries | Others’ entries | Outside pay-period edit window |
|-------|-------------|-----------------|--------------------------------|
| Employee | Yes, in window only | No | Blocked |
| Admin (`is_admin`) | Yes | Yes | Allowed after confirm dialog |

Pay-period edit windows (America/Chicago), same as Timmy:

- Entry days **9–23** → editable from that month’s 9th 00:00 through the 24th 23:59
- Entry days **24–month-end** and **1–8** → editable from that period’s 24th 00:00 through the following 9th 23:59

### Calendar create/edit

- Select one employee (admins) before Calendar View
- Click empty day grid → create modal (15‑minute snap, default 1 hour)
- Click a block or duration-only chip → edit modal
- No drag-resize / delete in this pass

`staff_name` must match `"First Last"` on `employees` (example: `Hannah Curtis`).

---

## Supabase SQL (you run this — the agent does not)

### Base tables

```sql
create table if not exists employees (
  id uuid primary key default gen_random_uuid(),
  first_name text not null,
  last_name text not null,
  staff_name text not null unique,
  office text not null default 'GCD',
  active boolean not null default true,
  created_at timestamptz default now()
);

create table if not exists currently_working (
  id uuid primary key default gen_random_uuid(),
  staff_name text not null,
  office text not null,
  client text not null,
  job_code text,
  notes text,
  task text,
  started_at timestamptz not null,
  planned_end_at timestamptz,
  status text not null,
  local_session_id text,
  updated_at timestamptz default now()
);

create unique index if not exists currently_working_one_active
  on currently_working (staff_name)
  where status = 'active';
```

### Auth columns on employees

```sql
alter table employees add column if not exists email text;
alter table employees add column if not exists is_admin boolean not null default false;
create unique index if not exists employees_email_lower_uidx
  on employees (lower(email)) where email is not null;
```

Then set emails and admins, e.g.:

```sql
update employees set email = 'hannah@example.com', is_admin = true
where staff_name = 'Hannah Curtis';

update employees set email = 'alex@example.com', is_admin = false
where staff_name = 'Alex Daley';
```

### Seed 48 employees (`staff_name` = first + space + last)

```sql
insert into employees (first_name, last_name, staff_name, office) values
  ('Alex','Daley','Alex Daley','GCD'),
  ('Alexus','Bonaparte','Alexus Bonaparte','GCD'),
  ('Andrea','Rottman','Andrea Rottman','GCD'),
  ('Ashley','Klugman','Ashley Klugman','GCD'),
  ('BB','Moncrief','BB Moncrief','GCD'),
  ('Becky','Means','Becky Means','GCD'),
  ('Bonnie','West','Bonnie West','GCD'),
  ('Brian','Guevara','Brian Guevara','GCD'),
  ('Briana','Ziino','Briana Ziino','GCD'),
  ('Case','Dunavant','Case Dunavant','GCD'),
  ('Connor','Arnold','Connor Arnold','GCD'),
  ('Dakota','Stephens','Dakota Stephens','GCD'),
  ('Eli','Massengale','Eli Massengale','GCD'),
  ('Fredia','Clark','Fredia Clark','GCD'),
  ('Hannah','Curtis','Hannah Curtis','GCD'),
  ('Heather','Henderson','Heather Henderson','GCD'),
  ('Isaac','Parkinson','Isaac Parkinson','GCD'),
  ('Jamie','Harper','Jamie Harper','GCD'),
  ('Jeanenne','Green','Jeanenne Green','GCD'),
  ('Jillian','Green','Jillian Green','GCD'),
  ('Julia','Moorhead','Julia Moorhead','GCD'),
  ('Keishah','Tanner','Keishah Tanner','GCD'),
  ('Ken','Green','Ken Green','GCD'),
  ('Keri','Kaitu','Keri Kaitu','GCD'),
  ('Kim','Mechling','Kim Mechling','GCD'),
  ('Lauren','Murray','Lauren Murray','GCD'),
  ('Lisa','Keil','Lisa Keil','GCD'),
  ('Marion','Greco','Marion Greco','GCD'),
  ('Mary','Marshall','Mary Marshall','GCD'),
  ('Mckenna','Schroeder','Mckenna Schroeder','GCD'),
  ('Megan','Brigadier','Megan Brigadier','GCD'),
  ('Melissa','Traughber','Melissa Traughber','GCD'),
  ('Micah','Nishimura','Micah Nishimura','GCD'),
  ('Nathan','Moorhead','Nathan Moorhead','GCD'),
  ('Patrick','McKinley','Patrick McKinley','GCD'),
  ('Paula','Hasle','Paula Hasle','GCD'),
  ('Leisa','Rintala','Leisa Rintala','GCD'),
  ('Robin','Waguespack','Robin Waguespack','GCD'),
  ('Rose','Stone','Rose Stone','GCD'),
  ('Sabra','Sandoval','Sabra Sandoval','GCD'),
  ('Shanya','Schweitzer','Shanya Schweitzer','GCD'),
  ('Solomon','Labrum','Solomon Labrum','GCD'),
  ('Stephanie','Lopez','Stephanie Lopez','GCD'),
  ('Steve','Hutchings','Steve Hutchings','GCD'),
  ('Steve','Pasillas','Steve Pasillas','GCD'),
  ('Tiffany','Green','Tiffany Green','GCD'),
  ('Tina','Ellett','Tina Ellett','GCD'),
  ('Weston','Brockbank','Weston Brockbank','GCD')
on conflict (staff_name) do nothing;
```

```sql
GRANT SELECT ON public.employees TO anon;
GRANT SELECT ON public.employees TO authenticated;
```

Grant Timmy’s submit key insert/update on `currently_working`. Dashboard uses the **service role on the server** after verifying the magic-link session.
