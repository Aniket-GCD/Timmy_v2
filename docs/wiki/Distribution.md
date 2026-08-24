# Distribution

How TimeAssist reaches an accountant's machine, and the constraints that shaped
the design.

## The pieces

- **Engine + MCP server** — the deterministic core, runnable as `timeassist mcp`
  (a stdlib JSON-RPC-over-stdio MCP server; entrypoint `scripts/timeassist_mcp.py`).
- **Windows `.exe`** — PyInstaller bundles the engine *and* a Python runtime, so
  the user installs nothing. Platform-native: the `.exe` is built only on a
  **Windows CI runner** (`.github/workflows/windows-build.yml`); a Linux/macOS
  box cannot produce it.
- **Cowork plugin** (`plugin/timeassist/`) — bundles the skill + the local MCP
  server into one installable unit:
  - `.claude-plugin/plugin.json` (manifest)
  - `skills/timmy/SKILL.md` (the `/timmy` skill + approval gate)
  - `.mcp.json` → `${CLAUDE_PLUGIN_ROOT}/bin/timeassist.exe --db ${CLAUDE_PLUGIN_DATA}/timeassist.sqlite mcp`, with `cwd` set to `${CLAUDE_PLUGIN_DATA}`
  - `bin/timeassist.exe` (dropped in by CI; gitignored, never committed)
- **Marketplace** (`.claude-plugin/marketplace.json`) — points the plugin source
  at a **`dist` branch** via `git-subdir`. Marketplaces fetch from git (or npm),
  **not** release zips, and the binary isn't in git — so CI publishes the built
  plugin (binary included) to a single-commit, force-pushed `dist` branch. The
  plugin starts at `0.1.0`; bump `.claude-plugin/plugin.json` for each pilot
  release you want users to receive. CI still publishes the built plugin
  (binary included) to the `dist` branch; users refresh marketplace metadata and
  update the installed plugin.

## How a user installs it

- **Marketplace (hands-off updates):** `/plugin marketplace add 0paani/timeassist-local-kit`
  → `/plugin install timeassist@timeassist-marketplace`. Update later with
  `/plugin marketplace update`.
- **File handoff (fallback, works without GitHub access):** download
  `timeassist-plugin.zip` from a Release and upload it in Cowork
  (Customize → plugins → upload). Manual updates per person.

## Platform stance

The current pilot plugin is intentionally **Windows-only**:

- it bundles `bin/timeassist.exe` built by the Windows CI/release flow;
- accountants do not need Python, terminal setup, or dependency installs;
- this is acceptable for a guided Windows/Cowork pilot, but every distributed zip must be built from the commit being tested;
- the binary is currently unsigned, so Windows SmartScreen or antivirus warnings are possible. Do not ask a real pilot user to bypass a warning unless Josh explicitly accepts that pilot risk.

This is a packaging constraint, not a core-architecture constraint. The deterministic engine is Python and can be built into platform-native binaries later.

## Universal packaging options

Recommended path after the Windows pilot proves the workflow:

1. **Platform-specific plugin builds** — `timeassist-windows`, `timeassist-macos`, and `timeassist-linux`, each bundling the right native binary and the same skill/MCP contract. This keeps the no-terminal experience and is the best long-term cross-platform shape.
2. **Single plugin with a platform launcher** — one package containing `timeassist-windows.exe`, `timeassist-macos`, `timeassist-linux`, plus a small launcher script. This is convenient but more fragile because Windows and Unix process-launch behavior differ.
3. **Python/source plugin** — point `.mcp.json` at Python source instead of a bundled binary. Good for developers; poor for nontechnical accountants because it assumes Python exists and is on PATH.
4. **Remote MCP server** — universal from the user's machine, but it breaks the local-first/privacy story and adds hosting, auth, tenant isolation, and vendor-approval work. Not recommended for the first accounting pilot.
5. **Desktop installer plus thin plugin** — a future polished route: install TimeAssist as a signed app, then have the plugin call the installed command. Better for mature distribution, overkill for the current lightweight pilot.

Do **not** rewrite the working Python engine just to chase universality. Treat universal support as a packaging/release problem unless pilot evidence proves otherwise.

## Data location

Cowork/plugin installs pin durable state under `${CLAUDE_PLUGIN_DATA}`:

- database: `${CLAUDE_PLUGIN_DATA}/timeassist.sqlite`
- default exports: `${CLAUDE_PLUGIN_DATA}/quickbooks-time-YYYY-MM-DD.csv`
- default review HTML: `${CLAUDE_PLUGIN_DATA}/review-YYYY-MM-DD.html`
- default sanitized packets: `${CLAUDE_PLUGIN_DATA}/sanitized-collaboration-packet-YYYY-MM-DD.md`
- backups: `${CLAUDE_PLUGIN_DATA}/backups/`

The MCP config also sets `cwd` to `${CLAUDE_PLUGIN_DATA}`. Tool results report full paths, so the helper can ask TimeAssist to show `status`, `review`, or `export` results and see where files landed. Direct CLI use still honors `--db` / `--output`; relative default artifacts resolve next to the selected database.

## The big constraint: repo visibility

The repo is **private**, and the marketplace/plugin are fetched from it, so:

- Only people with **authenticated GitHub access** to the private repo can add
  the marketplace. `/plugin marketplace add` failed in testing with "Marketplace
  sync failed" — Cowork's sandbox could not authenticate to clone the private repo.
- It is **not** in any public/community catalog (that needs an explicit
  Anthropic submission). Strangers cannot find or add it.

### Paths to real distribution

1. **Public distribution-only repo** — a slim public repo (`marketplace.json` +
   the compiled plugin/skill/binary; **no source, docs, or client data**) that CI
   pushes to. Anyone can `/plugin marketplace add` it with no auth, main repo
   stays private. *Not yet decided — requires explicitly crossing the "keep
   private" boundary.*
2. **Team/Enterprise org marketplace** — admin publishes the plugin to org
   members, private and hands-off. Needs the plan tier. **This is the intended
   eventual rollout.**
3. **File handoff** — works today regardless of visibility, but manual.

## Cowork lessons learned (so we don't repeat them)

- Cowork's "MCP Server **URL**" field is for *remote* servers only; local stdio
  servers aren't added there.
- Cowork runs in a **sandboxed VM** — it cannot spawn arbitrary local processes
  or auth to private git by default. Plugins are the supported way to ship a
  local server.
- The plugin **zip must contain a top-level `timeassist/` folder** (not contents
  at the archive root) for the Cowork uploader.
- "Plugin validation failed" in Cowork is a **known bug that hides the real
  reason**; check the desktop app's DevTools → Network → Response for the actual
  `validation_errors`.
