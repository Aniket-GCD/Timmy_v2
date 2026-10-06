"""Always-on-top Windows clock widget for this machine's Timmy session.

Identity is local settings.staff_name (not a login). Polls currently_working
GET. At test thresholds: prompt at 2 min, force-stop local timer at 5 min.
"""

from __future__ import annotations

import re
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Literal

from . import actions
from . import currently_working
from .db import connect
from .supabase_config import currently_working_table
from .supabase_ref import request_json

POLL_SECONDS = 20
IDLE_LINE = "Not on the clock"
_TITLE_ICON_NAME = "2-timmyclock-title-bar-icon-32-green-on-transparent.ico"
_CLIENT_WRAP_PX = 280

# Prompt at 2h; hard stop backup at 8h (plugin planned_end is the authority).
PROMPT_AFTER_SECONDS = 2 * 60 * 60
FORCE_STOP_AFTER_SECONDS = 8 * 60 * 60

IdleCheckAction = Literal["none", "prompt", "force_stop"]

# GCD dashboard palette
_COLOR_BG = "#efeeed"
_COLOR_GREEN = "#0e5727"
_COLOR_TEXT = "#3e3e3e"
_COLOR_MUTED = "#6b6b6b"
_COLOR_ACCENT = "#fbdcdd"
_COLOR_DOT_LIVE = "#5f8b55"
_COLOR_DOT_IDLE = "#c62828"
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
            "job": "",
            "elapsed": "",
            "status": "idle",
        }
    client = (row.get("client") or "").strip() or "—"
    started = row.get("started_at")
    elapsed = (
        _fmt_hms(now - parse_wall_clock_at(started), clamp_negative=True) if started else "0:00"
    )
    job = (row.get("job_code") or "").strip() or "—"
    status = "live"
    planned = row.get("planned_end_at")
    if planned and (parse_wall_clock_at(planned) - now).total_seconds() < 0:
        status = "overdue"
    return {
        "client": client,
        "job": job,
        "elapsed": elapsed,
        "status": status,
    }


def session_elapsed_seconds(row: dict[str, Any] | None, now: datetime) -> int | None:
    """Wall-clock seconds since started_at, or None if idle/missing."""
    if not row or not row.get("started_at"):
        return None
    total = int((now - parse_wall_clock_at(row.get("started_at"))).total_seconds())
    return max(0, total)


def idle_check_action(elapsed_s: int | None, *, prompted: bool) -> IdleCheckAction:
    """Decide prompt / force-stop from elapsed seconds (test thresholds)."""
    if elapsed_s is None:
        return "none"
    if elapsed_s >= FORCE_STOP_AFTER_SECONDS:
        return "force_stop"
    if elapsed_s >= PROMPT_AFTER_SECONDS and not prompted:
        return "prompt"
    return "none"


def prompt_job_label(row: dict[str, Any] | None) -> str:
    if not row:
        return "this task"
    job = (row.get("job_code") or "").strip()
    if job:
        return job
    client = (row.get("client") or "").strip()
    return client or "this task"


def should_ignore_live_row(
    row: dict[str, Any] | None,
    stopped_started_at: str | None,
) -> bool:
    """True when poll returned the same session we already stopped from the clock."""
    if not row or not stopped_started_at:
        return False
    return row.get("started_at") == stopped_started_at


