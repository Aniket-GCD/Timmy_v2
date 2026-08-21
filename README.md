# TimeAssist Local Kit

TimeAssist is a local-first prototype for turning interrupt-driven work into human-reviewed draft billable-time entries.

It is built for accountants, operators, and small teams who need a lightweight way to capture work as it happens, review it before billing, and export only approved entries. The goal is not surveillance or automatic writeback. The goal is a clear local workflow where the person remains the billing authority.

## Start here

- **Accountant/operator:** `docs/accountant-quick-start.md` — one-page plain-language workflow.
- **Helper/admin:** `docs/admin-install.md` and `docs/pilot-checklist.md` — install, validation, and first guided pilot.
- **Stakeholder walkthrough:** `docs/project-brief.md` and `docs/stakeholder-walkthrough.md` — framing, demo path, and decision prompts.
- **Technical reader:** `docs/wiki/Architecture.md`, `docs/wiki/Home.md`, `CHANGELOG.md`, `tests/`, and `plugin/timeassist/`.

## Current status

- **Stage:** stakeholder prototype moving toward a guided pilot.
- **Runtime:** deterministic Python core with local SQLite state.
- **Assistant surface:** local MCP stdio server plus a packaged Claude plugin prototype.
- **Data rule:** synthetic examples only. Do not commit real client data, exports, credentials, internal URLs, copied email/Teams text, or private work context.
- **Distribution focus:** first pilot bundle is Windows-oriented through the packaged plugin in `plugin/timeassist/`.

## What TimeAssist should prove

1. A user can start, switch, end, and review draft billable-time entries without making a spreadsheet the main interface.
2. Context-switch reminders help the user correct an active timer without feeling watched.
3. Every mutation has an event log.
4. Raw/exact time is the default; rounding happens only when the operator chooses it.
5. The accountant remains the billing authority.
6. Approved entries can produce a validated QuickBooks-ready handoff before any direct QuickBooks writeback.
7. The workflow feels helpful, not creepy.

## Local workflow model

```text
operator expertise + local work context
→ assistant-guided capture and review workflow
→ deterministic local engine records state and exports
→ human review approves entries
→ approved synthetic/export artifacts support handoff or design review
```

The model can help interpret user intent, but the Python engine owns state, time math, approval state, export bytes, and local file paths.

The context-switch loop is intentionally narrow: if a timer is already active, a scheduled check can ask `checkin_status`; the assistant prompts only when `should_prompt=true`. The user can answer "still," "switched 20 minutes ago," "done," "snooze," or "cancel," and each answer maps to a deterministic action.

## Repository map

```text
.github/                         CI for validation and Windows plugin packaging
.claude-plugin/marketplace.json  Marketplace/distribution metadata for the plugin package
config/                          Safe example config and synthetic lookup-data shape
demo/generated/                  Curated synthetic sample output from the stakeholder demo
docs/                            Quick starts, architecture, pilot docs, and stakeholder walkthroughs
exports/                         Local export target; real exports are gitignored
packaging/                       PyInstaller packaging assets
plugin/timeassist/               Shipped Claude plugin package and assistant behavior skill
samples/                         Synthetic examples only
scripts/                         CLI, MCP, demo, and packaging entrypoints
state/                           Local state target; real SQLite files are gitignored
templates/                       Review, export, and sanitized-packet templates
tests/                           Unit and smoke tests
timeassist/                      Deterministic local Python package
```

## Stakeholder demo

Generate synthetic walkthrough artifacts:

```bash
python scripts/run_stakeholder_demo.py
```

Or use the same flow through the main CLI:

```bash
python scripts/timeassist.py demo --output demo/generated
```

Then open:

- `docs/stakeholder-walkthrough.md` — talk track and decision prompts.
- `demo/generated/stakeholder-review.html` — stakeholder-friendly review screen.
- `demo/generated/quickbooks-time-export.csv` — synthetic approved-entry export.
- `demo/generated/sanitized-collaboration-packet.md` — anonymized packet for outside design review.

`demo/generated/` is intentionally tracked as curated synthetic sample output. Regenerate it when the demo story or output format changes.

## CLI shape

The stable action contract is intentionally boring:

