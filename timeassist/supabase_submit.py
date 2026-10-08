"""POST/PATCH local time_entries rows to Supabase. No live calls from tests."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from . import actions
from .db import connect
from .pay_period import can_edit_entry, entry_work_date, refuse_edit_message
from .supabase_config import time_entries_table, unassigned_client_name
from .supabase_ref import (
    DuplicateTimeEntryError,
    account_for_job_code,
    client_display_name,
    get_clients,
    get_job_codes,
    name_fold,
    request_json,
)

NEW_CLIENT_NOTES_PREFIX = "NEW CLIENT:"
# Default label; prefer unassigned_client_name(db_path=...) at call sites.
UNASSIGNED_CLIENT = "Unassigned"


def _unassigned_label(db_path: str | Path | None = None, environ: dict[str, str] | None = None) -> str:
    return unassigned_client_name(db_path=db_path, environ=environ)


class AmbiguousClientOfficeError(ValueError):
    """Client name exists in both GCD and MH. Do not guess the employee office."""


def _row_is_active(row: dict[str, Any]) -> bool:
    active = row.get("active")
    if active is None:
        return True
    if isinstance(active, bool):
        return active
    return str(active).strip().lower() in {"1", "true", "yes", "t"}


def office_for_client(client_name: str, roster: list[dict[str, Any]], staff_office: str) -> str:
    """Office written on a posted time entry.

    Admin, Early Out, Holiday, Staff Meeting, and Vacation use the person's
    office and ignore the client list. One roster office for any other name
    wins, even when the person works at the other office. The same real-client
    name in both GCD and MH is refused.
    """
    staff = actions.normalize_office(staff_office or "")
    if actions.special_client_policy(client_name):
        return staff
    target = name_fold(client_name or "")
    if not target:
        return staff
    offices: list[str] = []
    for row in roster:
        if not isinstance(row, dict) or not _row_is_active(row):
            continue
        display = client_display_name(row)
        if not display or name_fold(display) != target:
            continue
        office = (row.get("office") or "").strip().upper()
        if office not in {"GCD", "MH"} or office in offices:
            continue
        offices.append(office)
    if len(offices) == 1:
        return offices[0]
    if len(offices) > 1:
        shown = " and ".join(offices)
        raise AmbiguousClientOfficeError(
            f"{client_name.strip()} is in both {shown}. "
            "Say which office, the way the dashboard label does."
        )
    return staff


def _load_client_roster(
    *,
    environ: dict[str, str] | None = None,
    db_path: str | Path | None = None,
) -> list[dict[str, Any]]:
    rows = get_clients(environ=environ, db_path=db_path)
    return rows if isinstance(rows, list) else []


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


def is_new_client_path(
    entry: dict[str, Any],
    *,
    db_path: str | Path | None = None,
    environ: dict[str, str] | None = None,
) -> bool:
    notes = (entry.get("task_text") or "").strip()
    client = (entry.get("client_name") or "").strip()
    label = _unassigned_label(db_path=db_path, environ=environ)
    return notes.upper().startswith(NEW_CLIENT_NOTES_PREFIX) or client.casefold() == label.casefold()


def ensure_new_client_notes(spoken_name: str, work_notes: str) -> str:
    spoken = (spoken_name or "").strip() or "unknown"
    work = (work_notes or "").strip()
    if work.upper().startswith(NEW_CLIENT_NOTES_PREFIX):
        return work
    return f"{NEW_CLIENT_NOTES_PREFIX} {spoken} | {work}".rstrip(" |")


def apply_unassigned_payload(
    entry: dict[str, Any],
    payload: dict[str, Any],
    *,
    db_path: str | Path | None = None,
    environ: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Force client=Unassigned and NEW CLIENT notes when on the new-client path."""
    if not is_new_client_path(entry, db_path=db_path, environ=environ):
        return payload
    label = _unassigned_label(db_path=db_path, environ=environ)
    payload = dict(payload)
    payload["client"] = label
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
    db_path: str | Path | None = None,
    environ: dict[str, str] | None = None,
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
        "billable": True,
        "source_file": "timmy",
    }
    return apply_unassigned_payload(entry, payload, db_path=db_path, environ=environ)


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
        staff_office = actions.normalize_office(settings.get("office") or "")
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
        codes = get_job_codes(environ=environ, db_path=db_path)
        account = account_for_job_code(job_code, codes)
        roster = _load_client_roster(environ=environ, db_path=db_path)
        office = office_for_client(entry.get("client_name") or "", roster, staff_office)
        payload = time_entry_payload(
            entry, staff_name=staff_name, office=office, account=account,
            db_path=db_path, environ=environ,
        )
        table = time_entries_table(db_path=db_path, environ=environ)
        response = request_json(
            "POST",
            table,
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


def _dup_brief(entry: dict[str, Any]) -> dict[str, Any]:
    return {
        "entry_id": entry.get("entry_id"),
        "client": entry.get("client_name") or "",
        "notes": entry.get("task_text") or "",
    }


def _payload_in_detail(payload: dict[str, Any], detail: str) -> bool:
    if not detail:
        return False
    return (
        str(payload.get("entry_date") or "") in detail
        and str(payload.get("start_time") or "") in detail
        and str(payload.get("end_time") or "") in detail
    )


def _mark_submitted_rows(
    conn,
    rows: list[tuple[dict[str, Any], dict[str, Any]]],
    response: Any,
    changed_at: str,
) -> None:
    ids: list[str | None] = []
    if isinstance(response, list):
        for item in response:
            ids.append(_extract_supabase_id(item if isinstance(item, dict) else [item]))
    for index, (entry, _payload) in enumerate(rows):
        supabase_id = ids[index] if index < len(ids) else None
        entry_id = int(entry["entry_id"])
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
            before={"review_status": "approved", "submitted_at": None},
            after={"submitted_at": changed_at, "supabase_id": supabase_id},
            at=changed_at,
        )


