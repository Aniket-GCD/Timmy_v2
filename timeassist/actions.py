from __future__ import annotations

import csv
import hashlib
import hmac
import html
import json
import math
import re
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from . import paths
from .db import backup as backup_db, connect, initialize, slugify_client_key, vacuum as vacuum_db

# Hard session cap (Timmy plugin auto-end). 8 hours.
TEST_MAX_SESSION_MINUTES = 8 * 60


def now_iso() -> str:
    # Always the local machine wall clock (never UTC stamped as naive).
    # astimezone() resolves the OS timezone, then we store naive local ISO.
    return (
        datetime.now()
        .astimezone()
        .replace(tzinfo=None, microsecond=0)
        .isoformat()
    )


def parse_at(value: str | None) -> datetime:
    if not value:
        return datetime.now().astimezone().replace(tzinfo=None, microsecond=0)
    normalized = value.strip()
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    parsed = datetime.fromisoformat(normalized)
    # Everything runs on the operator's local wall clock. Fold any offset-aware
    # input to local naive so duration math and date bucketing never mix naive
    # and aware datetimes (subtracting those raises TypeError).
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone().replace(tzinfo=None)
    return parsed.replace(microsecond=0)


def iso(value: datetime) -> str:
    if value.tzinfo is not None:
        value = value.astimezone().replace(tzinfo=None)
    return value.replace(microsecond=0).isoformat()


def format_local_ampm(value: str | datetime | None = None) -> str:
    """12-hour AM/PM on the local machine clock (for Timmy start confirmations)."""
    if value is None:
        dt = datetime.now().astimezone().replace(tzinfo=None, microsecond=0)
    elif isinstance(value, datetime):
        dt = value
        if dt.tzinfo is not None:
            dt = dt.astimezone().replace(tzinfo=None)
        dt = dt.replace(microsecond=0)
    else:
        dt = parse_at(value)
    hour = dt.hour
    ampm = "AM" if hour < 12 else "PM"
    hour12 = hour % 12 or 12
    return f"{hour12}:{dt.minute:02d} {ampm}"


def normalize_date(value: str | None) -> str:
    # Resolve 'today'/blank to the local date; otherwise require a strict
    # YYYY-MM-DD. This stops a mistyped date ('2026-5-1') silently matching zero
    # rows (empty export reported as success) and blocks path-bearing values
    # ('../../x') from reaching the date-derived output filename.
    if not value or value == "today":
        return now_iso()[:10]
    candidate = value.strip()
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", candidate):
        raise ValueError("date must be 'today' or YYYY-MM-DD")
    try:
        datetime.strptime(candidate, "%Y-%m-%d")
    except ValueError:
        raise ValueError("date must be 'today' or YYYY-MM-DD")
    return candidate


def minutes_between(start_at: str, end_at: str) -> int:
    start = parse_at(start_at)
    end = parse_at(end_at)
    seconds = (end - start).total_seconds()
    if seconds < 0:
        raise ValueError("end time must be after start time")
    minutes = int(round(seconds / 60))
    # A strictly-positive session bills at least one raw minute: otherwise a
    # sub-30s task rounds to 0 and silently drops from billing, and round_minutes
    # can't recover it because it short-circuits on minutes <= 0.
    if seconds > 0 and minutes == 0:
        minutes = 1
    return minutes


def round_minutes(minutes: int, increment: int = 6, mode: str = "nearest") -> int:
    if minutes <= 0:
        return 0
    if increment <= 1:
        return minutes
    if mode == "up":
        return int(math.ceil(minutes / increment) * increment)
    remainder = minutes % increment
    if remainder == 0:
        return minutes
    lower = minutes - remainder
    upper = lower + increment
    # Billing floor: when "nearest" would round a positive entry down to 0,
    # bill one full increment instead — work done must never silently vanish
    # from the export (mirrors the >=1 raw-minute rule in minutes_between).
    return upper if remainder >= increment / 2 else max(increment, lower)


# Billing rounding rules are free-form names stored in the settings table under
# 'rounding_rule': 'exact' (raw minutes, the default), or 'nearest_<N>_minutes' /
# 'up_<N>_minutes' with any increment N from 1 to 60.
ROUNDING_RULE_FORMAT = (
    "rounding rules are 'exact', 'nearest_<N>_minutes', or 'up_<N>_minutes' "
    "with N from 1 to 60 (e.g. nearest_10_minutes)"
)
_ROUNDING_RULE_RE = re.compile(r"^(nearest|up)_([1-9]\d?)_minutes$")


def parse_rounding_rule(rule: str | None) -> tuple[int, str] | None:
    """Return (increment_minutes, mode) for a valid rule name, else None."""
    if rule == "exact":
        return (1, "nearest")
    match = _ROUNDING_RULE_RE.match(rule) if rule else None
    if not match:
        return None
    increment = int(match.group(2))
    if increment > 60:
        return None
    return (increment, match.group(1))


def get_rounding(conn) -> tuple[int, str]:
    row = conn.execute("SELECT setting_value FROM settings WHERE setting_key = 'rounding_rule'").fetchone()
    rule = row["setting_value"] if row else "exact"
    # Unknown stored values fall back to exact rather than crashing capture.
    return parse_rounding_rule(rule) or (1, "nearest")


def get_setting(conn, key: str, default: str | None = None) -> str | None:
    row = conn.execute("SELECT setting_value FROM settings WHERE setting_key = ?", (key,)).fetchone()
    return row["setting_value"] if row else default


EXPORT_FOLDER_PROMPT = (
    "TimeAssist will keep the official export inside Claude plugin data for audit safety, "
    "then copy the same CSV to Documents/TimeAssist Exports so it is easy to find. "
    "Keep that default, or choose a different export copy folder."
)


def export_folder_status(db_path: str | Path) -> dict[str, Any]:
    ensure_initialized(db_path)
    with connect(db_path) as conn:
        return _export_folder_status_from_conn(conn)


def _export_folder_status_from_conn(conn) -> dict[str, Any]:
    default_dir = str(paths.default_user_export_dir())
    custom_dir = get_setting(conn, "user_export_dir")
    confirmed_at = get_setting(conn, "user_export_dir_confirmed_at")
    if custom_dir:
        preference = "custom"
        user_export_dir = custom_dir
        survey_required = False
    elif confirmed_at:
        preference = "default_confirmed"
        user_export_dir = default_dir
        survey_required = False
    else:
        preference = "default_unconfirmed"
        user_export_dir = default_dir
        survey_required = True
    return {
        "survey_required": survey_required,
        "preference": preference,
        "user_export_dir": user_export_dir,
        "default_user_export_dir": default_dir,
        "custom_user_export_dir": custom_dir,
        "confirmed_at": confirmed_at,
        "prompt": EXPORT_FOLDER_PROMPT,
    }


def _upsert_setting(conn, key: str, value: str, changed_at: str) -> None:
    conn.execute(
        """
        INSERT INTO settings(setting_key, setting_value, scope, updated_at)
        VALUES (?, ?, 'local', ?)
        ON CONFLICT(setting_key) DO UPDATE SET
            setting_value = excluded.setting_value,
            updated_at = excluded.updated_at
        """,
        (key, value, changed_at),
    )


def confirm_default_user_export_dir(db_path: str | Path, at: str | None = None) -> dict[str, Any]:
    ensure_initialized(db_path)
    changed_at = iso(parse_at(at)) if at else now_iso()
    with connect(db_path) as conn:
        before = _export_folder_status_from_conn(conn)
        previous = get_setting(conn, "user_export_dir")
        conn.execute("DELETE FROM settings WHERE setting_key = 'user_export_dir'")
        _upsert_setting(conn, "user_export_dir_confirmed_at", changed_at, changed_at)
        after = _export_folder_status_from_conn(conn)
        log_event(conn, "config", "confirmed default user export folder", "setting", None, before=before, after=after, at=changed_at)
        conn.commit()
    return {"key": "user_export_dir", "value": after["user_export_dir"], "previous": previous, "export_folder": after}


def set_setting(db_path: str | Path, key: str, value: str, at: str | None = None) -> dict[str, Any]:
    ensure_initialized(db_path)
    changed_at = iso(parse_at(at)) if at else now_iso()
    if key == "rounding_rule" and parse_rounding_rule(value) is None:
        raise ValueError(f"unknown rounding rule: {value}; {ROUNDING_RULE_FORMAT}")
    if key == "strict_roster":
        value = normalize_strict_roster(value)
    if key == "operator_code":
        value = normalize_operator_code(value)
    if key == "staff_name":
        # Prefer configure_staff_name from MCP/CLI (supports soft-match confirm).
        # Direct set_setting still validates when Supabase credentials are present.
        resolved = _resolve_staff_or_raise(db_path, value, confirm_staff=False)
        value = resolved["staff_name"]
        office_from_roster = resolved.get("office")
        with connect(db_path) as conn:
            before = get_setting(conn, key)
            _upsert_setting(conn, key, value, changed_at)
            office_changed = None
            if office_from_roster in {"GCD", "MH"}:
                before_office = get_setting(conn, "office")
                if before_office != office_from_roster:
                    _upsert_setting(conn, "office", office_from_roster, changed_at)
                    office_changed = {"previous": before_office, "value": office_from_roster}
            log_event(conn, "config", f"set {key} to {value}", "setting", None, before={"key": key, "value": before}, after={"key": key, "value": value}, at=changed_at)
            conn.commit()
        result: dict[str, Any] = {"key": key, "value": value, "previous": before, "matched_employee": True}
        if office_changed is not None:
            result["office"] = office_changed
        return result
    if key == "office":
        value = normalize_office(value)
    if key == "reception_email":
        value = normalize_reception_email(value)
    if key == "user_export_dir":
        value = str(paths.resolve_user_export_dir(value))
    with connect(db_path) as conn:
        before = get_setting(conn, key)
        _upsert_setting(conn, key, value, changed_at)
        if key == "user_export_dir":
            _upsert_setting(conn, "user_export_dir_confirmed_at", changed_at, changed_at)
        log_event(conn, "config", f"set {key} to {value}", "setting", None, before={"key": key, "value": before}, after={"key": key, "value": value}, at=changed_at)
        export_folder = _export_folder_status_from_conn(conn) if key == "user_export_dir" else None
        conn.commit()
    result = {"key": key, "value": value, "previous": before}
    if export_folder is not None:
        result["export_folder"] = export_folder
    return result


def _staff_confirm_payload(classified: dict[str, Any]) -> dict[str, Any]:
    spoken = classified.get("spoken") or ""
    kind = classified.get("kind")
    suggested = classified.get("staff_name")
    office = classified.get("office")
    employee_choices = classified.get("choices") or []

    if kind == "ambiguous" and employee_choices:
        labels = [c.get("label") or c.get("staff_name") for c in employee_choices]
        return {
            "needs_staff_confirm": True,
            "match_kind": "ambiguous",
            "spoken_name": spoken,
            "suggested_staff_name": None,
            "suggested_office": None,
            "choices": employee_choices,
            "other_label": "Other",
            "ask": (
                f'Several firm employees match "{spoken}". '
                f"Please select your identity (name and office): "
                + "; ".join(str(label) for label in labels if label)
                + "."
            ),
            "if_yes": None,
        }

    if kind == "soft" and suggested:
        office_bit = (
            f' and office {office}' if office in {"GCD", "MH"} else ""
        )
        return {
            "needs_staff_confirm": True,
            "match_kind": "soft",
            "spoken_name": spoken,
            "suggested_staff_name": suggested,
            "suggested_office": office if office in {"GCD", "MH"} else None,
            "choices": (
                [{"staff_name": suggested, "office": office, "label": f"{suggested} ({office})"}]
                if office in {"GCD", "MH"}
                else [{"staff_name": suggested, "office": None, "label": suggested}]
            ),
            "other_label": "Other",
            "ask": (
                f'Please confirm: are you "{suggested}"{office_bit} on the firm employee list? '
                f"If yes, I will set your Timmy identity to that exact name"
                + office_bit
                + " so submissions stay uniform."
            ),
            "if_yes": {
                "retry_with_staff_name": suggested,
                "or_confirm_staff": True,
            },
        }
    return {
        "needs_staff_confirm": True,
        "match_kind": "none",
        "spoken_name": spoken,
        "suggested_staff_name": None,
        "suggested_office": None,
        "choices": [],
        "other_label": "Other",
        "ask": (
            f'No match on the firm employees list for "{spoken}". '
            f"Use list_employees (query=your name) to find the exact staff_name, "
            f"or ask an admin to add you to the firm employees list. Timmy cannot invent names."
        ),
        "if_yes": None,
    }


def _resolve_staff_or_raise(
    db_path: str | Path,
    spoken: str,
    *,
    confirm_staff: bool = False,
    environ: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Return {staff_name, office} from employees, or raise / skip when offline.

    When Supabase credentials are absent (local unit tests), returns the
    normalized spoken name with no office — same as pre-employees behavior.
    """
    spoken_norm = normalize_staff_name(spoken)
    live_env = _supabase_environ(environ)
    if live_env is None:
        return {"staff_name": spoken_norm, "office": None}
    from .supabase_ref import classify_employee_remote

    classified = classify_employee_remote(spoken_norm, environ=live_env, db_path=db_path)
    kind = classified["kind"]
    if kind in {"exact", "fold"}:
        return {"staff_name": classified["staff_name"], "office": classified.get("office")}
    if kind == "soft" and confirm_staff:
        return {"staff_name": classified["staff_name"], "office": classified.get("office")}
    payload = _staff_confirm_payload(classified)
    raise ValueError(payload["ask"])


def configure_staff_name(
    db_path: str | Path,
    spoken: str,
    *,
    confirm_staff: bool = False,
    at: str | None = None,
    environ: dict[str, str] | None = None,
    office: str | None = None,
) -> dict[str, Any]:
    """Set staff_name from the read-only employees table (canonical spelling + office)."""
    ensure_initialized(db_path)
    spoken_norm = normalize_staff_name(spoken)
    live_env = _supabase_environ(environ)
    if live_env is None:
        return set_setting(db_path, "staff_name", spoken_norm, at=at)

    from .supabase_ref import classify_employee_remote

    office_hint = (office or "").strip().upper() or None
    if office_hint not in {"GCD", "MH"}:
        office_hint = None
    classified = classify_employee_remote(
        spoken_norm, environ=live_env, db_path=db_path, office_hint=office_hint,
    )
    kind = classified["kind"]
    if kind == "ambiguous":
        return _staff_confirm_payload(classified)
    if kind == "soft" and not confirm_staff:
        return _staff_confirm_payload(classified)
    if kind == "none":
        return _staff_confirm_payload(classified)
    if kind not in {"exact", "fold"} and not (kind == "soft" and confirm_staff):
        return _staff_confirm_payload(classified)

    canonical = classified["staff_name"]
    office_val = classified.get("office")
    changed_at = iso(parse_at(at)) if at else now_iso()
    with connect(db_path) as conn:
        before = get_setting(conn, "staff_name")
        _upsert_setting(conn, "staff_name", canonical, changed_at)
        office_result = None
        if office_val in {"GCD", "MH"}:
            before_office = get_setting(conn, "office")
            _upsert_setting(conn, "office", office_val, changed_at)
            office_result = {"previous": before_office, "value": office_val}
            log_event(
                conn,
                "config",
                f"set office to {office_val} from employees",
                "setting",
                None,
                before={"key": "office", "value": before_office},
                after={"key": "office", "value": office_val},
                at=changed_at,
            )
        log_event(
            conn,
            "config",
            f"set staff_name to {canonical}",
            "setting",
            None,
            before={"key": "staff_name", "value": before},
            after={"key": "staff_name", "value": canonical},
            at=changed_at,
        )
        conn.commit()
    result: dict[str, Any] = {
        "key": "staff_name",
        "value": canonical,
        "previous": before,
        "matched_employee": True,
        "match_kind": kind if kind in {"exact", "fold"} else "soft",
    }
    if office_result is not None:
        result["office"] = office_result
    return result


def staff_setup_status(db_path: str | Path) -> dict[str, Any]:
    """Hint for first-run: staff_name must match firm employees."""
    ensure_initialized(db_path)
    with connect(db_path) as conn:
        staff = (get_setting(conn, "staff_name") or "").strip()
        office = (get_setting(conn, "office") or "").strip()
    required = not staff or office not in {"GCD", "MH"}
    return {
        "required": required,
        "staff_name": staff or None,
        "office": office or None,
        "message": (
            "Set your identity with config staff_name (must match the firm employees list). "
            "Timmy cross-checks the name and sets office from that row."
            if required
            else "Staff identity is set."
        ),
    }


def list_employees(
    db_path: str | Path,
    *,
    query: str | None = None,
    confirm_full_list: bool = False,
    environ: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Read-only employee directory for setup. Prefer query; full list needs confirm."""
    live_env = _supabase_environ(environ)
    if live_env is None:
        raise ValueError(
            "list_employees requires SUPABASE_URL/SUPABASE_KEY (employees live in Supabase only)."
        )
    from .supabase_ref import list_employees_remote

    needle = (query or "").strip()
    if not needle and not confirm_full_list:
        return {
            "employees": [],
            "employee_count": None,
            "message": (
                "Pass query= to search the employees list, or confirm_full_list=true "
                "to load every active staff_name."
            ),
        }
    rows = list_employees_remote(environ=live_env, db_path=db_path, query=needle or None)
    return {
        "employees": [
            {k: row[k] for k in ("staff_name", "office", "first_name", "last_name") if row.get(k)}
            for row in rows
        ],
        "employee_count": len(rows),
    }


def clear_setting(db_path: str | Path, key: str, at: str | None = None) -> dict[str, Any]:
    ensure_initialized(db_path)
    changed_at = iso(parse_at(at)) if at else now_iso()
    with connect(db_path) as conn:
        before = get_setting(conn, key)
        conn.execute("DELETE FROM settings WHERE setting_key = ?", (key,))
        if key == "user_export_dir":
            _upsert_setting(conn, "user_export_dir_confirmed_at", changed_at, changed_at)
        log_event(conn, "config", f"cleared {key}", "setting", None, before={"key": key, "value": before}, after={"key": key, "value": None}, at=changed_at)
        export_folder = _export_folder_status_from_conn(conn) if key == "user_export_dir" else None
        conn.commit()
    result: dict[str, Any] = {"key": key, "value": None, "previous": before}
    if export_folder is not None:
        result["export_folder"] = export_folder
    return result


# Internal maintenance/setup bookkeeping kept in the settings table but hidden
# from the operator-facing config readout (they are not settings the operator
# edits directly).
_INTERNAL_SETTINGS = {"last_maintenance_at", "user_export_dir_confirmed_at"}


def list_settings(db_path: str | Path) -> dict[str, str]:
    ensure_initialized(db_path)
    with connect(db_path) as conn:
        rows = conn.execute("SELECT setting_key, setting_value FROM settings ORDER BY setting_key").fetchall()
    return {row["setting_key"]: row["setting_value"] for row in rows if row["setting_key"] not in _INTERNAL_SETTINGS}


def database_size_bytes(db_path: str | Path) -> int:
    base = Path(db_path)
    total = 0
    for candidate in (base, base.with_name(base.name + "-wal"), base.with_name(base.name + "-shm")):
        if candidate.exists():
            total += candidate.stat().st_size
    return total


def _human_size(num_bytes: int) -> str:
    size = float(num_bytes)
    for unit in ("B", "KB", "MB"):
        if size < 1024:
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} GB"  # anything >= 1024 MB


