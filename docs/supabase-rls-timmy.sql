-- Timmy RLS policies for the publishable (anon) key.
-- Paste into Supabase SQL Editor. Does not use the secret key.
--
-- Goal:
--   - Timmy can READ clients + job_codes (lookups)
--   - Timmy can INSERT time_entries (after local approve)
--   - Timmy cannot UPDATE/DELETE anything
--   - tasks + submission_tracker stay locked to the publishable key
--
-- Re-run safe: drops and recreates these policy names only.

-- ---------------------------------------------------------------------------
-- Grants (RLS still applies; without GRANT, PostgREST returns permission errors)
-- ---------------------------------------------------------------------------
grant usage on schema public to anon, authenticated;

grant select on table public.clients to anon, authenticated;
grant select on table public.job_codes to anon, authenticated;
grant insert on table public.time_entries to anon, authenticated;

-- Do not grant write on lookups or trackers to the publishable key.
revoke insert, update, delete on table public.clients from anon, authenticated;
revoke insert, update, delete on table public.job_codes from anon, authenticated;
revoke all on table public.tasks from anon, authenticated;
revoke all on table public.submission_tracker from anon, authenticated;
revoke update, delete, truncate on table public.time_entries from anon, authenticated;

-- ---------------------------------------------------------------------------
-- Ensure RLS is on (you already have this; safe to re-run)
-- ---------------------------------------------------------------------------
alter table public.clients enable row level security;
alter table public.job_codes enable row level security;
alter table public.time_entries enable row level security;
alter table public.tasks enable row level security;
alter table public.submission_tracker enable row level security;

-- ---------------------------------------------------------------------------
-- clients: read-only lookup
-- ---------------------------------------------------------------------------
drop policy if exists "timmy_read_clients" on public.clients;
create policy "timmy_read_clients"
  on public.clients
  for select
  to anon, authenticated
  using (true);

-- ---------------------------------------------------------------------------
-- job_codes: read-only lookup
-- ---------------------------------------------------------------------------
drop policy if exists "timmy_read_job_codes" on public.job_codes;
create policy "timmy_read_job_codes"
  on public.job_codes
  for select
  to anon, authenticated
  using (true);

-- ---------------------------------------------------------------------------
-- time_entries: insert only (no select/update/delete for Timmy)
-- Basic shape checks; staff_name is trusted from local Timmy config (pilot).
-- ---------------------------------------------------------------------------
drop policy if exists "timmy_insert_time_entries" on public.time_entries;
create policy "timmy_insert_time_entries"
  on public.time_entries
  for insert
  to anon, authenticated
  with check (
    staff_name is not null
    and length(trim(staff_name)) > 0
    and office in ('GCD', 'MH')
    and entry_date is not null
    and client is not null
    and length(trim(client)) > 0
    and start_time is not null
    and end_time is not null
    and hours is not null
    and hours > 0
  );

-- No SELECT / UPDATE / DELETE policies for anon on time_entries
-- => publishable key cannot read or change existing rows.

-- ---------------------------------------------------------------------------
-- Verify
-- ---------------------------------------------------------------------------
-- select tablename, policyname, cmd, roles from pg_policies
-- where schemaname = 'public' order by tablename, policyname;
