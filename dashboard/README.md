# Timmy firm hours dashboard

Next.js dashboard for GCD hours. Employees use Timmy in Claude; this app shows submitted hours (and live “on the clock” in the header). With Supabase mode, staff sign in via **magic link** (Outlook).

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
| `NEXT_PUBLIC_DASHBOARD_DATA_SOURCE=mock` (default) | In-memory seed; **no login** (dev bypass — mock admin user) |
| `supabase` | Live data + **magic-link login** required |

Polling: entries + currently-working every **30s** while the tab is visible.

## Auth (magic link)

1. User opens the dashboard → `/login`
2. Enters work Outlook email → Supabase emails a one-time link
3. Click link → session cookie → app loads `employees` by `lower(email)`
4. **`is_admin`** → firm view + Employee dropdown; otherwise only that person’s hours

Staff never need Supabase console access. You maintain `employees.email` / `is_admin` in SQL.

### Supabase Auth setup (you)

1. Authentication → Providers → **Email** enabled (magic link)
2. URL configuration → Redirect URLs include:
   - `http://localhost:4321/auth/callback`
   - `https://YOUR-VERCEL-HOST/auth/callback`
3. Site URL = your production dashboard URL

## Env var names

| Variable | Role |
|----------|------|
| `NEXT_PUBLIC_DASHBOARD_DATA_SOURCE` | `mock` (default) or `supabase` |
| `NEXT_PUBLIC_SUPABASE_URL` | Same project URL (browser Auth) |
| `NEXT_PUBLIC_SUPABASE_ANON_KEY` | Anon/publishable key (Auth cookies only) |
| `SUPABASE_URL` | Project URL (server PostgREST) |
| `SUPABASE_SERVICE_ROLE_KEY` or `SUPABASE_KEY` | Server data access **after** session check |
| `SUPABASE_ENTRIES_TABLE` | Default `time_entries_timmy_v2` |
| `SUPABASE_CLIENTS_TABLE` | Default `clients` |
| `SUPABASE_JOB_CODES_TABLE` | Default `job_codes` |
| `SUPABASE_EMPLOYEES_TABLE` | Default `employees` |
| `SUPABASE_CURRENTLY_WORKING_TABLE` | Default `currently_working` |

## Features

- Header: Timmy logo; name / Updated / Currently working (one person)
- Admin-only Employee dropdown; others locked to self
- Ranges: Today, Yesterday, This week, This/Last pay period (US Central)
- Charts filter Time Entry Detail (day / client / job)
- Table View / Calendar View; edits write back to Supabase when in edit window

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
