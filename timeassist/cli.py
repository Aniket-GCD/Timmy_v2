from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from . import __version__
from . import actions
from . import demo as demo_runner
from . import paths


@dataclass
class CommandResult:
    ok: bool
    action: str
    status: str
    message: str
    details: dict[str, Any]

    def emit(self) -> int:
        print(json.dumps(asdict(self), indent=2, sort_keys=True))
        return 0 if self.ok else 1


def yes_no(value: str) -> str:
    normalized = value.strip().lower()
    if normalized not in {"yes", "no"}:
        raise argparse.ArgumentTypeError("expected yes or no")
    return normalized


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="timeassist",
        description="Local, human-reviewed billable-time assistant CLI prototype.",
    )
    parser.add_argument("--version", action="version", version=f"timeassist {__version__}")
    parser.add_argument("--db", default=paths.default_db_path(), help="path to the local SQLite database")
    sub = parser.add_subparsers(dest="command")

    init = sub.add_parser("init", help="initialize local state")
    init.add_argument("--at", help="ISO timestamp for deterministic demos/tests")
    init.add_argument("--dry-run", action="store_true", help="show what would be initialized")

    start = sub.add_parser("start", help="start a draft time session")
    start.add_argument("--client", required=True)
    start.add_argument("--task", required=True, help="notes: what was done")
    start.add_argument("--job-type", dest="job_type", help="job category, e.g. Administrative")
    start.add_argument("--billable", type=yes_no, default=None)
    start.add_argument("--at", help="ISO timestamp for demos/tests")
    start.add_argument("--dry-run", action="store_true")

    switch = sub.add_parser("switch", help="close current session and start another")
    switch.add_argument("--client", required=True)
    switch.add_argument("--task", required=True, help="notes: what was done")
    switch.add_argument("--job-type", dest="job_type", help="job category, e.g. Administrative")
    switch.add_argument("--billable", type=yes_no, default=None)
    switch.add_argument("--at", help="ISO timestamp for demos/tests")
    switch.add_argument("--minutes-ago", type=int, help="retroactively switch as if the work changed this many minutes before --at/now")
    switch.add_argument("--dry-run", action="store_true")

    clarify_active = sub.add_parser("clarify-active", help="clarify labels on the active timer without changing its start time")
    clarify_active.add_argument("--client")
    clarify_active.add_argument("--task", help="notes: what was done")
    clarify_active.add_argument("--job-type", dest="job_type", help="job category, e.g. Administrative")
    clarify_active.add_argument("--billable", type=yes_no, default=None)
    clarify_active.add_argument("--at", help="ISO timestamp for deterministic demos/tests")
    clarify_active.add_argument("--dry-run", action="store_true")

    end = sub.add_parser("end", help="end the active session")
    end.add_argument("--at", help="ISO timestamp for demos/tests")
    end.add_argument("--dry-run", action="store_true")

    add_missing = sub.add_parser("add-missing", help="add an explicit missing time block")
    add_missing.add_argument("--client", required=True)
    add_missing.add_argument("--task", required=True, help="notes: what was done")
    add_missing.add_argument("--job-type", dest="job_type", help="job category, e.g. Administrative")
    add_missing.add_argument("--start", required=True)
    add_missing.add_argument("--end", required=True)
    add_missing.add_argument("--billable", type=yes_no, default=None)
    add_missing.add_argument("--dry-run", action="store_true")

    edit = sub.add_parser("edit", help="edit a draft entry, or a submitted entry in the pay window")
    edit.add_argument("--entry-id", required=True, type=int)
    edit.add_argument("--client")
    edit.add_argument("--task", help="notes: what was done")
    edit.add_argument("--job-type", dest="job_type", help="job category, e.g. Administrative")
    edit.add_argument("--billable", type=yes_no)
    edit.add_argument("--start")
    edit.add_argument("--end")
    edit.add_argument("--at", help="ISO timestamp for deterministic demos/tests")
    edit.add_argument("--dry-run", action="store_true")

    review = sub.add_parser("review", help="review draft entries")
    review.add_argument("--date", default="today")
    review.add_argument("--to", dest="end_date", default=None, help="optional end date (YYYY-MM-DD or 'today'): review the whole span with one range token")
    review.add_argument("--format", default="json", choices=["json", "html"])
    review.add_argument("--output", help="optional path for HTML output")
    review.add_argument("--at", help="ISO timestamp for deterministic reminder/stale-session checks")
    review.add_argument("--dry-run", action="store_true")

    approve = sub.add_parser("approve", help="approve a draft entry, or all drafts for a date with --all")
    approve.add_argument("--entry-id", type=int)
    approve.add_argument("--all", action="store_true", help="approve all draft entries for --date")
    approve.add_argument("--date", default="today", help="date for --all")
    approve.add_argument("--review-token", dest="review_token", help="current token returned by review for this entry/date")
    approve.add_argument("--at", help="ISO timestamp for deterministic demos/tests")
    approve.add_argument("--dry-run", action="store_true")

    unapprove = sub.add_parser("unapprove", help="return an approved entry to draft")
    unapprove.add_argument("--entry-id", required=True, type=int)
    unapprove.add_argument("--at", help="ISO timestamp for deterministic demos/tests")
    unapprove.add_argument("--dry-run", action="store_true")

    export = sub.add_parser("export", help="export approved entries")
    export.add_argument("--date", default="today")
    export.add_argument("--to", dest="end_date", default=None, help="optional end date (YYYY-MM-DD or 'today'): export the whole span with one range token")
    export.add_argument("--format", default="quickbooks-csv", choices=["quickbooks-csv"])
    export.add_argument("--output", help="CSV output path")
    export.add_argument("--review-token", dest="review_token", help="current token returned by review for this date")
    export.add_argument("--at", help="ISO timestamp for deterministic demos/tests")
    export.add_argument("--dry-run", action="store_true")

    packet = sub.add_parser("sanitize-packet", help="create sanitized review packet")
    packet.add_argument("--date", default="today")
    packet.add_argument("--output", help="markdown output path")
    packet.add_argument("--dry-run", action="store_true")

    demo = sub.add_parser("demo", help="generate the synthetic stakeholder demo package")
    demo.add_argument("--date", default=demo_runner.DEFAULT_DEMO_DATE, help="demo date for deterministic timestamps")
    demo.add_argument("--output", default=str(Path("demo") / "generated"), help="directory for generated demo artifacts")
    demo.add_argument("--open", dest="open_html", action="store_true", help="open the stakeholder review HTML after generation")
    demo.add_argument("--dry-run", action="store_true")

    config = sub.add_parser("config", help="show local settings, or set staff_name/office/reception_email/rounding/export folder/strict roster")
    config.add_argument("--rounding-rule", help="set the billing rounding rule: exact, nearest_<N>_minutes, or up_<N>_minutes (N 1-60)")
    config.add_argument("--strict-roster", dest="strict_roster", choices=["yes", "no"], help="firm policy: when yes, needs_info entries can only resolve to roster names (confirm-as-is is off)")
    config.add_argument("--user-export-dir", help="copy each official export CSV to this operator-visible folder")
    config.add_argument("--clear-user-export-dir", action="store_true", help="clear the custom export folder and return to the default Documents/TimeAssist Exports folder")
    config.add_argument("--confirm-default-user-export-dir", action="store_true", help="accept the default Documents/TimeAssist Exports copy folder during first-run setup")
    config.add_argument("--operator-code", dest="operator_code", help="set the 2-4 letter operator code used in export filenames (e.g. AVD)")
    config.add_argument("--clear-operator-code", dest="clear_operator_code", action="store_true", help="clear the operator code")
    config.add_argument("--staff-name", dest="staff_name", help="staff name copied onto submitted time_entries")
    config.add_argument("--clear-staff-name", dest="clear_staff_name", action="store_true", help="clear staff_name")
    config.add_argument("--office", dest="office", help="office for submit: GCD or MH")
    config.add_argument("--clear-office", dest="clear_office", action="store_true", help="clear office")
    config.add_argument("--reception-email", dest="reception_email", help="To: address for draft Reception emails (never auto-sent)")
    config.add_argument("--clear-reception-email", dest="clear_reception_email", action="store_true", help="clear reception_email")
    config.add_argument("--confirm", action="store_true", help="required when changing settings")
    config.add_argument("--dry-run", action="store_true")

    reround = sub.add_parser("reround", help="re-apply the rounding rule to a date's draft entries")
    reround.add_argument("--date", default="today")
    reround.add_argument("--rounding-rule", dest="rounding_rule", help="rounding rule to set before re-rounding: exact, nearest_<N>_minutes, or up_<N>_minutes (N 1-60)")
    reround.add_argument("--confirm", action="store_true", help="required when setting a new rounding rule")
    reround.add_argument("--at", help="ISO timestamp for deterministic demos/tests")
    reround.add_argument("--dry-run", action="store_true")

    import_clients = sub.add_parser("import-clients", help="import a client roster CSV")
    import_clients.add_argument("--file", required=True, help="path to the clients CSV")
    import_clients.add_argument("--mode", choices=["replace", "merge"], default="replace")
    import_clients.add_argument("--confirm-replace", dest="confirm_replace", action="store_true", help="required when mode is replace")
    import_clients.add_argument("--at", help="ISO timestamp for deterministic demos/tests")
    import_clients.add_argument("--dry-run", action="store_true")

    add_client = sub.add_parser("add-client", help="add one new client to the roster")
    add_client.add_argument("--name", required=True, help="client display name")
    add_client.add_argument("--aliases", default="", help="optional ';'-separated alternate names")
    add_client.add_argument("--default-billable", dest="default_billable", choices=["yes", "no"], help="default billable flag (yes when omitted)")
    add_client.add_argument("--default-job-type", dest="default_job_type", default="", help="job code auto-filled on new entries")
    add_client.add_argument("--client-key", dest="client_key", help="optional stable key; derived from the name when omitted")
    add_client.add_argument("--at", help="ISO timestamp for deterministic demos/tests")
    add_client.add_argument("--dry-run", action="store_true")

    clients = sub.add_parser("clients", help="list the imported client roster")
    clients.add_argument("--dry-run", action="store_true")

    job_codes = sub.add_parser("job-codes", help="GET job codes from Supabase (read-only)")
    job_codes.add_argument("--dry-run", action="store_true")

    refresh_clients = sub.add_parser("refresh-clients", help="GET clients from Supabase and merge into local SQLite")
    refresh_clients.add_argument("--at", help="ISO timestamp for deterministic demos/tests")
    refresh_clients.add_argument("--dry-run", action="store_true")

    submit = sub.add_parser("submit", help="POST one approved local entry to Supabase")
    submit.add_argument("--entry-id", required=True, type=int)
    submit.add_argument("--at", help="ISO timestamp for deterministic demos/tests")
    submit.add_argument("--dry-run", action="store_true")

    update_submitted = sub.add_parser("update-submitted", help="PATCH an already-submitted Supabase row by supabase_id")
    update_submitted.add_argument("--entry-id", required=True, type=int)
    update_submitted.add_argument("--at", help="ISO timestamp for deterministic demos/tests")
    update_submitted.add_argument("--dry-run", action="store_true")

    draft_reception = sub.add_parser("draft-reception-email", help="build a Reception email draft (never sends)")
    draft_reception.add_argument("--client-name", required=True, help="spoken new-client name")
    draft_reception.add_argument("--dry-run", action="store_true")

    cancel = sub.add_parser("cancel", help="discard the active session without creating an entry")
    cancel.add_argument("--at", help="ISO timestamp for deterministic demos/tests")
    cancel.add_argument("--dry-run", action="store_true")

    checkin_status = sub.add_parser("checkin-status", help="show whether a session is open (for reminders)")
    checkin_status.add_argument("--dry-run", action="store_true")

    checkin = sub.add_parser("checkin", help="confirm you are still working on the active session")
    checkin.add_argument("--at", help="ISO timestamp for deterministic demos/tests")
    checkin.add_argument("--dry-run", action="store_true")

    snooze_checkin = sub.add_parser("snooze-checkin", help="pause check-in reminders for the active session")
    snooze_checkin.add_argument("--minutes", required=True, type=int, help="minutes to pause check-in reminders")
    snooze_checkin.add_argument("--at", help="ISO timestamp for deterministic demos/tests")
    snooze_checkin.add_argument("--dry-run", action="store_true")

    status = sub.add_parser("status", help="show local database footprint")
    status.add_argument("--dry-run", action="store_true")

    cleanup = sub.add_parser("cleanup", help="trim the audit log and reclaim space (never deletes entries)")
    cleanup.add_argument("--retention-days", type=int, dest="retention_days", help="override the audit retention window (default 90)")
    cleanup.add_argument("--no-vacuum", action="store_true", help="skip reclaiming space")
    cleanup.add_argument("--confirm", action="store_true", help="required because cleanup prunes audit-log history")
    cleanup.add_argument("--at", help="ISO timestamp for deterministic demos/tests")
    cleanup.add_argument("--dry-run", action="store_true")

    sub.add_parser("mcp", help="run the MCP stdio server for Cowork/Claude Code")

    return parser


