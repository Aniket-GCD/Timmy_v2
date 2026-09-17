-- qbo_tokens — OAuth refresh keys for QBO → clients sync
-- Run once in Supabase SQL editor (service_role / table owner).
-- Safe to re-run: create if not exists + enable RLS.
--
-- Plaintext refresh_token is intentional for v1 (same trust boundary as
-- SUPABASE_SERVICE_ROLE_KEY). RLS with no anon/authenticated policies
-- blocks browser/anon access; scripts use the service role key.

create table if not exists public.qbo_tokens (
  office text primary key,
  realm_id text not null,
  refresh_token text not null,
  updated_at timestamptz default now()
);

alter table public.qbo_tokens enable row level security;

-- No policies for anon / authenticated → only service_role (and owner) can access.
-- (Do not add SELECT policies for the dashboard anon key.)

comment on table public.qbo_tokens is
  'QBO OAuth refresh tokens per office (GCD/MH). Filled by qbo_oauth_setup.py; rotated by sync_qbo_clients.py.';

-- Verify:
-- select office, realm_id, updated_at from public.qbo_tokens;
