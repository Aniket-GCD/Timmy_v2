-- Timmy RLS policies for the publishable (anon) key.
-- Paste into Supabase SQL Editor. Does not use the secret key.
--
-- Goal (base + edits companion):
--   - Timmy can READ clients + job_codes (lookups)
--   - Timmy can INSERT time_entries (after local approve)
--   - Timmy can SELECT + UPDATE time_entries (pay window / superuser gated in Timmy)
--   - Timmy cannot DELETE; cannot write clients / job_codes / tasks / submission_tracker
--
-- Then paste docs/supabase-script-3-additive.sql (preferred: no DROP/REVOKE) for
-- Unassigned seed + SELECT/UPDATE. Alternate: docs/supabase-unassigned-and-edits.sql
-- (re-run safe via DROP POLICY IF EXISTS — triggers Supabase "destructive" warning).
-- Re-run safe for this file: drops and recreates these policy names only.

-- ---------------------------------------------------------------------------
-- Grants (RLS still applies; without GRANT, PostgREST returns permission errors)
-- ---------------------------------------------------------------------------
grant usage on schema public to anon, authenticated;

grant select on table public.clients to anon, authenticated;
grant select on table public.job_codes to anon, authenticated;
grant insert on table public.time_entries to anon, authenticated;
-- SELECT + UPDATE added in docs/supabase-unassigned-and-edits.sql

-- Do not grant write on lookups or trackers to the publishable key.
revoke insert, update, delete on table public.clients from anon, authenticated;
revoke insert, update, delete on table public.job_codes from anon, authenticated;
revoke all on table public.tasks from anon, authenticated;
revoke all on table public.submission_tracker from anon, authenticated;
revoke delete, truncate on table public.time_entries from anon, authenticated;

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
-- time_entries: insert (base). SELECT/UPDATE: see supabase-unassigned-and-edits.sql
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

-- ---------------------------------------------------------------------------
-- Verify
-- ---------------------------------------------------------------------------
-- select tablename, policyname, cmd, roles from pg_policies
-- where schemaname = 'public' order by tablename, policyname;
