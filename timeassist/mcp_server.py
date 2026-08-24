"""Stdlib-only MCP stdio server for the TimeAssist deterministic core.

No third-party dependencies: speaks JSON-RPC 2.0 over newline-delimited
stdio, the MCP stdio transport. The deterministic core in actions.py stays
the billing authority; this server is only a transport wrapper around it.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from . import __version__
from . import actions
from . import mcp_views
from . import paths

PROTOCOL_VERSION = "2025-06-18"
SERVER_NAME = "timeassist"
SERVER_VERSION = __version__

# MCP tool definitions. Names are snake_case (MCP tool names avoid hyphens).
# Each maps 1:1 to a deterministic action; the model never owns time math.
TOOLS: list[dict[str, Any]] = [
    {
        "name": "init_state",
        "description": "Initialize local SQLite state and event log. Safe to call repeatedly.",
        "inputSchema": {
            "type": "object",
            "properties": {"at": {"type": "string", "description": "Optional ISO timestamp for deterministic runs."}},
        },
    },
    {
        "name": "start",
        "description": (
            "Start a draft time session. Soft nickname matches and unknown names return "
            "needs_client_confirm (ask the operator) instead of writing — retry with the "
            "suggested roster client, or Unassigned + draft_reception_email for a new client. "
            "Fails if a session is already active (use switch or end first)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "client": {"type": "string"},
                "task": {"type": "string", "description": "notes: what was done."},
                "job_type": {"type": "string", "description": "Job Code from list_job_codes (stored locally as job_type)."},
                "billable": {"type": "string", "enum": ["yes", "no"], "description": "Omit to use roster default (else yes)."},
                "at": {"type": "string", "description": "Optional ISO timestamp."},
                "confirm_client": {
                    "type": "boolean",
                    "description": "True after the operator confirmed a soft match (or to proceed with an unmatched spoken name).",
                },
            },
            "required": ["client", "task"],
        },
    },
    {
        "name": "switch",
        "description": (
            "Close the active session at the switch time and immediately start a new one. "
            "Soft/unknown clients return needs_client_confirm before writing (same as start)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "client": {"type": "string"},
                "task": {"type": "string", "description": "notes: what was done."},
                "job_type": {"type": "string", "description": "Job Code from list_job_codes (stored locally as job_type)."},
                "billable": {"type": "string", "enum": ["yes", "no"], "description": "Omit to use roster default (else yes)."},
                "at": {"type": "string", "description": "Optional ISO timestamp."},
                "minutes_ago": {"type": "integer", "minimum": 1, "description": "If the operator says they switched N minutes ago, close/start at at-now minus this many minutes."},
                "confirm_client": {"type": "boolean", "description": "True after the operator confirmed the client match."},
            },
            "required": ["client", "task"],
        },
    },
    {
        "name": "clarify_active",
        "description": "Clarify client/notes/billable labels on the active timer without changing its start time.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "client": {"type": "string"},
                "task": {"type": "string", "description": "notes: what was done."},
                "job_type": {"type": "string", "description": "Job Code from list_job_codes (stored locally as job_type)."},
                "billable": {"type": "string", "enum": ["yes", "no"]},
                "at": {"type": "string", "description": "Optional ISO timestamp."},
            },
        },
    },
    {
        "name": "end",
        "description": "End the active session and create a draft time entry.",
        "inputSchema": {
            "type": "object",
            "properties": {"at": {"type": "string", "description": "Optional ISO timestamp."}},
        },
    },
    {
        "name": "add_missing",
        "description": (
            "Add an explicit missing time block as a draft entry. Soft nickname matches and "
            "unknown names return needs_client_confirm with an ask string — relay it to the "
            "operator; on yes retry with suggested_client (or confirm_client=true); on new "
            "client use Unassigned + NEW CLIENT notes + draft_reception_email."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "client": {"type": "string"},
                "task": {"type": "string", "description": "notes: what was done."},
                "job_type": {"type": "string", "description": "Job Code from list_job_codes (stored locally as job_type)."},
                "start": {"type": "string", "description": "ISO start timestamp."},
                "end": {"type": "string", "description": "ISO end timestamp."},
                "billable": {"type": "string", "enum": ["yes", "no"], "description": "Omit to use roster default (else yes)."},
                "confirm_client": {
                    "type": "boolean",
                    "description": "True after the operator confirmed a soft match or unmatched spoken name.",
                },
            },
            "required": ["client", "task", "start", "end"],
        },
    },
    {
        "name": "edit",
        "description": "Correct a draft/needs_info entry, or a submitted entry when the pay-period window (or superuser) allows. After editing a submitted row, call update_submitted to PATCH Supabase.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "entry_id": {"type": "integer"},
                "client": {"type": "string"},
                "task": {"type": "string", "description": "notes: what was done."},
                "job_type": {"type": "string", "description": "Job Code from list_job_codes (stored locally as job_type)."},
                "billable": {"type": "string", "enum": ["yes", "no"]},
                "start": {"type": "string", "description": "ISO start timestamp."},
                "end": {"type": "string", "description": "ISO end timestamp."},
                "at": {"type": "string", "description": "Optional ISO timestamp."},
            },
            "required": ["entry_id"],
        },
    },
    {
        "name": "review",
        "description": "Review entries for a date (default today). Read-only. Optionally render a review HTML file.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "date": {"type": "string", "default": "today", "description": "YYYY-MM-DD or 'today'."},
                "end_date": {"type": "string", "description": "YYYY-MM-DD; with date, reviews the whole span with ONE range token."},
                "html_output": {"type": "string", "description": "Optional path to write the review HTML."},
                "at": {"type": "string", "description": "Optional ISO timestamp for deterministic review warnings."},
            },
        },
    },
    {
        "name": "approve",
        "description": "Approve a single draft entry. Human-authority action: only call after the person confirms this specific entry from the current review.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "entry_id": {"type": "integer"},
                "review_token": {"type": "string", "description": "Current token returned by review for this entry's date."},
                "at": {"type": "string", "description": "Optional ISO timestamp."},
            },
            "required": ["entry_id", "review_token"],
        },
    },
    {
        "name": "approve_all",
        "description": "Approve ALL draft entries for a date. Only when the operator explicitly asks to approve everything from the current review — never on your own initiative.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "date": {"type": "string", "default": "today", "description": "YYYY-MM-DD or 'today'."},
                "review_token": {"type": "string", "description": "Current token returned by review for this date."},
                "at": {"type": "string", "description": "Optional ISO timestamp."},
            },
            "required": ["review_token"],
        },
    },
    {
        "name": "unapprove",
        "description": "Return an approved entry to draft. Cannot unapprove an already-exported entry.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "entry_id": {"type": "integer"},
                "at": {"type": "string", "description": "Optional ISO timestamp."},
            },
            "required": ["entry_id"],
        },
    },
    {
        "name": "export",
        "description": "Export approved entries for a date to a QuickBooks-ready CSV. Only already-approved entries are written; the official CSV stays under TimeAssist data and is also copied to the operator's export folder.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "date": {"type": "string", "default": "today", "description": "YYYY-MM-DD or 'today'."},
                "end_date": {"type": "string", "description": "YYYY-MM-DD; with date, exports the whole span with ONE range token."},
                "output": {"type": "string", "description": "Optional CSV output path. In plugin mode, paths must stay under the TimeAssist data directory."},
                "review_token": {"type": "string", "description": "Current token returned by review for this date."},
                "at": {"type": "string", "description": "Optional ISO timestamp."},
            },
            "required": ["review_token"],
        },
    },
    {
        "name": "sanitize_packet",
        "description": "Write an anonymized collaboration packet (client labels only) for outside design review.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "date": {"type": "string", "default": "today", "description": "YYYY-MM-DD or 'today'."},
                "output": {"type": "string", "description": "Optional markdown output path. In plugin mode, paths must stay under the TimeAssist data directory."},
            },
        },
    },
    {
        "name": "config",
        "description": "Show local settings, or set staff_name/office (GCD or MH)/reception_email/rounding/export copy folder/strict roster/operator initials. Admin action — confirm with the operator before changing settings.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "rounding_rule": {
                    "type": "string",
                    "description": "If provided, set the rounding rule: 'exact', 'nearest_<N>_minutes', or 'up_<N>_minutes' with N 1-60 (e.g. nearest_10_minutes); otherwise return current settings.",
                },
                "strict_roster": {
                    "type": "string",
                    "enum": ["yes", "no"],
                    "description": "Firm policy: when yes, needs_info entries can only resolve to roster names (confirm-as-is is off). Default no.",
                },
                "user_export_dir": {
                    "type": "string",
                    "description": "Persist an operator-chosen folder where each official export is copied (may be outside plugin data).",
                },
                "clear_user_export_dir": {
                    "type": "boolean",
                    "description": "Reset the export copy folder to the default Documents/TimeAssist Exports.",
                },
                "confirm_default_user_export_dir": {
                    "type": "boolean",
                    "description": "Record that the operator accepted the default Documents/TimeAssist Exports folder.",
                },
                "operator_code": {
                    "type": "string",
                    "description": "Set the operator initials code (2-4 letters) appended to export filenames.",
                },
                "clear_operator_code": {
                    "type": "boolean",
                    "description": "Remove the operator initials code from export filenames.",
                },
                "staff_name": {
                    "type": "string",
                    "description": "Your staff name as it should appear on submitted time_entries.",
                },
                "clear_staff_name": {
                    "type": "boolean",
                    "description": "Clear staff_name (submit will refuse until it is set again).",
                },
                "office": {
                    "type": "string",
                    "description": "Office code for submit: GCD or MH.",
                },
                "clear_office": {
                    "type": "boolean",
                    "description": "Clear office (submit will refuse until it is set again).",
                },
                "reception_email": {
                    "type": "string",
                    "description": "To: address for draft_reception_email (never auto-sent).",
                },
                "clear_reception_email": {
                    "type": "boolean",
                    "description": "Clear reception_email (drafts fall back to reception@example.com).",
                },
                "confirm": {"type": "boolean", "description": "Required true when changing a setting."},
            },
        },
    },
    {
        "name": "reround",
        "description": "Re-apply a rounding rule to a date's DRAFT entries from stored raw durations. Approved/exported entries never change. Setting rule requires confirm=true; 'exact' restores raw.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "date": {"type": "string", "default": "today", "description": "YYYY-MM-DD or 'today'."},
                "rule": {"type": "string", "description": "Optional rounding rule to set before re-rounding: 'exact', 'nearest_<N>_minutes', or 'up_<N>_minutes' with N 1-60. Omit to use the currently configured rule."},
                "confirm": {"type": "boolean", "description": "Required true when setting rule because it changes the rounding setting."},
                "at": {"type": "string", "description": "Optional ISO timestamp."},
            },
        },
    },
    {
        "name": "import_clients",
        "description": "DISABLED. Firm clients live only in Supabase (QuickBooks sync). Always errors — use list_clients (live) or Unassigned + draft_reception_email for new clients.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Ignored — tool is disabled."},
                "mode": {"type": "string", "enum": ["replace", "merge"], "default": "replace"},
                "confirm_replace": {"type": "boolean"},
            },
            "required": ["path"],
        },
    },
    {
        "name": "add_client",
        "description": "DISABLED. Firm clients live only in Supabase. Always errors — use Unassigned + draft_reception_email for new QuickBooks clients.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "display_name": {"type": "string"},
                "aliases": {"type": "string", "description": "Optional ';'-separated alternate names."},
                "default_billable": {"type": "string", "enum": ["yes", "no"], "description": "Defaults to yes."},
                "default_job_type": {"type": "string", "description": "Auto-fills Job Code on new entries for this client."},
                "client_key": {"type": "string", "description": "Optional stable key; derived from display_name when omitted."},
                "at": {"type": "string", "description": "Optional ISO timestamp."},
            },
            "required": ["display_name"],
        },
    },
    {
        "name": "list_clients",
        "description": (
            "Live Supabase client lookup (office-filtered). ALWAYS pass query with the spoken name "
            "(e.g. \"Ocean View Road\"). Empty query returns NO names — only a count + message. "
            "Prefer start/add_missing first: the engine soft-matches unique nicknames "
            "(Ocean View Road -> 0969 Ocean View Road). Full dump only with confirm_full_list=true "
            "when the operator explicitly asked for every name. Never invent client names."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Spoken name or fragments. Required for any name list (e.g. Ocean View Road).",
                },
                "confirm_full_list": {
                    "type": "boolean",
                    "description": "True only when the operator asked for the entire client list.",
                },
            },
        },
    },
    {
        "name": "list_job_codes",
        "description": "GET job codes and accounts from Supabase. Use these Job Code values; copy account from the matching row, never type account.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "refresh_clients",
        "description": "DISABLED. list_clients already queries Supabase live — no local cache to refresh. Always errors.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "submit",
        "description": "POST one locally approved time entry to Supabase. Refuses drafts and missing staff_name/office. Never submit without approve. Already-submitted rows are skipped (use update_submitted to PATCH).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "entry_id": {"type": "integer"},
                "at": {"type": "string", "description": "Optional ISO timestamp."},
            },
            "required": ["entry_id"],
        },
    },
    {
        "name": "update_submitted",
        "description": "PATCH the existing Supabase time_entries row for a locally submitted entry (by supabase_id). Pay-period/superuser gate applies. Never inserts a second row.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "entry_id": {"type": "integer"},
                "at": {"type": "string", "description": "Optional ISO timestamp (also used for pay-window check)."},
            },
            "required": ["entry_id"],
        },
    },
    {
        "name": "draft_reception_email",
        "description": "Build a ready email draft asking Reception to create a QuickBooks client. Returns text only — never sends.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "spoken_client_name": {
                    "type": "string",
                    "description": "The client name the operator spoke (not yet in QuickBooks).",
                },
            },
            "required": ["spoken_client_name"],
        },
    },
    {
        "name": "cancel",
        "description": "Discard the active tracking session WITHOUT creating a billable entry (for an abandoned or mistaken session). Fails if no session is active.",
        "inputSchema": {"type": "object", "properties": {"at": {"type": "string", "description": "Optional ISO timestamp."}}},
    },
    {
        "name": "checkin_status",
        "description": "Report whether a tracking session is open (read-only). Call when a scheduled reminder fires; stay silent unless should_prompt=true. Reply mapping: still->checkin, switched->switch, done->end, snooze->snooze_checkin, mistake->cancel.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "checkin",
        "description": "Record that the operator confirmed they are still working on the active session (updates last activity). Fails if no session is active.",
        "inputSchema": {"type": "object", "properties": {"at": {"type": "string", "description": "Optional ISO timestamp."}}},
    },
    {
        "name": "snooze_checkin",
        "description": "Temporarily suppress reminder prompts for the active session. Use when the operator says to pause reminders for N minutes.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "minutes": {"type": "integer", "minimum": 1, "description": "How long to suppress reminder prompts."},
                "at": {"type": "string", "description": "Optional ISO timestamp."},
            },
            "required": ["minutes"],
        },
    },
    {
        "name": "status",
        "description": "Report local database footprint: file size, entry counts by status, event count, date range, backup count, audit retention. Read-only.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "cleanup",
        "description": "Trim the audit log (events older than the retention window) and reclaim space (VACUUM). NEVER deletes time entries. Admin/maintenance action.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "retention_days": {"type": "integer", "minimum": 1, "description": "Override the audit retention window (default from settings, 90)."},
                "vacuum": {"type": "boolean", "default": True, "description": "Reclaim freed space after pruning."},
                "confirm": {"type": "boolean", "description": "Required true; cleanup prunes audit-log history."},
            },
        },
    },
    {
        "name": "discard_entry",
        "description": "Discard a mistaken draft/needs_info capture so it is never billed. Kept in the database for audit but hidden from review and export. Requires explicit operator confirmation.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "entry_id": {"type": "integer"},
                "confirm": {"type": "boolean", "description": "Required true after the operator confirms the discard."},
                "at": {"type": "string", "description": "Optional ISO timestamp."},
            },
            "required": ["entry_id"],
        },
    },
]

_TOOL_NAMES = {tool["name"] for tool in TOOLS}


def _date(value: str | None) -> str:
    return actions.normalize_date(value)


def _optional_date(value: str | None) -> str | None:
    # Truthy guard: a blank end_date means "absent", never "today"
    # (normalize_date("") resolves blank to today).
    return _date(value) if value else None


def _default_export_path(db_path: str | Path, date_value: str, end_date: str | None = None) -> str:
    return actions.default_export_filename(db_path, date_value, end_date=end_date)


def _default_packet_path(date_value: str) -> str:
    return paths.default_packet_path(date_value)


def _require_confirm(arguments: dict[str, Any], action: str) -> None:
    if arguments.get("confirm") is not True:
        raise ValueError(f"confirm=true is required before {action}")


def _validate_token_for_date(db_path: str | Path, date_value: str, arguments: dict[str, Any], end_date: str | None = None) -> None:
    actions.validate_review_token(db_path, date_value, arguments.get("review_token"), end_date=end_date)


def _validate_token_for_entry(db_path: str | Path, entry_id: int, arguments: dict[str, Any]) -> None:
    date_value = actions.entry_date(db_path, entry_id)
    actions.validate_review_token(db_path, date_value, arguments.get("review_token"))


def _safe_input_path(db_path: str | Path, input_path: str | Path) -> Path:
    return paths.resolve_input_path(input_path, db_path, restrict_to_data_dir=True)


def call_tool(name: str, arguments: dict[str, Any], db_path: str | Path) -> dict[str, Any]:
    """Dispatch an MCP tool call to the deterministic core. Raises on error."""
    if name == "init_state":
        return actions.init_state(db_path, arguments.get("at"))
    if name == "start":
        return actions.start_session(
            db_path,
            arguments["client"],
            arguments["task"],
            arguments.get("billable"),
            arguments.get("at"),
            job_type=arguments.get("job_type"),
            confirm_client=bool(arguments.get("confirm_client")),
        )
    if name == "switch":
        return actions.switch_session(
            db_path,
            arguments["client"],
            arguments["task"],
            arguments.get("billable"),
            arguments.get("at"),
            arguments.get("minutes_ago"),
            job_type=arguments.get("job_type"),
            confirm_client=bool(arguments.get("confirm_client")),
        )
    if name == "clarify_active":
        return actions.clarify_active_session(
            db_path,
            arguments.get("client"),
            arguments.get("task"),
            arguments.get("billable"),
            arguments.get("at"),
            job_type=arguments.get("job_type"),
        )
    if name == "end":
        return actions.end_session(db_path, arguments.get("at"))
    if name == "add_missing":
        return actions.add_missing_entry(
            db_path,
            arguments["client"],
            arguments["task"],
            arguments["start"],
            arguments["end"],
            arguments.get("billable"),
            job_type=arguments.get("job_type"),
            confirm_client=bool(arguments.get("confirm_client")),
        )
    if name == "edit":
        return actions.edit_entry(
            db_path,
            int(arguments["entry_id"]),
            arguments.get("client"),
            arguments.get("task"),
            arguments.get("billable"),
            arguments.get("start"),
            arguments.get("end"),
            arguments.get("at"),
            job_type=arguments.get("job_type"),
        )
    if name == "review":
        date_value = _date(arguments.get("date"))
        end_date = _optional_date(arguments.get("end_date"))
        # Collapse equal dates before the html_output refusal below, so
        # date == end_date with html_output still works as single-day
        # (engine collapses again in _normalize_date_span).
        if end_date == date_value:
            end_date = None
        html_output = arguments.get("html_output")
        if html_output and end_date is not None:
            raise ValueError(
                "end_date is not supported with html_output; render the HTML review one day at a time"
            )
        review = actions.review_entries(db_path, date_value, arguments.get("at"), end_date=end_date)
        if html_output:
            review["html_output"] = actions.render_review_html(review, html_output, db_path, restrict_to_data_dir=True)
        return review
    if name == "approve":
        entry_id = int(arguments["entry_id"])
        _validate_token_for_entry(db_path, entry_id, arguments)
        return actions.set_approval(db_path, entry_id, True, arguments.get("at"))
    if name == "approve_all":
        date_value = _date(arguments.get("date"))
        _validate_token_for_date(db_path, date_value, arguments)
        return actions.approve_all(db_path, date_value, arguments.get("at"))
    if name == "unapprove":
        return actions.set_approval(db_path, int(arguments["entry_id"]), False, arguments.get("at"))
    if name == "discard_entry":
        _require_confirm(arguments, "discarding an entry")
        return actions.discard_entry(db_path, int(arguments["entry_id"]), arguments.get("at"))
    if name == "export":
        date_value = _date(arguments.get("date"))
        end_date = _optional_date(arguments.get("end_date"))
        _validate_token_for_date(db_path, date_value, arguments, end_date=end_date)
        output = arguments.get("output") or _default_export_path(db_path, date_value, end_date=end_date)
        return actions.export_entries(db_path, date_value, output, arguments.get("format", "quickbooks-csv"), arguments.get("at"), end_date=end_date, restrict_to_data_dir=True)
    if name == "sanitize_packet":
        date_value = _date(arguments.get("date"))
        output = arguments.get("output") or _default_packet_path(date_value)
        return actions.write_sanitized_packet(db_path, date_value, output, restrict_to_data_dir=True)
    if name == "config":
        rule = arguments.get("rounding_rule")
        strict_roster = arguments.get("strict_roster")
        user_export_dir = arguments.get("user_export_dir")
        clear_user_export_dir = arguments.get("clear_user_export_dir") is True
        confirm_default_user_export_dir = arguments.get("confirm_default_user_export_dir") is True
        operator_code = arguments.get("operator_code")
        clear_operator_code = arguments.get("clear_operator_code") is True
        staff_name = arguments.get("staff_name")
        clear_staff_name = arguments.get("clear_staff_name") is True
        office = arguments.get("office")
        clear_office = arguments.get("clear_office") is True
        reception_email = arguments.get("reception_email")
        clear_reception_email = arguments.get("clear_reception_email") is True
        if sum(1 for value in (rule, strict_roster, user_export_dir, clear_user_export_dir, confirm_default_user_export_dir, operator_code, clear_operator_code, staff_name, clear_staff_name, office, clear_office, reception_email, clear_reception_email) if value) > 1:
            raise ValueError("change one TimeAssist setting at a time")
        if confirm_default_user_export_dir:
            _require_confirm(arguments, "changing TimeAssist settings")
            return actions.confirm_default_user_export_dir(db_path, arguments.get("at"))
        if rule:
            _require_confirm(arguments, "changing TimeAssist settings")
            return actions.set_setting(db_path, "rounding_rule", rule)
        if strict_roster:
            _require_confirm(arguments, "changing TimeAssist settings")
            return actions.set_setting(db_path, "strict_roster", strict_roster)
        if user_export_dir:
            _require_confirm(arguments, "changing TimeAssist settings")
            return actions.set_setting(db_path, "user_export_dir", user_export_dir)
        if clear_user_export_dir:
            _require_confirm(arguments, "changing TimeAssist settings")
            return actions.clear_setting(db_path, "user_export_dir")
        if operator_code:
            _require_confirm(arguments, "changing TimeAssist settings")
            return actions.set_setting(db_path, "operator_code", operator_code)
        if clear_operator_code:
            _require_confirm(arguments, "changing TimeAssist settings")
            return actions.clear_setting(db_path, "operator_code")
        if staff_name:
            _require_confirm(arguments, "changing TimeAssist settings")
            return actions.set_setting(db_path, "staff_name", staff_name)
        if clear_staff_name:
            _require_confirm(arguments, "changing TimeAssist settings")
            return actions.clear_setting(db_path, "staff_name")
        if office:
            _require_confirm(arguments, "changing TimeAssist settings")
            return actions.set_setting(db_path, "office", office)
        if clear_office:
            _require_confirm(arguments, "changing TimeAssist settings")
            return actions.clear_setting(db_path, "office")
        if reception_email:
            _require_confirm(arguments, "changing TimeAssist settings")
            return actions.set_setting(db_path, "reception_email", reception_email)
        if clear_reception_email:
            _require_confirm(arguments, "changing TimeAssist settings")
            return actions.clear_setting(db_path, "reception_email")
        return {"settings": actions.list_settings(db_path), "export_folder": actions.export_folder_status(db_path)}
    if name == "reround":
        if arguments.get("rule"):
            _require_confirm(arguments, "changing TimeAssist settings")
        return actions.reround_drafts(db_path, _date(arguments.get("date")), arguments.get("rule"), arguments.get("at"))
    if name == "import_clients":
        mode = arguments.get("mode", "replace")
        if mode == "replace" and arguments.get("confirm_replace") is not True:
            raise ValueError("confirm_replace=true is required because replace clears the existing client roster")
        csv_path = _safe_input_path(db_path, arguments["path"])
        return actions.import_clients(db_path, csv_path, mode)
    if name == "add_client":
        return actions.add_client(
            db_path,
            arguments["display_name"],
            arguments.get("aliases", ""),
            arguments.get("default_billable"),
            arguments.get("default_job_type", ""),
            arguments.get("client_key"),
            arguments.get("at"),
        )
    if name == "list_clients":
        return actions.list_clients(
            db_path,
            query=arguments.get("query"),
            confirm_full_list=bool(arguments.get("confirm_full_list")),
        )
    if name == "list_job_codes":
        from .supabase_ref import list_job_codes

        return list_job_codes(db_path=db_path)
    if name == "refresh_clients":
        return actions.refresh_clients(db_path)
    if name == "submit":
        from .supabase_submit import submit_entry

        return submit_entry(db_path, int(arguments["entry_id"]), at=arguments.get("at"))
    if name == "update_submitted":
        from .supabase_submit import update_submitted_entry

        return update_submitted_entry(db_path, int(arguments["entry_id"]), at=arguments.get("at"))
    if name == "draft_reception_email":
        return actions.draft_reception_email_for_db(db_path, arguments["spoken_client_name"])
    if name == "cancel":
        return actions.cancel_session(db_path, arguments.get("at"))
    if name == "checkin_status":
        return actions.checkin_status(db_path)
    if name == "checkin":
        return actions.checkin(db_path, arguments.get("at"))
    if name == "snooze_checkin":
        return actions.snooze_checkin(db_path, int(arguments["minutes"]), arguments.get("at"))
    if name == "status":
        return actions.database_status(db_path)
    if name == "cleanup":
        _require_confirm(arguments, "cleanup pruning audit-log history")
        return actions.cleanup_database(db_path, arguments.get("retention_days"), arguments.get("vacuum", True))
    raise ValueError(f"unknown tool: {name}")


def _ok(msg_id: Any, result: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": msg_id, "result": result}


def _err(msg_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": code, "message": message}}


def handle_message(msg: dict[str, Any], db_path: str | Path) -> dict[str, Any] | None:
    """Handle one JSON-RPC message. Returns a response, or None for notifications."""
    method = msg.get("method")
    msg_id = msg.get("id")
    is_request = "id" in msg

    if method == "initialize":
        client_version = (msg.get("params") or {}).get("protocolVersion")
        return _ok(msg_id, {
            "protocolVersion": client_version or PROTOCOL_VERSION,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
        })
    if method == "notifications/initialized":
        return None
    if method == "ping":
        return _ok(msg_id, {})
    if method == "tools/list":
        return _ok(msg_id, {"tools": TOOLS})
    if method == "tools/call":
        params = msg.get("params") or {}
        name = params.get("name")
        arguments = params.get("arguments") or {}
        if name not in _TOOL_NAMES:
            text = json.dumps({"ok": False, "error": f"unknown tool: {name}"}, separators=(",", ":"), sort_keys=True)
            return _ok(msg_id, {"content": [{"type": "text", "text": text}], "isError": True})
        if not isinstance(arguments, dict):
            text = json.dumps({"ok": False, "error": "arguments must be an object"}, separators=(",", ":"), sort_keys=True)
            return _ok(msg_id, {"content": [{"type": "text", "text": text}], "isError": True})
        try:
            result = call_tool(name, arguments, db_path)
            result = mcp_views.shape(name, result)
            text = json.dumps(result, separators=(",", ":"), sort_keys=True)
            return _ok(msg_id, {"content": [{"type": "text", "text": text}]})
        except Exception as exc:  # surface tool errors to the model, not as protocol failures
            text = json.dumps({"ok": False, "error": str(exc)}, separators=(",", ":"), sort_keys=True)
            return _ok(msg_id, {"content": [{"type": "text", "text": text}], "isError": True})

    if not is_request:
        return None
    return _err(msg_id, -32601, f"method not found: {method}")


def serve(db_path: str | Path) -> None:
    """Run the stdio JSON-RPC loop until stdin closes."""
    # MCP stdio is UTF-8, newline-delimited JSON. Windows text mode defaults to a
    # cp-* encoding and rewrites '\n' to '\r\n'; force UTF-8 and disable newline
    # translation so messages stay byte-clean on the target platform.
    for stream in (sys.stdin, sys.stdout):
        try:
            stream.reconfigure(encoding="utf-8", newline="\n")
        except (AttributeError, ValueError):
            pass
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            # Spec-correct parse error so a client awaiting a response fails fast
            # instead of hanging on a silently dropped (possibly-request) line.
            sys.stdout.write(json.dumps(_err(None, -32700, "parse error")) + "\n")
            sys.stdout.flush()
            continue
        response = handle_message(msg, db_path)
        if response is not None:
            sys.stdout.write(json.dumps(response) + "\n")
            sys.stdout.flush()
