# TimeAssist Local Kit — Project Brief

## Problem

Accountants lose billable time in the gaps: short interruptions, quick client questions, switching between tasks, spreadsheet friction, and trying to reconstruct the day later.

## Product thesis

TimeAssist should make draft time capture easier without turning into surveillance. The accountant stays in control. The system helps capture, organize, review, and export.

```text
quick capture
→ context-switch check-ins and corrections
→ structured draft entry
→ end-of-day review
→ human approval
→ QuickBooks-ready handoff
```

## V1 scope

- Local CLI action contract.
- Claude Code skill/workflow wrapper.
- Local SQLite state.
- Event log for every mutation.
- Context-switch check-ins: due-aware status, "still working" confirmations, snooze, and retroactive "switched N minutes ago" correction.
- Synthetic sample data.
- End-of-day review output.
- Approved-entry export template.
- Sanitized collaboration packet for outside review.

## Out of scope for v1

- Keystroke logging.
- Screen recording.
- Silent email/Teams surveillance.
- Automatic billing decisions.
- Direct QuickBooks writeback.
- Production use with real client data before stakeholder approval.

## Success criteria

- Staff can start, switch, and end a draft time block quickly.
- End-of-day review is faster than reconstructing a spreadsheet from memory.
- Draft entries can be edited before approval.
- Approved entries can be exported to a confirmed QuickBooks-ready route.
- Every meaningful action is traceable.
- The experience feels supportive, not intrusive.

## Stakeholder decisions needed

1. First pilot user: Josh only, or a nontechnical accountant as well?
2. First platform target: Windows-native, WSL-first, or both?
3. Billing increment and rounding rule.
4. Service-code list and default billable rules.
5. QuickBooks handoff route: Time Activities import, Spreadsheet Sync, QuickBooks Time CSV, API later, or approved importer.
6. Review surface: terminal markdown, CSV, local HTML, Microsoft List, n8n Data Table, or another tool.
7. What data classes are approved for any pilot.

## Privacy posture

This repo can contain planning, synthetic examples, schemas, and sanitized packets. Real client/work data stays outside the repo unless explicitly approved and redacted.
