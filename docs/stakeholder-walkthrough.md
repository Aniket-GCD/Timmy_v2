# Stakeholder Walkthrough

## Purpose

Use this walkthrough to show the prototype as a working decision workflow, not a finished product.

The key point for stakeholders:

> TimeAssist helps staff capture draft time while the work is happening, recover from client/context switching, then keeps human review in front of any billing handoff.

## What to show

### 1. Start with the problem

Accountants lose time in the gaps:

- short client questions;
- task switching;
- spreadsheet friction;
- trying to reconstruct the day from memory.

The goal is not surveillance. The goal is better draft capture and a cleaner review process.

### 2. Show the capture flow

Run or show the generated transcript:

```bash
python scripts/run_stakeholder_demo.py
```

The demo walks through:

```text
start Client A monthly cleanup
→ correct a context switch that happened 20 minutes ago
→ check whether the active timer needs a nudge
→ snooze or confirm the reminder
→ end the active task
→ add one missing time block
→ review the day, including any active-timer warning
→ approve two entries
→ export approved entries only
→ generate a sanitized collaboration packet
```

### 3. Show the review screen

Open:

```text
demo/generated/stakeholder-review.html
```

Point out:

- draft/approved/exported status is visible;
- the accountant still approves the time;
- an open timer warning appears before approval/export if the timer may still be running;
- event count shows the system is accountable;
- there is no screen recording, keystroke logging, or silent inbox monitoring.

### 4. Show the export

Open:

```text
demo/generated/quickbooks-time-export.csv
```

Point out:

- only approved entries export;
- draft entries stay behind;
- this is a QuickBooks-ready handoff shape, not direct writeback;
- the exact columns should be adjusted after the stakeholder confirms the QuickBooks route.

### 5. Show the privacy boundary

Open:

```text
demo/generated/sanitized-collaboration-packet.md
```

Point out:

- external review uses anonymized labels like Client 1 / Client 2;
- real client names, exports, credentials, internal URLs, and copied messages stay out;
- this supports design review without moving private data into the portfolio/VPS environment.

## Decisions to ask for tomorrow

1. What data classes are approved for a pilot?
2. What billing increment, rounding rule, and reminder cadence should v1 use?
3. Should reminders be local only during working hours, or should the pilot avoid scheduled reminders and test manual check-ins first?
4. Which QuickBooks handoff route should the first export target?
5. Who would be the first pilot user?
6. What review surface would feel natural: terminal/Claude, local HTML, Microsoft List, n8n Data Table, or something else?

## Positioning line

This is not an AI that decides what to bill. It is a workflow that helps the expert keep better track of what happened, review it clearly, and hand off only what they approve.