def database_status(db_path: str | Path) -> dict[str, Any]:
    ensure_initialized(db_path)
    counts = {"draft": 0, "approved": 0, "exported": 0, "needs_info": 0, "discarded": 0}
    with connect(db_path) as conn:
        for row in conn.execute("SELECT review_status, COUNT(*) AS c FROM time_entries GROUP BY review_status"):
            if row["review_status"] in counts:
                counts[row["review_status"]] = row["c"]
        total = conn.execute("SELECT COUNT(*) AS c FROM time_entries").fetchone()["c"]
        event_count = conn.execute("SELECT COUNT(*) AS c FROM event_log").fetchone()["c"]
        dates = conn.execute("SELECT MIN(substr(start_at, 1, 10)) AS mn, MAX(substr(start_at, 1, 10)) AS mx FROM time_entries").fetchone()
        retention = int(get_setting(conn, "audit_retention_days", "90"))
    counts["total"] = total
    size = database_size_bytes(db_path)
    backups_dir = Path(paths.default_backups_dir(db_path))
    backup_count = len(list(backups_dir.glob("timeassist-*.sqlite"))) if backups_dir.exists() else 0
    return {
        "db_path": str(db_path),
        "size_bytes": size,
        "size_human": _human_size(size),
        "entries": counts,
        "event_count": event_count,
        "oldest_entry_date": dates["mn"],
        "newest_entry_date": dates["mx"],
        "backup_count": backup_count,
        "audit_retention_days": retention,
    }


def cleanup_database(db_path: str | Path, retention_days: int | None = None, vacuum: bool = True, at: str | None = None) -> dict[str, Any]:
    ensure_initialized(db_path)
    now_value = at or now_iso()
    size_before = database_size_bytes(db_path)
    with connect(db_path) as conn:
        retention = retention_days if retention_days is not None else int(get_setting(conn, "audit_retention_days", "90"))
        if retention <= 0:
            raise ValueError("retention_days must be a positive integer")
        cutoff = iso(parse_at(now_value) - timedelta(days=retention))
        cur = conn.execute("DELETE FROM event_log WHERE created_at < ?", (cutoff,))
        pruned = cur.rowcount if cur.rowcount is not None else 0
        log_event(conn, "cleanup", f"pruned {pruned} audit event(s) older than {retention} days", "database", None, at=now_value)
        conn.commit()
    if vacuum:
        vacuum_db(db_path)
    size_after = database_size_bytes(db_path)
    return {"pruned_events": pruned, "retention_days": retention, "vacuumed": bool(vacuum), "size_before": size_before, "size_after": size_after}


def backup_stamp_suffix(path: Path) -> tuple[str, int] | None:
    match = re.fullmatch(r"timeassist-(\d{8}-\d{6})(?:-(\d+))?\.sqlite", path.name)
    if not match:
        return None
    stamp, suffix = match.groups()
    return stamp, int(suffix or "1")


def backup_sort_key(path: Path) -> tuple[str, int, str]:
    parsed = backup_stamp_suffix(path)
    if parsed is None:
        return (path.name, 0, path.name)
    stamp, suffix = parsed
    return (stamp, suffix, path.name)


def next_backup_path(backups_dir: Path, stamp: str) -> Path:
    existing_suffixes: list[int] = []
    for path in backups_dir.glob(f"timeassist-{stamp}*.sqlite"):
        parsed = backup_stamp_suffix(path)
        if parsed is not None and parsed[0] == stamp:
            existing_suffixes.append(parsed[1])
    if not existing_suffixes:
        return backups_dir / f"timeassist-{stamp}.sqlite"
    return backups_dir / f"timeassist-{stamp}-{max(existing_suffixes) + 1}.sqlite"


def backup_database(db_path: str | Path, keep: int = 5, at: str | None = None) -> dict[str, Any]:
    backups_dir = Path(paths.default_backups_dir(db_path))
    backups_dir.mkdir(parents=True, exist_ok=True)
    stamp = parse_at(at).strftime("%Y%m%d-%H%M%S")
    dest = next_backup_path(backups_dir, stamp)
    backup_db(db_path, dest)
    existing = sorted(backups_dir.glob("timeassist-*.sqlite"), key=backup_sort_key)
    removed: list[str] = []
    while len(existing) > keep:
        oldest = existing.pop(0)
        oldest.unlink()
        removed.append(str(oldest))
    return {"path": str(dest), "kept": len(existing), "removed": removed}


def client_label_values(display: str, aliases: str) -> list[str]:
    return [display, *[alias.strip() for alias in aliases.split(";") if alias.strip()]]


def validate_client_label_uniqueness(rows: list[tuple[str, str, str]]) -> None:
    seen_labels: dict[str, str] = {}
    for key, display, aliases in rows:
        for label in client_label_values(display, aliases):
            normalized_label = label.strip().lower()
            if not normalized_label:
                continue
            previous_key = seen_labels.get(normalized_label)
            if previous_key is not None and previous_key != key:
                raise ValueError(
                    f"duplicate client name/alias '{label}' appears for both '{previous_key}' and '{key}'; "
                    "make every display_name and alias unambiguous"
                )
            seen_labels[normalized_label] = key


LOCAL_ROSTER_DISABLED = (
    "Firm clients live only in Supabase (synced from QuickBooks). "
    "Local CSV import / add_client / refresh_clients are disabled. "
    "Matching is inside add_missing/start/switch against live Supabase; "
    "new clients use Unassigned + draft_reception_email."
)



def _local_roster_allowed() -> bool:
    """Test/demo only: import_clients / add_client into SQLite.

    Never used for list_clients or resolve — those are Supabase-only.
    Blocked when SUPABASE_URL+key are set (pilot MCP always has them).
    """
    import os
    if os.environ.get("TIMEASSIST_ALLOW_LOCAL_ROSTER") != "1":
        return False
    url = (os.environ.get("SUPABASE_URL") or "").strip()
    key = (
        (os.environ.get("SUPABASE_KEY") or "").strip()
        or (os.environ.get("SUPABASE_ANON_KEY") or "").strip()
        or (os.environ.get("SUPABASE_SECRET") or "").strip()
    )
    if url and key:
        return False
    return True


def _supabase_environ(
    environ: dict[str, str] | None = None,
) -> dict[str, str] | None:
    """Return an env mapping that has Supabase credentials, or None."""
    import os
    from .supabase_ref import credentials_from_env

    candidates: list[dict[str, str] | None] = [environ, dict(os.environ)]
    for env in candidates:
        if not env:
            continue
        try:
            credentials_from_env(env)
            return env
        except ValueError:
            continue
    return None


def import_clients(db_path: str | Path, csv_path: str | Path, mode: str = "replace", at: str | None = None) -> dict[str, Any]:
    if not _local_roster_allowed():
        raise ValueError(LOCAL_ROSTER_DISABLED)
    if mode not in {"replace", "merge"}:
        raise ValueError("mode must be 'replace' or 'merge'")
    ensure_initialized(db_path)
    changed_at = iso(parse_at(at)) if at else now_iso()
    path = Path(csv_path)
    if not path.exists():
        raise ValueError(f"clients file not found: {csv_path}")
    parsed: list[tuple[str, str, str, int, str]] = []
    seen_keys: dict[str, str] = {}
    seen_labels: dict[str, str] = {}
    # utf-8-sig strips the BOM that Excel's "CSV UTF-8" export prepends, which
    # would otherwise corrupt the first header (e.g. a phantom 'display_name').
    with path.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames or "display_name" not in reader.fieldnames:
            raise ValueError("clients CSV must have a 'display_name' column")
        for raw in reader:
            display = (raw.get("display_name") or "").strip()
            if not display:
                continue
            key = (raw.get("client_key") or "").strip() or slugify_client_key(display)
            # Two rows mapping to the same client_key (an explicit duplicate, or a
            # slugify collision like "Acme Co"/"Acme.Co" -> acme_co) would silently
            # overwrite one another. Fail loudly so no client is lost.
            if key in seen_keys:
                raise ValueError(
                    f"duplicate client_key '{key}' for '{seen_keys[key]}' and '{display}'; "
                    "give each client a unique client_key column"
                )
            seen_keys[key] = display
            aliases = (raw.get("aliases") or "").strip()
            labels = client_label_values(display, aliases)
            for label in labels:
                normalized_label = label.strip().lower()
                if not normalized_label:
                    continue
                previous_key = seen_labels.get(normalized_label)
                if previous_key is not None and previous_key != key:
                    raise ValueError(
                        f"duplicate client name/alias '{label}' appears for both '{previous_key}' and '{key}'; "
                        "make every display_name and alias unambiguous"
                    )
                seen_labels[normalized_label] = key
            parsed.append((key, display, aliases, parse_billable_flag(raw.get("default_billable")),
                           (raw.get("default_job_type") or "").strip()))
    with connect(db_path) as conn:
        if mode == "merge":
            incoming_keys = {key for key, _display, _aliases, _default_billable, _default_job_type in parsed}
            existing_rows = conn.execute(
                "SELECT client_key, display_name, aliases FROM clients ORDER BY client_key"
            ).fetchall()
            final_rows = [
                (row["client_key"], row["display_name"], row["aliases"] or "")
                for row in existing_rows
                if row["client_key"] not in incoming_keys
            ]
            final_rows.extend((key, display, aliases) for key, display, aliases, _default_billable, _default_job_type in parsed)
            validate_client_label_uniqueness(final_rows)
        if mode == "replace":
            conn.execute("DELETE FROM clients")
        # billable_locked = 0 on update is the ownership transfer: an operator CSV row for
        # a seeded admin key unlocks it, matching replace-mode behavior (operator wins).
        for key, display, aliases, default_billable, default_job_type in parsed:
            conn.execute(
                """
                INSERT INTO clients(client_key, display_name, aliases, default_billable, default_job_type, billable_locked, updated_at)
                VALUES (?, ?, ?, ?, ?, 0, ?)
                ON CONFLICT(client_key) DO UPDATE SET
                    display_name = excluded.display_name,
                    aliases = excluded.aliases,
                    default_billable = excluded.default_billable,
                    default_job_type = excluded.default_job_type,
                    billable_locked = 0,
                    updated_at = excluded.updated_at
                """,
                (key, display, aliases, default_billable, default_job_type, changed_at),
            )
        clients = [row_to_dict(r) for r in conn.execute("SELECT * FROM clients ORDER BY display_name").fetchall()]
        log_event(conn, "import_clients", f"imported {len(parsed)} client(s) ({mode})", "clients", None, after={"count": len(parsed), "mode": mode}, at=changed_at)
        conn.commit()
    return {"mode": mode, "imported_count": len(parsed), "clients": clients}


def add_client(db_path: str | Path, display_name: str, aliases: str = "",
               default_billable: str | None = None, default_job_type: str = "",
               client_key: str | None = None, at: str | None = None) -> dict[str, Any]:
    """Add ONE new client to the local roster (test escape hatch only)."""
    if not _local_roster_allowed():
        raise ValueError(LOCAL_ROSTER_DISABLED)
    ensure_initialized(db_path)
    changed_at = iso(parse_at(at)) if at else now_iso()
    display = (display_name or "").strip()
    if not display:
        raise ValueError("display_name is required")
    key = (client_key or "").strip() or slugify_client_key(display)
    aliases_value = (aliases or "").strip()
    with connect(db_path) as conn:
        existing = conn.execute("SELECT client_key, display_name, aliases FROM clients ORDER BY client_key").fetchall()
        for row in existing:
            if row["client_key"] == key:
                raise ValueError(
                    f"client_key '{key}' already exists for '{row['display_name']}'; "
                    "add_client only adds new clients — use import_clients to update the roster"
                )
        final_rows = [(row["client_key"], row["display_name"], row["aliases"] or "") for row in existing]
        final_rows.append((key, display, aliases_value))
        validate_client_label_uniqueness(final_rows)
        conn.execute(
            "INSERT INTO clients(client_key, display_name, aliases, default_billable, default_job_type, billable_locked, updated_at) VALUES (?, ?, ?, ?, ?, 0, ?)",
            (key, display, aliases_value, parse_billable_flag(default_billable), (default_job_type or "").strip(), changed_at),
        )
        client = row_to_dict(conn.execute("SELECT * FROM clients WHERE client_key = ?", (key,)).fetchone())
        count = conn.execute("SELECT COUNT(*) AS c FROM clients").fetchone()["c"]
        log_event(conn, "add_client", f"added client {display}", "clients", None, after={"client_key": key}, at=changed_at)
        conn.commit()
    return {"client": client, "client_count": count}


def refresh_clients(db_path: str | Path, at: str | None = None, environ: dict[str, str] | None = None) -> dict[str, Any]:
    """GET clients from Supabase and merge into local SQLite (test escape hatch only)."""
    if not _local_roster_allowed():
        raise ValueError(LOCAL_ROSTER_DISABLED)
    from .supabase_ref import client_display_name, get_clients

    ensure_initialized(db_path)
    changed_at = iso(parse_at(at)) if at else now_iso()
    remote = get_clients(environ=environ, db_path=db_path)
    parsed: list[tuple[str, str]] = []
    seen: dict[str, str] = {}
    for row in remote:
        display = client_display_name(row)
        if not display:
            continue
        key = slugify_client_key(display)
        if key in seen and seen[key] != display:
            raise ValueError(f"duplicate client_key '{key}' for '{seen[key]}' and '{display}'")
        seen[key] = display
        parsed.append((key, display))
    with connect(db_path) as conn:
        for key, display in parsed:
            conn.execute(
                """
                INSERT INTO clients(client_key, display_name, aliases, default_billable, default_job_type, billable_locked, updated_at)
                VALUES (?, ?, '', 1, '', 0, ?)
                ON CONFLICT(client_key) DO UPDATE SET
                    display_name = excluded.display_name,
                    updated_at = excluded.updated_at
                """,
                (key, display, changed_at),
            )
        count = conn.execute("SELECT COUNT(*) AS c FROM clients").fetchone()["c"]
        log_event(conn, "refresh_clients", f"merged {len(parsed)} remote client(s)", "clients", None, after={"imported_count": len(parsed)}, at=changed_at)
        conn.commit()
    return {"imported_count": len(parsed), "client_count": count}



