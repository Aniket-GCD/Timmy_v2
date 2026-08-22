"""POST/PATCH local time_entries rows to Supabase. No live calls from tests."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from . import actions
from .db import connect
from .pay_period import can_edit_entry, entry_work_date, refuse_edit_message
from .supabase_ref import account_for_job_code, get_job_codes, request_json

UNASSIGNED_CLIENT = "Unassigned"
NEW_CLIENT_NOTES_PREFIX = "NEW CLIENT:"


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


def is_new_client_path(entry: dict[str, Any]) -> bool:
    notes = (entry.get("task_text") or "").strip()
    client = (entry.get("client_name") or "").strip()
    return notes.upper().startswith(NEW_CLIENT_NOTES_PREFIX) or client.casefold() == UNASSIGNED_CLIENT.casefold()


def ensure_new_client_notes(spoken_name: str, work_notes: str) -> str:
    spoken = (spoken_name or "").strip() or "unknown"
    work = (work_notes or "").strip()
    if work.upper().startswith(NEW_CLIENT_NOTES_PREFIX):
        return work
    return f"{NEW_CLIENT_NOTES_PREFIX} {spoken} | {work}".rstrip(" |")


def apply_unassigned_payload(entry: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    """Force client=Unassigned and NEW CLIENT notes when on the new-client path."""
    if not is_new_client_path(entry):
        return payload
    payload = dict(payload)
    payload["client"] = UNASSIGNED_CLIENT
    notes = (entry.get("task_text") or "").strip()
    if not notes.upper().startswith(NEW_CLIENT_NOTES_PREFIX):
        spoken = (entry.get("raw_client_name") or entry.get("client_name") or "unknown").strip()
        notes = ensure_new_client_notes(spoken, notes)
    payload["notes"] = notes
    payload["task"] = notes
    return payload


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
    payload = {
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
    return apply_unassigned_payload(entry, payload)


def _extract_supabase_id(response: Any) -> str | None:
    if isinstance(response, list) and response:
        row = response[0]
        if isinstance(row, dict) and row.get("id") is not None:
            return str(row["id"])
    if isinstance(response, dict) and response.get("id") is not None:
        return str(response["id"])
    return None


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
                "supabase_id": entry.get("supabase_id"),
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
        response = request_json(
            "POST",
            "time_entries",
            body=payload,
            environ=environ,
            prefer="return=representation",
        )
        supabase_id = _extract_supabase_id(response)
        conn.execute(
            "UPDATE time_entries SET submitted_at = ?, supabase_id = COALESCE(?, supabase_id), updated_at = ? WHERE entry_id = ?",
            (changed_at, supabase_id, changed_at, entry_id),
        )
        actions.log_event(
            conn,
            "submit",
            f"submitted entry {entry_id} to Supabase",
            "time_entry",
            entry_id,
            before={"review_status": status, "submitted_at": None},
            after={"submitted_at": changed_at, "supabase_id": supabase_id},
            at=changed_at,
        )
        conn.commit()
    return {
        "entry_id": entry_id,
        "submitted": True,
        "skipped": False,
        "submitted_at": changed_at,
        "supabase_id": supabase_id,
        "payload_preview": {
            "client": payload["client"],
            "job_code": payload["job_code"],
            "account": payload["account"],
            "entry_date": payload["entry_date"],
            "start_time": payload["start_time"],
            "end_time": payload["end_time"],
            "hours": payload["hours"],
            "notes": payload["notes"],
        },
    }


def update_submitted_entry(
    db_path: str | Path,
    entry_id: int,
    *,
    environ: dict[str, str] | None = None,
    at: str | None = None,
) -> dict[str, Any]:
    """PATCH the same Supabase row by supabase_id. Never INSERT again for this block."""
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
        if not entry.get("submitted_at"):
            raise ValueError(f"entry {entry_id} is not submitted; use submit after local approve")
        supabase_id = (entry.get("supabase_id") or "").strip()
        if not supabase_id:
            raise ValueError(
                f"entry {entry_id} has no supabase_id; cannot PATCH — refuse a second INSERT for the same block"
            )
        work_date = entry_work_date(entry)
        if not can_edit_entry(work_date, staff_name, now=at or changed_at):
            raise ValueError(refuse_edit_message(work_date, now=at or changed_at))
        job_code = (entry.get("job_type") or "").strip()
        if not job_code:
            raise ValueError("set a Job Code before update_submitted; account is copied from job_codes, never typed")
        codes = get_job_codes(environ=environ)
        account = account_for_job_code(job_code, codes)
        payload = time_entry_payload(entry, staff_name=staff_name, office=office, account=account)
        request_json(
            "PATCH",
            "time_entries",
            body=payload,
            query={"id": f"eq.{supabase_id}"},
            environ=environ,
            prefer="return=representation",
        )
        conn.execute(
            "UPDATE time_entries SET updated_at = ? WHERE entry_id = ?",
            (changed_at, entry_id),
        )
        actions.log_event(
            conn,
            "update_submitted",
            f"PATCHed Supabase row {supabase_id} for entry {entry_id}",
            "time_entry",
            entry_id,
            before={"supabase_id": supabase_id},
            after={"updated_at": changed_at, "payload_client": payload["client"]},
            at=changed_at,
        )
        conn.commit()
    return {
        "entry_id": entry_id,
        "updated": True,
        "supabase_id": supabase_id,
        "updated_at": changed_at,
        "payload_preview": {
            "client": payload["client"],
            "job_code": payload["job_code"],
            "account": payload["account"],
            "entry_date": payload["entry_date"],
            "start_time": payload["start_time"],
            "end_time": payload["end_time"],
            "hours": payload["hours"],
            "notes": payload["notes"],
        },
    }
