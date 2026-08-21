# Project Board

This file mirrors the GitHub issues/project board so the plan remains readable from the repo itself.

GitHub issues are the active tracker. A GitHub Projects board should be created once the GitHub CLI token has `project` and `read:project` scopes; until then, the `status: now`, `status: next`, and `status: later` labels are the working board columns.

## Now

- [ ] Run stakeholder walkthrough and capture feedback — #12
- [ ] Confirm privacy boundary and approved pilot data classes — #2
- [ ] Confirm first QuickBooks handoff route to test — #3
- [ ] Create GitHub Projects board after auth scope refresh — #11

## Next

- [ ] Phase 1 — Deterministic local core
- [ ] Phase 2 — Review and approval workflow
- [ ] Phase 3 — Export and sanitized-packet generator

## Later

- [ ] Claude Code workflow hardening
- [ ] n8n/Teams wrapper spike
- [ ] QuickBooks API/writeback spike after approval
- [ ] Nontechnical installer/executable packaging

## Done

- [x] Phase 0 — Package skeleton and stakeholder brief — #1
- [x] Stakeholder prototype artifacts generated — `a15ea0d`

## Backlog themes

### Foundation

- Repo skeleton, docs, guardrails, example config, synthetic samples.
- Local CLI action contract.
- Validation commands.

### Deterministic core

- SQLite schema.
- Start/switch/end/snooze/add-missing actions.
- Event log.
- Rounding rules.

### Review and export

- End-of-day review.
- Edit/approve/unapprove flow.
- QuickBooks-ready export.
- Export audit trail.

### AI and workflow wrapper

- Claude Code skill uses CLI for all mutations.
- AI can parse messy intent and suggest descriptions, but not own time math, approvals, or export status.

### Stakeholder/pilot

- Stakeholder-friendly update template.
- Synthetic pilot script.
- Pilot feedback metrics: prompt fatigue, correction rate, review time, missing-time recovery.
