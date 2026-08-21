# Architecture

The core principle: **the AI handles language; the deterministic engine handles
money and truth.** Anything involving a number or a billing record is
deterministic and logged; anything involving understanding what the operator
meant is AI.

## Deterministic (the engine — `timeassist/`, shipped as `timeassist.exe`)

Pure-stdlib Python over SQLite. No third-party dependencies (keeps the binary
clean and the PyInstaller build simple). Owns:

- Duration math (`minutes_between`) and rounding (`round_minutes`).
- The entry state machine: `draft → approved → exported`.
- The event log — every mutation recorded with before/after.
- Export — writes **only** entries already in `approved` state; fixed CSV columns (Date, Client, Job Type, Notes, Duration (HH:MM), Billable); keeps the official CSV under plugin data and copies the exact bytes to `Documents/TimeAssist Exports` by default (using Windows `SHGetKnownFolderPath` for the real Documents folder, with `%USERPROFILE%` fallback) or a confirmed `user_export_dir` override for operator access.
- Date-range review/export (issue #34 lookback). `review`/`export` take an optional `end_date`; a ranged `review` returns per-day `days` summaries (not entry lists) plus one span-scoped `review_token`, and `export` writes a single CSV for the span (`quickbooks-time[-<CODE>]-<from>_to_<to>.csv`). Span normalization is shared (`_normalize_date_span`) so `end_date == date` collapses to a byte-identical single-day call and every prior single-day token stays valid. Approval stays per-day: `approve`/`approve_all` never take a range, so a range export only emits already-approved entries.
- Operator identity in filenames (`operator_code`, 2–4 letters). When set, it prefixes the default export filename and is echoed in the export result; the CSV columns are unchanged (the workbook is client-rows × employee-initials-columns, but the six columns are the firm's verbatim contract). The roster carries no rate/retainer fields — those are workbook formulas, not the tracker's job.
- Anonymization for the sanitized packet.
- Settings (rounding rule, `user_export_dir`, `strict_roster`, `operator_code`), first-run export-folder survey state, timestamps (local wall-clock), the review HTML.

## AI (the model in Cowork / Claude Code, guided by the skill)

- Parse intent ("I spent 20 min on Acme's call") → choose the right tool + args.
- On first run, explain the `export_folder` survey returned by `init_state`: keep the default `Documents/TimeAssist Exports` handoff copy or set a custom folder with confirmation.
- Match messy input to canonical clients/entries; ask when a field is missing.
- Summarize results readably.
- **Never** computes durations/totals/rounding or fabricates an entry — every
  change goes through a tool.

## The approval gate (shared, and worth understanding precisely)

- **AI side (fallible):** the skill instructs the model to approve/export only
  when the operator asks, and never on its own initiative. Bulk approval is
  allowed *when the operator requests it* (`approve_all`).
- **Deterministic side (guaranteed):** `export` can only ever write entries
  already `approved`, so a misbehaving model cannot export a raw draft.
- **The gap:** the model *can* call `approve`, so the engine guarantees "nothing
  un-approved is exported" but not "the model never approves something it
  shouldn't." That decision is initiated by the AI on the human's behalf — which
  is why the human stays the authority and why model choice matters for approve.

Trust model: **the human** is the authority, the **AI** is a convenient-but-
fallible intermediary, the **engine** is the incorruptible record-keeper.

## Tools exposed (MCP server)

`init_state`, `start`, `switch`, `end`, `add_missing`, `edit`, `review`,
`approve`, `approve_all`, `unapprove`, `export`, `sanitize_packet`, `config`.

## Model guidance

The engine owns the math, so the workflow isn't reasoning-heavy — it's
discipline-heavy (gate adherence, intent disambiguation). Sonnet is the safe
default, especially for the approve/export path; Haiku is fine for routine
capture if it holds the gate in testing. Opus is overkill.
