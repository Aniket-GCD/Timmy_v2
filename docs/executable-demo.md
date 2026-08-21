# Executable Demo Walkthrough

TimeAssist can be packaged as a platform-native executable for a stakeholder walkthrough. This is still a local prototype: it uses synthetic data, writes local files, and stops at human-reviewed export artifacts.

## Build

```bash
python scripts/package_executable.py
```

The build output is platform-native:

- Linux/macOS: `dist/timeassist`
- Windows: `dist/timeassist.exe`

A Linux build does not create a Windows `.exe`. Build on Windows or add CI release builds when the stakeholder needs a Windows binary.

## Run the packaged stakeholder flow

```bash
./dist/timeassist demo --output demo/generated-exe
```

Then open:

```text
demo/generated-exe/stakeholder-review.html
```

The same executable can also run the lower-level capture commands:

```bash
./dist/timeassist init
./dist/timeassist start --client "Client A" --task "monthly cleanup" --billable yes
./dist/timeassist switch --client "Client B" --task "tax question" --billable yes --minutes-ago 20
./dist/timeassist checkin-status
./dist/timeassist snooze-checkin --minutes 30
./dist/timeassist end
./dist/timeassist review --date today --format html --output review-today.html
# Copy or refresh REVIEW_TOKEN from each review output before approving/exporting.
./dist/timeassist approve --entry-id 1 --review-token "$REVIEW_TOKEN"
./dist/timeassist review --date today
./dist/timeassist export --date today --format quickbooks-csv --output quickbooks-time-today.csv --review-token "$REVIEW_TOKEN"
```

## Stakeholder talk track

1. Run `timeassist demo` from the packaged binary.
2. Open the branded HTML review.
3. Point out that entries begin as drafts.
4. Show the context-switch correction path: "I switched 20 minutes ago" closes the prior timer at the honest transition time.
5. Show that check-in reminders are self-report prompts, not screen monitoring.
6. Show that only approved entries export.
7. Show the privacy boundary: no screen recording, no keystroke capture, no direct QuickBooks writeback in v1.
8. Ask the pilot decisions:
   - Which data classes are approved?
   - Which billing increment and rounding rule should v1 enforce?
   - Which QuickBooks handoff route should the first export target?
   - Who is the first pilot user?

## Privacy boundary

Do not use real client names, copied emails, QuickBooks exports, credentials, internal URLs, or private work context in this demo unless the stakeholder has explicitly approved those data classes for a pilot.
