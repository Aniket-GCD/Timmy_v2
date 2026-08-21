# Roster Name Matching UX — Design Spec (start of next 0.1.x)

> **Status: FOLDED into `2026-07-01-timmy-pilot-feedback.md` — do not execute from
> this doc.** Content carries over unchanged except the management tiebreak extension
> defined there.

**Source:** Cowork pilot feedback, Sonnet, full day on v0.1.20-prototype
([issue #33](https://github.com/0paani/timeassist-local-kit/issues/33)). Two of the
three threads in that feedback; the third (QuickBooks Desktop IIF export) is **parked
in #33** pending the operator's QuickBooks details and is explicitly out of scope here.

**Goal:** Stop making the operator ask "are all these clients on the roster?". Two
reinforcing changes:
- **2b** — individual names typed as `Firstname Lastname` auto-match roster/QuickBooks
  entries stored as `Lastname, Firstname`, so they never become `needs_info` in the
  first place ("match as it goes").
- **2a** — whatever legitimately does *not* match is surfaced to the operator
  proactively at review, before approval, instead of on request.

## Scope

**In:**
- Deterministic comma-swap matching in `resolve_client` (engine).
- A SKILL.md workflow change so the assistant proactively surfaces `needs_info`
  clients at review before approval.

**Out (explicitly):**
- QuickBooks IIF / Desktop export (parked in #33).
- Fuzzy / typo-tolerant matching and lone-first-name matching — **rejected** as
  mis-billing risks that break the deterministic-engine invariant.
- Any roster schema change, re-import requirement, or new MCP tool.

## Architecture

### Section A — 2b: comma-swap matching (engine, `timeassist/actions.py`)

A pure helper:

```python
def name_fold(name: str) -> str:
    s = " ".join(name.lower().split())        # lower + collapse whitespace
    if "," in s:
        parts = [p.strip() for p in s.split(",")]
        if len(parts) == 2 and all(parts):
            s = f"{parts[1]} {parts[0]}"        # "smith, john" -> "john smith"
    return s
```

`resolve_client` gains a **third pass**, after the existing exact-display-name and
exact-alias passes (`actions.py:452`):

```
target = name_fold(typed_name)
matches = [r for r in rows if name_fold(r["display_name"]) == target]
if len(matches) == 1:  return that client's (display_name, default_billable)
# 0 matches OR >1 (ambiguous) -> fall through to the existing needs_info return
```

Safety properties (all to be pinned by tests):
- Only names **containing a comma** fold differently; businesses (`Acme Holdings LLC`)
  are untouched — they still hit the exact pass or stay `needs_info`.
- Resolves **both directions**, case- and whitespace-insensitive.
- **Ambiguity (two `Smith, John`s) → no guess → `needs_info`.** Never bills blind.
- Folds `display_name` only; aliases stay exact-match.
- Pure function; **no schema change, no roster re-import** — works on the existing
  roster immediately. Runs at capture/switch *and* `edit`, so smart matching applies
  live, not just at review.

### Section B — 2a: proactively surface genuine unmatched (SKILL.md)

`review` already returns every `needs_info` entry (with client + reason) and a
`skipped_needs_info_count` (`mcp_views.py:70`). The data is present; the gap is the
assistant not acting on it. **SKILL.md-only change, no new result field** (protects the
Cowork token budget — the names are already in the review payload):

> When `review` returns entries with `needs_info` (or `skipped_needs_info_count > 0`),
> proactively name those clients to the operator and offer to resolve them **before**
> approval — do not wait to be asked. Resolve via the existing one-`edit` confirm-as-is
> recipe.

### Section C — Testing & sync

**New tests (synthetic data only):**
- `name_fold` units: comma-swap both directions; case/whitespace insensitivity;
  no-comma business names unchanged; malformed/multi-comma names fall through safely.
- `resolve_client` integration: `John Smith` → `Smith, John` resolves at capture
  *and* at `edit`; duplicate `Smith, John` stays `needs_info` (pins no-blind-bill);
  unknown individual still `needs_info`.
- SKILL.md surfacing phrase asserted by the existing assistant-contract gate test.

**Sync checklist (CLAUDE.md "easy to miss"):**
- Engine-only `resolve_client` change → **no** MCP tool/`TOOLS`/`call_tool`/`mcp_views`
  change and **no** `windows-build.yml` PowerShell-contract change.
- Update **both** SKILL.md copies (`plugin/timeassist/.../SKILL.md` gated contract +
  repo-root skill) so they don't drift.
- `CHANGELOG.md`: operator-facing note ("names like `John Smith` now match roster
  `Smith, John` automatically; unmatched clients are flagged before approval").
- Pin the "ambiguous → needs_info, never guess" intent with a test + comment (per the
  rounding-floor convention) — intentional-but-surprising behavior.
- Full suite green before every commit: `python3 -m unittest discover -s tests`.

## Decisions locked

- **Exact comma-swap only.** No fuzzy, no typo tolerance, no lone-first-name matching.
- **Ambiguity never resolves** — two roster entries folding to the same name keep the
  entry `needs_info`; the engine never picks one.
- **No new result field for 2a** — surfacing is a behavioral (SKILL.md) fix; review
  already carries the data. Revisit only if surfacing proves unreliable in a later pilot.
- **Fold `display_name` only**, not aliases.
- Version bump deferred to the release step (ship via `shipping-a-timeassist-release`
  when Josh says go); no tag in this branch.

## Baseline

Branch from `main` (228 tests + 5 subtests green). Worker rules: stdlib only; full
suite before every commit; commits end with the project Co-Authored-By trailer.
Codex will review the diff — keep the engine change a small, pure, well-tested unit.
