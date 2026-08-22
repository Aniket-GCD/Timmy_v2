-- Script 2 (full / re-runnable). Prefer docs/supabase-script-3-additive.sql if you
-- want to avoid DROP POLICY / REVOKE / CREATE OR REPLACE (Supabase "destructive" UI).
-- Paste-ready SQL for Unassigned seed + SELECT/UPDATE on time_entries.
-- Paste into Supabase SQL Editor. Agent environments must NOT run this against live.
-- Timezone for pay windows: America/Chicago (documented; Timmy enforces in Python).
--
-- Security this iteration: Timmy is the gate for pay-period + superuser allowlist.
-- RLS UPDATE uses using (true) so shared publishable key can PATCH; residual risk
-- matches the existing INSERT trust model. Follow-up: Edge Function + JWT for hard RLS.
--
-- Re-run safe for policies named below. Adjust Unassigned insert if unique constraints differ.

-- ---------------------------------------------------------------------------
-- A1. Seed Unassigned in clients (firm should also create Unassigned in QBO)
-- ---------------------------------------------------------------------------
insert into public.clients (name, office, qbo_customer_id, active)
values ('Unassigned', 'GCD', 'UNASSIGNED', true),
       ('Unassigned', 'MH', 'UNASSIGNED-MH', true)
on conflict do nothing;

-- Do not grant Timmy write on clients (keep revoke).
revoke insert, update, delete on table public.clients from anon, authenticated;

-- ---------------------------------------------------------------------------
-- A2. Optional helper (documentation / future RLS). Timmy does NOT rely on this
--     for the pilot gate — see timeassist/pay_period.py.
-- Period A: days 9–23 → editable through day 24 23:59:59 Chicago
-- Period B: day 24–month-end + 1–8 → editable through day 9 next month 23:59:59
-- ---------------------------------------------------------------------------
create or replace function public.time_entry_in_edit_window(entry_date date)
returns boolean
language sql
stable
as $$
  with chicago_now as (
    select (timezone('America/Chicago', now()))::timestamp as ts
  ),
  bounds as (
    select
      entry_date as ed,
      extract(day from entry_date)::int as d,
      extract(year from entry_date)::int as y,
      extract(month from entry_date)::int as m
  )
  select case
    when (select d from bounds) between 9 and 23 then
      (select ts from chicago_now) >= make_timestamp((select y from bounds), (select m from bounds), 9, 0, 0, 0)
      and (select ts from chicago_now) <= make_timestamp((select y from bounds), (select m from bounds), 24, 23, 59, 59)
    when (select d from bounds) >= 24 then
      (select ts from chicago_now) >= make_timestamp((select y from bounds), (select m from bounds), 24, 0, 0, 0)
      and (select ts from chicago_now) <= (
        make_timestamp(
          case when (select m from bounds) = 12 then (select y from bounds) + 1 else (select y from bounds) end,
          case when (select m from bounds) = 12 then 1 else (select m from bounds) + 1 end,
          9, 23, 59, 59
        )
      )
    else
      -- days 1–8
      (select ts from chicago_now) >= (
        make_timestamp(
          case when (select m from bounds) = 1 then (select y from bounds) - 1 else (select y from bounds) end,
          case when (select m from bounds) = 1 then 12 else (select m from bounds) - 1 end,
          24, 0, 0, 0
        )
      )
      and (select ts from chicago_now) <= make_timestamp((select y from bounds), (select m from bounds), 9, 23, 59, 59)
  end;
$$;

-- ---------------------------------------------------------------------------
-- A3. Grants + policies: SELECT + UPDATE for Timmy (pilot: Timmy is the gate)
-- Keep existing insert policy from docs/supabase-rls-timmy.sql
-- ---------------------------------------------------------------------------
grant select, update on table public.time_entries to anon, authenticated;

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
  using (true)  -- Timmy enforces pay window + superuser; shared key cannot encode names
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

-- Out-of-window superuser Supabase writes: Timmy allowlist bypasses the *app*
-- check; with using(true) PATCH succeeds. Until an Edge Function exists, that
-- is intentional for this pilot. Dashboard / service role remains available.

-- ---------------------------------------------------------------------------
-- Verify
-- ---------------------------------------------------------------------------
-- select tablename, policyname, cmd, roles from pg_policies
-- where schemaname = 'public' and tablename = 'time_entries'
-- order by policyname;
