# TimeAssist Wiki

Curated reference for the TimeAssist Local Kit. For the original framing see
`docs/project-brief.md` and `docs/project-board.md`; this wiki captures the
decisions and mechanics we've worked out since.

> **Naming:** the product is now called **Timmy** for operators. This is a
> user-facing rename only — the package, CLI, exe, repo, MCP server, and plugin
> identifiers all stay `timeassist`, so the build is unchanged. See
> `../../CHANGELOG.md` for the full list of recent operator-facing changes
> (Job Type, built-in admin clients, comma-swap name matching, notes nudges,
> and the renamed export columns).

## What it is

A local, human-reviewed billable-time assistant for accountants. The operator
captures draft time entries in plain language; a deterministic engine does all
the math and state; the human approves; only approved entries export to a
QuickBooks-ready CSV. The goal is helpful capture, not surveillance.

## Pages

- [Architecture](Architecture.md) — what's deterministic vs AI, and the approval gate.
- [Distribution](Distribution.md) — how it ships (Cowork plugin, MCP server, Windows .exe, marketplace) and the access limits.
- [Deploy](Deploy.md) — the release process and the gotchas we hit.
- [Decisions & Roadmap](Decisions-and-Roadmap.md) — what's decided, what's shelved, what's next.

## Quick reference

- **Repo:** `0paani/timeassist-local-kit` (**private**).
- **Releases / downloads:** GitHub Releases (`timeassist.exe`, `timeassist-plugin.zip`).
- **Marketplace add (once auth/visibility is sorted):** `/plugin marketplace add 0paani/timeassist-local-kit` → `/plugin install timeassist@timeassist-marketplace`.
- **Pilot docs:** `../accountant-quick-start.md`, `../admin-install.md`, `../pilot-checklist.md`.
- **Local validation:**
  ```bash
  python3 scripts/timeassist.py --help
  python3 -m unittest discover -s tests -v
  python3 scripts/timeassist_mcp.py --db timeassist.sqlite   # MCP server
  ```
- **Data location:** Plugin installs use `%LOCALAPPDATA%\Timmy\timeassist.sqlite`; default exports/review files/backups land next to it and tool results report full paths.
