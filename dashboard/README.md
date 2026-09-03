# GCD firm hours dashboard (founder admin)

View-only Next.js dashboard for firm totals. Employees keep using Timmy in Claude. This app does **not** POST/PATCH entries from the UI.

## Run locally

```bash
cd dashboard
npm install
npm run dev
```

Open http://localhost:4321

```bash
npm test
```

## Modes

| Env | Behavior |
|-----|----------|
| `NEXT_PUBLIC_DASHBOARD_DATA_SOURCE=mock` (default) | In-memory multi-staff seed + mock live sessions |
| `supabase` | Live **reads** from Supabase (`time_entries_timmy_v2`, `employees`, `currently_working`) |

Polling: submitted entries + currently-working every **30s** while the tab is visible; also refetch on focus / `visibilitychange`. Clients and job codes are not polled.

## Env var names

| Variable | Role |
|----------|------|
| `NEXT_PUBLIC_DASHBOARD_DATA_SOURCE` | `mock` (default) or `supabase` |
| `SUPABASE_URL` | Project URL |
| `SUPABASE_SERVICE_ROLE_KEY` or `SUPABASE_KEY` | Server read key (service role is enough for founder-only API routes) |
| `SUPABASE_ENTRIES_TABLE` | Default `time_entries_timmy_v2` |
| `SUPABASE_CLIENTS_TABLE` | Default `clients` (unused in view-only UI) |
| `SUPABASE_JOB_CODES_TABLE` | Default `job_codes` (unused in view-only UI) |
| `SUPABASE_EMPLOYEES_TABLE` | Default `employees` |
| `SUPABASE_CURRENTLY_WORKING_TABLE` | Default `currently_working` |
| `DASHBOARD_OFFICE` | Optional; unused as page identity (header is **GCD · Firm hours**) |
| `DASHBOARD_STAFF_NAME` | **Do not** use as the page identity. Write API routes still exist but the UI never calls them. |

## Features

- Header: **GCD · Firm hours**, range context, last-updated time
- Ranges: Today, Yesterday, This week (Sun–Sat), This/Last pay period (US Central)
- KPIs: Total, Billable, Admin (`job_code === "Admin"`) + %, Clients — hours as h:mm
- Charts: Admin vs non-admin by day, top 8 clients, job codes
- **Employee** dropdown (default All staff): scopes KPIs, charts, Day Detail. Calendar still needs one person (picking Calendar with All staff auto-selects someone with hours).
- On the clock: active `currently_working` rows (firm-wide; not billed hours)
- Day detail: read-only, grouped by staff when All staff; Show/Hide detail
- Calendar: same `chartDays` as Hours by Day; timed blocks + duration-only strip
- Default data is **mock** until `NEXT_PUBLIC_DASHBOARD_DATA_SOURCE=supabase`

`staff_name` must match `"First Last"` from `GCD Employees 9.1.2026.csv` (example: `Hannah Curtis`).

---

## Supabase SQL (you run this — the agent does not)

Paste in the Supabase SQL editor. Adjust table names only if they collide, then set the env vars above.

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

### Seed 48 employees (`staff_name` = first + space + last)

Add extra submitters (e.g. Aniket) in a separate insert if they are not on the CSV.

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

Optional extra (only if they already submit and are not on the CSV):

```sql
insert into employees (first_name, last_name, staff_name, office)
values ('Aniket','','Aniket','GCD')
on conflict (staff_name) do nothing;
```

Grant Timmy’s existing submit key **insert/update** on `currently_working`. Dashboard routes only **select**. Confirm one Timmy `staff_name` matches `employees.staff_name` exactly.

Timmy also needs **read-only** access to `employees` for install identity:

```sql
GRANT SELECT ON public.employees TO anon;
GRANT SELECT ON public.employees TO authenticated;
```

If RLS is enabled on `currently_working`, also allow the publishable (`anon`) key to write:

```sql
CREATE POLICY currently_working_insert_anon ON public.currently_working
  FOR INSERT TO anon WITH CHECK (true);

CREATE POLICY currently_working_update_anon ON public.currently_working
  FOR UPDATE TO anon USING (true) WITH CHECK (true);
```

(Pilot alternative: `ALTER TABLE public.currently_working DISABLE ROW LEVEL SECURITY;`)
