"""Always-on-top Windows clock widget for this machine's Timmy session.

Identity is local settings.staff_name (not a login). Polls currently_working
GET; Stop calls local end_session (draft + existing live-row close).
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from . import actions
from . import currently_working
from .db import connect
from .supabase_config import currently_working_table
from .supabase_ref import request_json

POLL_SECONDS = 20
IDLE_LINE = "Not on the clock"


def local_staff_name(db_path: str | Path) -> str | None:
    identity = currently_working._staff_office(db_path)
    if identity:
        return identity[0]
    with connect(db_path) as conn:
        name = (actions.get_setting(conn, "staff_name") or "").strip()
    return name or None


def _fmt_hms(delta: timedelta) -> str:
    total = int(delta.total_seconds())
    sign = "-" if total < 0 else ""
    total = abs(total)
    hours, rem = divmod(total, 3600)
    minutes, _sec = divmod(rem, 60)
    return f"{sign}{hours}:{minutes:02d}"


def format_clock_line(row: dict[str, Any] | None, now: datetime) -> str:
    if not row:
        return IDLE_LINE
    client = (row.get("client") or "").strip() or "—"
    started = row.get("started_at")
    elapsed = _fmt_hms(now - actions.parse_at(started)) if started else "0:00"
    line = f"{client}  {elapsed}"
    planned = row.get("planned_end_at")
    if planned:
        remain = actions.parse_at(planned) - now
        if remain.total_seconds() < 0:
            line += f"  overdue {_fmt_hms(remain)}"
        else:
            line += f"  {_fmt_hms(remain)} left"
    return line


def fetch_live_row(
    db_path: str | Path,
    *,
    environ: dict[str, str] | None = None,
) -> dict[str, Any] | None:
    try:
        actions.maybe_end_overdue_planned(db_path)
    except Exception:
        pass
    staff = local_staff_name(db_path)
    if not staff:
        return None
    table = currently_working_table(db_path=db_path, environ=environ)
    rows = request_json(
        "GET",
        table,
        query={
            "select": "client,job_code,started_at,planned_end_at,status,staff_name",
            "staff_name": f"eq.{staff}",
            "status": "eq.active",
            "limit": "1",
        },
        environ=environ,
        timeout=8,
    )
    if not isinstance(rows, list) or not rows:
        return None
    return rows[0]


def snapshot(
    db_path: str | Path,
    *,
    now: datetime | None = None,
    environ: dict[str, str] | None = None,
) -> dict[str, Any]:
    staff = local_staff_name(db_path)
    wall = now or datetime.now().replace(microsecond=0)
    try:
        row = fetch_live_row(db_path, environ=environ)
        err = None
    except Exception as exc:
        row = None
        err = str(exc)
    return {
        "staff_name": staff,
        "row": row,
        "line": format_clock_line(row, wall),
        "error": err,
        "can_stop": row is not None,
    }


def stop_session(db_path: str | Path) -> dict[str, Any] | None:
    """End the local timer (draft). end_session already closes currently_working."""
    try:
        return actions.end_session(db_path)
    except ValueError:
        return None


def run_widget(db_path: str | Path, *, poll_seconds: int = POLL_SECONDS) -> int:
    try:
        import tkinter as tk
    except ImportError:
        print("tkinter is required for the clock widget (bundled with Windows Python).")
        return 1

    path = str(db_path)
    cache: dict[str, Any] = {"row": None}

    root = tk.Tk()
    root.title("Timmy")
    root.attributes("-topmost", True)
    root.resizable(False, False)
    root.geometry("320x88")

    staff_var = tk.StringVar(value="")
    line_var = tk.StringVar(value=IDLE_LINE)

    tk.Label(root, textvariable=staff_var, font=("Segoe UI", 9), anchor="w").pack(
        fill="x", padx=10, pady=(8, 0)
    )
    tk.Label(root, textvariable=line_var, font=("Segoe UI", 12, "bold"), anchor="w").pack(
        fill="x", padx=10, pady=4
    )

    def refresh_network() -> None:
        snap = snapshot(path)
        staff = snap["staff_name"] or "(set staff_name in Timmy config)"
        staff_var.set(staff)
        if snap["error"] and not snap["row"]:
            if cache["row"]:
                line_var.set(format_clock_line(cache["row"], datetime.now().replace(microsecond=0)) + "  (offline)")
            else:
                line_var.set(f"{IDLE_LINE}  (offline)")
        else:
            cache["row"] = snap["row"]
            line_var.set(snap["line"])
        root.after(poll_seconds * 1000, refresh_network)

    def tick() -> None:
        line_var.set(format_clock_line(cache["row"], datetime.now().replace(microsecond=0)))
        root.after(1000, tick)

    def on_stop() -> None:
        stop_session(path)
        cache["row"] = None
        line_var.set(IDLE_LINE)

    tk.Button(root, text="Stop", command=on_stop, width=10).pack(pady=(0, 8))
    refresh_network()
    tick()
    root.mainloop()
    return 0
