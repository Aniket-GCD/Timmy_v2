# Changelog

All notable TimeAssist prototype changes should be recorded here.

This project is still pre-1.0. Treat each `v0.1.x-prototype` release as a guided-pilot checkpoint: what changed for operators, what changed in the deterministic engine, and what was verified before publishing downloadable assets.

## Unreleased — MCQ capture + office + QBO sync

### Added
- Multiple-choice client confirm: soft/miss capture returns `choices` (top 3) +
  `other_label` for AskUserQuestion / numbered lists (Weston feedback).
- `list_job_codes` accepts `client` / `office` and returns `suggested_job_codes`
  (recent entry frequency, else catalog fallback).
- Office-aware employee classify: same name at GCD+MH returns `ambiguous`
  choices; `config` may pass `staff_name` + `office` together to disambiguate.
- QBO→Supabase sync seeds Unassigned (GCD/MH) via `timeassist/clients_seed.py`;
  docs in `docs/qbo-clients-sync.md`; GH Actions workflow
  `.github/workflows/qbo-clients-sync.yml` (every 6h).
- `qbo_tokens` table SQL (`docs/supabase-qbo-tokens.sql`) + `qbo_oauth_setup.py`
  for one-time Intuit authorize per office (GCD/MH).
- Dashboard Production OAuth: `/qbo-connect`, `/api/qbo/start`, `/api/qbo/callback`
  (HTTPS redirect on Vercel; writes `qbo_tokens`).
- Pilot checklist: `docs/pilot-mcq-checklist.md`.

### Changed
- Operator success copy: **Entry logged.** — never say Supabase / ready for export.
- Timmy skill: MCQ start flow (client → job → notes → single timer start).
- QBO sync loads companies from Supabase `qbo_tokens` (not `QBO_COMPANIES`);
  persists rotated refresh tokens immediately (including `--dry-run`); skips an
  office if `updated_at` is within 5 minutes; per-office refresh failures log
  re-auth instructions and exit non-zero.

## v0.1.24-prototype — 2026-07-08