def local_open_clock_row(db_path: str | Path) -> dict[str, Any] | None:
    """Clock fields from the local active session when Supabase has no live row."""
    with connect(db_path) as conn:
        active = actions.get_active_session(conn)
    if not active:
        return None
    return {
        "client": active.get("client_name") or "",
        "job_code": active.get("job_type") or "",
        "started_at": active.get("started_at"),
        "planned_end_at": active.get("planned_end_at"),
        "status": "active",
        "staff_name": local_staff_name(db_path) or "",
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
    local = local_open_clock_row(db_path)
    staff = local_staff_name(db_path)
    if not staff:
        return local
    table = currently_working_table(db_path=db_path, environ=environ)
    try:
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
    except Exception:
        if local:
            return local
        raise
    if isinstance(rows, list) and rows:
        return rows[0]
    return local


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
    """End local timer if present and always clear the live currently_working row."""
    entry: dict[str, Any] | None = None
    try:
        entry = actions.end_session(db_path)
    except ValueError:
        entry = None
    try:
        currently_working.close_live(db_path, status="closed")
    except Exception:
        pass
    return entry


def _play_prompt_beep() -> None:
    try:
        import winsound

        winsound.MessageBeep()
    except Exception:
        pass


def _title_icon_path() -> Path | None:
    name = _TITLE_ICON_NAME
    candidates: list[Path] = []
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            candidates.append(Path(meipass) / "assets" / name)
        candidates.append(Path(sys.executable).resolve().parent / "assets" / name)
    here = Path(__file__).resolve().parent
    candidates.append(here.parent / "assets" / name)
    for path in candidates:
        if path.is_file():
            return path
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
    idle_state: dict[str, Any] = {
        "prompted_started_at": None,
        "force_done_started_at": None,
        "stopped_started_at": None,
        "dialog": None,
    }

    root = tk.Tk()
    root.title("Timmy Clock")
    root.attributes("-topmost", True)
    root.resizable(False, False)
    root.configure(bg=_COLOR_BG)
    root.geometry("360x110")
    icon = _title_icon_path()
    if icon is not None:
        try:
            root.iconbitmap(default=str(icon))
        except tk.TclError:
            pass

    _drag: dict[str, int] = {"x": 0, "y": 0}

    def start_drag(event: Any) -> None:
        _drag["x"] = event.x_root - root.winfo_x()
        _drag["y"] = event.y_root - root.winfo_y()

    def on_drag(event: Any) -> None:
        root.geometry(f"+{event.x_root - _drag['x']}+{event.y_root - _drag['y']}")

    frame = tk.Frame(root, bg=_COLOR_BG, padx=14, pady=6)
    frame.pack(fill="both", expand=True)
    for widget in (root, frame):
        widget.bind("<Button-1>", start_drag)
        widget.bind("<B1-Motion>", on_drag)

    body = tk.Frame(frame, bg=_COLOR_BG)
    body.pack(fill="both", expand=True)
    body.bind("<Button-1>", start_drag)
    body.bind("<B1-Motion>", on_drag)
    body.columnconfigure(1, weight=1)

    dot = tk.Canvas(body, width=12, height=12, bg=_COLOR_BG, highlightthickness=0)
    dot.grid(row=0, column=0, sticky="nw", padx=(0, 8), pady=(4, 0))
    dot_id = dot.create_oval(2, 2, 10, 10, fill=_COLOR_DOT_IDLE, outline="")

    right = tk.Frame(body, bg=_COLOR_BG)
    right.grid(row=0, column=1, sticky="nsew")
    right.bind("<Button-1>", start_drag)
    right.bind("<B1-Motion>", on_drag)

    client_var = tk.StringVar(value=IDLE_LINE)
    client_lbl = tk.Label(
        right,
        textvariable=client_var,
        font=("Segoe UI Semibold", 12),
        fg=_COLOR_TEXT,
        bg=_COLOR_BG,
        anchor="w",
        justify="left",
        wraplength=_CLIENT_WRAP_PX,
    )
    client_lbl.pack(fill="x", anchor="w")
    client_lbl.bind("<Button-1>", start_drag)
    client_lbl.bind("<B1-Motion>", on_drag)

    bottom = tk.Frame(right, bg=_COLOR_BG)
    bottom.pack(fill="x", pady=(2, 0))
    bottom.bind("<Button-1>", start_drag)
    bottom.bind("<B1-Motion>", on_drag)

    job_var = tk.StringVar(value="")
    job_lbl = tk.Label(
        bottom,
        textvariable=job_var,
        font=("Segoe UI", 9),
        fg=_COLOR_MUTED,
        bg=_COLOR_BG,
        anchor="w",
    )
    job_lbl.pack(side="left", fill="x", expand=True)
    job_lbl.bind("<Button-1>", start_drag)
    job_lbl.bind("<B1-Motion>", on_drag)

    elapsed_var = tk.StringVar(value="")
    elapsed_lbl = tk.Label(
        bottom,
        textvariable=elapsed_var,
        font=("Segoe UI Semibold", 16),
        fg=_COLOR_GREEN,
        bg=_COLOR_BG,
        anchor="e",
    )
    elapsed_lbl.pack(side="right")
    elapsed_lbl.bind("<Button-1>", start_drag)
    elapsed_lbl.bind("<B1-Motion>", on_drag)

    footer = tk.Frame(frame, bg=_COLOR_BG)
    footer.pack(fill="x", pady=(4, 0))

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
        job_var.set(display.get("job") or "")
        elapsed_var.set(display["elapsed"])
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

    def show_idle_ui() -> None:
        cache["row"] = None
        apply_display(
            {"client": IDLE_LINE, "job": "", "elapsed": "", "status": "idle"},
            offline=False,
        )
        set_banner("")

    def dismiss_prompt() -> None:
        dlg = idle_state.get("dialog")
        idle_state["dialog"] = None
        if dlg is not None:
            try:
                dlg.destroy()
            except tk.TclError:
                pass

    def apply_stop(started_at: str | None = None) -> None:
        dismiss_prompt()
        if started_at:
            idle_state["stopped_started_at"] = started_at
            idle_state["force_done_started_at"] = started_at
            idle_state["prompted_started_at"] = started_at
        stop_session(path)
        show_idle_ui()

    def open_still_working_prompt(row: dict[str, Any]) -> None:
        if idle_state.get("dialog") is not None:
            return
        started = row.get("started_at")
        job = prompt_job_label(row)
        dlg = tk.Toplevel(root)
        idle_state["dialog"] = dlg
        dlg.title("Timmy Clock")
        dlg.attributes("-topmost", True)
        dlg.resizable(False, False)
        dlg.configure(bg=_COLOR_BG)
        dlg.transient(root)

        msg = (
            f"2 hours has elapsed since you started your timer for {job}. "
            "Are you still working on the same task?"
        )
        tk.Label(
            dlg,
            text=msg,
            font=("Segoe UI", 10),
            fg=_COLOR_TEXT,
            bg=_COLOR_BG,
            wraplength=320,
            justify="left",
            padx=16,
            pady=14,
        ).pack(fill="x")

        btns = tk.Frame(dlg, bg=_COLOR_BG, padx=16)
        btns.pack(fill="x", pady=(0, 14))

        def mark_prompted() -> None:
            idle_state["prompted_started_at"] = started

        def on_yes() -> None:
            mark_prompted()
            dismiss_prompt()

        def on_no() -> None:
            mark_prompted()
            apply_stop(started)

        def on_close() -> None:
            # X / no answer — keep tracking; do not re-prompt this session.
            mark_prompted()
            dismiss_prompt()

        tk.Button(btns, text="Yes", width=10, command=on_yes).pack(side="right", padx=(8, 0))
        tk.Button(btns, text="No", width=10, command=on_no).pack(side="right")
        dlg.protocol("WM_DELETE_WINDOW", on_close)
        dlg.update_idletasks()
        # Fixed size — winfo_reqheight under-reports on Windows DPI and clips Yes/No.
        dlg.minsize(420, 200)
        dlg.geometry("420x200")
        try:
            dlg.lift()
            dlg.focus_force()
        except tk.TclError:
            pass
        _play_prompt_beep()

    def sync_idle_flags_for_row(row: dict[str, Any] | None) -> None:
        """Clear prompt/force flags only when started_at changes to a new session.

        Do not clear stopped_started_at / force_done just because cache row is
        briefly None after a stop (that would let the next poll revive it).
        """
        if row is None:
            dismiss_prompt()
            return
        started = row.get("started_at")
        stopped = idle_state.get("stopped_started_at")
        if stopped and started and started != stopped:
            idle_state["stopped_started_at"] = None
        if idle_state.get("prompted_started_at") not in (None, started):
            idle_state["prompted_started_at"] = None
            dismiss_prompt()
        if idle_state.get("force_done_started_at") not in (None, started):
            idle_state["force_done_started_at"] = None

    def accept_live_row(row: dict[str, Any] | None) -> dict[str, Any] | None:
        if should_ignore_live_row(row, idle_state.get("stopped_started_at")):
            return None
        if row is None and idle_state.get("stopped_started_at"):
            # True idle from server — clear revive guard for the next timer.
            idle_state["stopped_started_at"] = None
        return row

    def refresh_network() -> None:
        snap = snapshot(path)
        staff = snap["staff_name"]
        if not staff:
            set_banner("Open Timmy in Claude and set staff name, then reopen.")
            apply_display(
                {"client": IDLE_LINE, "job": "", "elapsed": "", "status": "idle"},
                offline=False,
            )
            cache["row"] = None
            sync_idle_flags_for_row(None)
            root.after(poll_seconds * 1000, refresh_network)
            return
        if snap["error"] and not snap["row"]:
            cache["offline"] = True
            if cache["row"]:
                display = clock_display(cache["row"], datetime.now().replace(microsecond=0))
                apply_display(display, offline=True)
                set_banner("Offline — showing last known session")
            else:
                apply_display(
                    {"client": IDLE_LINE, "job": "", "elapsed": "", "status": "idle"},
                    offline=True,
                )
                set_banner("Offline — check your connection")
        else:
            cache["offline"] = False
            row = accept_live_row(snap["row"])
            cache["row"] = row
            if row is None:
                show_idle_ui()
            else:
                apply_display(clock_display(row, datetime.now().replace(microsecond=0)), offline=False)
                set_banner("")
            sync_idle_flags_for_row(row)
        root.after(poll_seconds * 1000, refresh_network)

    def tick() -> None:
        now = datetime.now().replace(microsecond=0)
        row = cache.get("row")
        if row is not None:
            if should_ignore_live_row(row, idle_state.get("stopped_started_at")):
                show_idle_ui()
                root.after(1000, tick)
                return
            display = clock_display(row, now)
            apply_display(display, offline=bool(cache["offline"]))
            if cache["offline"]:
                set_banner("Offline — showing last known session")

            started = row.get("started_at")
            prompted = idle_state.get("prompted_started_at") == started
            elapsed_s = session_elapsed_seconds(row, now)
            action = idle_check_action(elapsed_s, prompted=prompted)

            if action == "force_stop":
                if idle_state.get("force_done_started_at") != started:
                    apply_stop(started)
            elif action == "prompt":
                open_still_working_prompt(row)
        else:
            sync_idle_flags_for_row(None)
        root.after(1000, tick)

    refresh_network()
    tick()
    root.mainloop()
    return 0
