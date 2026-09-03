# Timmy Windows clock widget

Always-on-top companion next to Timmy. It is **not** inside Claude and does **not** use a staff login.

Identity is this machine’s local Timmy `staff_name` (same setting used on submit).

## What it shows

- On the clock: client + elapsed hours:minutes, plus countdown to `planned_end_at` when Timmy set a planned duration.
- Idle: `Not on the clock`.
- **Stop**: local `end_session` (draft in SQLite). Existing Timmy sync then closes `currently_working`. Never auto-submits to `time_entries_timmy_v2`.

Polls `currently_working` every 20 seconds (GET only). Also runs the local planned-end heartbeat so a missed auto-stop can close at `planned_end_at` while the widget is open.

## Run

Same env as Timmy (`SUPABASE_URL`, `SUPABASE_KEY` or `SUPABASE_ANON_KEY` / `SUPABASE_SECRET`). Point `--db` at the same SQLite Timmy uses.

From the kit root:

```bash
python scripts/timeassist.py --db timeassist.sqlite tray
```

Plugin data dir (Cowork):

```bash
python scripts/timeassist.py --db "%CLAUDE_PLUGIN_DATA%\timeassist.sqlite" tray
```

Optional: `--interval 15` (seconds; 15–30 is the intended range).

Requires Windows Python with tkinter (the usual python.org installer). No extra packages.

Set `staff_name` first if the widget shows `(set staff_name in Timmy config)`:

```bash
python scripts/timeassist.py --db timeassist.sqlite config --staff-name "Hannah Curtis" --office GCD --confirm
```
