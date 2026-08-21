# TimeAssist Guided Pilot Checklist

Use this checklist for the first guided pilot. The goal is not to prove every feature. The goal is to see whether a nontechnical accountant can capture, review, approve, and export a small day of time without the workflow feeling creepy or fragile.

## Before the session

- [ ] Use synthetic data unless real pilot data has been explicitly approved.
- [ ] Confirm Cowork and the TimeAssist plugin are installed.
- [ ] Confirm the local TimeAssist state initializes successfully.
- [ ] Prepare a tiny synthetic roster CSV, if roster import is part of the test.
- [ ] Decide the rounding rule to test.
- [ ] Decide whether to test reminders manually or with a scheduled Cowork task.
- [ ] Decide the reminder cadence to discuss if scheduling is in scope, such as 30–60 minutes during the workday.
- [ ] Decide where the exported CSV should be handed off or inspected.

## Pilot script

### 1. Install and verify

- [ ] Install/upload the plugin.
- [ ] Start a fresh Cowork chat.
- [ ] Say: “Use TimeAssist and initialize local state.”
- [ ] Ask: “Show TimeAssist status.”
- [ ] Confirm no real client data is present.

Record:

- install completion time:
- any helper intervention needed:
- validation/install errors:

### 2. Optional roster import

- [ ] Import the approved local synthetic roster CSV.
- [ ] List clients.
- [ ] Confirm aliases resolve to the expected display names.

Record:

- roster file location:
- import result:
- any confusing client-name behavior:

### 3. Set or confirm rounding

- [ ] Ask what rounding rule is active.
- [ ] Set the test rule, if needed.
- [ ] Confirm the accountant understands raw vs rounded time.

Record:

- selected rule:
- did the explanation make sense?:

### 4. Capture a synthetic workday

Use simple, fake client names.

- [ ] “Start time for Client A monthly cleanup.”
- [ ] “I switched 20 minutes ago to Client B tax question.”
- [ ] Ask TimeAssist whether the active timer needs a check-in.
- [ ] Reply “Still” or “Pause reminders for 30 minutes.”
- [ ] “End my current timer.”
- [ ] “Add missing time from 10:00 to 10:30 for Client A call notes.”
- [ ] “Review today.”

Record:

- missed/stale sessions:
- context-switch corrections recovered:
- reminder prompts shown:
- reminder prompts suppressed because nothing was due:
- snoozes requested:
- corrections needed:
- phrases that did not work naturally:
- places where the assistant over-explained:

### 5. Review and correct

- [ ] Ask: “Review today.”
- [ ] Make at least one correction to a draft entry.
- [ ] Confirm the corrected review looks right.
- [ ] Confirm draft, approved, and exported states are understandable.

Record:

- number of corrections:
- did entry IDs make sense?:
- did the review feel trustworthy?:

### 6. Approve

- [ ] Approve one or two specific entries.
- [ ] Review again.
- [ ] Optionally test “Approve all of today” only if the accountant understands it.

Record:

- approval time:
- did approval feel deliberate?:
- any accidental approval risk?:

### 7. Export

- [ ] Say: “Export approved time.”
- [ ] Confirm only approved entries were exported.
- [ ] Confirm the tool result includes the export path.
- [ ] Open or inspect the CSV.
- [ ] Confirm whether the CSV shape matches the intended QuickBooks handoff route.

Record:

- export file path:
- exported row count:
- remaining draft count:
- QuickBooks/import friction:

## Feedback questions

Ask these at the end:

1. Where did this save you time?
2. Where did it slow you down?
3. Did the reminder/check-in flow help with context switching, or did it feel like nagging?
4. Did anything feel creepy or too automated?
5. Did you trust the review screen enough to approve from it?
6. What phrase did you naturally want to say that did not work?
7. Was the export file easy to find?
8. Would you use this for one real day if the data rules were approved?

## Pilot metrics

- install completion time:
- number of times the user needed help:
- missed/stale sessions per day:
- corrections per review:
- approval/export time at end of day:
- “Did this feel creepy?” score, 1–5:
- export handoff friction:

## Exit decision

Choose one:

- [ ] Ready for another synthetic pilot.
- [ ] Ready for a tightly approved real-data pilot.
- [ ] Needs install/data-path hardening first.
- [ ] Needs review/export UX changes first.
- [ ] Stop; workflow does not feel useful enough yet.

Notes:

-
