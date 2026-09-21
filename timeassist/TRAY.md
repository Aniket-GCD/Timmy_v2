# Timmy Windows clock widget

Small always-on-top window for **this machine’s** Timmy session. Not inside Claude.
Mostly display-only — stop in Claude / Timmy, except the still-working check below.

## For everyone (recommended)

1. Open **Timmy Clock** from your **Desktop** or **Start Menu** (created the first time the clock runs successfully).
2. Or double-click **`TimmyClock.exe`** next to Timmy’s `.mcp.json` in the plugin folder (org install or zip).

First-time tip: open Claude and use Timmy once so the database exists, then start the clock. After that, use the Desktop shortcut. The first successful open also adds a **Startup** shortcut so Timmy Clock opens when Windows signs in (remove it from the Startup folder to disable).

Plain-language card: `plugin/timeassist/TimmyClock.txt`.

## What it shows

- Client name (wraps to a second line when long)
- Job code under the name; large **elapsed** time bottom-right
- Idle: `Not on the clock` with a red status dot
- Title bar: Timmy icon + “Timmy Clock” only

Polls Supabase `currently_working` about every 20 seconds.

## Still-working check

- At **2 hours** elapsed: system beep + topmost Yes/No prompt on TimmyClock. Yes or close without answering keeps tracking; No ends the local Timmy timer and clears the live ticker.
- At **8 hours**: the **Timmy plugin** auto-ends the session (`planned_end_at` hard cap). TimmyClock follows within ~20s when the live row clears.

## How TimmyClock.exe finds data

1. Loads `SUPABASE_URL` / `SUPABASE_KEY` from `.mcp.json` beside the exe, or from the org Timmy plugin under Claude’s session folders
2. Finds `timeassist.sqlite` under `%LOCALAPPDATA%\Timmy\`, then Claude Store  
   `%LOCALAPPDATA%\Packages\Claude_*\LocalCache\Local\Timmy\`, then beside the plugin
3. Uses local `staff_name` from that database
4. On success, copies itself to `%LOCALAPPDATA%\Timmy\TimmyClock.exe` and refreshes Desktop / Start Menu / Startup shortcuts

## Developers

```bash
python scripts/timeassist.py --db timeassist.sqlite tray
python scripts/package_executable.py   # builds dist/timeassist.exe + dist/TimmyClock.exe
```

Kit-root `Start Timmy Clock.vbs` is a thin fallback: prefers `TimmyClock.exe` in `plugin/timeassist/`, otherwise the old script launcher.
