"""Best-effort live-row sync for currently_working. Never writes time_entries.

Network/auth/table-missing failures are swallowed by callers so the local timer
stays the billing authority. This table is a dashboard/tray ticker only.
"""

from __future__ import annotations

import threading
from datetime import datetime
from pathlib import Path
from typing import Any

from .db import connect
from .supabase_config import currently_working_table
from .supabase_ref import request_json

_auto_end_timer: threading.Timer | None = None


def _staff_office(db_path: str | Path) -> tuple[str, str] | None:
    with connect(db_path) as conn:
        settings = {
            row["setting_key"]: row["setting_value"]
            for row in conn.execute("SELECT setting_key, setting_value FROM settings")
        }
    staff = (settings.get("staff_name") or "").strip()
    office = (settings.get("office") or "").strip().upper()
    if not staff or office not in {"GCD", "MH"}:
        return None
    return staff, office


def _live_payload(session: dict[str, Any], staff_name: str, office: str, *, status: str) -> dict[str, Any]:
    notes = (session.get("task_text") or "").strip()
    job = (session.get("job_type") or "").strip() or None
    payload: dict[str, Any] = {
        "staff_name": staff_name,
        "office": office,
        "client": session.get("client_name") or "",
        "job_code": job,
        "notes": notes or None,
        "task": notes or None,
        "started_at": session.get("started_at"),
        "planned_end_at": session.get("planned_end_at") or None,
        "status": status,
        "local_session_id": str(session["session_id"]) if session.get("session_id") is not None else None,
        "updated_at": session.get("updated_at") or session.get("started_at"),
    }
    return payload


def upsert_active(
    db_path: str | Path,
    session: dict[str, Any],
    *,
    environ: dict[str, str] | None = None,
) -> None:
    identity = _staff_office(db_path)
    if not identity or not session:
        return
    staff_name, office = identity
    table = currently_working_table(db_path=db_path, environ=environ)
    body = _live_payload(session, staff_name, office, status="active")
    existing = request_json(
        "GET",
        table,
        query={
            "select": "id",
            "staff_name": f"eq.{staff_name}",
            "status": "eq.active",
            "limit": "1",
        },
        environ=environ,
        timeout=8,
    )
    if isinstance(existing, list) and existing and existing[0].get("id") is not None:
        request_json(
            "PATCH",
            table,
            body=body,
            query={"id": f"eq.{existing[0]['id']}"},
            environ=environ,
            timeout=8,
            prefer="return=minimal",
        )
        return
    request_json(
        "POST",
        table,
        body=body,
        environ=environ,
        timeout=8,
        prefer="return=minimal",
    )


def close_live(
    db_path: str | Path,
    *,
    status: str = "closed",
    updated_at: str | None = None,
    environ: dict[str, str] | None = None,
) -> None:
    identity = _staff_office(db_path)
    if not identity:
        return
    staff_name, _office = identity
    table = currently_working_table(db_path=db_path, environ=environ)
    body: dict[str, Any] = {"status": status}
    if updated_at:
        body["updated_at"] = updated_at
    request_json(
        "PATCH",
        table,
        body=body,
        query={"staff_name": f"eq.{staff_name}", "status": "eq.active"},
        environ=environ,
        timeout=8,
        prefer="return=minimal",
    )


def cancel_auto_end() -> None:
    global _auto_end_timer
    timer = _auto_end_timer
    _auto_end_timer = None
    if timer is not None:
        timer.cancel()


def schedule_auto_end(db_path: str | Path, planned_end_at: str | None) -> None:
    """Wall-clock timer. Skips if planned end is already in the past (heartbeat handles that)."""
    cancel_auto_end()
    if not planned_end_at:
        return
    from .actions import parse_at

    delay = (parse_at(planned_end_at) - datetime.now().replace(microsecond=0)).total_seconds()
    if delay <= 0:
        return
    path = str(db_path)

    def _fire() -> None:
        from . import actions as _actions

        try:
            _actions.maybe_end_overdue_planned(path)
        except Exception:
            pass

    timer = threading.Timer(delay, _fire)
    timer.daemon = True
    global _auto_end_timer
    _auto_end_timer = timer
    timer.start()
