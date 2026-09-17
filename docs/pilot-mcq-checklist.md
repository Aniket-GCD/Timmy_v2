# Weston / Nate — Timmy MCQ pilot checklist

Use after installing a plugin build that includes the MCQ skill + engine.

## Start timer (happy path)

1. `/timmy start the timer on express 3g trucking` (or similar spoken name)
2. **Client MCQ** — top 3 closest + Other (not open “Did you mean?” only)
3. **Job code MCQ** — suggested codes + Other
4. **Notes** — short text or Skip for now
5. See exactly: `Timer started for {CLIENT} at {TIME}.` — then work

## Approve

1. Draft table → “Want me to approve this?”
2. Say **approve**
3. Hear **Entry logged.** — no “Supabase”, no “ready for export”

## Staff / office

1. Fresh setup asks name
2. Soft/ambiguous match shows name **and office** choices
3. Client list matches that office only

## Packaging note

Engine + MCP changes require rebuilding `timeassist.exe` then
`python scripts/package_plugin.py` before installing the zip in Claude.
Skill-only wording can ship in the zip without PyInstaller, but this release
includes engine changes — rebuild the exe for pilots.
