# Timmy Windows clock widget

Small always-on-top window for **this machine’s** Timmy session. Not inside Claude.
**Display only** — stop the timer in Claude / Timmy, not on the widget.

## For everyone (recommended)

1. Open **Timmy Clock** from your **Desktop** or **Start Menu** (created the first time the clock runs successfully).
2. Or double-click **`TimmyClock.exe`** next to Timmy’s `.mcp.json` in the plugin folder (org install or zip).

First-time tip: open Claude and use Timmy once so the database exists, then start the clock. After that, use the Desktop shortcut.

Plain-language card: `plugin/timeassist/TimmyClock.txt`.

## What it shows

- On the clock: client + large **elapsed** time (local wall-clock, same as the dashboard)
- Countdown when a planned end is set
- Idle: `Not on the clock`

Polls Supabase `currently_working` about every 20 seconds.

## How TimmyClock.exe finds data

1. Loads `SUPABASE_URL` / `SUPABASE_KEY` from `.mcp.json` beside the exe, or from the org Timmy plugin under Claude’s session folders
2. Finds `timeassist.sqlite` under `%LOCALAPPDATA%\Timmy\`, then Claude Store  
   `%LOCALAPPDATA%\Packages\Claude_*\LocalCache\Local\Timmy\`, then beside the plugin
3. Uses local `staff_name` from that database
4. On success, copies itself to `%LOCALAPPDATA%\Timmy\TimmyClock.exe` and refreshes Desktop / Start Menu shortcuts

## Developers

```bash
python scripts/timeassist.py --db timeassist.sqlite tray
python scripts/package_executable.py   # builds dist/timeassist.exe + dist/TimmyClock.exe
```

Kit-root `Start Timmy Clock.vbs` is a thin fallback: prefers `TimmyClock.exe` in `plugin/timeassist/`, otherwise the old script launcher.
