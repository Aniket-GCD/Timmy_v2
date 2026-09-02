"""Model-facing views of action results for the MCP server.

The deterministic core (actions.py) and the CLI return full row dicts for
audit and debugging. Every byte of an MCP tool result is read by the model in
Cowork, so this module trims each result to what the assistant actually needs:
audit metadata is dropped, null fields are omitted, and entry lists the model
has already seen in `review` are summarized to counts. Shaping must only ever
remove or rename fields for the model — never alter the engine's stored state.
"""

from __future__ import annotations

from typing import Any

from .actions import capture_note_text, format_hhmm


def drop_nones(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: drop_nones(item) for key, item in value.items() if item is not None}
    if isinstance(value, list):
        return [drop_nones(item) for item in value]
    return value


def slim_entry(entry: dict[str, Any]) -> dict[str, Any]:
    minutes = entry.get("rounded_minutes")
    job = entry.get("job_type")
    if job is None:
        job = ""
    else:
        job = str(job)
    start = entry.get("start_at")
    entry_date = None
    if isinstance(start, str) and len(start) >= 10:
        entry_date = start[:10]
    slim: dict[str, Any] = {
        "entry_id": entry.get("entry_id"),
        "entry_date": entry_date,
        "client": entry.get("client_name"),
        "notes": entry.get("task_text"),
        # Always emit Job Code (blank string OK) so the snapshot table keeps the column.
        "job_type": job,
        "job_code": job,
        "billable": "yes" if entry.get("billable") else "no",
        "start": start,
        "end": entry.get("end_at"),
        "minutes": minutes,
        "status": entry.get("review_status"),
    }
    if minutes is not None:
        slim["hours"] = int(minutes) / 60
        slim["duration"] = format_hhmm(int(minutes))
    if entry.get("duration_only") or (
        entry.get("capture_note") and "duration_only" in str(entry.get("capture_note"))
    ):
        slim["duration_only"] = True
    if entry.get("suggested_job_type"):
        slim["suggested_job_type"] = entry["suggested_job_type"]
    if entry.get("submitted_at"):
        slim["submitted_at"] = entry["submitted_at"]
    if entry.get("supabase_id"):
        slim["supabase_id"] = entry["supabase_id"]
    if entry.get("duration_minutes") != entry.get("rounded_minutes"):
        slim["raw_minutes"] = entry.get("duration_minutes")
    if entry.get("notes_missing"):
        slim["notes_missing"] = True
    if entry.get("raw_client_name"):
        slim["spoken_client"] = entry["raw_client_name"]
    if entry.get("capture_status") == "needs_info":
        slim["needs_info"] = (
            capture_note_text(entry.get("capture_note"), entry.get("client_name"))
            or entry.get("needs_review_reason")
            or "needs_info"
        )
    if entry.get("submit_result") is not None:
        slim["submit_result"] = entry["submit_result"]
    if entry.get("submit_error") is not None:
        slim["submit_error"] = entry["submit_error"]
    return slim


def slim_session(session: dict[str, Any] | None) -> dict[str, Any] | None:
    if not session:
        return None
    job = session.get("job_type")
    if job is None:
        job = ""
    else:
        job = str(job)
    slim: dict[str, Any] = {
        "client": session.get("client_name"),
        "notes": session.get("task_text"),
        "job_type": job,
        "job_code": job,
        "started_at": session.get("started_at"),
    }
    if session.get("suggested_job_type"):
        slim["suggested_job_type"] = session["suggested_job_type"]
    if session.get("raw_client_name"):
        slim["spoken_client"] = session["raw_client_name"]
    if session.get("last_checkin_at") and session.get("last_checkin_at") != session.get("started_at"):
        slim["last_checkin_at"] = session["last_checkin_at"]
    if session.get("snoozed_until"):
        slim["snoozed_until"] = session["snoozed_until"]
    if session.get("status") and session.get("status") != "active":
        slim["status"] = session["status"]
    if session.get("capture_status") == "needs_info":
        slim["needs_info"] = (
            capture_note_text(session.get("capture_note"), session.get("client_name"))
            or "needs_info"
        )
    return slim


