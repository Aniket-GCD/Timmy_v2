# TimeAssist Admin Install Notes

This note is for the helper installing TimeAssist for a guided pilot. Keep the accountant-facing path simple: install the plugin, verify the local tools work, then hand them the one-page quick start.

## Pilot posture

- Use synthetic data first.
- Do not bundle real client rosters in the plugin.
- Import roster data only from an approved local CSV on the pilot machine.
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
  skills/billable-time-assistant/SKILL.md
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
3. Confirm the `billable-time-assistant` skill and `timeassist` tools are available.
4. Start a fresh chat and ask: “Use TimeAssist and initialize local state.”
5. Ask for `status` to confirm the local database was created.

Known packaging note: the zip should contain a top-level `timeassist/` folder, not just the files at the archive root.

## First-run setup with the accountant

1. Open the accountant quick start: `docs/accountant-quick-start.md`.
2. Initialize local state. Cowork should surface the export-folder choice: keep
   the default `Documents/TimeAssist Exports` handoff folder or choose another
   folder. Accepting the default requires a confirmed `config` action, and a
   custom folder also requires confirmation.
3. If approved, import a local roster CSV with these columns:

```csv
client_key,display_name,aliases,default_billable,default_job_type
acme,Acme Co,"ACME;Acme",yes,Bookkeeping
```

   Only `display_name` is required. `default_job_type` fills the Job Type
   column automatically on every new entry for that client — set it for each
   roster client so exports never have a blank Job Type. A starter template
   lives at `config/clients.example.csv`. A single new client can later be
   added in one step (ask TimeAssist to add it, or `add-client` on the CLI) —
   no need to re-import the whole CSV.

4. List clients and confirm aliases resolve as expected. If the firm requires
   every billed name to match the master list exactly, turn on strict roster
   mode (`config` setting `strict_roster` = `yes`): entries for unknown names
   are still captured, but can only be fixed by matching or adding a roster
   client — "keep the name as typed" is disabled.
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

Plugin installs now pin the database to `${CLAUDE_PLUGIN_DATA}/timeassist.sqlite`. Default exports, review HTML, and sanitized packets are written under `${CLAUDE_PLUGIN_DATA}/exports/`, `${CLAUDE_PLUGIN_DATA}/reviews/`, and `${CLAUDE_PLUGIN_DATA}/packets/`; backups are written under `${CLAUDE_PLUGIN_DATA}/backups/`. QuickBooks CSV exports are also copied byte-for-byte to the confirmed/default handoff folder, normally `Documents/TimeAssist Exports`. Tool results report full paths. During the pilot, ask TimeAssist for `status`, `config`, or review/export results if you need to confirm the exact local path.

## Troubleshooting

- **Plugin upload/validation fails:** check the desktop app's DevTools/network response for the real validation error; Cowork may show a generic message.
- **Windows warns about the app:** the pilot binary may be unsigned. Do not ask a real pilot user to bypass warnings unless Josh explicitly approves that pilot risk.
- **No tools appear:** confirm the plugin zip structure, plugin manifest, `.mcp.json`, and bundled `bin/timeassist.exe` are present.
- **Export location is unclear:** ask TimeAssist to export again only if safe, or review the previous tool result for the full path. Do not guess.
- **Roster import fails:** verify CSV headers and keep the file local. Do not paste private client lists into chat.

## Handoff to the accountant

Give them only:

- the installed Cowork environment;
- `docs/accountant-quick-start.md`;
- the synthetic pilot script from `docs/pilot-checklist.md`.

Keep developer commands and repo details out of the accountant's first experience.