def name_fold(name: str) -> str:
    from .supabase_ref import name_fold as _name_fold
    return _name_fold(name)



def _resolve_client_row_local(conn, name: str):
    """Return the full roster row a label resolves to, or None (needs_info).

    All matching passes live here so callers share one deterministic order:
    exact display name wins over any alias, then a comma-swap fold so
    'John Smith' matches roster 'Smith, John'. `resolve_client` and the
    capture resolvers are thin wrappers over this.
    """
    target = name.strip().lower()
    # Deterministic order, and an exact display-name match always wins over an
    # alias match (even another client's alias) — so two passes, exact first.
    rows = conn.execute("SELECT * FROM clients ORDER BY client_key").fetchall()
    for row in rows:
        if row["display_name"].strip().lower() == target:
            return row
    for row in rows:
        aliases = [a.strip().lower() for a in (row["aliases"] or "").split(";") if a.strip()]
        if target in aliases:
            return row
    # Third pass: comma-swap fold so 'John Smith' matches roster 'Smith, John'
    # (and vice versa). Display names only; aliases stay exact-match above.
    folded_target = name_fold(name)
    fold_matches = [row for row in rows if name_fold(row["display_name"]) == folded_target]
    if len(fold_matches) == 1:
        return fold_matches[0]
    # 0 or >1 fold matches: never guess between people — fall through (needs_info).
    # Management-shell protection (pilot feedback #34) is inherent here: a
    # "... Management" roster entry is only ever billed on an exact match of its
    # full name, so ambiguous input never lands on the shell — pinned by
    # ManagementTiebreakTests. (An explicit fourth tiebreak pass was implemented
    # and removed as unreachable dead code; do not reintroduce it.)
    return None


def _resolve_client_local(conn, name: str) -> tuple[str, int | None]:
    """Thin wrapper preserving the historic (display_name, default_billable|None)
    tuple API; all matching logic lives in `resolve_client_row`."""
    row = _resolve_client_row_local(conn, name)
    if row is None:
        return name, None
    return row["display_name"], int(row["default_billable"])




def _unassigned_known_row(
    name: str,
    *,
    db_path: str | Path | None,
    environ: dict[str, str] | None,
):
    """Treat configured Unassigned as known even if the live roster row is briefly missing."""
    from .supabase_config import unassigned_client_name
    from .supabase_ref import roster_row_from_display

    label = unassigned_client_name(db_path=db_path, environ=environ)
    if name.strip().casefold() == label.casefold():
        return roster_row_from_display(label)
    return None


def resolve_client_row(conn, name: str, *, environ: dict[str, str] | None = None, db_path: str | Path | None = None):
    """Match spoken name against live Supabase clients only.

    Never reads the local SQLite ``clients`` table (stale CSV imports). Test
    suites without Supabase credentials may set TIMEASSIST_ALLOW_LOCAL_ROSTER=1
    to use SQLite; the pilot MCP always has Supabase env so that path is dead.

    The configured holding-bucket name (default ``Unassigned``) resolves as known
    even when the live Supabase row is briefly missing — seed it in Supabase only
    (not QuickBooks); replace later via ``edit`` once the real client exists.
    """
    # Capture looks up the full firm roster (both offices). Submit still stamps
    # settings.office onto Supabase — lookup must not hide cross-office clients.
    live_env = _supabase_environ(environ)
    if live_env is not None:
        from .supabase_ref import resolve_client_remote, roster_row_from_display
        resolved_db = db_path or _sqlite_file_from_conn(conn)
        display = resolve_client_remote(
            name, environ=live_env, office=None, db_path=resolved_db,
        )
        if display is None:
            return _unassigned_known_row(name, db_path=resolved_db, environ=live_env)
        return roster_row_from_display(display)
    if _local_roster_allowed():
        row = _resolve_client_row_local(conn, name)
        if row is not None:
            return row
        resolved_db = db_path or _sqlite_file_from_conn(conn)
        return _unassigned_known_row(name, db_path=resolved_db, environ=environ)
    from .supabase_ref import resolve_client_remote, roster_row_from_display
    resolved_db = db_path or _sqlite_file_from_conn(conn)
    display = resolve_client_remote(
        name, environ=environ, office=None, db_path=resolved_db,
    )
    if display is None:
        return _unassigned_known_row(name, db_path=resolved_db, environ=environ)
    return roster_row_from_display(display)


def client_confirm_gate(
    conn,
    client: str,
    *,
    confirm_client: bool = False,
    environ: dict[str, str] | None = None,
    db_path: str | Path | None = None,
) -> dict[str, Any] | None:
    """If live soft/unmatched needs operator confirmation, return a no-write payload.

    Exact / comma-fold hits resolve silently. Soft unique hits and total misses
    return ``needs_client_confirm`` so Timmy asks before writing time.
    """
    live_env = _supabase_environ(environ)
    if live_env is None and _local_roster_allowed():
        return None
    if confirm_client:
        return None
    from .supabase_config import unassigned_client_name
    from .supabase_ref import classify_client_remote, list_clients_remote, top_client_choices

    resolved_db = db_path or _sqlite_file_from_conn(conn)
    classified = classify_client_remote(
        client, environ=live_env, office=None, db_path=resolved_db,
    )
    spoken = classified["spoken"] or client.strip()
    kind = classified["kind"]
    if kind in {"exact", "fold"}:
        return None
    unassigned = unassigned_client_name(db_path=resolved_db, environ=live_env)
    if spoken.casefold() == unassigned.casefold():
        return None

    roster_names = [
        row["display_name"]
        for row in list_clients_remote(
            environ=live_env, office=None, db_path=resolved_db,
        )
        if row.get("display_name")
        and str(row["display_name"]).casefold() != unassigned.casefold()
    ]
    prefer = classified.get("display_name") if kind == "soft" else None
    choices = top_client_choices(spoken, roster_names, limit=3, prefer=prefer)

    if_new = {
        "client": unassigned,
        "notes_prefix": f"NEW CLIENT: {spoken} | ",
        "draft_reception_email": True,
    }
    if kind == "soft":
        suggested = classified["display_name"]
        return {
            "needs_client_confirm": True,
            "match_kind": "soft",
            "spoken_client": spoken,
            "suggested_client": suggested,
            "choices": choices,
            "other_label": "Other",
            "ask": (
                f'Please select the correct client for "{spoken}" '
                f"(choices include the closest roster matches, or Other for a new client / Unassigned)."
            ),
            "if_yes": {
                "retry_with_client": suggested,
                "or_confirm_client": True,
            },
            "if_new_client": if_new,
        }
    return {
        "needs_client_confirm": True,
        "match_kind": "none",
        "spoken_client": spoken,
        "suggested_client": None,
        "choices": choices,
        "other_label": "Other",
        "ask": (
            f'No exact match on the firm client list for "{spoken}". '
            f"Please select from the closest matches, or Other for a new client "
            f'(held under "{unassigned}" with a NEW CLIENT note).'
        ),
        "if_yes": None,
        "if_new_client": if_new,
    }


def _sqlite_file_from_conn(conn) -> str | None:
    try:
        row = conn.execute("PRAGMA database_list").fetchone()
    except Exception:
        return None
    if row is None:
        return None
    # (seq, name, file) — file may be empty for :memory:
    path = row[2] if not isinstance(row, dict) else row["file"]
    return path or None


def resolve_client(conn, name: str, *, environ: dict[str, str] | None = None, db_path: str | Path | None = None) -> tuple[str, int | None]:
    row = resolve_client_row(conn, name, environ=environ, db_path=db_path)
    if row is None:
        return name, None
    return row["display_name"], int(row["default_billable"])


def list_clients(
    db_path: str | Path,
    environ: dict[str, str] | None = None,
    query: str | None = None,
    *,
    confirm_full_list: bool = False,
) -> dict[str, Any]:
    """Live GET of Supabase clients only — never reads the local SQLite clients table.

    Empty ``query`` without ``confirm_full_list`` returns no names (count + message).
    """
    ensure_initialized(db_path)
    from .supabase_ref import list_clients_remote

    live_env = _supabase_environ(environ)
    if live_env is None and not _local_roster_allowed():
        # Force the credentials error from the live client.
        live_env = environ
    elif live_env is None and _local_roster_allowed():
        # Tests without Supabase: still do not dump SQLite via this API.
        raise ValueError(
            "list_clients is Supabase-only. Set SUPABASE_URL/SUPABASE_KEY, or mock "
            "timeassist.supabase_ref.get_clients in tests (install_live_clients)."
        )

    q = (query or "").strip()
    want_full = bool(confirm_full_list)
    # Full firm roster (both offices) — operators bounce between GCD and MH clients.
    if not q and not want_full:
        count = len(list_clients_remote(environ=live_env, office=None, db_path=db_path))
        return {
            "clients": [],
            "client_count": count,
            "message": (
                "Pass query with the spoken client name (required). "
                "Do not dump the full list. Prefer add_missing/start/switch — "
                "soft matches return needs_client_confirm "
                "(e.g. Ocean View Road -> ask about 0969 Ocean View Road). "
                "Full list only with confirm_full_list=true when the operator asked."
            ),
        }
    clients = list_clients_remote(
        environ=live_env,
        office=None,
        db_path=db_path,
        query=None if want_full and not q else q,
    )
    return {"clients": clients, "client_count": len(clients)}


# Special clients still get job-code defaults; billable is no longer forced.
SPECIAL_CLIENT_POLICY: dict[str, dict[str, Any]] = {
    "admin": {"auto_job": False, "job_code": "Administrative"},
    "vacation": {"auto_job": True, "job_code": "Administrative"},
    "holiday": {"auto_job": True, "job_code": "Administrative"},
    "early out": {"auto_job": True, "job_code": "Administrative"},
    "staff meeting": {"auto_job": True, "job_code": "Administrative"},
}


def special_client_policy(display_name: str | None) -> dict[str, Any] | None:
    """Firm special clients: job code auto or suggest-only (billable unused)."""
    if not display_name:
        return None
    return SPECIAL_CLIENT_POLICY.get(display_name.strip().casefold())


def apply_client_policy(
    row: sqlite3.Row | None,
    billable_requested: str | bool | None,
    job_type_requested: str | None,
    *,
    current_billable: int | None = None,
    current_job_type: str | None = None,
) -> tuple[int, str]:
    """Client policy for job codes. Billable is always yes (firm no longer tracks it).

    job_type_requested None = preserve current (then special auto_job if still blank);
    "" = explicit clear; any other string wins.
    """
    _ = billable_requested, current_billable  # accepted but ignored
    display = row["display_name"] if row is not None else None
    special = special_client_policy(display)
    billable = 1

    if job_type_requested is None:
        job_type = (current_job_type or "").strip()
        if special is not None and special.get("auto_job") and not job_type:
            job_type = str(special.get("job_code") or "Administrative")
    else:
        job_type = (job_type_requested or "").strip()

    return billable, job_type


