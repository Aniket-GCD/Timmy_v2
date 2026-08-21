# Timmy Pilot Feedback Round 2 — Design Spec (v0.1.21 iteration)

> **Status: SHIPPED in v0.1.21-prototype (PR #35) — never execute this plan.
> Review-fix addendum: `docs/plans/2026-07-02-timmy-review-fixes.md`.**

**Source:** Pilot-firm email, multi-operator feedback on **v0.1.19-prototype**
([issue #34](https://github.com/0paani/timeassist-local-kit/issues/34)). This spec
**folds in and supersedes** `docs/plans/2026-06-17-roster-name-matching.md` (from #33);
that doc's Sections A–C and Decisions Locked apply here unchanged except where extended
below.

**Pilot baseline note:** operators have not seen v0.1.20 — its one-step `needs_info`
confirmation already softens the resolution flow; call this out in the changelog/skill
notes so it isn't re-reported.

**Out of scope (parked in #34):** QB client-list auto-sync job (needs QB storage
details), billing-sheet layout / historical lookback (sheet not received), forced
export folder ("down the line"), importing the real client list (privacy invariant:
synthetic data only during prototype; roster import stays format-agnostic).

## 1. Data model (`timeassist/db.py`, idempotent `ALTER TABLE ... ADD COLUMN`)

- `time_entries` and `active_sessions`: `job_type TEXT NOT NULL DEFAULT ''`.
- `clients`: `default_job_type TEXT NOT NULL DEFAULT ''`,
  `billable_locked INTEGER NOT NULL DEFAULT 0`.
- **No column rename.** `task_text` stays as-is in the schema but is presented as
  **Notes** at every boundary (MCP views, CLI labels, exports, SKILL.md). Job Type is a
  free string — no enum until H&A supplies a vocabulary.

## 2. Admin pseudo-clients

Seed roster entries **Admin, Early Out, Holiday, Staff Meeting** (idempotent, on
`initialize()`): `default_job_type='Administrative'`, `default_billable=0`,
`billable_locked=1`.

Engine enforcement (in `actions.py`, not the model/SKILL):
- `start`/`switch`/`edit`/`clarify_active` on a `billable_locked` client force
  `billable=0` and `job_type='Administrative'` (from `default_job_type`).
- Any attempt to set `billable=1` on a locked client is rejected with a plain-language
  error the assistant can relay verbatim.
- Pinned by tests (intentional-but-surprising convention).

## 3. Name matching (folded 2026-06-17 spec + management tiebreak)

- **Comma-swap `name_fold` third pass** in `resolve_client` exactly per the 2026-06-17
  spec: display-name only, both directions, case/whitespace-insensitive, businesses
  untouched, pure function, no schema change.
- **Management tiebreak (new, deterministic):** when a matching pass yields **exactly
  two** candidates and **exactly one** display name contains the word "management"
  (case-insensitive), resolve to the other candidate and record the tiebreak in
  `capture_note` (e.g. `management_tiebreak:<rejected name>` — humanized at the
  boundary via `capture_note_text`). Rationale: firms run near-identically-named
  management companies; accidental billing to them is the risk being avoided.
  - Any other ambiguity (0 management names, 2 management names, >2 candidates) still
    falls through to `needs_info` — the never-guess invariant holds; this is a
    deterministic rule, not a guess. Pin with test + comment.
- **Proactive surfacing at review** stays a SKILL.md-only change per the 2026-06-17
  spec (review already carries `needs_info` entries + `skipped_needs_info_count`).
- **Approve/export roster gate:** already enforced via `needs_info` (placeholder names
  never block capture; they block approval/export until resolved). No mechanical
  change; SKILL.md states the placeholder-then-must-match contract explicitly.

**Implementation note (shipped):** the management protection shipped as *inherent*
matching behaviour, not as the explicit tiebreak pass described above. The explicit
exactly-two/exactly-one-management pass was implemented and then proven unreachable —
any non-management input that would strip-match the management/non-management pair
already uniquely fold-matches the non-management row in an earlier pass — so it was
removed. A management name is only billed on exact operator naming. See the
2026-07-01 entry in `docs/decision-log.md`; do not reintroduce the explicit pass.

## 4. Notes nudge (never blocks approval)

- `review` result gains `missing_notes_count` (omitted when 0 — compact-JSON rule).
- `stop` and `switch` results gain a compact `notes_missing: true` flag when the entry
  they just closed has empty notes (the "day of" nudge hook).
- SKILL.md: nudge the operator once day-of (on the stop/switch flag) and once at review
  (on `missing_notes_count`), phrased as a nudge; approval is **not** gated on notes.

## 5. Timmy branding (user-facing only)

- SKILL.md persona/name, `plugin/timeassist/plugin.json` display name + description,
  `.claude-plugin/marketplace.json` display fields (repo root — not under `plugin/`),
  `docs/accountant-quick-start.md` (keep non-technical), wiki intro, CHANGELOG.
- **Unchanged:** Python package, CLI script names, MCP server/tool names, exe filename,
  repo name, `windows-build.yml`. Zero build-pipeline risk. The version-match test
  (`__init__.py` ↔ plugin.json) must still pass.

## 6. Boundary shapes (columns)

- MCP slim entry (in `mcp_views.py` only; `actions.py`/CLI stay full-fidelity):
  `task` key → `notes`; add `job_type` (dropped when empty per nulls-dropped rule).
- Exports emit columns **Date, Client, Job Type, Notes, Duration, Billable** with
  Duration formatted **HH:MM** from `rounded_minutes`. Display-only formatting — the
  engine keeps storing integer minutes; the rounding floor (never round positive work
  to 0) is untouched.

## 7. Testing & sync

**New tests (synthetic data only):**
- Migration idempotence for all new columns + admin-client seeding (double-initialize).
- Billable-lock enforcement across start/switch/edit/clarify_active + rejection error.
- Management tiebreak: resolves in both orderings; 2-management pair stays
  `needs_info`; 3-candidate case stays `needs_info`; substring "management" inside a
  longer word does not count (word match).
- `name_fold` + `resolve_client` suite per the 2026-06-17 spec.
- HH:MM export formatting (incl. >24h totals if applicable) and export column headers.
- `missing_notes_count` / `notes_missing` flags present when empty, absent when 0.
- SKILL.md gate test updated for new key phrases (Timmy, notes nudge, surfacing,
  placeholder contract).

**Sync checklist (CLAUDE.md "easy to miss"):**
- Both SKILL.md copies (plugin gated copy + repo skill) updated together.
- `mcp_views.py` shape change → check `tests/test_workflow_smoke_contract.py`
  PowerShell payload-key assertions in step with `windows-build.yml` (the exact gap
  that failed the first v0.1.19 build).
- No new MCP tool → no `TOOLS`/`call_tool`/tool-name-set changes expected; verify.
- `CHANGELOG.md` operator-facing notes, including "already in 0.1.20" callout.
- Full suite green before every commit: `python3 -m unittest discover -s tests`.

## Decisions locked

- v0.1.19 is the pilot baseline; plan against current `main` (0.1.20).
- `task_text` presents as Notes everywhere; Job Type is a new free-string field forced
  to "Administrative" only for the four locked admin clients.
- Management tiebreak is a deterministic engine rule (exactly-two / exactly-one-management),
  never a model-side preference; all other ambiguity stays `needs_info`.
- Notes nudge never blocks approval.
- Timmy rename is branding-only; all internals stay `timeassist`.
- Parked (in #34): QB roster auto-sync, billing sheet, export-folder enforcement.
- Everything from the 2026-06-17 spec's Decisions Locked (exact comma-swap only; no
  fuzzy matching; fold display_name only; no new result field for surfacing) carries
  over, except the management tiebreak now defined above.
- Release later via `shipping-a-timeassist-release`; first release after 2026-06-15
  requires a `workflow_dispatch` validation run before tagging (runner image redirect).
- Implementation subagents: **Opus** (operator instruction).

## Baseline

Branch from `main` (228 tests + 5 subtests green). Stdlib only — never add third-party
deps. Commits end with the project Co-Authored-By trailer.
