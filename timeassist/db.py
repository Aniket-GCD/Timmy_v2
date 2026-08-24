from __future__ import annotations

import re
import sqlite3
from contextlib import contextmanager
from pathlib import Path

SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS active_sessions (
    session_id INTEGER PRIMARY KEY AUTOINCREMENT,
    client_name TEXT NOT NULL,
    task_text TEXT NOT NULL,
    billable INTEGER NOT NULL DEFAULT 1,
    started_at TEXT NOT NULL,
    raw_client_name TEXT,
    raw_task_text TEXT,
    capture_status TEXT NOT NULL DEFAULT 'resolved',
    capture_note TEXT,
    clarified_at TEXT,
    last_checkin_at TEXT,
    snoozed_until TEXT,
    status TEXT NOT NULL DEFAULT 'active',
    job_type TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS one_active_session
ON active_sessions(status)
WHERE status = 'active';

CREATE TABLE IF NOT EXISTS time_entries (
    entry_id INTEGER PRIMARY KEY AUTOINCREMENT,
    client_name TEXT NOT NULL,
    task_text TEXT NOT NULL,
    billable INTEGER NOT NULL DEFAULT 1,
    start_at TEXT NOT NULL,
    end_at TEXT NOT NULL,
    duration_minutes INTEGER NOT NULL,
    rounded_minutes INTEGER NOT NULL,
    review_status TEXT NOT NULL DEFAULT 'draft',
    raw_client_name TEXT,
    raw_task_text TEXT,
    capture_status TEXT NOT NULL DEFAULT 'resolved',
    capture_note TEXT,
    clarified_at TEXT,
    export_path TEXT,
    job_type TEXT NOT NULL DEFAULT '',
    submitted_at TEXT,
    supabase_id TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS event_log (
    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type TEXT NOT NULL,
    actor TEXT NOT NULL DEFAULT 'cli',
    input_summary TEXT NOT NULL,
    object_type TEXT,
    object_id INTEGER,
    before_json TEXT,
    after_json TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS settings (
    setting_key TEXT PRIMARY KEY,
    setting_value TEXT NOT NULL,
    scope TEXT NOT NULL DEFAULT 'local',
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS clients (
    client_key TEXT PRIMARY KEY,
    display_name TEXT NOT NULL,
    aliases TEXT NOT NULL DEFAULT '',
    default_billable INTEGER NOT NULL DEFAULT 1,
    default_job_type TEXT NOT NULL DEFAULT '',
    billable_locked INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL
);
"""

DEFAULT_SETTINGS = {
    "timezone": "local",
    "rounding_rule": "exact",
    "quickbooks_writeback": "disabled",
    "privacy_mode": "synthetic-or-approved-data-only",
    "settings_version": "2",
    "audit_retention_days": "90",
    "checkin_interval_minutes": "45",
    "stale_session_minutes": "480",
}

CAPTURE_COLUMN_DEFINITIONS = {
    "raw_client_name": "TEXT",
    "raw_task_text": "TEXT",
    "capture_status": "TEXT NOT NULL DEFAULT 'resolved'",
    "capture_note": "TEXT",
    "clarified_at": "TEXT",
}

ENTRY_JOB_COLUMN_DEFINITIONS = {"job_type": "TEXT NOT NULL DEFAULT ''"}
ENTRY_SUBMITTED_COLUMN_DEFINITIONS = {"submitted_at": "TEXT"}
ENTRY_SUPABASE_ID_COLUMN_DEFINITIONS = {"supabase_id": "TEXT"}
CLIENT_COLUMN_DEFINITIONS = {
    "default_job_type": "TEXT NOT NULL DEFAULT ''",
    "billable_locked": "INTEGER NOT NULL DEFAULT 0",
}
ADMIN_CLIENT_SEEDS = ("Admin", "Early Out", "Holiday", "Staff Meeting")
# Unassigned lives in Supabase only (live client list). Do not seed locally.


def slugify_client_key(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", name.strip().lower()).strip("_")
    return slug or "client"


def _column_names(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}


def _ensure_columns(conn: sqlite3.Connection, table: str, definitions: dict[str, str]) -> None:
    columns = _column_names(conn, table)
    for column, definition in definitions.items():
        if column not in columns:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def _ensure_capture_columns(conn: sqlite3.Connection, table: str) -> None:
    _ensure_columns(conn, table, CAPTURE_COLUMN_DEFINITIONS)
    conn.execute(
        f"UPDATE {table} SET capture_status = 'resolved' "
        "WHERE capture_status IS NULL OR capture_status = ''"
    )


@contextmanager
def connect(db_path: str | Path):
    # Must close the connection, not just commit: sqlite3's own `with` block
    # commits but leaves the handle open, which on Windows locks the file (and
    # leaks a handle per call in the long-running MCP server).
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    # WAL: lets the CLI and the long-lived MCP server read concurrently and
    # cuts "database is locked" errors. Creates -wal/-shm sidecar files next to
    # the DB — a manual file copy must include all three (the backup-on-export
    # path uses SQLite's backup API, which handles this correctly).
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 30000")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def vacuum(db_path: str | Path) -> None:
    # VACUUM cannot run inside a transaction, so use a dedicated autocommit
    # connection rather than the transactional connect() context manager.
    conn = sqlite3.connect(Path(db_path))
    conn.isolation_level = None
    try:
        conn.execute("VACUUM")
    finally:
        conn.close()


def backup(src_path: str | Path, dest_path: str | Path) -> None:
    # SQLite online backup API — produces a consistent copy even under WAL.
    src = sqlite3.connect(Path(src_path))
    dest = sqlite3.connect(Path(dest_path))
    try:
        src.backup(dest)
    finally:
        dest.close()
        src.close()


def initialize(db_path: str | Path, now: str) -> None:
    with connect(db_path) as conn:
        conn.executescript(SCHEMA)
        _ensure_capture_columns(conn, "active_sessions")
        _ensure_capture_columns(conn, "time_entries")
        _ensure_columns(conn, "active_sessions", ENTRY_JOB_COLUMN_DEFINITIONS)
        _ensure_columns(conn, "time_entries", ENTRY_JOB_COLUMN_DEFINITIONS)
        _ensure_columns(conn, "time_entries", ENTRY_SUBMITTED_COLUMN_DEFINITIONS)
        _ensure_columns(conn, "time_entries", ENTRY_SUPABASE_ID_COLUMN_DEFINITIONS)
        _ensure_columns(conn, "clients", CLIENT_COLUMN_DEFINITIONS)
        # One-time migration: DBs created before raw-by-default have no
        # settings_version marker. If such a legacy DB is still on the old
        # nearest_6_minutes default, flip it to raw exactly once. The marker
        # below guarantees this never re-runs and never overrides a future
        # deliberate 6-minute choice.
        has_marker = conn.execute(
            "SELECT 1 FROM settings WHERE setting_key = 'settings_version'"
        ).fetchone()
        if has_marker is None:
            legacy_rule = conn.execute(
                "SELECT setting_value FROM settings WHERE setting_key = 'rounding_rule'"
            ).fetchone()
            if legacy_rule is not None and legacy_rule["setting_value"] == "nearest_6_minutes":
                conn.execute(
                    "UPDATE settings SET setting_value = 'exact', updated_at = ? WHERE setting_key = 'rounding_rule'",
                    (now,),
                )
                # Leave an audit trail: this silently changes how time is rounded,
                # so the operator can see it happened and re-confirm if they had
                # deliberately chosen 6-minute rounding before the upgrade.
                conn.execute(
                    """
                    INSERT INTO event_log(event_type, actor, input_summary, object_type, object_id, created_at)
                    VALUES ('migration', 'system', 'migrated rounding_rule nearest_6_minutes -> exact (raw-default)', 'setting', NULL, ?)
                    """,
                    (now,),
                )
        for key, value in DEFAULT_SETTINGS.items():
            # Seed defaults only when missing. initialize() runs on every action
            # via ensure_initialized(), so DO UPDATE here would clobber any
            # operator setting change (e.g. rounding_rule) on the next action.
            conn.execute(
                """
                INSERT INTO settings(setting_key, setting_value, scope, updated_at)
                VALUES (?, ?, 'local', ?)
                ON CONFLICT(setting_key) DO NOTHING
                """,
                (key, value, now),
            )
        # Seed the built-in non-billable admin clients. ON CONFLICT DO NOTHING so
        # a re-run never clobbers operator roster edits (initialize() runs on
        # every action via ensure_initialized()); additionally skip a seed whose
        # name is already an operator row's display name or alias under a
        # different key — otherwise the seeded display name would shadow that
        # label (exact display match beats alias match in resolve_client_row),
        # creating a collision the roster import itself would have rejected.
        label_owner: dict[str, str] = {}
        for row in conn.execute("SELECT client_key, display_name, aliases FROM clients"):
            for label in (row["display_name"], *(row["aliases"] or "").split(";")):
                normalized = label.strip().lower()
                if normalized:
                    label_owner.setdefault(normalized, row["client_key"])
        for display_name in ADMIN_CLIENT_SEEDS:
            key = slugify_client_key(display_name)
            if label_owner.get(display_name.lower(), key) != key:
                continue
            conn.execute(
                """
                INSERT INTO clients(client_key, display_name, aliases, default_billable, default_job_type, billable_locked, updated_at)
                VALUES (?, ?, '', 0, 'Administrative', 1, ?)
                ON CONFLICT(client_key) DO NOTHING
                """,
                (key, display_name, now),
            )
            label_owner.setdefault(display_name.lower(), key)
        conn.commit()
