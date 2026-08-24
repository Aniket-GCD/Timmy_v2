# Timmy Quick Start for Accountants

Timmy (formerly TimeAssist) helps you capture draft billable time while you work, then review and approve it before anything is exported.

It is not surveillance. It does not watch your screen, read your email, or bill clients on its own. You stay in charge of what gets approved.

## The basic rhythm

1. Tell Timmy what you are starting.
2. Tell it when you switch or stop.
3. Review the day before approving anything.
4. Export only the entries you approved.

## Phrases you can say

- “Start time for Client A monthly cleanup.”
- “Switch to Client B tax question.”
- “I switched 20 minutes ago to Client B tax question.”
- “End my current timer.”
- “Pause reminders for 30 minutes.”
- “Add missing time from 10:00 to 10:30 for Client A call notes.”
- “Review today.”
- “Change entry 2 to Client C payroll question.”
- “Approve entries 1 and 2.”
- “Approve all of today.”
- “Export approved time.”

## First-day setup

A helper may do this with you during the pilot:

1. Open Claude Cowork with Timmy enabled.
2. Say: “Use Timmy and initialize my local time file.”
3. Confirm the export handoff folder. The default is your real Documents folder,
   `Documents\TimeAssist Exports`, so exported CSVs are easy to find. A helper
   can set a different folder if needed.
4. Confirm Timmy can list your firm's clients from Supabase (ask for a short
   client list). There is no local CSV roster import — names come from the
   live firm list.
5. Tell Timmy your initials once. The helper sets your short code from the firm's
   employee list (for example AVD), and every export file you produce carries it —
   `quickbooks-time-AVD-2026-06-30.csv` — so files from different people stay
   easy to tell apart.
6. Pick a rounding preference: keep raw time, or round to any number of minutes you like — for example nearest 6, round up 6, nearest 15, or nearest 10.
   If you round, very short work never disappears: a 7-minute call rounded to
   nearest 15 bills as 15 minutes, never 0. Keep raw time if you don't want that.
7. Run a synthetic practice day before using real client names.

Client names are read live from Supabase for your office. They are not stored
as a separate CSV on your machine.

## Client names and built-in categories

- **A few categories are always there.** Admin, Early Out, Holiday, and Staff Meeting
  are built in. They are always non-billable and always filed as "Administrative", so
  you can log that time without it ever landing on a client bill.
- **Names match how people say them.** Soft matching can resolve a nickname
  (for example "Bill's Shop") to the full QuickBooks name when that match is unique.
- **Job Codes come from the firm list.** Use `list_job_codes` / ask Timmy for
  Job Codes — do not invent accounts or codes.

## Context-switch reminders

Timmy can help with the "wait, what was I billing?" problem without watching your screen.

When a reminder runs, Timmy first checks whether you have an active timer. If nothing is open, it should stay quiet. If a timer has been open long enough, it may ask something like:

> “Timmy has Client A monthly cleanup open for 47 minutes. Still the right timer, or did work shift?”

Useful replies:

- “Still.” Timmy records a check-in and keeps the timer running.
- “I switched 20 minutes ago to Client B tax question.” Timmy closes the old timer at the honest switch time and starts the new one there.
- “Done.” Timmy ends the active timer.
- “Pause reminders for 30 minutes.” Timmy keeps the timer open but stops nudging until the snooze expires.
- “That timer was a mistake.” Timmy cancels it without creating billable time.

If a timer was left open for hours or overnight, Timmy should ask you to resolve it before approving or exporting the day.

## Reviewing the day

At the end of the day, say:

> “Review today.”

Timmy should show draft, approved, and exported entries separately. Review before approval. If something is wrong, ask it to fix the draft entry first.

Useful review phrases:

- “Show me what is still draft.”
- “Change entry 3 to non-billable.”
- “Move entry 4 to Client B.”
- “Unapprove entry 2.”
- “Approve all of today.”

## Exporting

Only approved entries are exported.

Say:

> “Export approved time.”

You can also ask for a whole month or a span of days in one file — for example
“Export June” or “Export the 25th through the 5th” — and Timmy writes a single
CSV for the range. You still review and approve each day first; the range export
only includes time you already approved.

After export, Timmy should tell you how many entries were exported and where the file was written. Confirm that file before importing or handing it off.

The exported file has one row per approved entry with columns Date, Client, Job Type,
Notes, Duration, and Billable. "Notes" is the short description of what you worked on;
if you left it blank, Timmy gently reminds you when the timer stops and again at review,
but it never blocks you from approving.

There is no direct QuickBooks writeback in this pilot.

## Privacy boundaries

- Timmy keeps the working time file on this computer.
- It only creates draft entries from what you ask it to record.
- You approve entries before export.
- It does not silently bill, upload, or sync entries.
- Use synthetic data until Josh/helper confirms real pilot data is approved.

## If something feels off

- Say “Review today” before approving.
- Ask Timmy to edit the draft instead of deleting and recreating it.
- If a timer was started by mistake, say “Cancel the active session.”
- If you walked away and forgot to stop, say when you actually stopped and ask Timmy to close it there.
- If you are unsure where an export went, ask: “Show me the full export path.”

If the answer feels confusing, stop before approving or exporting and ask the helper to check it with you.