def _view_review(result: dict[str, Any]) -> dict[str, Any]:
    ranged = result.get("end_date") is not None
    if ranged:
        shaped: dict[str, Any] = {
            "date": result["date"],
            "end_date": result["end_date"],
            "days": result["days"],
            "totals": result["totals"],
            "skipped_needs_info_count": result["skipped_needs_info_count"],
            "review_token": result["review_token"],
        }
    else:
        shaped = {
            "date": result["date"],
            "entries": [slim_entry(entry) for entry in result["entries"]],
            "totals": result["totals"],
            "skipped_needs_info_count": result["skipped_needs_info_count"],
            "review_token": result["review_token"],
        }
    if result.get("missing_notes_count"):
        shaped["missing_notes_count"] = result["missing_notes_count"]
    warning = result.get("active_timer_warning") or {}
    if warning.get("has_active_timer"):
        shaped["active_timer"] = {
            "session": slim_session(result.get("active_session")),
            "open_minutes": warning.get("open_minutes"),
            "is_stale": warning.get("is_stale"),
            "suggested_actions": warning.get("suggested_actions"),
        }
    if "html_output" in result:
        shaped["html_output"] = result["html_output"]
    return shaped


def _view_approve_all(result: dict[str, Any]) -> dict[str, Any]:
    shaped: dict[str, Any] = {
        "date": result["date"],
        "approved_count": result["approved_count"],
        "skipped_needs_info_count": result["skipped_needs_info_count"],
        "skipped_needs_info_minutes": result["skipped_needs_info_minutes"],
    }
    if result.get("skipped_locked_count"):
        shaped["skipped_locked_count"] = result["skipped_locked_count"]
        shaped["skipped_locked_minutes"] = result["skipped_locked_minutes"]
    if result.get("skipped_missing_job_code_count"):
        shaped["skipped_missing_job_code_count"] = result["skipped_missing_job_code_count"]
        shaped["skipped_missing_job_code_minutes"] = result["skipped_missing_job_code_minutes"]
    if result.get("submitted_count") is not None:
        shaped["submitted_count"] = result["submitted_count"]
    if result.get("submit_failed_count"):
        shaped["submit_failed_count"] = result["submit_failed_count"]
    if result.get("submit_results"):
        shaped["submit_results"] = result["submit_results"]
    if result.get("entries"):
        shaped["entries"] = [slim_entry(e) for e in result["entries"]]
    return shaped


def _view_reround(result: dict[str, Any]) -> dict[str, Any]:
    return {
        "date": result["date"],
        "rule": result["rule"],
        "rerounded_count": result["rerounded_count"],
        "total_draft_minutes": sum(int(entry["rounded_minutes"]) for entry in result["entries"]),
    }


def _view_export(result: dict[str, Any]) -> dict[str, Any]:
    shaped: dict[str, Any] = {
        "date": result["date"],
        "exported_count": result["exported_count"],
        "skipped_needs_info_count": result["skipped_needs_info_count"],
        "skipped_needs_info_minutes": result["skipped_needs_info_minutes"],
        "csv": result.get("user_visible_output") or result["output"],
    }
    if result.get("end_date"):
        shaped["end_date"] = result["end_date"]
    if result.get("operator_code"):
        shaped["operator_code"] = result["operator_code"]
    if result.get("skipped_locked_count"):
        shaped["skipped_locked_count"] = result["skipped_locked_count"]
        shaped["skipped_locked_minutes"] = result["skipped_locked_minutes"]
    if result.get("user_visible_output") and result["user_visible_output"] != result["output"]:
        shaped["official_csv"] = result["output"]
    if result.get("user_visible_copy_error"):
        shaped["copy_error"] = result["user_visible_copy_error"]
    if not result.get("backup"):
        shaped["backup_warning"] = "database backup failed at export time; export itself succeeded"
    return shaped


def _view_checkin_status(result: dict[str, Any]) -> dict[str, Any]:
    if not result.get("active"):
        return {"active": False, "should_prompt": False}
    shaped: dict[str, Any] = {
        "active": True,
        "session": slim_session(result["session"]),
        "open_minutes": result["open_minutes"],
        "minutes_since_checkin": result["minutes_since_checkin"],
        "should_prompt": result["should_prompt"],
        "prompt_reason": result["prompt_reason"],
        "is_stale": result["is_stale"],
    }
    if result.get("snoozed_until"):
        shaped["snoozed_until"] = result["snoozed_until"]
    return shaped


def _view_status(result: dict[str, Any]) -> dict[str, Any]:
    shaped = dict(result)
    shaped.pop("db_path", None)
    return shaped