def normalized_date(value: str) -> str:
    return actions.normalize_date(value)


def dry_run_result(args: argparse.Namespace) -> CommandResult:
    action = args.command or "help"
    details = {k: v for k, v in vars(args).items() if k not in {"command"}}
    if action == "init":
        message = "Would create local state folders, SQLite schema, default settings, and event log."
    else:
        message = f"Would run {action}; no state was changed."
    return CommandResult(True, action, "dry-run", message, details)


def default_export_path(db_path: str | Path, date_value: str, end_date: str | None = None) -> str:
    return actions.default_export_filename(db_path, date_value, end_date)


def default_packet_path(date_value: str) -> str:
    return paths.default_packet_path(date_value)


def require_review_token(token: str | None) -> str:
    if not token:
        raise ValueError("review_token is required; run review first and pass --review-token")
    return token


def require_confirm(value: bool, action: str) -> None:
    if value is not True:
        raise ValueError(f"confirm=true is required before {action}; pass --confirm")


def require_confirm_replace(value: bool) -> None:
    if value is not True:
        raise ValueError("confirm_replace=true is required because replace clears the existing client roster; pass --confirm-replace")


def run_command(args: argparse.Namespace) -> CommandResult:
    if getattr(args, "dry_run", False):
        return dry_run_result(args)

    db_path = args.db
    command = args.command
    if command == "init":
        details = actions.init_state(db_path, args.at)
        return CommandResult(True, command, "initialized", "Local TimeAssist state is ready.", details)
    if command == "start":
        session = actions.start_session(db_path, args.client, args.task, args.billable, args.at, job_type=args.job_type)
        return CommandResult(True, command, "started", f"Started draft time for {args.client}.", {"active_session": session})
    if command == "switch":
        details = actions.switch_session(db_path, args.client, args.task, args.billable, args.at, args.minutes_ago, job_type=args.job_type)
        return CommandResult(True, command, "switched", f"Switched draft time to {args.client}.", details)
    if command == "clarify-active":
        session = actions.clarify_active_session(db_path, args.client, args.task, args.billable, args.at, job_type=args.job_type)
        return CommandResult(True, command, "clarified", "Clarified the active timer without changing its start time.", {"active_session": session})
    if command == "end":
        entry = actions.end_session(db_path, args.at)
        return CommandResult(True, command, "ended", "Ended the active session and created a draft entry.", {"closed_entry": entry})
    if command == "add-missing":
        entry = actions.add_missing_entry(db_path, args.client, args.task, args.start, args.end, args.billable, job_type=args.job_type)
        return CommandResult(True, command, "added", "Added a missing draft time entry.", {"entry": entry})
    if command == "edit":
        entry = actions.edit_entry(db_path, args.entry_id, args.client, args.task, args.billable, args.start, args.end, args.at, job_type=args.job_type)
        return CommandResult(True, command, "edited", f"Edited draft entry {args.entry_id}.", {"entry": entry})
    if command == "review":
        date_value = normalized_date(args.date)
        end_date = normalized_date(args.end_date) if args.end_date is not None else None
        if args.format == "html" and end_date is not None and end_date != date_value:
            raise ValueError(
                "--to is not supported with --format html; render the HTML review one day at a time"
            )
        details = actions.review_entries(db_path, date_value, args.at, end_date=end_date)
        if args.format == "html":
            output = args.output or paths.default_review_html_path(date_value)
            details["html_output"] = actions.render_review_html(details, output, db_path)
        return CommandResult(True, command, "review-ready", "Review is ready. Nothing has been exported.", details)
    if command == "approve":
        if args.all and args.entry_id is not None:
            raise ValueError("approve accepts --all or --entry-id, not both")
        if args.all:
            date_value = normalized_date(args.date)
            actions.validate_review_token(db_path, date_value, require_review_token(args.review_token))
            details = actions.approve_all(db_path, date_value, args.at)
            return CommandResult(True, command, "approved", f"Approved {details['approved_count']} draft entries.", details)
        if args.entry_id is None:
            raise ValueError("approve requires --entry-id or --all")
        date_value = actions.entry_date(db_path, args.entry_id)
        actions.validate_review_token(db_path, date_value, require_review_token(args.review_token))
        entry = actions.set_approval(db_path, args.entry_id, True, args.at)
        return CommandResult(True, command, "approved", f"Approved entry {args.entry_id}.", {"entry": entry})
    if command == "unapprove":
        entry = actions.set_approval(db_path, args.entry_id, False, args.at)
        return CommandResult(True, command, "unapproved", f"Returned entry {args.entry_id} to draft.", {"entry": entry})
    if command == "export":
        date_value = normalized_date(args.date)
        end_date = normalized_date(args.end_date) if args.end_date is not None else None
        actions.validate_review_token(db_path, date_value, require_review_token(args.review_token), end_date=end_date)
        output = args.output or default_export_path(db_path, date_value, end_date)
        details = actions.export_entries(db_path, date_value, output, args.format, args.at, end_date=end_date)
        return CommandResult(True, command, "exported", f"Exported {details['exported_count']} approved entries.", details)
    if command == "sanitize-packet":
        date_value = normalized_date(args.date)
        output = args.output or default_packet_path(date_value)
        details = actions.write_sanitized_packet(db_path, date_value, output)
        return CommandResult(True, command, "packet-created", "Created sanitized collaboration packet.", details)
    if command == "demo":
        details = demo_runner.run_demo(args.output, args.date, args.open_html)
        return CommandResult(True, command, "demo-generated", "Stakeholder demo package generated.", details)
    if command == "config":
        requested_changes = [
            bool(args.rounding_rule),
            bool(args.strict_roster),
            bool(args.user_export_dir),
            bool(args.clear_user_export_dir),
            bool(args.confirm_default_user_export_dir),
            bool(args.operator_code),
            bool(args.clear_operator_code),
            bool(args.staff_name),
            bool(args.clear_staff_name),
            bool(args.office),
            bool(args.clear_office),
            bool(args.reception_email),
            bool(args.clear_reception_email),
        ]
        if sum(1 for value in requested_changes if value) > 1:
            raise ValueError("change one TimeAssist setting at a time")
        if args.confirm_default_user_export_dir:
            require_confirm(args.confirm, "changing TimeAssist settings")
            details = actions.confirm_default_user_export_dir(db_path)
            return CommandResult(True, command, "config-updated", "Confirmed the default Documents/TimeAssist Exports copy folder.", details)
        if args.rounding_rule:
            require_confirm(args.confirm, "changing TimeAssist settings")
            details = actions.set_setting(db_path, "rounding_rule", args.rounding_rule)
            return CommandResult(True, command, "config-updated", f"Set rounding_rule to {args.rounding_rule}.", details)
        if args.strict_roster:
            require_confirm(args.confirm, "changing TimeAssist settings")
            details = actions.set_setting(db_path, "strict_roster", args.strict_roster)
            return CommandResult(True, command, "config-updated", f"Set strict_roster to {details['value']}.", details)
        if args.user_export_dir:
            require_confirm(args.confirm, "changing TimeAssist settings")
            details = actions.set_setting(db_path, "user_export_dir", args.user_export_dir)
            return CommandResult(True, command, "config-updated", f"Set user_export_dir to {details['value']}.", details)
        if args.clear_user_export_dir:
            require_confirm(args.confirm, "changing TimeAssist settings")
            details = actions.clear_setting(db_path, "user_export_dir")
            return CommandResult(True, command, "config-updated", "Cleared user_export_dir.", details)
        if args.operator_code:
            require_confirm(args.confirm, "changing TimeAssist settings")
            details = actions.set_setting(db_path, "operator_code", args.operator_code)
            return CommandResult(True, command, "config-updated", f"Set operator_code to {details['value']}.", details)
        if args.clear_operator_code:
            require_confirm(args.confirm, "changing TimeAssist settings")
            details = actions.clear_setting(db_path, "operator_code")
            return CommandResult(True, command, "config-updated", "Cleared operator_code.", details)
        if args.staff_name:
            require_confirm(args.confirm, "changing TimeAssist settings")
            details = actions.set_setting(db_path, "staff_name", args.staff_name)
            return CommandResult(True, command, "config-updated", f"Set staff_name to {details['value']}.", details)
        if args.clear_staff_name:
            require_confirm(args.confirm, "changing TimeAssist settings")
            details = actions.clear_setting(db_path, "staff_name")
            return CommandResult(True, command, "config-updated", "Cleared staff_name.", details)
        if args.office:
            require_confirm(args.confirm, "changing TimeAssist settings")
            details = actions.set_setting(db_path, "office", args.office)
            return CommandResult(True, command, "config-updated", f"Set office to {details['value']}.", details)
        if args.clear_office:
            require_confirm(args.confirm, "changing TimeAssist settings")
            details = actions.clear_setting(db_path, "office")
            return CommandResult(True, command, "config-updated", "Cleared office.", details)
        if args.reception_email:
            require_confirm(args.confirm, "changing TimeAssist settings")
            details = actions.set_setting(db_path, "reception_email", args.reception_email)
            return CommandResult(True, command, "config-updated", f"Set reception_email to {details['value']}.", details)
        if args.clear_reception_email:
            require_confirm(args.confirm, "changing TimeAssist settings")
            details = actions.clear_setting(db_path, "reception_email")
            return CommandResult(True, command, "config-updated", "Cleared reception_email.", details)
        return CommandResult(True, command, "config", "Current local settings.", {"settings": actions.list_settings(db_path), "export_folder": actions.export_folder_status(db_path)})
    if command == "reround":
        date_value = normalized_date(args.date)
        if args.rounding_rule:
            require_confirm(args.confirm, "changing TimeAssist settings")
        details = actions.reround_drafts(db_path, date_value, args.rounding_rule, args.at)
        return CommandResult(True, command, "rerounded", f"Rerounded {details['rerounded_count']} draft entries.", details)
    if command == "import-clients":
        if args.mode == "replace":
            require_confirm_replace(args.confirm_replace)
        details = actions.import_clients(db_path, args.file, args.mode, args.at)
        return CommandResult(True, command, "clients-imported", f"Imported {details['imported_count']} client(s).", details)
    if command == "add-client":
        details = actions.add_client(db_path, args.name, args.aliases, args.default_billable, args.default_job_type, args.client_key, args.at)
        return CommandResult(True, command, "client-added", f"Added client {details['client']['display_name']}.", details)
    if command == "clients":
        details = actions.list_clients(db_path)
        return CommandResult(True, command, "clients", "Current client roster.", details)
    if command == "job-codes":
        from .supabase_ref import list_job_codes

        details = list_job_codes()
        return CommandResult(True, command, "job-codes", f"{len(details['job_codes'])} job code(s).", details)
    if command == "refresh-clients":
        details = actions.refresh_clients(db_path, args.at)
        return CommandResult(True, command, "clients-refreshed", f"Merged {details['imported_count']} remote client(s).", details)
    if command == "submit":
        from .supabase_submit import submit_entry

        details = submit_entry(db_path, args.entry_id, at=args.at)
        message = "Already submitted." if details.get("skipped") else f"Submitted entry {args.entry_id}."
        return CommandResult(True, command, "submitted", message, details)
    if command == "update-submitted":
        from .supabase_submit import update_submitted_entry

        details = update_submitted_entry(db_path, args.entry_id, at=args.at)
        return CommandResult(True, command, "updated", f"Updated submitted entry {args.entry_id} in Supabase.", details)
    if command == "draft-reception-email":
        details = actions.draft_reception_email_for_db(db_path, args.client_name)
        return CommandResult(True, command, "draft", "Reception email draft (not sent).", details)
    if command == "cancel":
        details = actions.cancel_session(db_path, args.at)
        return CommandResult(True, command, "canceled", "Discarded the active session; no entry created.", {"session": details})
    if command == "checkin-status":
        details = actions.checkin_status(db_path)
        message = (
            f"Tracking {details['session']['client_name']} for {details['open_minutes']} min."
            if details["active"] else "No active session."
        )
        return CommandResult(True, command, "checkin-status", message, details)
    if command == "checkin":
        details = actions.checkin(db_path, args.at)
        return CommandResult(True, command, "checked-in", "Recorded that you are still working.", {"session": details})
    if command == "snooze-checkin":
        details = actions.snooze_checkin(db_path, args.minutes, args.at)
        return CommandResult(True, command, "snoozed", f"Paused check-in reminders for {args.minutes} minutes.", {"session": details})
    if command == "status":
        details = actions.database_status(db_path)
        return CommandResult(True, command, "status", f"Database is {details['size_human']} ({details['entries']['total']} entries).", details)
    if command == "cleanup":
        require_confirm(args.confirm, "cleanup pruning audit-log history")
        details = actions.cleanup_database(db_path, args.retention_days, not args.no_vacuum, args.at)
        return CommandResult(True, command, "cleaned", f"Pruned {details['pruned_events']} old audit event(s).", details)
    raise ValueError(f"unsupported command: {command}")


def error_result(command: str | None, exc: Exception) -> CommandResult:
    return CommandResult(False, command or "unknown", "error", str(exc), {})


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help()
        return 0
    if args.command == "mcp":
        from .mcp_server import serve

        serve(args.db)
        return 0
    try:
        return run_command(args).emit()
    except Exception as exc:  # keep CLI stakeholder-friendly: structured error output
        return error_result(args.command, exc).emit()
