# TimeAssist Admin Install Notes

This note is for the helper installing TimeAssist for a guided pilot. Keep the accountant-facing path simple: install the plugin, verify the local tools work, then hand them the one-page quick start.

## Pilot posture

- Use synthetic data first.
- Do not bundle real client rosters in the plugin.
- Firm clients come from live Supabase (env: `SUPABASE_URL`, `SUPABASE_KEY`). Table names live in the plugin’s `config/supabase.json` (loaded automatically next to `bin/timeassist.exe`). Current pilot writes to `time_entries_timmy_v2`; never put API keys in that file.
- Keep exports local and human-approved.
- Do not promise direct QuickBooks writeback; the current handoff is a CSV export.

## What to install

For a guided pilot, prefer the release zip handoff unless the user is on a managed Team/Enterprise plugin marketplace.

Expected plugin contents:

```text
timeassist/
  .claude-plugin/plugin.json
  .mcp.json
  README.md
  config/supabase.json
  skills/timmy/SKILL.md
  bin/timeassist.exe
```

The bundled executable is Windows-native. Build or download the Windows artifact; a Linux/macOS checkout will not include a runnable `.exe`.

## Validate before handoff

From the repo root:

```bash
python scripts/timeassist.py --help
python scripts/timeassist.py init --dry-run
python -m unittest discover -s tests -v
claude plugin validate ./plugin/timeassist
```

If you are checking marketplace metadata too:

```bash
claude plugin validate .claude-plugin/marketplace.json
```

For a direct MCP smoke test with a throwaway database:

```bash
printf '%s\n' \
  '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18"}}' \
  '{"jsonrpc":"2.0","id":2,"method":"tools/list"}' \
  | python scripts/timeassist_mcp.py --db /tmp/timeassist-smoke.sqlite
```

## Install in Cowork

1. Download or build the plugin zip.
2. In Cowork, open plugin/customization settings and upload the plugin zip.
3. Confirm the `/timmy` skill and `timeassist` tools are available.
4. Start a fresh chat and ask: “Use Timmy and initialize local state.”
5. Ask for `status` to confirm the local database was created.

Known packaging note: the zip should contain a top-level `timeassist/` folder, not just the files at the archive root.

## First-run setup with the accountant

1. Open the accountant quick start: `docs/accountant-quick-start.md`.
2. Initialize local state. Cowork should surface the export-folder choice: keep
   the default `Documents/TimeAssist Exports` handoff folder or choose another
   folder. Accepting the default requires a confirmed `config` action, and a
   custom folder also requires confirmation.
3. Set `SUPABASE_URL` / `SUPABASE_KEY` on the timeassist MCP (shipped in
   `.mcp.json` for this pilot). Confirm `list_clients` returns live Supabase
   names for the configured office — **do not import a local clients CSV**
   (`import_clients` is disabled).
4. List clients and confirm soft-matching works (e.g. a nickname resolves to the
   full QBO name). If the firm requires every billed name to match the master
   list exactly, turn on strict roster mode (`config` setting `strict_roster` =
   `yes`): entries for unknown names are still captured, but can only be fixed
   by matching a Supabase client or using the Unassigned + Reception flow.
5. Set the operator's initials code (`config` setting `operator_code`, 2–4
   letters from the firm's employee list, e.g. `AVD`). Each install belongs to
   one operator; the code is stamped into that operator's export filenames
   (`quickbooks-time-AVD-2026-06-30.csv`) so files collected into a shared
   folder stay attributable. It does not change the CSV columns.
6. Choose a rounding rule:
   - raw/exact
   - nearest N minutes or round up N minutes, for any N from 1 to 60
     (for example nearest 6, round up 6, nearest 15, nearest 10)
7. Run the synthetic pilot checklist before real entries.
8. Record where the database and exports land on this machine.

Plugin installs store the database at `%LOCALAPPDATA%\Timmy\timeassist.sqlite` (chosen by `timeassist.exe`, not Claude). Default exports, review HTML, and sanitized packets are written under that folder’s `exports/`, `reviews/`, and `packets/` subdirs; backups under `backups/`. QuickBooks CSV exports are also copied byte-for-byte to the confirmed/default handoff folder, normally `Documents/TimeAssist Exports`. Tool results report full paths. During the pilot, ask TimeAssist for `status`, `config`, or review/export results if you need to confirm the exact local path.

## Troubleshooting

- **Plugin upload/validation fails:** check the desktop app's DevTools/network response for the real validation error; Cowork may show a generic message.
- **Windows warns about the app:** the pilot binary may be unsigned. Confirm with the firm admin before asking a pilot user to bypass SmartScreen.
- **No tools appear:** confirm the plugin zip structure, plugin manifest, `.mcp.json`, and bundled `bin/timeassist.exe` are present.
- **Export location is unclear:** ask TimeAssist to export again only if safe, or review the previous tool result for the full path. Do not guess.
- **Client list fails:** confirm Supabase env on the MCP server and that Unassigned exists for GCD/MH. Do not fall back to a local CSV import.
## Handoff to the accountant

Give them only:

- the installed Cowork environment;
- `docs/accountant-quick-start.md`;
- the synthetic pilot script from `docs/pilot-checklist.md`.

Keep developer commands and repo details out of the accountant's first experience.
