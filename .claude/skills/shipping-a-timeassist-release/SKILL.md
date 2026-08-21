---
name: shipping-a-timeassist-release
description: Use when a finished TimeAssist branch needs to become a published release — "ship it", "release", "tag the version", "get this through the loop" — or when verifying or recovering a vX.Y.Z-prototype tag build.
---

# Shipping a TimeAssist Release

## Overview

Nothing builds on merge. The Windows release build runs ONLY when a `v*` tag is
pushed, and a release is done only when that tag run is green AND the published
assets are verified — never before.

This skill starts from a finished, reviewed feature branch. For the
implementation itself, use superpowers:subagent-driven-development against a
plan in `docs/plans/`.

## The loop

1. **Preflight (on the feature branch)**
   - `python3 -m unittest discover -s tests` — all green.
   - Version bumped in BOTH `timeassist/__init__.py` and
     `plugin/timeassist/.claude-plugin/plugin.json` (a test enforces the match)
     plus a `CHANGELOG.md` entry.
   - Changed MCP tools or output shapes? Update BOTH the plugin
     `skills/billable-time-assistant/SKILL.md` AND the PowerShell smoke test in
     `.github/workflows/windows-build.yml` — it asserts MCP payload keys
     (e.g. export's `csv`/`official_csv`) and the local suite will NOT catch a
     mismatch. This exact gap failed the first v0.1.19 tag build.
   - `gh run list --workflow=windows-build.yml --limit 3` — let any in-flight
     release run finish first (parallel runs race over the `dist` force-push).
2. **PR and merge** (direct pushes to main are blocked)
   ```bash
   git push -u origin <branch>
   gh pr create --base main --head <branch> --title "..." --body "..."
   gh pr merge <N> --merge --delete-branch
   git switch main && git pull --ff-only
   ```
   PRs have NO required CI here — the build is tag-triggered, so don't wait on
   `gh pr checks`. Don't rebase the reviewed branch; the repo merges with merge
   commits.
3. **Tag from merged main** — this is the trigger:
   ```bash
   git tag -a vX.Y.Z-prototype -m "TimeAssist vX.Y.Z prototype"
   git push origin vX.Y.Z-prototype
   ```
4. **Watch the tag run** (a background subagent can babysit; ~2–3 min)
   ```bash
   gh run list --workflow=windows-build.yml --limit 2   # grab RUN_ID
   gh run watch <RUN_ID> --exit-status
   ```
   Run `gh run watch` as its own command and read the exit code directly —
   chaining (`&& echo ok`) masks failures.
5. **Verify the release** — required before reporting success:
   ```bash
   gh release view vX.Y.Z-prototype --json tagName,url,assets
   gh release download vX.Y.Z-prototype -D /tmp/rel-verify && sha256sum /tmp/rel-verify/*
   unzip -l /tmp/rel-verify/timeassist-plugin.zip | head -25
   git fetch origin dist && git show origin/dist:plugin/timeassist/.claude-plugin/plugin.json | grep '"version"'
   ```
   Expect: both assets (`timeassist.exe`, `timeassist-plugin.zip`); zip has a
   top-level `timeassist/` folder containing `bin/timeassist.exe`, `.mcp.json`,
   and `skills/billable-time-assistant/SKILL.md`; `origin/dist` shows the new
   version.

## When the tag run fails

- `gh run view <RUN_ID> --log-failed | tail -80` to find the failing step.
- Fix on a NEW branch + PR (main is protected).
- Release never published (`gh release view` says not found)? Move the tag:
  ```bash
  git push --delete origin vX.Y.Z-prototype && git tag -d vX.Y.Z-prototype
  # after the fix merges, re-tag main and push again
  ```
- Release already published? Don't mutate it — ship the fix as the next patch
  version instead.

## Done checklist (report all of it)

- PR URL + merge commit; run ID + conclusion (exit code read directly)
- Release URL; asset names, sizes, SHA256 hashes
- Plugin zip structure verified; `origin/dist` version matches
- Known caveats: unsigned Windows exe; private-repo marketplace access

## Red flags

- "Merged, so it's released" — nothing builds on merge; push the tag.
- Waiting on PR checks — there are none.
- `gh run watch ... && ...` — masked exit code.
- Output-shape change without touching `windows-build.yml`'s smoke assertions.
- Reporting success without downloading/inspecting the published assets.