def submit_approved_batch(
    db_path: str | Path,
    entries: list[dict[str, Any]],
    *,
    environ: dict[str, str] | None = None,
    at: str | None = None,
) -> dict[str, Any]:
    """POST approved rows in one request. Job codes are fetched once.

    A duplicate-key error drops the conflicting row and retries the rest once.
    """
    skipped_duplicates: list[dict[str, Any]] = []
    submit_failures: list[dict[str, Any]] = []
    if not entries:
        return {
            "submitted_count": 0,
            "submit_failed_count": 0,
            "skipped_duplicates": skipped_duplicates,
        }
    actions.ensure_initialized(db_path)
    changed_at = actions.iso(actions.parse_at(at)) if at else actions.now_iso()
    try:
        codes = get_job_codes(environ=environ, db_path=db_path)
        roster = _load_client_roster(environ=environ, db_path=db_path)
    except Exception as exc:
        return {
            "submitted_count": 0,
            "submit_failed_count": len(entries),
            "skipped_duplicates": skipped_duplicates,
            "submit_error": str(exc),
        }
    with connect(db_path) as conn:
        settings = {
            row["setting_key"]: row["setting_value"]
            for row in conn.execute("SELECT setting_key, setting_value FROM settings")
        }
        staff_name = actions.normalize_staff_name(settings.get("staff_name") or "")
        staff_office = actions.normalize_office(settings.get("office") or "")
        ready: list[tuple[dict[str, Any], dict[str, Any]]] = []
        seen: set[tuple[str, str, str, str, str]] = set()
        for entry in entries:
            if entry.get("submitted_at"):
                continue
            try:
                job_code = (entry.get("job_type") or "").strip()
                account = account_for_job_code(job_code, codes)
                office = office_for_client(entry.get("client_name") or "", roster, staff_office)
                payload = time_entry_payload(
                    entry, staff_name=staff_name, office=office, account=account,
                    db_path=db_path, environ=environ,
                )
            except ValueError as exc:
                submit_failures.append({**_dup_brief(entry), "error": str(exc)})
                continue
            key = (
                payload["staff_name"],
                payload["office"],
                payload["entry_date"],
                payload["start_time"],
                payload["end_time"],
            )
            if key in seen:
                skipped_duplicates.append(_dup_brief(entry))
                continue
            seen.add(key)
            ready.append((entry, payload))
        if not ready:
            conn.commit()
            return {
                "submitted_count": 0,
                "submit_failed_count": len(submit_failures),
                "skipped_duplicates": skipped_duplicates,
                "submit_failures": submit_failures,
            }
        table = time_entries_table(db_path=db_path, environ=environ)

        def _post(rows: list[tuple[dict[str, Any], dict[str, Any]]]) -> Any:
            return request_json(
                "POST",
                table,
                body=[payload for _entry, payload in rows],
                environ=environ,
                prefer="return=representation",
            )

        def _finish(rows: list[tuple[dict[str, Any], dict[str, Any]]], response: Any) -> dict[str, Any]:
            _mark_submitted_rows(conn, rows, response, changed_at)
            conn.commit()
            return {
                "submitted_count": len(rows),
                "submit_failed_count": len(submit_failures),
                "skipped_duplicates": skipped_duplicates,
                "submit_failures": submit_failures,
            }

        try:
            return _finish(ready, _post(ready))
        except DuplicateTimeEntryError as exc:
            detail = exc.detail or ""
            dropped = False
            kept: list[tuple[dict[str, Any], dict[str, Any]]] = []
            for entry, payload in ready:
                if not dropped and _payload_in_detail(payload, detail):
                    skipped_duplicates.append(_dup_brief(entry))
                    dropped = True
                    continue
                kept.append((entry, payload))
            if not dropped:
                return {
                    "submitted_count": 0,
                    "submit_failed_count": len(ready) + len(submit_failures),
                    "skipped_duplicates": skipped_duplicates,
                    "submit_failures": submit_failures,
                    "submit_error": str(exc),
                }
            if not kept:
                conn.commit()
                return {
                    "submitted_count": 0,
                    "submit_failed_count": len(submit_failures),
                    "skipped_duplicates": skipped_duplicates,
                    "submit_failures": submit_failures,
                }
            try:
                return _finish(kept, _post(kept))
            except Exception as retry_exc:
                return {
                    "submitted_count": 0,
                    "submit_failed_count": len(kept) + len(submit_failures),
                    "skipped_duplicates": skipped_duplicates,
                    "submit_failures": submit_failures,
                    "submit_error": str(retry_exc),
                }
        except Exception as exc:
            return {
                "submitted_count": 0,
                "submit_failed_count": len(ready) + len(submit_failures),
                "skipped_duplicates": skipped_duplicates,
                "submit_failures": submit_failures,
                "submit_error": str(exc),
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
        staff_office = actions.normalize_office(settings.get("office") or "")
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
        codes = get_job_codes(environ=environ, db_path=db_path)
        account = account_for_job_code(job_code, codes)
        roster = _load_client_roster(environ=environ, db_path=db_path)
        office = office_for_client(entry.get("client_name") or "", roster, staff_office)
        payload = time_entry_payload(
            entry, staff_name=staff_name, office=office, account=account,
            db_path=db_path, environ=environ,
        )
        table = time_entries_table(db_path=db_path, environ=environ)
        request_json(
            "PATCH",
            table,
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