def _view_client_confirm(result: dict[str, Any]) -> dict[str, Any]:
    return {
        "needs_client_confirm": True,
        "match_kind": result.get("match_kind"),
        "spoken_client": result.get("spoken_client"),
        "suggested_client": result.get("suggested_client"),
        "ask": result.get("ask"),
        "if_yes": result.get("if_yes"),
        "if_new_client": result.get("if_new_client"),
    }


def _view_entry(result: dict[str, Any]) -> dict[str, Any]:
    if result.get("needs_client_confirm"):
        return _view_client_confirm(result)
    return slim_entry(result)


def _view_session(result: dict[str, Any]) -> dict[str, Any]:
    if result.get("needs_client_confirm"):
        return _view_client_confirm(result)
    return slim_session(result) or {}


def _view_switch(result: dict[str, Any]) -> dict[str, Any]:
    if result.get("needs_client_confirm"):
        return _view_client_confirm(result)
    return {
        "closed_entry": slim_entry(result["closed_entry"]),
        "new_session": slim_session(result["new_active_session"]),
    }


def _view_list_clients(result: dict[str, Any]) -> dict[str, Any]:
    shaped: dict[str, Any] = {
        "clients": [
            {key: client[key] for key in ("client_key", "display_name", "aliases", "default_billable") if key in client}
            for client in result.get("clients", [])
        ]
    }
    if result.get("client_count") is not None:
        shaped["client_count"] = result["client_count"]
    if result.get("message"):
        shaped["message"] = result["message"]
    return shaped


def _view_import_clients(result: dict[str, Any]) -> dict[str, Any]:
    # Counts only: the roster echo would burn tokens and now carries engine-only
    # columns (billable_locked, default_job_type); the model can call list_clients.
    return {"mode": result["mode"], "imported_count": result["imported_count"]}


def _view_add_client(result: dict[str, Any]) -> dict[str, Any]:
    client = result.get("client", {})
    slim = {key: client.get(key) for key in ("client_key", "display_name", "default_billable")}
    if client.get("aliases"):
        slim["aliases"] = client["aliases"]
    if client.get("default_job_type"):
        slim["default_job_type"] = client["default_job_type"]
    return {"client": slim, "client_count": result["client_count"]}


_VIEWS = {
    "review": _view_review,
    "approve_all": _view_approve_all,
    "reround": _view_reround,
    "export": _view_export,
    "checkin_status": _view_checkin_status,
    "status": _view_status,
    "list_clients": _view_list_clients,
    "list_job_codes": lambda result: {"job_codes": result.get("job_codes", [])},
    "refresh_clients": lambda result: {
        "imported_count": result.get("imported_count"),
        "client_count": result.get("client_count"),
    },
    "submit": lambda result: {
        "entry_id": result.get("entry_id"),
        "submitted": result.get("submitted"),
        "skipped": result.get("skipped"),
        "reason": result.get("reason"),
        "submitted_at": result.get("submitted_at"),
        "supabase_id": result.get("supabase_id"),
        "payload_preview": result.get("payload_preview"),
    },
    "update_submitted": lambda result: {
        "entry_id": result.get("entry_id"),
        "updated": result.get("updated"),
        "supabase_id": result.get("supabase_id"),
        "updated_at": result.get("updated_at"),
        "payload_preview": result.get("payload_preview"),
    },
    "draft_reception_email": lambda result: {
        "to": result.get("to"),
        "subject": result.get("subject"),
        "body": result.get("body"),
        "mailto": result.get("mailto"),
        "sent": False,
        "note": result.get("note"),
    },
    "import_clients": _view_import_clients,
    "add_client": _view_add_client,
    "switch": _view_switch,
    "start": _view_session,
    "clarify_active": _view_session,
    "cancel": _view_session,
    "checkin": _view_session,
    "snooze_checkin": _view_session,
    "end": _view_entry,
    "add_missing": _view_entry,
    "edit": _view_entry,
    "approve": _view_entry,
    "unapprove": _view_entry,
    "discard_entry": _view_entry,
}


def shape(tool_name: str, result: dict[str, Any]) -> dict[str, Any]:
    """Return the compact model-facing view of a tool result.

    job_type/job_code blank strings must survive so review snapshots keep the
    Job Code column — strip only true Nones.
    """
    view = _VIEWS.get(tool_name)
    shaped = view(result) if view else result
    return drop_nones(shaped)