def resolve_capture_with_metadata(
    conn,
    client: str,
    task: str,
    billable: str | bool | None,
    *,
    clarification: bool = False,
    job_type: str | None = None,
    current_job_type: str | None = None,
    environ: dict[str, str] | None = None,
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    """Resolve a capture while preserving the user's raw switch/clarify text.

    Unknown roster labels never block capture. For initial switch capture they are
    marked needs_info so review/export can surface them; an explicit clarify/edit
    with billable intent can resolve the pending metadata without changing time.
    Billable/job_type policy is enforced once, in `apply_client_policy`: an explicit
    job_type wins ("" clears), else the caller's `current_job_type` is preserved,
    else job_type stays blank (roster default is suggestion-only) except specials
    with auto_job.
    """
    raw_client = client.strip()
    raw_task = task.strip()
    row = resolve_client_row(conn, raw_client, environ=environ, db_path=db_path)
    canonical = row["display_name"] if row is not None else raw_client
    billable_explicit = billable is not None
    billable_int, job_type_resolved = apply_client_policy(
        row, billable, job_type, current_job_type=current_job_type)
    known_client = row is not None
    # `clarification and billable_explicit` below is the confirm-as-is escape
    # hatch (both edit and clarify_active funnel deliberate confirmations here
    # with an explicit billable). strict_roster is firm policy that closes it:
    # a needs_info entry may only resolve to a roster name (issue #39 item 1,
    # Decision 1 = C). Plain capture (clarification=False) never raises —
    # capture-now/clarify-later is an invariant under every mode.
    if not known_client and clarification and billable_explicit and strict_roster_enabled(conn):
        raise ValueError(
            f"strict roster mode is on: '{raw_client}' is not on the firm client list; "
            "correct the entry to a known client, or use Unassigned + draft_reception_email for a new firm client"
        )
    needs_info = not known_client and not (clarification and billable_explicit)
    client_changed = canonical.strip().lower() != raw_client.lower()
    # Do not echo the client label into notes (senior feedback #2).
    task_text = raw_task
    if raw_task and not raw_task.upper().startswith("NEW CLIENT:"):
        if raw_task.casefold() in {raw_client.casefold(), canonical.casefold()}:
            task_text = ""
    suggested = ""
    special = special_client_policy(canonical)
    if special and not special["auto_job"] and not (job_type_resolved or "").strip():
        suggested = str(special["job_code"])
    elif row is not None and not int(row["billable_locked"]):
        suggested = (row["default_job_type"] or "").strip()
    result = {
        "client_name": canonical,
        "task_text": task_text,
        "billable": billable_int,
        "job_type": job_type_resolved,
        "raw_client_name": raw_client if (client_changed or needs_info) else None,
        "raw_task_text": raw_task,
        "capture_status": "needs_info" if needs_info else "resolved",
        "capture_note": "client_not_in_roster" if needs_info else None,
        "clarified_at": None,
    }
    if suggested and not (job_type_resolved or "").strip():
        result["suggested_job_type"] = suggested
    return result


def _attach_suggested_job_type(conn, payload: dict[str, Any], *, remote: bool = True) -> dict[str, Any]:
    """Add suggested_job_type when stored job_type is blank (suggestion only)."""
    if (payload.get("job_type") or "").strip():
        return payload
    if payload.get("suggested_job_type"):
        return payload
    client_name = payload.get("client_name")
    if not client_name:
        return payload
    special = special_client_policy(client_name)
    if special and not special["auto_job"]:
        payload["suggested_job_type"] = str(special["job_code"])
        return payload
    if not remote:
        return payload
    row = resolve_client_row(conn, client_name)
    if row is None or int(row["billable_locked"]):
        return payload
    suggested = (row["default_job_type"] or "").strip()
    if suggested:
        payload["suggested_job_type"] = suggested
    return payload


def capture_note_text(note: str | None, client_name: str | None = None) -> str | None:
    """Human wording for stored capture-note tokens (storage keeps the token)."""
    if not note:
        return None
    # duration_only may be combined with other tokens via ';'
    primary = note.split(";")[0].strip()
    if primary == "client_not_in_roster":
        return f"client '{client_name}' is not in the roster" if client_name else "client is not in the roster"
    if primary == "duration_only":
        return None
    return note


def needs_review_reason(entry: dict[str, Any]) -> str | None:
    if entry.get("capture_status") == "needs_info":
        return capture_note_text(entry.get("capture_note"), entry.get("client_name")) or "needs_info"
    return None


def row_to_dict(row: Any) -> dict[str, Any]:
    return dict(row) if row is not None else {}


def bool_to_int(value: str | bool) -> int:
    if isinstance(value, bool):
        return 1 if value else 0
    return 1 if value.strip().lower() == "yes" else 0


# Lenient billable parsing for imported rosters: accountants hand-write CSVs and
# naturally use true/false, 1/0, y/n — not just yes/no. Unrecognized or blank
# values fall back to billable (the roster default), matching "absent -> yes".
_BILLABLE_FALSY = {"no", "false", "0", "n", "f"}
_BILLABLE_TRUTHY = {"yes", "true", "1", "y", "t"}


def parse_billable_flag(value: str | None, default: int = 1) -> int:
    if value is None:
        return default
    token = value.strip().lower()
    if not token:
        return default
    if token in _BILLABLE_FALSY:
        return 0
    if token in _BILLABLE_TRUTHY:
        return 1
    return default


def normalize_strict_roster(value: str) -> str:
    """Store strict_roster as canonical yes/no; reject anything unrecognized so
    a typo can't silently leave the firm policy off (v0.1.22 rounding pattern)."""
    token = (value or "").strip().lower()
    if token in _BILLABLE_TRUTHY or token == "on":
        return "yes"
    if token in _BILLABLE_FALSY or token == "off":
        return "no"
    raise ValueError(f"strict_roster must be yes or no, got: {value}")


def strict_roster_enabled(conn) -> bool:
    return (get_setting(conn, "strict_roster", "no") or "no").strip().lower() in _BILLABLE_TRUTHY


_OPERATOR_CODE_RE = re.compile(r"^[A-Z]{2,4}$")


def normalize_staff_name(value: str) -> str:
    token = (value or "").strip()
    if not token:
        raise ValueError("staff_name is not set; run config with staff_name before submit")
    return token


def normalize_office(value: str) -> str:
    token = (value or "").strip().upper()
    if token not in {"GCD", "MH"}:
        raise ValueError("office must be GCD or MH; run config before submit")
    return token


def normalize_reception_email(value: str) -> str:
    token = (value or "").strip()
    if not token or "@" not in token:
        raise ValueError("reception_email must be a non-empty email address")
    return token


def draft_reception_email_for_db(
    db_path: str | Path,
    spoken_client_name: str,
) -> dict[str, Any]:
    """Build a Reception email draft from local settings. Never sends."""
    from .reception_email_draft import draft_reception_email

    ensure_initialized(db_path)
    with connect(db_path) as conn:
        staff = (get_setting(conn, "staff_name") or "").strip() or "Staff"
        office = (get_setting(conn, "office") or "").strip() or "GCD"
        to_email = get_setting(conn, "reception_email")
    return draft_reception_email(
        spoken_client_name=spoken_client_name,
        staff_name=staff,
        office=office,
        to_email=to_email,
    )


def normalize_operator_code(value: str) -> str:
    token = (value or "").strip().upper()
    if not _OPERATOR_CODE_RE.match(token):
        raise ValueError(
            f"operator_code must be 2-4 letters (your initials code on the firm's employee list), got: {value}"
        )
    return token


def get_operator_code(conn) -> str | None:
    value = (get_setting(conn, "operator_code") or "").strip().upper()
    return value or None


def default_export_filename(db_path: str | Path, date_value: str, end_date: str | None = None) -> str:
    ensure_initialized(db_path)
    with connect(db_path) as conn:
        code = get_operator_code(conn)
    return paths.default_export_path(date_value, end_date=end_date, operator_code=code)


def billable_text(value: int) -> str:
    return "Yes" if value else "No"


def format_hhmm(minutes: int) -> str:
    # Display-only H:MM rendering of stored integer minutes. The engine keeps
    # billing in whole minutes; this never changes the rounding floor.
    return f"{minutes // 60}:{minutes % 60:02d}"


def csv_safe(value: Any) -> str:
    # Defuse CSV/spreadsheet formula injection: Excel/Sheets/QuickBooks treat a
    # cell starting with = + - @ (including after leading whitespace/control
    # characters) as a live formula. Prefix such values with an apostrophe so
    # they import as plain text.
    text = str(value)
    stripped = text.lstrip(" \t\r\n")
    return "'" + text if stripped[:1] in ("=", "+", "-", "@") or text[:1] in ("\t", "\r") else text


def log_event(conn, event_type: str, input_summary: str, object_type: str | None = None, object_id: int | None = None, before: dict | None = None, after: dict | None = None, at: str | None = None) -> None:
    conn.execute(
        """
        INSERT INTO event_log(event_type, actor, input_summary, object_type, object_id, before_json, after_json, created_at)
        VALUES (?, 'cli', ?, ?, ?, ?, ?, ?)
        """,
        (
            event_type,
            input_summary,
            object_type,
            object_id,
            json.dumps(before, sort_keys=True) if before is not None else None,
            json.dumps(after, sort_keys=True) if after is not None else None,
            at or now_iso(),
        ),
    )


def _maybe_daily_prune(db_path: str | Path) -> None:
    # Cheap guard: run a silent audit-log prune at most once per 24h. Uses raw
    # SQL (not set_setting/ensure_initialized) to avoid re-entrancy. Never logs
    # an event and never touches time_entries. Pruning is wall-clock maintenance,
    # so it uses real time, independent of any caller-supplied logical `at`.
    now_value = now_iso()
    with connect(db_path) as conn:
        last_row = conn.execute("SELECT setting_value FROM settings WHERE setting_key = 'last_maintenance_at'").fetchone()
        if last_row is not None:
            try:
                elapsed = (parse_at(now_value) - parse_at(last_row["setting_value"])).total_seconds()
            except ValueError:
                elapsed = None
            if elapsed is not None and elapsed < 86400:
                return
        retention_row = conn.execute("SELECT setting_value FROM settings WHERE setting_key = 'audit_retention_days'").fetchone()
        retention = int(retention_row["setting_value"]) if retention_row else 90
        cutoff = iso(parse_at(now_value) - timedelta(days=retention))
        conn.execute("DELETE FROM event_log WHERE created_at < ?", (cutoff,))
        conn.execute(
            """
            INSERT INTO settings(setting_key, setting_value, scope, updated_at)
            VALUES ('last_maintenance_at', ?, 'local', ?)
            ON CONFLICT(setting_key) DO UPDATE SET setting_value = excluded.setting_value, updated_at = excluded.updated_at
            """,
            (now_value, now_value),
        )
        conn.commit()


def ensure_initialized(db_path: str | Path, at: str | None = None) -> None:
    initialize(db_path, at or now_iso())
    _maybe_daily_prune(db_path)


def init_state(db_path: str | Path, at: str | None = None) -> dict[str, Any]:
    created_at = at or now_iso()
    initialize(db_path, created_at)
    with connect(db_path) as conn:
        log_event(conn, "init", "initialized local TimeAssist state", "database", None, at=created_at)
        export_folder = _export_folder_status_from_conn(conn)
        conn.commit()
    return {
        "database": str(db_path),
        "created_at": created_at,
        "export_folder": export_folder,
        "staff_setup": staff_setup_status(db_path),
    }


def get_active_session(conn) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT * FROM active_sessions WHERE status = 'active' ORDER BY session_id DESC LIMIT 1"
    ).fetchone()
    return row_to_dict(row) if row else None


def resolve_planned_end(
    started_at: str,
    duration_minutes: int | None = None,
    planned_end_at: str | None = None,
) -> str | None:
    has_minutes = duration_minutes is not None
    has_stamp = bool((planned_end_at or "").strip())
    if has_minutes and has_stamp:
        raise ValueError("pass duration_minutes or planned_end_at, not both")
    started = parse_at(started_at)
    cap = iso(started + timedelta(minutes=TEST_MAX_SESSION_MINUTES))
    result: str | None = None
    if has_minutes:
        minutes = int(duration_minutes)
        if minutes <= 0:
            raise ValueError("duration_minutes must be greater than zero")
        result = iso(started + timedelta(minutes=minutes))
    elif has_stamp:
        ended = iso(parse_at(planned_end_at))
        if parse_at(ended) <= started:
            raise ValueError("planned_end_at must be after the session start")
        result = ended
    # Hard cap: always enforce start + TEST_MAX_SESSION_MINUTES ceiling.
    if result is None or parse_at(result) > parse_at(cap):
        return cap
    return result


def _insert_active_session(
    conn,
    capture: dict[str, Any],
    started_at: str,
    planned_end_at: str | None = None,
) -> int:
    """One INSERT for both start and switch, so the capture-column list can
    never drift between them (schema adds via ALTER ... DEFAULT would silently
    diverge a forgotten copy)."""
    cur = conn.execute(
        """
        INSERT INTO active_sessions(
            client_name, task_text, billable, job_type, started_at, raw_client_name,
            raw_task_text, capture_status, capture_note, clarified_at,
            last_checkin_at, planned_end_at, status, created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?)
        """,
        (
            capture["client_name"], capture["task_text"], capture["billable"],
            capture["job_type"], started_at, capture["raw_client_name"],
            capture["raw_task_text"], capture["capture_status"], capture["capture_note"],
            capture["clarified_at"], started_at, planned_end_at, started_at, started_at,
        ),
    )
    return cur.lastrowid


def _sync_currently_working(
    kind: str,
    db_path: str | Path,
    session: dict[str, Any] | None = None,
    *,
    at: str | None = None,
) -> dict[str, Any]:
    """Best-effort ticker sync. Never raises into the local timer path."""
    try:
        from . import currently_working as live

        if kind == "upsert":
            live.upsert_active(db_path, session or {})
            live.schedule_auto_end(db_path, (session or {}).get("planned_end_at"))
        else:
            live.cancel_auto_end()
            live.close_live(db_path, status=kind, updated_at=at)
        return {"ok": True, "action": kind}
    except Exception as exc:
        # Local timer remains authority; surface a short error so Timmy can warn.
        return {"ok": False, "action": kind, "error": str(exc).replace("\n", " ").strip()[:240]}


def maybe_end_overdue_planned(db_path: str | Path, at: str | None = None) -> dict[str, Any] | None:
    """If planned_end_at has passed, close at that stamp (draft locally). Heartbeat + timer."""
    ensure_initialized(db_path)
    checked = iso(parse_at(at)) if at else now_iso()
    with connect(db_path) as conn:
        active = get_active_session(conn)
        planned = (active or {}).get("planned_end_at") if active else None
        if not active or not planned:
            return None
        if parse_at(checked) < parse_at(planned):
            return None
    return end_session(db_path, planned)


def start_session(
    db_path: str | Path,
    client: str,
    task: str,
    billable: str | None = None,
    at: str | None = None,
    job_type: str | None = None,
    *,
    confirm_client: bool = False,
    duration_minutes: int | None = None,
    planned_end_at: str | None = None,
) -> dict[str, Any]:
    ensure_initialized(db_path)
    maybe_end_overdue_planned(db_path, at)
    started = iso(parse_at(at)) if at else now_iso()
    planned = resolve_planned_end(started, duration_minutes, planned_end_at)
    with connect(db_path) as conn:
        pending = client_confirm_gate(
            conn, client, confirm_client=confirm_client, db_path=db_path,
        )
        if pending:
            return pending
        active = get_active_session(conn)
        if active:
            raise ValueError(
                f"a timer is already running for {active['client_name']} — {active['task_text']} "
                f"(started {active['started_at']}); use switch to change clients or end to stop it"
            )
        capture = resolve_capture_with_metadata(conn, client, task, billable, job_type=job_type)
        try:
            session_id = _insert_active_session(conn, capture, started, planned)
        except sqlite3.IntegrityError as exc:
            raise ValueError("active session already exists; use switch or end first") from exc
        session = row_to_dict(conn.execute("SELECT * FROM active_sessions WHERE session_id = ?", (session_id,)).fetchone())
        if capture.get("suggested_job_type"):
            session["suggested_job_type"] = capture["suggested_job_type"]
        log_event(conn, "start", f"started {capture['client_name']}: {capture['task_text']}", "active_session", session["session_id"], after=session, at=started)
        conn.commit()
    session["currently_working_sync"] = _sync_currently_working("upsert", db_path, session)
    return session


