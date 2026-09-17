"""Always-on-top Windows clock widget for this machine's Timmy session.

Identity is local settings.staff_name (not a login). Polls currently_working
GET. Display-only — stop the timer in Claude/Timmy, not here.
"""

from __future__ import annotations

import re
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

# GCD dashboard palette
_COLOR_BG = "#efeeed"
_COLOR_GREEN = "#0e5727"
_COLOR_TEXT = "#3e3e3e"
_COLOR_MUTED = "#6b6b6b"
_COLOR_ACCENT = "#fbdcdd"
_COLOR_BORDER = "#d8d6d3"
_COLOR_DOT_LIVE = "#5f8b55"
_COLOR_DOT_IDLE = "#b0aea9"
_COLOR_DOT_WARN = "#c45c26"

# Mirror dashboard parseLocalStartMs: strip Z / ±offset, treat digits as local.
_OFFSET_RE = re.compile(r"[+-]\d{2}:?\d{2}$")


def local_staff_name(db_path: str | Path) -> str | None:
    identity = currently_working._staff_office(db_path)
    if identity:
        return identity[0]
    with connect(db_path) as conn:
        name = (actions.get_setting(conn, "staff_name") or "").strip()
    return name or None


def parse_wall_clock_at(value: str | None) -> datetime:
    """Parse started_at / planned_end_at as local wall-clock (dashboard parity).

    Does not change billing ``parse_at`` — only clock display math.
    """
    if not value:
        return datetime.now().replace(microsecond=0)
    naive = value.strip()
    if naive.endswith("Z") or naive.endswith("z"):
        naive = naive[:-1]
    naive = _OFFSET_RE.sub("", naive)
    parsed = datetime.fromisoformat(naive)
    if parsed.tzinfo is not None:
        parsed = parsed.replace(tzinfo=None)
    return parsed.replace(microsecond=0)


def _fmt_hms(delta: timedelta, *, clamp_negative: bool = False) -> str:
    total = int(delta.total_seconds())
    if clamp_negative and total < 0:
        total = 0
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
    elapsed = (
        _fmt_hms(now - parse_wall_clock_at(started), clamp_negative=True) if started else "0:00"
    )
    line = f"{client}  {elapsed}"
    planned = row.get("planned_end_at")
    if planned:
        remain = parse_wall_clock_at(planned) - now
        if remain.total_seconds() < 0:
            line += f"  overdue {_fmt_hms(remain)}"
        else:
            line += f"  {_fmt_hms(remain)} left"
    return line


def clock_display(row: dict[str, Any] | None, now: datetime) -> dict[str, str]:
    """Structured fields for the branded UI (line kept for tests/CLI)."""
    if not row:
        return {
            "client": IDLE_LINE,
            "elapsed": "",
            "secondary": "",
            "status": "idle",
        }
    client = (row.get("client") or "").strip() or "—"
    started = row.get("started_at")
    elapsed = (
        _fmt_hms(now - parse_wall_clock_at(started), clamp_negative=True) if started else "0:00"
    )
    secondary = ""
    status = "live"
    job = (row.get("job_code") or "").strip()
    planned = row.get("planned_end_at")
    if planned:
        remain = parse_wall_clock_at(planned) - now
        if remain.total_seconds() < 0:
            secondary = f"Overdue {_fmt_hms(remain)}"
            status = "overdue"
        else:
            secondary = f"{_fmt_hms(remain)} left"
    if job:
        secondary = f"{job}  ·  {secondary}" if secondary else job
    return {
        "client": client,
        "elapsed": elapsed,
        "secondary": secondary,
        "status": status,
    }


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
    display = clock_display(row, wall)
    return {
        "staff_name": staff,
        "row": row,
        "line": format_clock_line(row, wall),
        "display": display,
        "error": err,
        "can_stop": False,
    }


