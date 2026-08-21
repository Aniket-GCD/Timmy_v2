# Decisions & Roadmap

## Decisions made

- **Platform target: Windows only.** All pilot users are on Windows; the `.exe`
  is the distribution unit.
- **Delivery surface: Claude Cowork** (desktop, no terminal) for nontechnical
  accountants — same Skills/MCP system as Claude Code.
- **Architecture: deterministic engine + AI front end.** The model never owns
  billing math/state/export. See [Architecture](Architecture.md).
- **Rounding: raw (`exact`) by default.** Time is captured unrounded unless the
  operator turns rounding on. Settings-driven via `config` / `reround`, with
  free-form `nearest_<N>_minutes` / `up_<N>_minutes` for any increment from 1
  to 60 (2026-07-02; previously a fixed 6/15 list); `reround` re-applies a rule
  to a day's drafts and `exact` restores raw.
- **Bulk approve allowed** when the operator explicitly asks (`approve_all`); the
  AI still never approves/exports on its own initiative.
- **Client roster import shipped** (2026-05-28). `import-clients` loads a CSV
  (`client_key, display_name, aliases, default_billable`) into a local `clients`
  table; capture canonicalizes names (incl. aliases) and applies each client's
  billable default. Unknown clients are recorded as-typed (soft). **Privacy:**
  the roster is client data — imported **locally per install**, never bundled
  into the distributed plugin.
- **Data lives in plugin data for Cowork installs** (`${CLAUDE_PLUGIN_DATA}/timeassist.sqlite` plus generated exports/review files); direct CLI use still follows the provided `--db` path/current working directory.
- **Repo stays private.** Distribution via file handoff or (eventually) a
  Team/Enterprise org marketplace; a public distribution-only repo is an option
  but not yet chosen.
- **No QuickBooks writeback in v1** — stop at a reviewed, QuickBooks-ready CSV.

## Open questions (from the brief, still live)

- First QuickBooks handoff route (#3) — drives the export schema.
- Billing increment confirmation + service-code list (#4).
- Which data classes are approved for a real pilot.

## Shelved

- **`.xlsx` roster import.** CSV roster import shipped (see Decisions made);
  `.xlsx` stays shelved because it needs a dependency (`openpyxl`), which breaks
  the zero-dep ethos. Alternatives: "Save As CSV", or AI-assisted parsing (Cowork
  reads the file → structured import). For team rollout, point installs at a
  **shared client CSV the firm maintains** rather than baking clients into the
  plugin artifact.

## Backlog / next

- **Team/Enterprise org-marketplace rollout** (the intended distribution end state).
- **Code signing** (Azure Artifact Signing) to clear SmartScreen — see [Deploy](Deploy.md).
- **Real QuickBooks export** — the placeholder `Service` column was dropped from
  the prototype export; a real service-code mapping + handoff-route decision is a
  pilot task.
- **Public distribution-only repo** — if/when we want zero-auth `/plugin
  marketplace add` before Team/Enterprise.
- Possibly `.xlsx` roster import (see Shelved).