def close_active_session(conn, ended: str) -> dict[str, Any]:
    active = get_active_session(conn)
    if not active:
        raise ValueError("no active session to end")
    duration = minutes_between(active["started_at"], ended)
    rounded = round_minutes(duration, *get_rounding(conn))
    capture_status = active.get("capture_status") or "resolved"
    review_status = "needs_info" if capture_status == "needs_info" else "draft"
    cur = conn.execute(
        """
        INSERT INTO time_entries(
            client_name, task_text, billable, job_type, start_at, end_at, duration_minutes,
            rounded_minutes, review_status, raw_client_name, raw_task_text,
            capture_status, capture_note, clarified_at, created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            active["client_name"],
            active["task_text"],
            active["billable"],
            active.get("job_type", ""),
            active["started_at"],
            ended,
            duration,
            rounded,
            review_status,
            active.get("raw_client_name"),
            active.get("raw_task_text"),
            capture_status,
            active.get("capture_note"),
            active.get("clarified_at"),
            ended,
            ended,
        ),
    )
    conn.execute(
        "UPDATE active_sessions SET status = 'closed', updated_at = ? WHERE session_id = ?",
        (ended, active["session_id"]),
    )
    entry = row_to_dict(conn.execute("SELECT * FROM time_entries WHERE entry_id = ?", (cur.lastrowid,)).fetchone())
    log_event(conn, "end", f"closed {active['client_name']}: {active['task_text']}", "time_entry", entry["entry_id"], before=active, after=entry, at=ended)
    return entry


def _notes_missing(task_text: str | None) -> bool:
    return not (task_text or "").strip()


def _flag_missing_notes(entry: dict[str, Any]) -> dict[str, Any]:
    # #34: nudge (never gate) when Notes were skipped. Result signal only — not a stored
    # column, and never persisted: callers must apply this AFTER their log_event calls so
    # the flag stays out of event_log snapshots.
    if _notes_missing(entry.get("task_text")):
        entry["notes_missing"] = True
    return entry


def end_session(db_path: str | Path, at: str | None = None) -> dict[str, Any]:
    ensure_initialized(db_path)
    ended = iso(parse_at(at)) if at else now_iso()
    with connect(db_path) as conn:
        entry = close_active_session(conn, ended)
        conn.commit()
    entry = _flag_missing_notes(entry)
    entry["currently_working_sync"] = _sync_currently_working("closed", db_path, at=ended)
    return entry


def switch_session(
    db_path: str | Path,
    client: str,
    task: str,
    billable: str | None = None,
    at: str | None = None,
    minutes_ago: int | None = None,
    job_type: str | None = None,
    *,
    confirm_client: bool = False,
    duration_minutes: int | None = None,
    planned_end_at: str | None = None,
) -> dict[str, Any]:
    ensure_initialized(db_path)
    switched_dt = parse_at(at)
    if minutes_ago is not None:
        offset = int(minutes_ago)
        if offset <= 0:
            raise ValueError("minutes_ago must be greater than zero")
        switched_dt = switched_dt - timedelta(minutes=offset)
    switched_at = iso(switched_dt)
    planned = resolve_planned_end(switched_at, duration_minutes, planned_end_at)
    with connect(db_path) as conn:
        pending = client_confirm_gate(
            conn, client, confirm_client=confirm_client, db_path=db_path,
        )
        if pending:
            return pending
        active = get_active_session(conn)
        if active and parse_at(switched_at) < parse_at(active["started_at"]):
            raise ValueError(
                f"that switch time ({switched_at}) is before the current timer started "
                f"({active['started_at']}); confirm when the switch actually happened"
            )
        closed = close_active_session(conn, switched_at)
        capture = resolve_capture_with_metadata(conn, client, task, billable, job_type=job_type)
        session_id = _insert_active_session(conn, capture, switched_at, planned)
        new_session = row_to_dict(conn.execute("SELECT * FROM active_sessions WHERE session_id = ?", (session_id,)).fetchone())
        if capture.get("suggested_job_type"):
            new_session["suggested_job_type"] = capture["suggested_job_type"]
        log_event(conn, "switch", f"switched to {capture['client_name']}: {capture['task_text']}", "active_session", new_session["session_id"], after={"closed_entry": closed, "new_active_session": new_session}, at=switched_at)
        conn.commit()
    new_session["currently_working_sync"] = _sync_currently_working("upsert", db_path, new_session)
    return {"closed_entry": _flag_missing_notes(closed), "new_active_session": new_session}


def clarify_active_session(
    db_path: str | Path,
    client: str | None = None,
    task: str | None = None,
    billable: str | None = None,
    at: str | None = None,
    job_type: str | None = None,
) -> dict[str, Any]:
    ensure_initialized(db_path)
    clarified_at = iso(parse_at(at)) if at else now_iso()
    with connect(db_path) as conn:
        active = get_active_session(conn)
        if not active:
            raise ValueError("no active session to clarify")
        next_client = client if client is not None else active["client_name"]
        next_task = task if task is not None else active["task_text"]
        # Preserve stored job_type (including blank). Never auto-fill roster
        # default — suggest via suggested_job_type only until the operator confirms.
        current_job_type = active.get("job_type") if active.get("job_type") is not None else ""
        capture = resolve_capture_with_metadata(conn, next_client, next_task, billable if billable is not None else None, clarification=True, job_type=job_type, current_job_type=current_job_type)
        if client is not None and billable is None and active.get("capture_status") == "needs_info" and capture["capture_status"] == "needs_info":
            # The operator addressed the client; that confirms the open timer.
            # Known roster clients already resolved above with their roster
            # default; unknown names resolve here keeping the session's current
            # billable rather than demanding it be retyped.
            capture = resolve_capture_with_metadata(conn, next_client, next_task, bool(active["billable"]), clarification=True, job_type=job_type, current_job_type=current_job_type)
        if billable is None and client is None:
            capture["billable"] = active["billable"]
        capture["clarified_at"] = clarified_at if capture["capture_status"] == "resolved" else active.get("clarified_at")
        conn.execute(
            """
            UPDATE active_sessions
            SET client_name = ?, task_text = ?, billable = ?, job_type = ?, raw_client_name = ?, raw_task_text = ?,
                capture_status = ?, capture_note = ?, clarified_at = ?, updated_at = ?
            WHERE session_id = ?
            """,
            (
                capture["client_name"],
                capture["task_text"],
                capture["billable"],
                capture["job_type"],
                capture["raw_client_name"],
                capture["raw_task_text"],
                capture["capture_status"],
                capture["capture_note"],
                capture["clarified_at"],
                clarified_at,
                active["session_id"],
            ),
        )
        session = row_to_dict(conn.execute("SELECT * FROM active_sessions WHERE session_id = ?", (active["session_id"],)).fetchone())
        if capture.get("suggested_job_type"):
            session["suggested_job_type"] = capture["suggested_job_type"]
        else:
            _attach_suggested_job_type(conn, session)
        log_event(
            conn,
            "clarify_active",
            f"clarified active session {session['client_name']}: {session['task_text']}",
            "active_session",
            session["session_id"],
            before=active,
            after=session,
            at=clarified_at,
        )
        conn.commit()
    session["currently_working_sync"] = _sync_currently_working("upsert", db_path, session)
    return session


def cancel_session(db_path: str | Path, at: str | None = None) -> dict[str, Any]:
    ensure_initialized(db_path)
    canceled_at = iso(parse_at(at)) if at else now_iso()
    with connect(db_path) as conn:
        active = get_active_session(conn)
        if not active:
            raise ValueError("no active session to cancel")
        conn.execute(
            "UPDATE active_sessions SET status = 'canceled', updated_at = ? WHERE session_id = ?",
            (canceled_at, active["session_id"]),
        )
        after = row_to_dict(conn.execute("SELECT * FROM active_sessions WHERE session_id = ?", (active["session_id"],)).fetchone())
        log_event(conn, "cancel", f"canceled active session for {active['client_name']} (no entry created)", "active_session", active["session_id"], before=active, after=after, at=canceled_at)
        conn.commit()
    after["currently_working_sync"] = _sync_currently_working("canceled", db_path, at=canceled_at)
    return after


def _int_setting(conn, key: str, default: int) -> int:
    raw = get_setting(conn, key, str(default))
    try:
        value = int(str(raw))
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


CHECKIN_SUGGESTED_ACTIONS = ["still", "switched", "done", "snooze", "cancel"]
REVIEW_ACTIVE_TIMER_ACTIONS = ["checkin", "end", "switch", "snooze", "cancel"]


def _active_timer_warning(active: dict[str, Any] | None, reviewed_at: str, stale_session_minutes: int) -> dict[str, Any]:
    if not active:
        return {
            "has_active_timer": False,
            "session": None,
            "client_name": None,
            "task_text": None,
            "started_at": None,
            "last_checkin_at": None,
            "snoozed_until": None,
            "open_minutes": None,
            "is_stale": False,
            "prompt_reason": "idle",
            "suggested_actions": [],
        }
    try:
        open_minutes = minutes_between(active["started_at"], reviewed_at)
    except ValueError:
        open_minutes = 0
    is_stale = open_minutes >= stale_session_minutes
    return {
        "has_active_timer": True,
        "session": {
            "client_name": active["client_name"],
            "task_text": active["task_text"],
            "started_at": active["started_at"],
            "last_checkin_at": active["last_checkin_at"],
            "snoozed_until": active.get("snoozed_until"),
        },
        "client_name": active["client_name"],
        "task_text": active["task_text"],
        "started_at": active["started_at"],
        "last_checkin_at": active["last_checkin_at"],
        "snoozed_until": active.get("snoozed_until"),
        "open_minutes": open_minutes,
        "is_stale": is_stale,
        "prompt_reason": "stale_active_timer" if is_stale else "active_timer_open",
        "suggested_actions": REVIEW_ACTIVE_TIMER_ACTIONS,
    }


def checkin_status(db_path: str | Path, at: str | None = None) -> dict[str, Any]:
    ensure_initialized(db_path)
    auto_closed = maybe_end_overdue_planned(db_path, at)
    checked_at = iso(parse_at(at)) if at else now_iso()
    with connect(db_path) as conn:
        active = get_active_session(conn)
        checkin_interval = _int_setting(conn, "checkin_interval_minutes", 45)
        stale_session_minutes = _int_setting(conn, "stale_session_minutes", 480)
    if not active:
        idle = {
            "active": False,
            "session": None,
            "open_minutes": None,
            "minutes_since_checkin": None,
            "snoozed_until": None,
            "should_prompt": False,
            "prompt_reason": "idle",
            "is_stale": False,
            "checkin_interval_minutes": checkin_interval,
            "stale_session_minutes": stale_session_minutes,
            "suggested_actions": [],
        }
        if auto_closed:
            idle["should_prompt"] = True
            idle["prompt_reason"] = "planned_end_reached"
            idle["auto_ended"] = True
            idle["closed_entry"] = auto_closed
        return idle
    try:
        open_minutes = minutes_between(active["started_at"], checked_at)
    except ValueError:
        open_minutes = 0  # started in the future (clock skew); treat as just-opened
    last_checkin_at = active["last_checkin_at"] or active["started_at"]
    try:
        minutes_since_checkin = minutes_between(last_checkin_at, checked_at)
    except ValueError:
        minutes_since_checkin = 0  # future check-in from clock skew; do not prompt
    is_stale = open_minutes >= stale_session_minutes
    interval_due = minutes_since_checkin >= checkin_interval
    snoozed_until = active.get("snoozed_until")
    is_snoozed = False
    if snoozed_until:
        try:
            is_snoozed = parse_at(checked_at) < parse_at(snoozed_until)
        except ValueError:
            is_snoozed = False
    if is_snoozed:
        should_prompt = False
        prompt_reason = "snoozed"
    else:
        should_prompt = is_stale or interval_due
        if is_stale:
            prompt_reason = "stale_session"
        elif interval_due:
            prompt_reason = "interval_elapsed"
        else:
            prompt_reason = None
    return {
        "active": True,
        "session": {
            "client_name": active["client_name"],
            "task_text": active["task_text"],
            "started_at": active["started_at"],
            "last_checkin_at": active["last_checkin_at"],
            "planned_end_at": active.get("planned_end_at"),
        },
        "open_minutes": open_minutes,
        "minutes_since_checkin": minutes_since_checkin,
        "snoozed_until": snoozed_until,
        "should_prompt": should_prompt,
        "prompt_reason": prompt_reason,
        "is_stale": is_stale,
        "checkin_interval_minutes": checkin_interval,
        "stale_session_minutes": stale_session_minutes,
        "suggested_actions": CHECKIN_SUGGESTED_ACTIONS,
    }


def snooze_checkin(db_path: str | Path, minutes: int, at: str | None = None) -> dict[str, Any]:
    ensure_initialized(db_path)
    snooze_minutes = int(minutes)
    if snooze_minutes <= 0:
        raise ValueError("minutes must be greater than zero")
    snoozed_at_dt = parse_at(at)
    snoozed_at = iso(snoozed_at_dt)
    snoozed_until = iso(snoozed_at_dt + timedelta(minutes=snooze_minutes))
    with connect(db_path) as conn:
        active = get_active_session(conn)
        if not active:
            raise ValueError("no active session to snooze")
        conn.execute(
            "UPDATE active_sessions SET snoozed_until = ?, updated_at = ? WHERE session_id = ?",
            (snoozed_until, snoozed_at, active["session_id"]),
        )
        after = row_to_dict(conn.execute("SELECT * FROM active_sessions WHERE session_id = ?", (active["session_id"],)).fetchone())
        log_event(conn, "snooze_checkin", f"snoozed check-in reminders for {snooze_minutes} minutes", "active_session", active["session_id"], before=active, after=after, at=snoozed_at)
        conn.commit()
    return after


def checkin(db_path: str | Path, at: str | None = None) -> dict[str, Any]:
    ensure_initialized(db_path)
    auto_closed = maybe_end_overdue_planned(db_path, at)
    if auto_closed:
        return {"auto_ended": True, "closed_entry": auto_closed, "status": "closed"}
    checked_at = iso(parse_at(at)) if at else now_iso()
    with connect(db_path) as conn:
        active = get_active_session(conn)
        if not active:
            raise ValueError("no active session to check in on")
        conn.execute(
            "UPDATE active_sessions SET last_checkin_at = ?, updated_at = ? WHERE session_id = ?",
            (checked_at, checked_at, active["session_id"]),
        )
        after = row_to_dict(conn.execute("SELECT * FROM active_sessions WHERE session_id = ?", (active["session_id"],)).fetchone())
        log_event(conn, "checkin", f"confirmed still working on {active['client_name']}", "active_session", active["session_id"], before=active, after=after, at=checked_at)
        conn.commit()
    return after


# Days larger than this stay out of the model reply and skip per-row roster downloads.
REVIEW_FULL_BODY_LIMIT = 20


def overlapping_block_message(row: dict[str, Any]) -> str:
    return (
        f"This block overlaps entry {row['entry_id']} "
        f"({row['client_name']} {row['start_at']}–{row['end_at']}). "
        "Split the stretch into the time before, the exception, and the time after. "
        "Touching endpoints (end equal to the next start) are allowed."
    )


def find_overlapping_entry(conn, start_iso: str, end_iso: str) -> dict[str, Any] | None:
    """Return a same-day block that overlaps [start, end). Touching ends do not overlap."""
    day = start_iso[:10]
    rows = conn.execute(
        """
        SELECT entry_id, client_name, start_at, end_at FROM time_entries
        WHERE substr(start_at, 1, 10) = ? AND review_status != 'discarded'
        ORDER BY start_at, entry_id
        """,
        (day,),
    ).fetchall()
    start = parse_at(start_iso)
    end = parse_at(end_iso)
    for row in rows:
        other_start = parse_at(row["start_at"])
        other_end = parse_at(row["end_at"])
        if start < other_end and end > other_start:
            return row_to_dict(row)
    return None


def add_missing_entry(
    db_path: str | Path,
    client: str,
    task: str,
    start: str | None = None,
    end: str | None = None,
    billable: str | None = None,
    job_type: str | None = None,
    *,
    date: str | None = None,
    duration_minutes: int | None = None,
    confirm_client: bool = False,
) -> dict[str, Any]:
    """Add a draft entry from either clock times or duration+date.

    Clock path: start + end (existing).
    Duration path: date + duration_minutes; engine synthesizes placeholder
    start/end from midnight (packed after existing same-day blocks on collision).
    """
    ensure_initialized(db_path)
    duration_only = False
    if start is not None and end is not None:
        start_iso = iso(parse_at(start))
        end_iso = iso(parse_at(end))
        duration = minutes_between(start_iso, end_iso)
    elif duration_minutes is not None and date:
        duration_only = True
        duration = int(duration_minutes)
        if duration <= 0:
            raise ValueError("duration_minutes must be a positive integer")
        day = date.strip()[:10]
        # Validate date shape via parse_at
        parse_at(f"{day}T00:00:00")
        with connect(db_path) as conn:
            start_iso, end_iso = _pack_duration_window(conn, day, duration)
    elif start is not None or end is not None:
        raise ValueError("provide both start and end, or date + duration_minutes")
    else:
        raise ValueError("provide start+end, or date + duration_minutes")
    with connect(db_path) as conn:
        pending = client_confirm_gate(
            conn, client, confirm_client=confirm_client, db_path=db_path,
        )
        if pending:
            return pending
        capture = resolve_capture_with_metadata(conn, client, task, billable, job_type=job_type)
        if duration_only:
            # Mark so review can prefer Duration over placeholder clocks.
            note = capture.get("capture_note")
            capture["capture_note"] = "duration_only" if not note else f"{note};duration_only"
        rounded = round_minutes(duration, *get_rounding(conn))
        overlap = find_overlapping_entry(conn, start_iso, end_iso)
        if overlap:
            raise ValueError(overlapping_block_message(overlap))
        review_status = "needs_info" if capture["capture_status"] == "needs_info" else "draft"
        cur = conn.execute(
            """
            INSERT INTO time_entries(
                client_name, task_text, billable, job_type, start_at, end_at, duration_minutes,
                rounded_minutes, review_status, raw_client_name, raw_task_text,
                capture_status, capture_note, clarified_at, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                capture["client_name"], capture["task_text"], capture["billable"],
                capture["job_type"], start_iso, end_iso, duration, rounded, review_status,
                capture["raw_client_name"], capture["raw_task_text"],
                capture["capture_status"], capture["capture_note"], capture["clarified_at"],
                end_iso, end_iso,
            ),
        )
        entry = row_to_dict(conn.execute("SELECT * FROM time_entries WHERE entry_id = ?", (cur.lastrowid,)).fetchone())
        if capture.get("suggested_job_type"):
            entry["suggested_job_type"] = capture["suggested_job_type"]
        if duration_only:
            entry["duration_only"] = True
        log_event(conn, "add_missing", f"added missing time for {capture['client_name']}: {capture['task_text']}", "time_entry", entry["entry_id"], after=entry, at=end_iso)
        conn.commit()
    return entry


def _batch_roster_names(conn, db_path: str | Path) -> list[str]:
    """One roster read for a whole spreadsheet. Never once per row."""
    from .supabase_ref import list_clients_remote

    live = _supabase_environ(None)
    if live is not None or not _local_roster_allowed():
        rows = list_clients_remote(environ=live, office=None, db_path=db_path)
        return [str(row["display_name"]) for row in rows if row.get("display_name")]
    fetched = conn.execute("SELECT display_name FROM clients").fetchall()
    return [str(row["display_name"]) for row in fetched if row["display_name"]]


def add_missing_batch(db_path: str | Path, rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Save many clock rows in one transaction. Exact matches with a job code only.

    Unmatched names, missing job codes, and overlapping blocks are listed in
    needs_attention and are not saved. Returns counts plus a review token.
    """
    from .supabase_ref import classify_client_name

    if not isinstance(rows, list):
        raise ValueError("entries must be a list of rows")
    ensure_initialized(db_path)
    added_dates: dict[str, int] = {}
    needs_attention: list[dict[str, str]] = []
    with connect(db_path) as conn:
        names = _batch_roster_names(conn, db_path)
        for raw in rows:
            if not isinstance(raw, dict):
                needs_attention.append({"client": "", "notes": "", "reason": "row must be an object"})
                continue
            client = str(raw.get("client") or "").strip()
            notes = str(raw.get("task") or raw.get("notes") or "").strip()
            job = str(raw.get("job_type") or raw.get("job_code") or "").strip()
            brief = {"client": client, "notes": notes}
            start = raw.get("start")
            end = raw.get("end")
            if not client:
                needs_attention.append({**brief, "reason": "missing client"})
                continue
            if not start or not end:
                needs_attention.append({**brief, "reason": "missing start or end"})
                continue
            try:
                start_iso = iso(parse_at(str(start)))
                end_iso = iso(parse_at(str(end)))
                if minutes_between(start_iso, end_iso) <= 0:
                    raise ValueError("end must be after start")
            except ValueError as exc:
                needs_attention.append({**brief, "reason": str(exc)})
                continue
            classified = classify_client_name(client, names)
            if classified["kind"] in {"exact", "fold"}:
                canonical = str(classified["display_name"])
            elif special_client_policy(client):
                canonical = client
            else:
                needs_attention.append({**brief, "reason": "not an exact client match"})
                continue
            if not job:
                needs_attention.append({**brief, "reason": "no job code"})
                continue
            overlap = find_overlapping_entry(conn, start_iso, end_iso)
            if overlap:
                needs_attention.append({**brief, "reason": overlapping_block_message(overlap)})
                continue
            duration = minutes_between(start_iso, end_iso)
            rounded = round_minutes(duration, *get_rounding(conn))
            conn.execute(
                """
                INSERT INTO time_entries(
                    client_name, task_text, billable, job_type, start_at, end_at, duration_minutes,
                    rounded_minutes, review_status, raw_client_name, raw_task_text,
                    capture_status, capture_note, clarified_at, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    canonical, notes, 1, job, start_iso, end_iso, duration, rounded, "draft",
                    None, notes, "resolved", None, None, end_iso, end_iso,
                ),
            )
            added_dates[start_iso[:10]] = added_dates.get(start_iso[:10], 0) + 1
        if added_dates:
            log_event(
                conn, "add_missing",
                f"added {sum(added_dates.values())} spreadsheet rows",
                at=now_iso(),
            )
        conn.commit()
        tokens: list[dict[str, Any]] = []
        for day in sorted(added_dates):
            tokens.append({
                "date": day,
                "added_count": added_dates[day],
                "review_token": review_token(day, list_entries_for_date(conn, day)),
            })
    result: dict[str, Any] = {
        "added_count": sum(added_dates.values()),
        "needs_attention": needs_attention,
    }
    if len(tokens) == 1:
        result["date"] = tokens[0]["date"]
        result["review_token"] = tokens[0]["review_token"]
    elif tokens:
        result["dates"] = tokens
    return result


