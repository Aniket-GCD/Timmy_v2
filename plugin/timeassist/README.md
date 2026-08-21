# TimeAssist plugin

A Claude / Cowork plugin that bundles the billable-time assistant **skill** and a **local MCP server** into one installable unit. Installing it gives the operator TimeAssist tools for capture, review, edit, approve, export, and sanitized packets.

The accountant should not need this file. In the repo, send them to `../../docs/accountant-quick-start.md`.

## Contents

```text
.claude-plugin/plugin.json                 plugin manifest
skills/billable-time-assistant/SKILL.md    assistant workflow + approval gate
.mcp.json                                  local MCP server declaration
bin/timeassist.exe                         Windows engine, added by CI/release build
```

## Pilot install

For a guided pilot, use one of these routes:

- **File handoff:** download the release plugin zip and upload it in Cowork plugin settings.
- **Managed org:** on Team/Enterprise, publish through the org/marketplace path once approved.

After install, start a fresh Cowork chat and ask:

> Use TimeAssist and initialize local state.

Then follow:

- `../../docs/admin-install.md` for helper setup and validation.
- `../../docs/pilot-checklist.md` for the synthetic first-day pilot.

## Data and privacy notes

- Plugin installs pin the database to `${CLAUDE_PLUGIN_DATA}/timeassist.sqlite`.
- Default exports, review HTML, sanitized packets, and backups are written next to that database.
- On first run, `init_state` returns an `export_folder` survey so Cowork can ask the operator to accept the default `Documents/TimeAssist Exports` handoff folder or choose a custom one.
- A built-in copy step writes each official QuickBooks CSV to the confirmed/default handoff folder; a confirmed `user_export_dir` setting can override that folder without letting model-supplied export paths escape plugin data.
- Tool results report both the internal `output` and `user_visible_output`.
- The roster is not bundled; import only an approved local CSV.
- The assistant should review drafts before approval and export only approved entries.
- There is no direct QuickBooks writeback in this pilot.

## Develop / test locally

```bash
claude --plugin-dir ./plugin/timeassist
/reload-plugins
```

Validate from the repo root:

```bash
claude plugin validate ./plugin/timeassist
python -m unittest discover -s tests -v
```

The current pilot bundle is Windows-only. That is intentional for the first guided Cowork test. For macOS/Linux or broader distribution options, see `../../docs/wiki/Distribution.md`.

The bundled binary is platform-native. Build the Windows `.exe` with the repo's Windows CI/release flow; a Linux/macOS checkout will not have a runnable `bin/` binary.
