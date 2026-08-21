"""POST one approved local time_entries row to Supabase. No live calls from tests."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from . import actions
from .db import connect
from .supabase_ref import account_for_job_code, get_job_codes, request_json


def _clock_parts(iso_ts: str) -> tuple[str, str]:
    """Split local ISO start/end into entry_date + start_time/end_time (HH:MM:SS)."""
    stamp = (iso_ts or "").strip()
    if "T" in stamp:
        date_part, time_part = stamp.split("T", 1)
    elif " " in stamp:
        date_part, time_part = stamp.split(" ", 1)
    else:
        raise ValueError("entry is missing a start/end timestamp")
    time_part = time_part.split("+", 1)[0].split("Z", 1)[0]
    if len(time_part) == 5:
        time_part = time_part + ":00"
    if len(time_part) < 8:
        raise ValueError("entry times must include hours and minutes")
    return date_part[:10], time_part[:8]


def time_entry_payload(
    entry: dict[str, Any],
    *,
    staff_name: str,
    office: str,
    account: str,
) -> dict[str, Any]:
    notes = (entry.get("task_text") or "").strip()
    job_code = (entry.get("job_type") or "").strip()
    entry_date, start_time = _clock_parts(entry["start_at"])
    _, end_time = _clock_parts(entry["end_at"])
    minutes = int(entry["rounded_minutes"])
    return {
        "staff_name": staff_name,
        "office": office,
        "client": entry.get("client_name") or "",
        "job_code": job_code,
        "account": account,
        "notes": notes,
        "task": notes,
        "entry_date": entry_date,
        "start_time": start_time,
        "end_time": end_time,
        "hours": minutes / 60,
        "billable": bool(entry.get("billable")),
        "source_file": "timmy",
    }


def submit_entry(
    db_path: str | Path,
    entry_id: int,
    *,
    environ: dict[str, str] | None = None,
    at: str | None = None,
) -> dict[str, Any]:
    """POST one locally approved entry. Idempotent via submitted_at. Never invent times."""
    actions.ensure_initialized(db_path)
    changed_at = actions.iso(actions.parse_at(at)) if at else actions.now_iso()
    with connect(db_path) as conn:
        settings = {row["setting_key"]: row["setting_value"] for row in conn.execute("SELECT setting_key, setting_value FROM settings")}
        staff_name = actions.normalize_staff_name(settings.get("staff_name") or "")
        office = actions.normalize_office(settings.get("office") or "")
        row = conn.execute("SELECT * FROM time_entries WHERE entry_id = ?", (entry_id,)).fetchone()
        if row is None:
            raise ValueError(f"unknown entry {entry_id}")
        entry = actions.row_to_dict(row)
        if entry.get("submitted_at"):
            return {
                "entry_id": entry_id,
                "submitted": True,
                "skipped": True,
                "reason": "already submitted",
                "submitted_at": entry["submitted_at"],
            }
        status = entry.get("review_status")
        if status != "approved":
            raise ValueError(
                f"entry {entry_id} is {status}; submit only after local approve (never submit a draft)"
            )
        job_code = (entry.get("job_type") or "").strip()
        if not job_code:
            raise ValueError("set a Job Code before submit; account is copied from job_codes, never typed")
        codes = get_job_codes(environ=environ)
        account = account_for_job_code(job_code, codes)
        payload = time_entry_payload(entry, staff_name=staff_name, office=office, account=account)
        request_json("POST", "time_entries", body=payload, environ=environ)
        conn.execute(
            "UPDATE time_entries SET submitted_at = ?, updated_at = ? WHERE entry_id = ?",
            (changed_at, changed_at, entry_id),
        )
        actions.log_event(
            conn,
            "submit",
            f"submitted entry {entry_id} to Supabase",
            "time_entry",
            entry_id,
            before={"review_status": status, "submitted_at": None},
            after={"submitted_at": changed_at},
            at=changed_at,
        )
        conn.commit()
    return {
        "entry_id": entry_id,
        "submitted": True,
        "skipped": False,
        "submitted_at": changed_at,
        "payload_preview": {
            "client": payload["client"],
            "job_code": payload["job_code"],
            "account": payload["account"],
            "entry_date": payload["entry_date"],
            "start_time": payload["start_time"],
            "end_time": payload["end_time"],
            "hours": payload["hours"],
        },
    }