def _pack_duration_window(conn, day: str, duration: int) -> tuple[str, str]:
    """Synthesize start/end for a duration-only entry; pack after same-day blocks."""
    rows = conn.execute(
        """
        SELECT start_at, end_at FROM time_entries
        WHERE substr(start_at, 1, 10) = ? AND review_status != 'discarded'
        ORDER BY start_at, entry_id
        """,
        (day,),
    ).fetchall()
    cursor = parse_at(f"{day}T00:00:00")
    for row in rows:
        block_start = parse_at(row["start_at"])
        block_end = parse_at(row["end_at"])
        candidate_end = cursor + timedelta(minutes=duration)
        # Overlap if candidate intersects [block_start, block_end)
        if cursor < block_end and candidate_end > block_start:
            cursor = block_end
    start_iso = iso(cursor)
    end_iso = iso(cursor + timedelta(minutes=duration))
    return start_iso, end_iso


def reround_drafts(db_path: str | Path, date_value: str, rule: str | None = None, at: str | None = None) -> dict[str, Any]:
    ensure_initialized(db_path)
    changed_at = iso(parse_at(at)) if at else now_iso()
    if rule is not None:
        # set_setting validates the rule name and raises the teaching error
        set_setting(db_path, "rounding_rule", rule, changed_at)
    rerounded: list[dict[str, Any]] = []
    with connect(db_path) as conn:
        increment, mode = get_rounding(conn)
        rows = conn.execute(
            "SELECT * FROM time_entries WHERE substr(start_at, 1, 10) = ? AND review_status = 'draft' ORDER BY start_at, entry_id",
            (date_value,),
        ).fetchall()
        for row in rows:
            before = row_to_dict(row)
            new_rounded = round_minutes(int(before["duration_minutes"]), increment, mode)
            conn.execute(
                "UPDATE time_entries SET rounded_minutes = ?, updated_at = ? WHERE entry_id = ?",
                (new_rounded, changed_at, before["entry_id"]),
            )
            after = row_to_dict(conn.execute("SELECT * FROM time_entries WHERE entry_id = ?", (before["entry_id"],)).fetchone())
            log_event(conn, "reround", f"rerounded entry {before['entry_id']} to {new_rounded} min", "time_entry", before["entry_id"], before=before, after=after, at=changed_at)
            rerounded.append(after)
        current_rule = get_setting(conn, "rounding_rule", "exact")
        conn.commit()
    return {"date": date_value, "rule": current_rule, "rerounded_count": len(rerounded), "entries": rerounded}


def edit_entry(
    db_path: str | Path,
    entry_id: int,
    client: str | None = None,
    task: str | None = None,
    billable: str | bool | None = None,
    start: str | None = None,
    end: str | None = None,
    at: str | None = None,
    job_type: str | None = None,
) -> dict[str, Any]:
    ensure_initialized(db_path)
    changed_at = iso(parse_at(at)) if at else now_iso()
    with connect(db_path) as conn:
        before = row_to_dict(conn.execute("SELECT * FROM time_entries WHERE entry_id = ?", (entry_id,)).fetchone())
        if not before:
            raise ValueError(f"entry {entry_id} not found")
        is_submitted = bool(before.get("submitted_at"))
        if before["review_status"] not in {"draft", "needs_info"}:
            if before["review_status"] == "discarded":
                raise ValueError(f"entry {entry_id} was discarded; use add_missing to recreate it")
            if is_submitted and before["review_status"] in {"approved", "exported"}:
                from .pay_period import can_edit_entry, entry_work_date, refuse_edit_message

                staff_name = get_setting(conn, "staff_name") or ""
                work_date = entry_work_date(before)
                if not can_edit_entry(work_date, staff_name, now=at or changed_at):
                    raise ValueError(refuse_edit_message(work_date, now=at or changed_at))
            else:
                raise ValueError(
                    f"entry {entry_id} is {before['review_status']}; only draft entries can be edited (unapprove first)"
                )
        was_needs_info = before["review_status"] == "needs_info"
        new_task = task if task is not None else before["task_text"]
        if client is not None or was_needs_info:
            # Preserve stored job_type (including blank). Roster default is
            # suggestion-only until the operator explicitly sets job_type.
            capture = resolve_capture_with_metadata(
                conn,
                client if client is not None else before["client_name"],
                new_task,
                billable if billable is not None else None,
                clarification=was_needs_info,
                job_type=job_type,
                current_job_type=before.get("job_type") if before.get("job_type") is not None else "",
            )
            if was_needs_info and client is not None and billable is None and capture["capture_status"] == "needs_info":
                # The operator addressed the client; that is the confirmation.
                # Known roster clients already resolved above; unknown names
                # resolve here keeping the entry's current billable.
                capture = resolve_capture_with_metadata(
                    conn,
                    client,
                    new_task,
                    bool(before["billable"]),
                    clarification=True,
                    job_type=job_type,
                    current_job_type=before.get("job_type") if before.get("job_type") is not None else "",
                )
            if billable is None and client is None:
                capture["billable"] = before["billable"]
            new_client = capture["client_name"]
            new_billable = capture["billable"]
            new_job_type = capture["job_type"]
            capture_status = capture["capture_status"]
            capture_note = capture["capture_note"]
            raw_client_name = capture["raw_client_name"]
            raw_task_text = capture["raw_task_text"]
            clarified_at = changed_at if was_needs_info and capture_status == "resolved" else before.get("clarified_at")
        else:
            new_client = before["client_name"]
            if billable is None and job_type is None:
                # Nothing policy-relevant requested: preserve stored values and
                # skip the roster scan entirely.
                new_billable = before["billable"]
                new_job_type = before.get("job_type") or ""
            else:
                # Enforce client policy on any billable/job_type edit so a locked
                # (administrative) client can never be flipped billable via edit.
                row = resolve_client_row(conn, new_client)
                new_billable, new_job_type = apply_client_policy(
                    row, billable, job_type,
                    current_billable=before["billable"],
                    current_job_type=before.get("job_type") or "")
            capture_status = before.get("capture_status") or "resolved"
            capture_note = before.get("capture_note")
            raw_client_name = before.get("raw_client_name")
            raw_task_text = before.get("raw_task_text")
            clarified_at = before.get("clarified_at")
        new_review_status = "draft" if was_needs_info and capture_status == "resolved" else before["review_status"]
        # Submitted rows stay approved/exported; never bounce them to draft via edit.
        if is_submitted and before["review_status"] in {"approved", "exported"}:
            new_review_status = before["review_status"]
        new_start = iso(parse_at(start)) if start else before["start_at"]
        new_end = iso(parse_at(end)) if end else before["end_at"]
        duration = minutes_between(new_start, new_end)
        rounded = round_minutes(duration, *get_rounding(conn))
        conn.execute(
            """
            UPDATE time_entries
            SET client_name = ?, task_text = ?, billable = ?, job_type = ?, start_at = ?, end_at = ?,
                duration_minutes = ?, rounded_minutes = ?, review_status = ?, raw_client_name = ?,
                raw_task_text = ?, capture_status = ?, capture_note = ?, clarified_at = ?, updated_at = ?
            WHERE entry_id = ?
            """,
            (
                new_client,
                new_task,
                new_billable,
                new_job_type,
                new_start,
                new_end,
                duration,
                rounded,
                new_review_status,
                raw_client_name,
                raw_task_text,
                capture_status,
                capture_note,
                clarified_at,
                changed_at,
                entry_id,
            ),
        )
        after = row_to_dict(conn.execute("SELECT * FROM time_entries WHERE entry_id = ?", (entry_id,)).fetchone())
        log_event(
            conn,
            "edit",
            f"edited {'submitted' if is_submitted else 'draft'} entry {entry_id}",
            "time_entry",
            entry_id,
            before=before,
            after=after,
            at=changed_at,
        )
        conn.commit()
        _attach_suggested_job_type(conn, after)
    return after


def discard_entry(db_path: str | Path, entry_id: int, at: str | None = None) -> dict[str, Any]:
    """Soft-delete a mistaken capture. The row is kept forever (review_status
    'discarded') so billing history is never destroyed; it is hidden from
    review and can never be approved or exported. Recovery is add_missing."""
    ensure_initialized(db_path)
    changed_at = iso(parse_at(at)) if at else now_iso()
    with connect(db_path) as conn:
        before = row_to_dict(conn.execute("SELECT * FROM time_entries WHERE entry_id = ?", (entry_id,)).fetchone())
        if not before:
            raise ValueError(f"entry {entry_id} not found")
        if before["review_status"] not in {"draft", "needs_info"}:
            raise ValueError(
                f"entry {entry_id} is {before['review_status']}; only draft or needs_info entries "
                "can be discarded (unapprove an approved entry first)"
            )
        conn.execute(
            "UPDATE time_entries SET review_status = 'discarded', updated_at = ? WHERE entry_id = ?",
            (changed_at, entry_id),
        )
        after = row_to_dict(conn.execute("SELECT * FROM time_entries WHERE entry_id = ?", (entry_id,)).fetchone())
        log_event(conn, "discard", f"discarded entry {entry_id} (never billed)", "time_entry", entry_id, before=before, after=after, at=changed_at)
        conn.commit()
    return after


