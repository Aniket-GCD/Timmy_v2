# Deploy

How to ship a new build. There is also a `deploy-windows-build` skill that
automates this loop.

## The flow

1. **Preflight:** `python3 -m unittest discover -s tests` passes; working tree
   committed.
2. **Get it reviewable:** direct pushes to `main` are **blocked** by the harness,
   so push to a feature branch and open a PR (`git push origin HEAD:<branch>` +
   `gh pr create`). Merge via `gh pr merge`.
3. **Trigger the build:** push a `vX` tag — `git tag -a vX -m "…"` then
   `git push origin vX`. Tag builds use the workflow from the tagged commit, so a
   tag works even for an un-merged commit.
4. **Watch:** `gh run watch <id> --exit-status`. **Read the exit code directly** —
   chaining another command after it masks the pass/fail.
5. **On failure:** `gh run view <id> --log-failed`, fix the root cause (never
   disable a check), push a **new** tag.

## What CI does (`.github/workflows/windows-build.yml`, `windows-latest`)

1. Run unit tests.
2. Build `timeassist.exe` (PyInstaller via `scripts/package_executable.py`).
3. Verify the CLI and smoke-test the MCP stdio server.
4. Package the Cowork plugin zip (`scripts/package_plugin.py`).
5. On a `vX` tag: publish a GitHub Release with `timeassist.exe` +
   `timeassist-plugin.zip`, and force-push the built plugin (binary included) to
   the **`dist` branch** for the marketplace.

## Gotchas (hard-won)

- **`main` push is blocked** → branch + PR + tag.
- **`gh run watch` exit code is masked** if you chain commands after it.
- **Linux can't build the `.exe`** → only the Windows runner produces it.
- **sqlite connections must close** — `db.connect()` is a context manager that
  closes; otherwise Windows locks the file (this failed the first CI run).
- **Plugin zip needs a top-level folder** — see [Distribution](Distribution.md).

## Next pipeline change

**Code signing.** Unsigned `.exe` trips Windows SmartScreen. Recommended path:
**Azure Artifact Signing** (formerly Trusted Signing) — ~$9.99/mo, cloud-based
(fits CI, no USB token), individual sign-up available in US/Canada. Note: since
March 2024, EV no longer gives instant SmartScreen reputation — OV is fine;
reputation builds with download volume.
