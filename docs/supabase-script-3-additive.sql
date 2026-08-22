-- Script 3 (idempotent) — Unassigned seed + SELECT/UPDATE for Timmy edits
-- Paste AFTER docs/supabase-rls-timmy.sql (script 1).
-- Safe to re-run: drops and recreates only these two policy names; does not delete rows.
--
-- Pay-period + superuser gates live in Timmy (pay_period.py), not in this SQL.
-- Agent environments must NOT run this against live Supabase.
--
-- If check already shows timmy_select_time_entries + timmy_update_time_entries
-- and Unassigned for GCD/MH, you are done — no need to run this again.

-- ---------------------------------------------------------------------------
-- 1. Seed Unassigned
-- ---------------------------------------------------------------------------
insert into public.clients (name, office, qbo_customer_id, active)
values ('Unassigned', 'GCD', 'UNASSIGNED', true),
       ('Unassigned', 'MH', 'UNASSIGNED-MH', true)
on conflict do nothing;

-- ---------------------------------------------------------------------------
-- 2. Grants
-- ---------------------------------------------------------------------------
grant select, update on table public.time_entries to anon, authenticated;

-- ---------------------------------------------------------------------------
-- 3. Policies (re-runnable)
-- ---------------------------------------------------------------------------
drop policy if exists "timmy_select_time_entries" on public.time_entries;
create policy "timmy_select_time_entries"
  on public.time_entries
  for select
  to anon, authenticated
  using (true);

drop policy if exists "timmy_update_time_entries" on public.time_entries;
create policy "timmy_update_time_entries"
  on public.time_entries
  for update
  to anon, authenticated
  using (true)
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
-- select policyname, cmd from pg_policies
-- where schemaname = 'public' and tablename = 'time_entries' order by policyname;
-- select name, office from public.clients where name = 'Unassigned';