def list_entries_for_range(conn, date_value: str, end_date: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT * FROM time_entries
        WHERE substr(start_at, 1, 10) BETWEEN ? AND ? AND review_status != 'discarded'
        ORDER BY start_at, entry_id
        """,
        (date_value, end_date),
    ).fetchall()
    return [row_to_dict(row) for row in rows]


def list_entries_for_date(conn, date_value: str) -> list[dict[str, Any]]:
    return list_entries_for_range(conn, date_value, date_value)


def review_token(date_value: str, entries: list[dict[str, Any]], end_date: str | None = None) -> str:
    snapshot = {
        "date": date_value,
        "entries": [
            {
                "entry_id": entry["entry_id"],
                "client_name": entry["client_name"],
                "task_text": entry["task_text"],
                "billable": entry["billable"],
                "start_at": entry["start_at"],
                "end_at": entry["end_at"],
                "duration_minutes": entry["duration_minutes"],
                "rounded_minutes": entry["rounded_minutes"],
                "review_status": entry["review_status"],
                "capture_status": entry.get("capture_status"),
                "capture_note": entry.get("capture_note"),
                "clarified_at": entry.get("clarified_at"),
                "export_path": entry["export_path"],
                "updated_at": entry["updated_at"],
            }
            for entry in entries
        ],
    }
    # end_date == date_value must hash like a plain single day; review_entries
    # collapses that case to end_date=None before calling here, so the second
    # condition is a safety net for direct callers — keep the two in sync.
    if end_date and end_date != date_value:
        snapshot["end_date"] = end_date
    payload = json.dumps(snapshot, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def validate_review_token(db_path: str | Path, date_value: str, token: str | None, end_date: str | None = None) -> None:
    # Mirror review_entries' collapse: end_date == date_value is single-day, so the
    # operator-facing messages must keep the (pinned) single-day wording there.
    ranged = bool(end_date) and end_date != date_value
    scope = "date range" if ranged else "date"
    whose = "date range's" if ranged else "day's"
    refreshed = "range" if ranged else "day"
    if not token:
        raise ValueError(f"review_token is required: call review for this {scope} first and pass back its review_token")
    review = review_entries(db_path, date_value, end_date=end_date)
    if not hmac.compare_digest(str(token), review["review_token"]):
        raise ValueError(
            f"review_token is stale because the {whose} entries changed after that review; "
            f"call review again, show the operator the refreshed {refreshed}, then retry"
        )


def entry_date(db_path: str | Path, entry_id: int) -> str:
    ensure_initialized(db_path)
    with connect(db_path) as conn:
        row = conn.execute("SELECT start_at FROM time_entries WHERE entry_id = ?", (entry_id,)).fetchone()
    if row is None:
        raise ValueError(f"entry {entry_id} not found")
    return str(row["start_at"])[:10]


def _normalize_date_span(date_value: str, end_date: str | None) -> str | None:
    """Validate and normalise end_date for a review/export span.

    Precondition: date_value must already be a normalised YYYY-MM-DD string
    (ordering is a lexical string compare; callers must normalise before calling).

    Returns the collapsed end_date (None when end_date is absent or equal to
    date_value — both map to the single-day path).  Raises ValueError for a
    malformed or out-of-order end_date.
    """
    if end_date is None:
        return None
    end_date = normalize_date(end_date)  # raises ValueError on malformed input
    if end_date < date_value:
        raise ValueError(
            f"end_date ({end_date}) must not be before date ({date_value})"
        )
    if end_date == date_value:
        return None  # collapse to single-day path
    return end_date


def review_entries(db_path: str | Path, date_value: str, at: str | None = None, end_date: str | None = None) -> dict[str, Any]:
    ensure_initialized(db_path)
    reviewed_at = iso(parse_at(at)) if at else now_iso()
    end_date = _normalize_date_span(date_value, end_date)
    ranged = end_date is not None
    with connect(db_path) as conn:
        if ranged:
            entries = list_entries_for_range(conn, date_value, end_date)
        else:
            entries = list_entries_for_date(conn, date_value)
        # A long day must not download the firm roster once per blank job code.
        remote_suggest = len(entries) <= REVIEW_FULL_BODY_LIMIT
        for entry in entries:
            entry["needs_review_reason"] = needs_review_reason(entry)
            _attach_suggested_job_type(conn, entry, remote=remote_suggest)
            if entry.get("capture_note") and "duration_only" in str(entry["capture_note"]):
                entry["duration_only"] = True
        active = get_active_session(conn)
        if active:
            _attach_suggested_job_type(conn, active, remote=remote_suggest)
        stale_session_minutes = _int_setting(conn, "stale_session_minutes", 480)
        event_count = conn.execute("SELECT COUNT(*) AS c FROM event_log").fetchone()["c"]
        last_activity_at = conn.execute("SELECT MAX(created_at) AS m FROM event_log").fetchone()["m"]
    totals: dict[str, int] = {"draft_minutes": 0, "approved_minutes": 0, "exported_minutes": 0, "needs_info_minutes": 0}
    skipped_needs_info_count = 0
    skipped_needs_info_minutes = 0
    for entry in entries:
        key = f"{entry['review_status']}_minutes"
        if key in totals:
            totals[key] += int(entry["rounded_minutes"])
        if entry.get("capture_status") == "needs_info" or entry.get("review_status") == "needs_info":
            skipped_needs_info_count += 1
            skipped_needs_info_minutes += int(entry["rounded_minutes"])
    totals["skipped_needs_info_minutes"] = skipped_needs_info_minutes
    # #34: nudge count for entries whose Notes were skipped.
    missing_notes_count = sum(1 for e in entries if _notes_missing(e.get("task_text")))
    result: dict[str, Any] = {
        "date": date_value,
        "entries": entries,
        "missing_notes_count": missing_notes_count,
        "active_session": active,
        "active_timer_warning": _active_timer_warning(active, reviewed_at, stale_session_minutes),
        "totals": totals,
        "skipped_needs_info_count": skipped_needs_info_count,
        "skipped_needs_info_minutes": skipped_needs_info_minutes,
        "event_count": event_count,
        "last_activity_at": last_activity_at,
        "review_token": review_token(date_value, entries, end_date=end_date),
    }
    if ranged:
        result["end_date"] = end_date
        # Build per-day summaries grouped by entry date, ascending order.
        days_map: dict[str, dict[str, Any]] = {}
        for entry in entries:
            d = str(entry["start_at"])[:10]
            if d not in days_map:
                days_map[d] = {
                    "date": d,
                    "entry_count": 0,
                    "draft_minutes": 0,
                    "approved_minutes": 0,
                    "exported_minutes": 0,
                    "needs_info_count": 0,
                }
            day = days_map[d]
            day["entry_count"] += 1
            status = entry["review_status"]
            # needs_info minutes intentionally have no per-day bucket (spec:
            # needs_info_count only); totals carry needs_info_minutes for the span.
            minutes_key = f"{status}_minutes"
            if minutes_key in day:
                day[minutes_key] += int(entry["rounded_minutes"])
            if entry.get("capture_status") == "needs_info" or status == "needs_info":
                day["needs_info_count"] += 1
        result["days"] = [days_map[d] for d in sorted(days_map)]
    return result


def _locked_billable_reason(conn, entry: dict[str, Any]) -> str | None:
    """Formerly blocked approve/export of billable+admin-locked clients.

    Firm no longer tracks billable vs non-billable — always allow.
    """
    _ = conn, entry
    return None


def set_approval(db_path: str | Path, entry_id: int, approved: bool, at: str | None = None) -> dict[str, Any]:
    ensure_initialized(db_path)
    status = "approved" if approved else "draft"
    changed_at = iso(parse_at(at)) if at else now_iso()
    with connect(db_path) as conn:
        before = row_to_dict(conn.execute("SELECT * FROM time_entries WHERE entry_id = ?", (entry_id,)).fetchone())
        if not before:
            raise ValueError(f"entry {entry_id} not found")
        if before["review_status"] == "discarded":
            raise ValueError(f"entry {entry_id} was discarded; use add_missing to recreate it if it should be billed")
        if before["review_status"] == "exported":
            if approved:
                return before
            raise ValueError("exported entries cannot be unapproved in this prototype")
        if not approved and before.get("submitted_at"):
            raise ValueError(
                f"entry {entry_id} was already submitted; do not unapprove — "
                "edit locally then call update_submitted (never a second INSERT)"
            )
        if before["review_status"] == "needs_info" or before.get("capture_status") == "needs_info":
            reason = capture_note_text(before.get("capture_note"), before.get("client_name")) or "missing client/task details"
            raise ValueError(
                f"entry {entry_id} needs clarification before approval ({reason}); "
                "confirm or correct it with edit — pass entry_id and client — to return it to draft"
            )
        if approved:
            locked_reason = _locked_billable_reason(conn, before)
            if locked_reason:
                raise ValueError(locked_reason)
            if not (before.get("job_type") or "").strip():
                raise ValueError(
                    f"entry {entry_id} has no Job Code; set/confirm a Job Code before approve "
                    "(suggest via list_job_codes or suggested_job_type — never auto-pick)"
                )
        if before["review_status"] == status:
            return before
        conn.execute(
            "UPDATE time_entries SET review_status = ?, updated_at = ? WHERE entry_id = ?",
            (status, changed_at, entry_id),
        )
        after = row_to_dict(conn.execute("SELECT * FROM time_entries WHERE entry_id = ?", (entry_id,)).fetchone())
        log_event(conn, "approve" if approved else "unapprove", f"set entry {entry_id} to {status}", "time_entry", entry_id, before=before, after=after, at=changed_at)
        conn.commit()
    return after


def approve_all(db_path: str | Path, date_value: str, at: str | None = None) -> dict[str, Any]:
    ensure_initialized(db_path)
    changed_at = iso(parse_at(at)) if at else now_iso()
    approved: list[dict[str, Any]] = []
    skipped_needs_info_count = 0
    skipped_needs_info_minutes = 0
    skipped_locked_count = 0
    skipped_locked_minutes = 0
    skipped_missing_job_code_count = 0
    skipped_missing_job_code_minutes = 0
    skipped_missing_job_code: list[dict[str, Any]] = []
    with connect(db_path) as conn:
        skipped_rows = conn.execute(
            """
            SELECT * FROM time_entries
            WHERE substr(start_at, 1, 10) = ?
              AND review_status != 'discarded'
              AND (review_status = 'needs_info' OR COALESCE(capture_status, 'resolved') = 'needs_info')
            ORDER BY start_at, entry_id
            """,
            (date_value,),
        ).fetchall()
        skipped = [row_to_dict(row) for row in skipped_rows]
        skipped_needs_info_count = len(skipped)
        skipped_needs_info_minutes = sum(int(entry["rounded_minutes"]) for entry in skipped)
        rows = conn.execute(
            """
            SELECT * FROM time_entries
            WHERE substr(start_at, 1, 10) = ?
              AND review_status = 'draft'
              AND COALESCE(capture_status, 'resolved') != 'needs_info'
            ORDER BY start_at, entry_id
            """,
            (date_value,),
        ).fetchall()
        for row in rows:
            before = row_to_dict(row)
            # Legacy safety net (#34): never bulk-approve billable time on a
            # now-locked admin client; surface it as a skip, never auto-flip it.
            if _locked_billable_reason(conn, before):
                skipped_locked_count += 1
                skipped_locked_minutes += int(before["rounded_minutes"])
                continue
            if not (before.get("job_type") or "").strip():
                skipped_missing_job_code_count += 1
                skipped_missing_job_code_minutes += int(before["rounded_minutes"])
                skipped_missing_job_code.append({
                    "entry_id": before["entry_id"],
                    "client": before.get("client_name") or "",
                    "notes": before.get("task_text") or "",
                })
                continue
            conn.execute(
                "UPDATE time_entries SET review_status = 'approved', updated_at = ? WHERE entry_id = ?",
                (changed_at, before["entry_id"]),
            )
            after = row_to_dict(conn.execute("SELECT * FROM time_entries WHERE entry_id = ?", (before["entry_id"],)).fetchone())
            log_event(conn, "approve", f"bulk-approved entry {before['entry_id']}", "time_entry", before["entry_id"], before=before, after=after, at=changed_at)
            approved.append(after)
        conn.commit()
    return {
        "date": date_value,
        "approved_count": len(approved),
        "skipped_needs_info_count": skipped_needs_info_count,
        "skipped_needs_info_minutes": skipped_needs_info_minutes,
        "skipped_locked_count": skipped_locked_count,
        "skipped_locked_minutes": skipped_locked_minutes,
        "skipped_missing_job_code_count": skipped_missing_job_code_count,
        "skipped_missing_job_code_minutes": skipped_missing_job_code_minutes,
        "skipped_missing_job_code": skipped_missing_job_code,
        "entries": approved,
    }


def export_entries(db_path: str | Path, date_value: str, output: str | Path, export_format: str = "quickbooks-csv", at: str | None = None, *, end_date: str | None = None, restrict_to_data_dir: bool = False) -> dict[str, Any]:
    if export_format != "quickbooks-csv":
        raise ValueError("only quickbooks-csv export is supported in this prototype")
    ensure_initialized(db_path)
    end_date = _normalize_date_span(date_value, end_date)
    ranged = end_date is not None
    end = end_date if ranged else date_value
    output_path = paths.resolve_artifact_path(output, db_path, restrict_to_data_dir=restrict_to_data_dir, artifact_subdir="exports")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    exported_at = iso(parse_at(at)) if at else now_iso()
    skipped_needs_info_count = 0
    skipped_needs_info_minutes = 0
    skipped_locked_count = 0
    skipped_locked_minutes = 0
    with connect(db_path) as conn:
        skipped_rows = conn.execute(
            """
            SELECT * FROM time_entries
            WHERE substr(start_at, 1, 10) BETWEEN ? AND ?
              AND review_status != 'discarded'
              AND (review_status = 'needs_info' OR COALESCE(capture_status, 'resolved') = 'needs_info')
            ORDER BY start_at, entry_id
            """,
            (date_value, end),
        ).fetchall()
        skipped = [row_to_dict(row) for row in skipped_rows]
        skipped_needs_info_count = len(skipped)
        skipped_needs_info_minutes = sum(int(entry["rounded_minutes"]) for entry in skipped)
        # Include already-exported rows so re-exporting a span regenerates the
        # COMPLETE file rather than a header-only CSV that drops prior work.
        rows = conn.execute(
            """
            SELECT * FROM time_entries
            WHERE substr(start_at, 1, 10) BETWEEN ? AND ? AND review_status IN ('approved', 'exported')
            ORDER BY start_at, entry_id
            """,
            (date_value, end),
        ).fetchall()
        entries = [row_to_dict(row) for row in rows]
        # Legacy safety net (#34): a billable entry on a now-locked admin client
        # must never reach the export; drop and count it, mirroring the needs_info
        # skip. Never auto-flips stored billable — the operator edits it first.
        kept: list[dict[str, Any]] = []
        for entry in entries:
            if _locked_billable_reason(conn, entry):
                skipped_locked_count += 1
                skipped_locked_minutes += int(entry["rounded_minutes"])
                continue
            kept.append(entry)
        entries = kept
        if not entries:
            span_label = f"{date_value}..{end}" if ranged else date_value
            raise ValueError(f"no approved or previously exported entries for {span_label}; nothing to export")
        # Write to a temp file and atomically replace, so a failed export never
        # clobbers a previously good CSV.
        tmp_path = output_path.with_name(f".{output_path.name}.tmp")
        with tmp_path.open("w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=["Date", "Client", "Job Code", "Notes", "Duration", "Billable"])
            writer.writeheader()
            for entry in entries:
                writer.writerow(
                    {
                        "Date": entry["start_at"][:10],
                        "Client": csv_safe(entry["client_name"]),
                        "Job Code": csv_safe(entry.get("job_type") or ""),
                        "Notes": csv_safe(entry["task_text"]),
                        "Duration": format_hhmm(entry["rounded_minutes"]),
                        "Billable": billable_text(entry["billable"]),
                    }
                )
        tmp_path.replace(output_path)
        for entry in entries:
            if entry["review_status"] != "approved":
                continue  # already exported; included in the file, no re-transition
            before = dict(entry)
            conn.execute(
                "UPDATE time_entries SET review_status = 'exported', export_path = ?, updated_at = ? WHERE entry_id = ?",
                (str(output_path), exported_at, entry["entry_id"]),
            )
            after = row_to_dict(conn.execute("SELECT * FROM time_entries WHERE entry_id = ?", (entry["entry_id"],)).fetchone())
            log_event(conn, "export", f"exported entry {entry['entry_id']} to QuickBooks-ready CSV", "time_entry", entry["entry_id"], before=before, after=after, at=exported_at)
        post_rows = conn.execute(
            """
            SELECT * FROM time_entries
            WHERE substr(start_at, 1, 10) BETWEEN ? AND ? AND review_status IN ('approved', 'exported')
            ORDER BY start_at, entry_id
            """,
            (date_value, end),
        ).fetchall()
        # Locked-billable rows are never transitioned to 'exported' above, so the
        # re-fetch would re-include them; filter them out so exported_count and the
        # returned entries reflect only what actually reached the CSV.
        entries = [e for e in (row_to_dict(row) for row in post_rows) if not _locked_billable_reason(conn, e)]
        operator_code = get_operator_code(conn)
        conn.commit()
    # Best-effort recovery point at each billing handoff — a backup failure must
    # never fail the export itself.
    backup_path = None
    try:
        backup_path = backup_database(db_path, at=exported_at)["path"]
    except Exception:
        backup_path = None
    user_export_dir = None
    user_visible_output = None
    user_visible_copy_error = None
    with connect(db_path) as conn:
        user_export_dir = get_setting(conn, "user_export_dir")
    if user_export_dir:
        user_export_dir = str(Path(user_export_dir).expanduser().resolve())
    else:
        user_export_dir = str(paths.default_user_export_dir())
    try:
        user_visible_output = str(paths.copy_export_to_user_dir(output_path, user_export_dir))
    except Exception as exc:
        user_visible_copy_error = str(exc)
        user_visible_output = None
    result: dict[str, Any] = {
        "date": date_value,
        "format": export_format,
        "output": str(output_path),
        "exported_count": len(entries),
        "skipped_needs_info_count": skipped_needs_info_count,
        "skipped_needs_info_minutes": skipped_needs_info_minutes,
        "skipped_locked_count": skipped_locked_count,
        "skipped_locked_minutes": skipped_locked_minutes,
        "entries": entries,
        "backup": backup_path,
        "user_export_dir": user_export_dir,
        "user_visible_output": user_visible_output,
        "user_visible_copy_error": user_visible_copy_error,
    }
    if ranged:
        result["end_date"] = end_date
    if operator_code:
        result["operator_code"] = operator_code
    return result


def anonymized_entries(entries: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, str]]:
    mapping: dict[str, str] = {}
    job_type_mapping: dict[str, str] = {}
    safe_entries: list[dict[str, Any]] = []
    for index, entry in enumerate(entries, start=1):
        client = entry["client_name"]
        if client not in mapping:
            mapping[client] = f"Client {len(mapping) + 1}"
        safe = dict(entry)
        safe["client_name"] = mapping[client]
        # task_text and job_type are free text that routinely embeds real
        # client/contact detail; the packet promises anonymized labels only.
        safe["task_text"] = f"Task {index}"
        job_type = entry.get("job_type") or ""
        if job_type:
            if job_type not in job_type_mapping:
                job_type_mapping[job_type] = f"Job Code {len(job_type_mapping) + 1}"
            safe["job_type"] = job_type_mapping[job_type]
        safe_entries.append(safe)
    return safe_entries, mapping


def write_sanitized_packet(db_path: str | Path, date_value: str, output: str | Path, *, restrict_to_data_dir: bool = False) -> dict[str, Any]:
    review = review_entries(db_path, date_value)
    safe_entries, mapping = anonymized_entries(review["entries"])
    output_path = paths.resolve_artifact_path(output, db_path, restrict_to_data_dir=restrict_to_data_dir, artifact_subdir="packets")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Sanitized TimeAssist Collaboration Packet",
        "",
        "## Boundary",
        "",
        "This packet uses synthetic/anonymized labels only. Do not paste real client names, copied emails, credentials, QuickBooks exports, or internal URLs.",
        "",
        "## Workflow goal",
        "",
        "Help an accountant review draft billable-time entries before any QuickBooks handoff.",
        "",
        "## Entries",
        "",
    ]
    if not safe_entries:
        lines.append("No entries for this date.")
    else:
        lines.append("| Date | Client | Job Code | Notes | Duration | Office | Status |")
        lines.append("|---|---|---|---|---:|---|---|")
        for entry in safe_entries:
            lines.append(
                f"| {entry['start_at'][:10]} | {entry['client_name']} | {entry.get('job_type') or ''} | {entry['task_text']} | {format_hhmm(int(entry['rounded_minutes']))} | {entry.get('office') or ''} | {entry['review_status']} |"
            )
    lines.extend([
        "",
        "## Open questions for stakeholder",
        "",
        "- Which QuickBooks handoff route should the first export target?",
        "- What billing increment and rounding rule should this use?",
        "- Which data classes are approved for a pilot?",
        "",
        "## Anonymization summary",
        "",
        f"- {len(mapping)} client label(s) generated.",
    ])
    output_path.write_text("\n".join(lines) + "\n")
    return {"output": str(output_path), "entry_count": len(safe_entries), "client_label_count": len(mapping)}


def format_minutes(total: int) -> str:
    total = int(total)
    hours, mins = divmod(total, 60)
    if hours and mins:
        return f"{hours}h {mins}m"
    if hours:
        return f"{hours}h"
    return f"{mins}m"


_STATUS_LABELS = {
    "draft": "Draft",
    "approved": "Approved",
    "exported": "Exported",
    "needs_info": "Needs info",
}


def status_pill(status: str) -> str:
    safe = status if status in _STATUS_LABELS else "draft"
    label = _STATUS_LABELS.get(status, html.escape(status.replace("_", " ").title()))
    return f"<span class='pill {safe}'>{label}</span>"


def billable_pill(billable: int) -> str:
    if billable:
        return "<span class='pill billable'>Billable</span>"
    return "<span class='pill nonbillable'>Non-billable</span>"


REVIEW_STYLE = """
:root{
  --dark:#173247; --dark2:#24465D; --light:#F4FBFF; --card:#ffffff;
  --text:#071421; --muted:#5F7890; --accent:#16C7F7; --accent2:#6F8CFF;
  --border:#B7E8FA; --eyebrow:#047EA9; --ice:#EAF8FF; --ice2:#DDF4FF;
  color-scheme:light;
}
*{box-sizing:border-box;}
body{
  margin:0; color:var(--text);
  font-family:Inter,"Geist","Geist Sans",ui-sans-serif,system-ui,-apple-system,"Segoe UI",Roboto,Arial,sans-serif;
  background:
    radial-gradient(circle at 88% -2%, rgba(139,234,255,.40), transparent 26%),
    radial-gradient(circle at 4% 102%, rgba(221,244,255,.70), transparent 30%),
    linear-gradient(rgba(183,232,250,.30) 1px, transparent 1px),
    linear-gradient(90deg, rgba(183,232,250,.30) 1px, transparent 1px),
    linear-gradient(rgba(221,239,248,.16) 1px, transparent 1px),
    linear-gradient(90deg, rgba(221,239,248,.16) 1px, transparent 1px),
    var(--light);
  background-size:auto,auto,96px 96px,96px 96px,24px 24px,24px 24px,auto;
  background-attachment:fixed;
  -webkit-font-smoothing:antialiased;
}
main{max-width:1080px; margin:0 auto; padding:52px 24px 72px;}
.topline{height:4px; border-radius:999px; background:linear-gradient(90deg,#8BEAFF,var(--accent),var(--accent2)); opacity:.9; margin-bottom:30px;}
.eyebrow{text-transform:uppercase; letter-spacing:.22em; color:var(--eyebrow); font-size:11px; font-weight:700;}
.chip{display:inline-block; background:var(--eyebrow); color:#fff; font-weight:700; letter-spacing:.14em; text-transform:uppercase; font-size:11px; padding:6px 12px; border-radius:8px;}
h1{font-size:clamp(34px,5vw,52px); line-height:1.02; letter-spacing:-.03em; margin:18px 0 14px; max-width:20ch;}
h2{font-size:25px; letter-spacing:-.02em; margin:0;}
h3{font-size:16px; margin:0;}
p{color:var(--muted); line-height:1.6; margin:0;}
.lead{margin-top:12px; max-width:62ch; color:#466078;}
.card{background:var(--card); border:1px solid var(--border); border-radius:20px; padding:30px; box-shadow:0 18px 50px rgba(8,126,164,.10);}
.section{margin-top:24px;}
.section-head{margin-bottom:16px;}
.section-head .eyebrow{display:block; margin-bottom:6px;}
.thesis{margin-top:22px; border-left:4px solid var(--accent); background:var(--dark); color:#F4FBFF; padding:18px 22px; border-radius:0 14px 14px 0; font-size:17px; line-height:1.45;}
.thesis strong{color:#8BEAFF;}
.metrics{display:grid; grid-template-columns:repeat(4,1fr); gap:14px; margin-top:22px;}
.metric{background:var(--card); border:1px solid var(--border); border-radius:16px; padding:18px; box-shadow:0 10px 28px rgba(8,126,164,.06);}
.metric .val{font-size:30px; font-weight:800; letter-spacing:-.02em; color:var(--eyebrow); font-variant-numeric:tabular-nums;}
.metric .lbl{display:block; margin-top:6px; font-size:12px; font-weight:700; text-transform:uppercase; letter-spacing:.06em; color:var(--text);}
.metric .sub{display:block; margin-top:3px; font-size:12px; color:var(--muted);}
.loop{display:grid; grid-template-columns:repeat(4,1fr); gap:18px;}
.loop-step{position:relative; background:var(--ice); border:1px solid var(--border); border-radius:14px; padding:16px;}
.loop-step .n{display:inline-grid; place-items:center; width:26px; height:26px; border-radius:50%; background:var(--accent); color:#fff; font-size:12px; font-weight:800; margin-bottom:10px;}
.loop-step strong{display:block; font-size:15px; color:var(--text);}
.loop-step .d{display:block; margin-top:4px; font-size:13px; color:var(--muted); line-height:1.4;}
.loop-step:not(:last-child)::after{content:"\\2192"; position:absolute; right:-13px; top:50%; transform:translateY(-50%); color:var(--accent); font-weight:700; font-size:18px; z-index:1;}
.actions{display:flex; flex-wrap:wrap; gap:10px; margin-top:18px;}
.button{border:1px solid #8cd8f0; background:var(--ice); color:#075f81; border-radius:999px; padding:9px 14px; font-weight:800; font-size:13px;}
.button.secondary{background:#fff; color:#3d5470; border-color:var(--border);}
.table-wrap{overflow-x:auto; border-radius:16px;}
table{width:100%; border-collapse:separate; border-spacing:0; overflow:hidden; border:1px solid var(--border); border-radius:16px; background:#fff;}
th,td{padding:13px 16px; border-bottom:1px solid #e4f3fb; text-align:left; font-size:14px;}
th{color:var(--eyebrow); font-size:11px; text-transform:uppercase; letter-spacing:.08em; background:var(--ice); font-weight:700;}
tr:last-child td{border-bottom:0;}
td.entry-id{color:var(--muted); font-variant-numeric:tabular-nums;}
td.client{font-weight:700; color:var(--text);}
td.window,td.mins{font-variant-numeric:tabular-nums;}
td.empty{text-align:center; color:var(--muted); padding:30px;}
.pill{display:inline-flex; align-items:center; gap:6px; border-radius:999px; padding:4px 11px; font-size:12px; font-weight:700; border:1px solid transparent; white-space:nowrap;}
.pill::before{content:""; width:7px; height:7px; border-radius:50%; background:currentColor;}
.pill.draft{color:#3d5470; background:#eef3f8; border-color:#d7e3ee;}
.pill.draft::before{opacity:.5;}
.pill.approved{color:#067a9e; background:#e1f7ff; border-color:#a9e2f4;}
.pill.exported{color:#1c3a52; background:#dfeaf3; border-color:#bcd2e4;}
.pill.needs_info{color:#4a51c4; background:#ecefff; border-color:#c9d2ff;}
.pill.billable{color:#067a9e; background:#e1f7ff; border-color:#a9e2f4;}
.pill.nonbillable{color:#5F7890; background:#f1f5f9; border-color:#dde6ef;}
.pill.nonbillable::before{opacity:.45;}
.note{margin-bottom:16px; display:flex; gap:10px; align-items:flex-start; background:var(--ice2); border:1px solid var(--border); border-radius:12px; padding:12px 16px; font-size:13px; color:#254258; line-height:1.45;}
.note b{color:var(--eyebrow);}
.qgrid{display:grid; grid-template-columns:1fr 1fr; gap:12px;}
.qcard{background:var(--ice); border:1px solid var(--border); border-radius:14px; padding:20px;}
.qcard span{color:var(--eyebrow); font-weight:700; font-size:11px; letter-spacing:.12em;}
.qcard p{margin-top:8px; color:var(--text); font-size:15px; line-height:1.48;}
.qcard.gate{grid-column:1/-1; background:#fff; border-color:#8BEAFF; border-width:1.5px;}
.guard{background:
    radial-gradient(circle at 90% 0%, rgba(22,199,247,.18), transparent 32%),
    radial-gradient(circle at 0% 100%, rgba(111,140,255,.12), transparent 34%),
    var(--dark);
  color:#F4FBFF; border:1px solid #24465D; border-radius:20px; padding:30px;}
.guard .eyebrow{color:#8BEAFF;}
.guard h2{color:#F4FBFF;}
.guard p{color:#CFE9F7;}
.guard-grid{display:grid; grid-template-columns:repeat(2,1fr); gap:14px; margin-top:20px;}
.guard-item{border:1px solid rgba(139,234,255,.22); background:rgba(15,40,60,.45); border-radius:14px; padding:16px;}
.guard-item strong{display:block; color:#8BEAFF; font-size:14px; margin-bottom:6px;}
.guard-item span{font-size:13.5px; color:#CFE9F7; line-height:1.5;}
.guard-line{margin-top:22px; font-size:19px; font-weight:800; color:#8BEAFF; letter-spacing:-.01em;}
.foot{margin-top:34px; display:flex; justify-content:space-between; gap:12px; flex-wrap:wrap; color:var(--muted); font-size:12px;}
@media (max-width:880px){
  .metrics{grid-template-columns:repeat(2,1fr);}
  .loop{grid-template-columns:1fr 1fr;}
  .loop-step:nth-child(2)::after{content:"";}
  .qgrid,.guard-grid{grid-template-columns:1fr;}
}
@media (max-width:520px){
  .metrics,.loop{grid-template-columns:1fr;}
  .loop-step::after{content:""!important;}
}
@media print{
  body{background:var(--light);}
  .card,.metric,.guard{box-shadow:none;}
}
"""


def render_review_html(review: dict[str, Any], output: str | Path, db_path: str | Path | None = None, *, restrict_to_data_dir: bool = False) -> str:
    output_path = paths.resolve_artifact_path(output, db_path, restrict_to_data_dir=restrict_to_data_dir, artifact_subdir="reviews")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    entries = review["entries"]
    totals = review["totals"]
    date_value = review["date"]
    event_count = review["event_count"]
    active = review.get("active_session")
    office_label = ""
    if db_path is not None:
        with connect(db_path) as conn:
            office_label = (get_setting(conn, "office") or "").strip()

    total_minutes = sum(int(entry["rounded_minutes"]) for entry in entries)
    cleared_minutes = int(totals["approved_minutes"]) + int(totals["exported_minutes"])
    entry_count = len(entries)
    safe_date = html.escape(date_value)

    rows = []
    for entry in entries:
        if entry.get("duration_only") or (
            entry.get("capture_note") and "duration_only" in str(entry.get("capture_note"))
        ):
            window = "—"
        else:
            window = f"{html.escape(entry['start_at'][11:16])}–{html.escape(entry['end_at'][11:16])}"
        reason = entry.get("needs_review_reason")
        status_html = status_pill(entry['review_status'])
        if reason:
            status_html += f"<div class='sub'>Needs review: {html.escape(reason)}</div>"
        entry_office = html.escape(str(entry.get("office") or office_label or "—"))
        rows.append(
            "<tr>"
            f"<td class='date'>{html.escape(entry['start_at'][:10])}</td>"
            f"<td class='client'>{html.escape(entry['client_name'])}</td>"
            f"<td class='job-type'>{html.escape(entry.get('job_type') or '')}</td>"
            f"<td class='task'>{html.escape(entry['task_text'])}</td>"
            f"<td class='window'>{window}</td>"
            f"<td class='mins'>{html.escape(format_hhmm(int(entry['rounded_minutes'])))}</td>"
            f"<td class='office'>{entry_office}</td>"
            f"<td>{status_html}</td>"
            "</tr>"
        )
    body_rows = "\n".join(rows) if rows else "<tr><td class='empty' colspan='8'>No entries captured yet for this day.</td></tr>"

    active_note = ""
    if active:
        active_note = (
            "<div class='note'><b>Heads up:</b> a session for "
            f"{html.escape(active['client_name'])} is still running. End it before the final "
            "review so the day reads complete.</div>"
        )

    body = f"""<main>
  <div class="topline"></div>
  <header class="card">
    <span class="chip">Stakeholder prototype · v1 walkthrough</span>
    <h1>Human-reviewed billable time, captured without surveillance.</h1>
    <p class="lead">TimeAssist turns scattered work blocks into clean draft entries an accountant can review at the end of the day. Nothing leaves this machine until a person approves it.</p>
    <div class="thesis"><strong>Draft first. You decide.</strong> Every entry starts as an editable draft. You stay the authority on what is billable, what gets corrected, and what is ever exported to QuickBooks.</div>
  </header>

  <section class="metrics">
    <div class="metric"><div class="val">{format_minutes(total_minutes)}</div><span class="lbl">Tracked today</span><span class="sub">{entry_count} entries · {safe_date}</span></div>
    <div class="metric"><div class="val">{format_minutes(totals['draft_minutes'])}</div><span class="lbl">Awaiting review</span><span class="sub">still in draft</span></div>
    <div class="metric"><div class="val">{format_minutes(cleared_minutes)}</div><span class="lbl">Cleared</span><span class="sub">approved &amp; exported</span></div>
    <div class="metric"><div class="val">{event_count}</div><span class="lbl">Logged events</span><span class="sub">auditable mutations</span></div>
  </section>

  <section class="card section">
    <div class="section-head">
      <span class="eyebrow">How the workflow runs</span>
      <h2>Capture → Review → Approve → Export</h2>
    </div>
    <p>Human review before export to QuickBooks is the rule, not an optional setting. The loop below is the only path an entry can take.</p>
    <div class="loop" style="margin-top:18px;">
      <div class="loop-step"><span class="n">1</span><strong>Capture</strong><span class="d">Start, switch, end, or add missing time as drafts.</span></div>
      <div class="loop-step"><span class="n">2</span><strong>Review</strong><span class="d">Entries stay editable and visible end-of-day.</span></div>
      <div class="loop-step"><span class="n">3</span><strong>Approve</strong><span class="d">Approve draft entries one by one; the rest stay open.</span></div>
      <div class="loop-step"><span class="n">4</span><strong>Export</strong><span class="d">Only approved time becomes a QuickBooks-ready CSV.</span></div>
    </div>
    <div class="actions">
      <span class="button">Approve draft</span>
      <span class="button secondary">Edit draft</span>
      <span class="button secondary">Export approved</span>
    </div>
  </section>

  <section class="card section">
    <div class="section-head">
      <span class="eyebrow">Daily review · {safe_date}</span>
      <h2>Today's entries</h2>
    </div>
{active_note}    <div class="table-wrap">
      <table>
        <thead><tr><th>Date</th><th>Client</th><th>Job Code</th><th>Notes</th><th>Window</th><th>Duration</th><th>Office</th><th>Status</th></tr></thead>
        <tbody>{body_rows}</tbody>
      </table>
    </div>
  </section>

  <section class="card section">
    <div class="section-head">
      <span class="eyebrow">Before a real pilot</span>
      <h2>Open questions for you</h2>
    </div>
    <div class="qgrid">
      <div class="qcard"><span>DECISION 1</span><p>Which QuickBooks handoff route should the first export target?</p></div>
      <div class="qcard"><span>DECISION 2</span><p>What billing increment and rounding rule should this enforce?</p></div>
      <div class="qcard"><span>DECISION 3</span><p>Which service codes map to each task type?</p></div>
      <div class="qcard"><span>DECISION 4</span><p>Which data classes are approved for the pilot?</p></div>
      <div class="qcard gate"><span>GO / NO-GO</span><p>With those answered, are we cleared to run a one-week supervised pilot on real entries?</p></div>
    </div>
  </section>

  <section class="guard section">
    <span class="eyebrow">Privacy boundary · v1 guardrails</span>
    <h2>What this prototype will not do</h2>
    <p>The goal is trustworthy capture, not monitoring. These boundaries hold for v1.</p>
    <div class="guard-grid">
      <div class="guard-item"><strong>No surveillance</strong><span>No screen recording or keystroke capture. Every change is an explicit, logged action you can audit.</span></div>
      <div class="guard-item"><strong>Drafts, not records</strong><span>Entries are editable drafts until you approve them — never silent final billing.</span></div>
      <div class="guard-item"><strong>You stay the authority</strong><span>Approval is required before anything is exported. The accountant decides.</span></div>
      <div class="guard-item"><strong>No QuickBooks writeback</strong><span>v1 stops at a reviewed, QuickBooks-ready CSV. No direct writeback into your books.</span></div>
    </div>
    <div class="guard-line">Draft first. You decide.</div>
  </section>

  <div class="foot">
    <span>TimeAssist — local, human-reviewed billable-time prototype</span>
    <span>Synthetic data · review for {safe_date}</span>
  </div>
</main>"""

    html_text = (
        "<!doctype html>\n"
        '<html lang="en">\n'
        "<head>\n"
        '  <meta charset="utf-8" />\n'
        '  <meta name="viewport" content="width=device-width, initial-scale=1" />\n'
        "  <title>TimeAssist Stakeholder Review</title>\n"
        f"  <style>{REVIEW_STYLE}</style>\n"
        "</head>\n"
        "<body>\n"
        f"{body}\n"
        "</body>\n"
        "</html>\n"
    )
    output_path.write_text(html_text, encoding="utf-8")
    return str(output_path)