def stop_session(db_path: str | Path) -> dict[str, Any] | None:
    """End the local timer (draft). Kept for CLI/tests; widget is display-only."""
    try:
        return actions.end_session(db_path)
    except ValueError:
        return None


def _show_setup_window(message: str) -> int:
    try:
        import tkinter as tk
        from tkinter import messagebox
    except ImportError:
        print(message)
        return 1
    root = tk.Tk()
    root.withdraw()
    messagebox.showerror("Timmy Clock", message)
    root.destroy()
    return 1


def run_widget(
    db_path: str | Path | None = None,
    *,
    poll_seconds: int = POLL_SECONDS,
    setup_error: str | None = None,
) -> int:
    try:
        import tkinter as tk
    except ImportError:
        print("tkinter is required for the clock widget (bundled with Windows Python).")
        return 1

    if setup_error:
        return _show_setup_window(setup_error)
    if db_path is None:
        return _show_setup_window("Timmy Clock has no database path.")

    path = str(db_path)
    cache: dict[str, Any] = {"row": None, "offline": False, "banner": ""}

    root = tk.Tk()
    root.title("Timmy Clock")
    root.attributes("-topmost", True)
    root.resizable(False, False)
    root.configure(bg=_COLOR_BG)
    root.geometry("360x108")

    _drag: dict[str, int] = {"x": 0, "y": 0}

    def start_drag(event: Any) -> None:
        _drag["x"] = event.x_root - root.winfo_x()
        _drag["y"] = event.y_root - root.winfo_y()

    def on_drag(event: Any) -> None:
        root.geometry(f"+{event.x_root - _drag['x']}+{event.y_root - _drag['y']}")

    frame = tk.Frame(root, bg=_COLOR_BG, padx=14, pady=10)
    frame.pack(fill="both", expand=True)
    for widget in (root, frame):
        widget.bind("<Button-1>", start_drag)
        widget.bind("<B1-Motion>", on_drag)

    header = tk.Frame(frame, bg=_COLOR_BG)
    header.pack(fill="x")
    header.bind("<Button-1>", start_drag)
    header.bind("<B1-Motion>", on_drag)

    brand = tk.Label(
        header,
        text="TIMMY",
        font=("Segoe UI Semibold", 9),
        fg=_COLOR_GREEN,
        bg=_COLOR_BG,
        anchor="w",
    )
    brand.pack(side="left")
    brand.bind("<Button-1>", start_drag)
    brand.bind("<B1-Motion>", on_drag)

    staff_var = tk.StringVar(value="")
    staff_lbl = tk.Label(
        header,
        textvariable=staff_var,
        font=("Segoe UI", 8),
        fg=_COLOR_MUTED,
        bg=_COLOR_BG,
        anchor="e",
    )
    staff_lbl.pack(side="right")
    staff_lbl.bind("<Button-1>", start_drag)
    staff_lbl.bind("<B1-Motion>", on_drag)

    body = tk.Frame(frame, bg=_COLOR_BG)
    body.pack(fill="x", pady=(6, 0))
    body.bind("<Button-1>", start_drag)
    body.bind("<B1-Motion>", on_drag)

    dot = tk.Canvas(body, width=12, height=12, bg=_COLOR_BG, highlightthickness=0)
    dot.pack(side="left", padx=(0, 8))
    dot_id = dot.create_oval(2, 2, 10, 10, fill=_COLOR_DOT_IDLE, outline="")

    client_var = tk.StringVar(value=IDLE_LINE)
    client_lbl = tk.Label(
        body,
        textvariable=client_var,
        font=("Segoe UI Semibold", 12),
        fg=_COLOR_TEXT,
        bg=_COLOR_BG,
        anchor="w",
    )
    client_lbl.pack(side="left", fill="x", expand=True)
    client_lbl.bind("<Button-1>", start_drag)
    client_lbl.bind("<B1-Motion>", on_drag)

    elapsed_var = tk.StringVar(value="")
    elapsed_lbl = tk.Label(
        body,
        textvariable=elapsed_var,
        font=("Segoe UI Semibold", 16),
        fg=_COLOR_GREEN,
        bg=_COLOR_BG,
        anchor="e",
    )
    elapsed_lbl.pack(side="right")
    elapsed_lbl.bind("<Button-1>", start_drag)
    elapsed_lbl.bind("<B1-Motion>", on_drag)

    secondary_var = tk.StringVar(value="")
    secondary_lbl = tk.Label(
        frame,
        textvariable=secondary_var,
        font=("Segoe UI", 9),
        fg=_COLOR_MUTED,
        bg=_COLOR_BG,
        anchor="w",
    )
    secondary_lbl.pack(fill="x", pady=(2, 0))
    secondary_lbl.bind("<Button-1>", start_drag)
    secondary_lbl.bind("<B1-Motion>", on_drag)

    footer = tk.Frame(frame, bg=_COLOR_BG)
    footer.pack(fill="x", pady=(6, 0))

    banner_var = tk.StringVar(value="")
    banner_lbl = tk.Label(
        footer,
        textvariable=banner_var,
        font=("Segoe UI", 8),
        fg=_COLOR_GREEN,
        bg=_COLOR_ACCENT,
        anchor="w",
        padx=6,
        pady=2,
    )

    def set_dot(color: str) -> None:
        dot.itemconfig(dot_id, fill=color)

    def apply_display(display: dict[str, str], *, offline: bool) -> None:
        client_var.set(display["client"])
        elapsed_var.set(display["elapsed"])
        secondary_var.set(display["secondary"])
        status = display["status"]
        if offline:
            set_dot(_COLOR_DOT_WARN)
        elif status == "live":
            set_dot(_COLOR_DOT_LIVE)
        elif status == "overdue":
            set_dot(_COLOR_DOT_WARN)
        else:
            set_dot(_COLOR_DOT_IDLE)

    def set_banner(text: str) -> None:
        cache["banner"] = text
        if text:
            banner_var.set(text)
            if not banner_lbl.winfo_ismapped():
                banner_lbl.pack(side="left", fill="x", expand=True)
        else:
            banner_var.set("")
            if banner_lbl.winfo_ismapped():
                banner_lbl.pack_forget()

    def refresh_network() -> None:
        snap = snapshot(path)
        staff = snap["staff_name"]
        if not staff:
            staff_var.set("Set your name in Timmy")
            set_banner("Open Timmy in Claude and set staff name, then reopen.")
            apply_display(
                {"client": IDLE_LINE, "elapsed": "", "secondary": "", "status": "idle"},
                offline=False,
            )
            cache["row"] = None
            root.after(poll_seconds * 1000, refresh_network)
            return
        staff_var.set(staff)
        if snap["error"] and not snap["row"]:
            cache["offline"] = True
            if cache["row"]:
                display = clock_display(cache["row"], datetime.now().replace(microsecond=0))
                apply_display(display, offline=True)
                set_banner("Offline — showing last known session")
            else:
                apply_display(
                    {"client": IDLE_LINE, "elapsed": "", "secondary": "", "status": "idle"},
                    offline=True,
                )
                set_banner("Offline — check your connection")
        else:
            cache["offline"] = False
            cache["row"] = snap["row"]
            apply_display(snap["display"], offline=False)
            set_banner("")
        root.after(poll_seconds * 1000, refresh_network)

    def tick() -> None:
        if cache["row"] is not None:
            display = clock_display(cache["row"], datetime.now().replace(microsecond=0))
            apply_display(display, offline=bool(cache["offline"]))
            if cache["offline"]:
                set_banner("Offline — showing last known session")
        root.after(1000, tick)

    tk.Frame(root, bg=_COLOR_BORDER, height=1).pack(fill="x", side="bottom")

    refresh_network()
    tick()
    root.mainloop()
    return 0