### Added
- Ask for a whole date range in one file. `review` and `export` now take an end
  date, so "give me June" — or a span that overlaps the old and new methods —
  produces a single CSV instead of one export per day (issue #34). You still
  review and approve day by day; the range export only writes time you already
  approved, and a single review token now covers the whole span.
- Set your initials once. A new `operator_code` setting (2–4 letters, your code
  on the firm's employee list, set with `config`) tags every export file —
  `quickbooks-time-AVD-2026-06-30.csv` — so each person's daily files stay
  distinct in a shared folder. The columns inside the CSV are unchanged.

## v0.1.23-prototype — 2026-07-02

### Added
- Strict roster mode (`strict_roster`, off unless your firm turns it on): entries
  flagged for an unknown client name can only be fixed by matching a client on
  the roster — "keep the name as typed" is no longer accepted. Capture is never
  blocked; the rule applies when the flagged entry is fixed.
- One-step roster add: a new client can be added to the roster in a single
  `add_client` call (or `add-client` on the command line) instead of re-importing
  the whole CSV. Adding never overwrites an existing client.
- Fixing a flagged entry now also fills a blank Job Type from the client's
  roster default; a Job Type you typed is never overwritten.

### Documented
- The rounding floor is now signed-off billing policy (issue #39 item 4): with
  rounding on, a short piece of work always bills at least one full increment —
  a 7-minute call under nearest-15 becomes 15 minutes, never 0. Keep raw time
  (`exact`) if you don't want a floor.

## v0.1.22-prototype — 2026-07-02

### Changed
- Rounding is no longer limited to 6- or 15-minute increments: any
  `nearest_<N>_minutes` / `up_<N>_minutes` rule from 1 to 60 minutes now works
  (for example `nearest_10_minutes`). Invalid rule names are rejected with a
  plain-language explanation instead of being stored and silently ignored.

## v0.1.21-prototype — 2026-07-02

Pilot feedback round 2 (issue #34). Operators upgrading from v0.1.19 also get
v0.1.20's one-step needs_info confirmation, which they have not seen yet.

### Added
- Job Type on every entry. Roster CSVs may include a `default_job_type` column;
  new time for that client fills it in automatically.
- Administrative clients (Admin, Early Out, Holiday, Staff Meeting) are built in,
  always non-billable, and always Administrative — the engine enforces this.
- Names typed as `John Smith` now match roster entries stored as `Smith, John`.
- When a client and its near-identical "management" company both appear on the
  roster, name-matching never lands on the management company by accident: it is
  billed only when named exactly; anything ambiguous is flagged for review instead
  of guessed.
- A client name that isn't on the roster is flagged for confirmation on every
  capture path (timers, switches, and added blocks) — approval and export always
  see it first.
- Approve and export refuse time billed to an administrative client (protects
  data recorded before this version); the sanitized packet now anonymizes Job
  Type labels too.
- Gentle nudges when an entry has no notes: once when the timer stops, once at review.

### Changed
- TimeAssist is now called **Timmy** (user-facing name only).
- Entry "task" is now "Notes"; exports use columns Date, Client, Job Type, Notes,
  Duration (HH:MM), Billable.
- Importing a roster row whose name matches a built-in administrative client takes
  ownership of it (your row, your billing settings); the built-ins never override
  names or aliases already on your roster.
- Review proactively lists unresolved clients before approval.

## v0.1.20-prototype — 2026-06-09

Smoother needs-info confirmation for the Cowork pilot.

### Added

- Confirming an unknown client now takes one step: `edit` with the client name
  resolves a needs_info entry without retyping billable (same for
  `clarify_active` on the open timer).

### Changed

- needs_info reasons are now plain language ("client 'acme' is not in the
  roster") in tool results and approval-rejection errors, and the rejection
  error explains the exact resolution recipe.
- Plugin skill: documents the confirm-as-is recipe and forbids self-initiated
  roster imports.

## v0.1.19-prototype — 2026-06-09

Token efficiency and conversational UX for the Cowork pilot.

### Added

- Added the `discard_entry` tool: soft-delete a mistaken capture (kept for
  audit, hidden from review/approval/export, requires operator confirmation).
- Added plain-language engine errors the assistant can relay verbatim
  (running-timer conflicts, stale `review_token`, `needs_info` approval
  rejections).
- Added a warning to export results when the automatic database backup failed.

### Changed

- Made MCP tool results compact: no pretty-printing, slim entry/session shapes,
  no echoed entry lists from `approve_all`/`reround`/`export`, and null fields
  omitted (~50-70% smaller results on a typical day).
- Trimmed MCP tool descriptions and shipped a ~45% smaller SKILL.md.

## v0.1.18-prototype — 2026-06-09

Release: https://github.com/0paani/timeassist-local-kit/releases/tag/v0.1.18-prototype  
PR: https://github.com/0paani/timeassist-local-kit/pull/24

### Added

- Added non-blocking client switching: when an operator switches clients, TimeAssist closes the old active timer and starts the new active timer immediately at the switch timestamp.
- Added capture metadata for later cleanup: `raw_client_name`, `raw_task_text`, `capture_status`, `capture_note`, and `clarified_at`.
- Added idempotent SQLite migration support for the new capture metadata columns.
- Added `clarify_active` / `clarify-active` so the active timer's labels can be cleaned up without changing its start time.
- Added tests for unknown-client switching, `needs_info` review behavior, active clarification, post-close cleanup, and approval/export gating.

### Changed

- Unknown client labels now become `needs_info` instead of blocking capture.
- Review output now surfaces unresolved capture state and skipped `needs_info` counts/minutes.
- Single-entry approval rejects unresolved `needs_info` entries.
- Bulk approval and export skip unresolved `needs_info` entries instead of silently treating them as ready.
- Plugin guidance now states the product rule directly: "Capture now, clarify later" and "switch immediately."

### Verified

- Local validation: `python3 -m unittest discover -s tests -v` → 190 tests passed.
- Release workflow: https://github.com/0paani/timeassist-local-kit/actions/runs/27223681897 → success.
- Downloaded release assets were inspected after publication:
  - `timeassist.exe` SHA256: `d24bdf771c4a8f5fa376cb160ec56c2341237286faf587140847b2dea49fb3ca`
  - `timeassist-plugin.zip` SHA256: `4284e4465c21ba47beb11f50d2c25bb95de06bc51fa06b76268ced84512d3145`
  - Standalone and bundled EXE hashes match.
  - Downloaded plugin package passed `claude plugin validate --strict`.

## v0.1.17-prototype — 2026-06-09

Release: https://github.com/0paani/timeassist-local-kit/releases/tag/v0.1.17-prototype  
PR: https://github.com/0paani/timeassist-local-kit/pull/23

### Added

- Added the Honest Nudge Loop for active timers: `checkin_status`, `checkin`, and `snooze_checkin` paths.
- Added default check-in settings for active timers, including interval and stale-session thresholds.
- Added explicit retroactive switching with `minutes_ago` for user-reported corrections like "switched 20 minutes ago."
- Added active-timer warnings during review so runaway timers are surfaced before approval/export.

### Changed

- The assistant/plugin workflow now frames reminders as self-report correction, not surveillance.
- The nudge loop preserves the deterministic engine boundary: reminders prompt the operator, but state changes still go through explicit tools.

### Verified

- Local validation before release: 183 tests passed.
- Release workflow: https://github.com/0paani/timeassist-local-kit/actions/runs/27187636658 → success.
- Published release assets were verified after download.

## v0.1.16-prototype — 2026-06-04

Release: https://github.com/0paani/timeassist-local-kit/releases/tag/v0.1.16-prototype

### Added

- Added first-run export-folder survey behavior so operators understand where official CSVs live and where user-visible copies are placed.
- Added validation around the default user-visible export folder flow.

## v0.1.15-prototype — 2026-06-03

Release: https://github.com/0paani/timeassist-local-kit/releases/tag/v0.1.15-prototype

### Changed

- Bumped the pilot version after Windows CI path normalization work.
- Superseded the `v0.1.14-prototype` tag path, which did not produce the final published release asset set.

## v0.1.13-prototype — 2026-06-03

Release: https://github.com/0paani/timeassist-local-kit/releases/tag/v0.1.13-prototype

### Changed

- Hardened the pilot release path for the packaged Windows/plugin artifact.

## v0.1.12-prototype — 2026-06-01

Release: https://github.com/0paani/timeassist-local-kit/releases/tag/v0.1.12-prototype

### Changed

- Hardened MCP approval and file-safety behavior before export handoff.

## Earlier prototype releases

Earlier `v0.1.x-prototype` tags established the local deterministic core, stakeholder demo artifacts, plugin packaging shape, raw time capture defaults, roster support, and QuickBooks-ready CSV handoff. Backfill these entries as needed when older pilot context becomes important.