```bash
python scripts/timeassist.py init
python scripts/timeassist.py start --client "Client A" --task "monthly cleanup" --billable yes
python scripts/timeassist.py switch --client "Client B" --task "tax question" --billable yes --minutes-ago 20
python scripts/timeassist.py checkin-status
python scripts/timeassist.py snooze-checkin --minutes 30
python scripts/timeassist.py end
python scripts/timeassist.py review --date today
python scripts/timeassist.py approve --entry-id 1
python scripts/timeassist.py export --date today --format quickbooks-csv
python scripts/timeassist.py sanitize-packet --date today
```

The current CLI creates local SQLite state, records draft entries, logs events, produces a review screen, exports approved synthetic entries, and generates an anonymized collaboration packet.

## Cowork / MCP plugin prototype

The deterministic core is exposed over a local MCP stdio server so the same engine is reachable from Claude Cowork and Claude Code. The server is stdlib-only — no extra dependencies.

For a guided Cowork pilot, use the packaged plugin in `plugin/timeassist/` instead of asking an accountant to edit MCP config by hand:

- accountant workflow: `docs/accountant-quick-start.md`
- helper install path: `docs/admin-install.md`
- pilot runbook: `docs/pilot-checklist.md`

Developer server entrypoint:

```bash
python scripts/timeassist_mcp.py --db state/timeassist.sqlite
```

Developer MCP registration example:

```json
{
  "mcpServers": {
    "timeassist": {
      "command": "python3",
      "args": ["scripts/timeassist_mcp.py", "--db", "state/timeassist.sqlite"],
      "env": {}
    }
  }
}
```

The current pilot bundle is Windows-only because `plugin/timeassist/.mcp.json` launches `bin/timeassist.exe`. That is intentional for the first guided Cowork pilot. See `docs/wiki/Distribution.md` for cross-platform packaging options if the workflow needs macOS or Linux support.

The plugin pins its database to `${CLAUDE_PLUGIN_DATA}/timeassist.sqlite`. The official export CSV, review HTML, sanitized packets, and backups live in subfolders next to that database (`exports/`, `backups/`, …) — that internal copy is the audit source of truth. Every export also copies the exact CSV bytes to a user-visible folder so the accountant can find it: `Documents/TimeAssist Exports` by default, or the folder chosen via `config` `user_export_dir` (requires `confirm=true`).

Tools exposed include capture, review, edit, approve/approve-all, unapprove, export, sanitized packet, roster import/list, reminders/check-ins, status, cleanup, and config for settings such as rounding and `user_export_dir`. The shipped assistant behavior contract lives at `plugin/timeassist/skills/billable-time-assistant/SKILL.md`.

## Executable showcase build

Build a platform-native one-file executable with PyInstaller:

```bash
python scripts/package_executable.py
```

Then run the demo without invoking Python directly:

```bash
./dist/timeassist --help
./dist/timeassist demo --output demo/generated-exe
```

Open `demo/generated-exe/stakeholder-review.html` for the branded stakeholder review. This build is platform-native: Linux creates a Linux binary, macOS creates a macOS binary, and Windows should build the `.exe` on Windows or through CI.

See `docs/executable-demo.md` for a stakeholder walkthrough script.

## Local validation

```bash
python scripts/timeassist.py --help
python scripts/timeassist.py init --dry-run
python -m unittest discover -s tests -v
python scripts/run_stakeholder_demo.py
```

Smoke-test the MCP transport directly with a throwaway DB:

```bash
printf '%s\n' \
  '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18"}}' \
  '{"jsonrpc":"2.0","id":2,"method":"tools/list"}' \
  | python scripts/timeassist_mcp.py --db /tmp/timeassist-smoke.sqlite
```

Validate plugin packaging metadata when the Claude CLI is available:

```bash
claude plugin validate --strict ./plugin/timeassist
claude plugin validate --strict ./.claude-plugin/marketplace.json
```

## Privacy boundary

Do not commit:

- real client names or IDs;
- QuickBooks exports, company files, or credentials;
- `.env` files;
- SQLite state files from real use;
- copied email/Teams text;
- internal URLs, screenshots, or private documents.

Use `sanitize-packet` before asking an outside assistant or portfolio bot for design review.
