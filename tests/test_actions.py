from __future__ import annotations

import csv
import json
import os
import sqlite3
import tempfile
import unittest
from unittest import mock
from pathlib import Path

from timeassist import actions, db, paths
from tests.remote_roster import install_live_clients

# Legacy CSV roster helpers remain for unit tests that still seed SQLite.
os.environ["TIMEASSIST_ALLOW_LOCAL_ROSTER"] = "1"


def _seed_roster(test_case, *names: str) -> None:
    """Seed via live mock (preferred) — also works with local roster escape hatch."""
    install_live_clients(test_case, *names)
    # Also merge into local SQLite so tests that still use local resolve stay green.
    path = Path(getattr(test_case, "db", Path(test_case.tmp.name) / "timeassist.sqlite")).parent / "roster-seed.csv"
    if not hasattr(test_case, "db"):
        return
    # Quote display names so commas (e.g. "Smith, John") survive CSV parsing.
    lines = ["display_name,aliases,default_billable\n"]
    for name in names:
        safe = '"' + name.replace('"', '""') + '"'
        lines.append(f"{safe},,yes\n")
    path.write_text("".join(lines))
    actions.import_clients(test_case.db, path, mode="merge")


# Job Code is required before approve. Legacy tests that never set job_type still
# exercise approve/export paths — fill a placeholder only when blank so those
# suites stay meaningful. Call sites that assert the gate use _raw_set_approval /
# _raw_approve_all.
_raw_set_approval = actions.set_approval
_raw_approve_all = actions.approve_all


def _fill_blank_job_type(db_path, entry_id: int | None = None, *, date_value: str | None = None) -> None:
    with db.connect(db_path) as conn:
        if entry_id is not None:
            conn.execute(
                "UPDATE time_entries SET job_type = 'Tax' WHERE entry_id = ? AND TRIM(COALESCE(job_type, '')) = ''",
                (entry_id,),
            )
        elif date_value is not None:
            conn.execute(
                """
                UPDATE time_entries SET job_type = 'Tax'
                WHERE substr(start_at, 1, 10) = ?
                  AND review_status = 'draft'
                  AND TRIM(COALESCE(job_type, '')) = ''
                """,
                (date_value,),
            )
        conn.commit()


def _set_approval_compat(db_path, entry_id, approved, at=None):
    if approved:
        _fill_blank_job_type(db_path, entry_id=entry_id)
    return _raw_set_approval(db_path, entry_id, approved, at)


def _approve_all_compat(db_path, date_value, at=None):
    _fill_blank_job_type(db_path, date_value=date_value)
    return _raw_approve_all(db_path, date_value, at)


actions.set_approval = _set_approval_compat  # type: ignore[assignment]
actions.approve_all = _approve_all_compat  # type: ignore[assignment]

class RoundingDefaultTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = Path(self.tmp.name) / "timeassist.sqlite"
        install_live_clients(self, "Acme Co")

    def test_new_install_defaults_to_exact(self) -> None:
        actions.init_state(self.db, "2026-05-28T09:00:00")
        settings = actions.list_settings(self.db)
        self.assertEqual(settings["rounding_rule"], "exact")
        self.assertEqual(settings["settings_version"], "2")

    def test_new_install_does_not_round(self) -> None:
        actions.init_state(self.db, "2026-05-28T09:00:00")
        # 23 minutes would round to 24 under nearest_6; raw must stay 23.
        entry = actions.add_missing_entry(
            self.db, "Acme Co", "cleanup",
            "2026-05-28T09:00:00", "2026-05-28T09:23:00", "yes",
        )
        self.assertEqual(entry["duration_minutes"], 23)
        self.assertEqual(entry["rounded_minutes"], 23)

    def test_legacy_db_migrates_six_minute_default_to_exact(self) -> None:
        # Simulate a pre-change DB: schema + old default, no settings_version.
        conn = sqlite3.connect(self.db)
        conn.executescript(db.SCHEMA)
        conn.execute(
            "INSERT INTO settings(setting_key, setting_value, scope, updated_at) "
            "VALUES ('rounding_rule', 'nearest_6_minutes', 'local', '2026-01-01T00:00:00')"
        )
        conn.commit()
        conn.close()

        db.initialize(self.db, "2026-05-28T09:00:00")

        settings = actions.list_settings(self.db)
        self.assertEqual(settings["rounding_rule"], "exact")
        self.assertEqual(settings["settings_version"], "2")

    def test_migrated_db_keeps_explicit_six_minute_choice(self) -> None:
        # A DB already stamped with the marker is never re-migrated.
        conn = sqlite3.connect(self.db)
        conn.executescript(db.SCHEMA)
        conn.executemany(
            "INSERT INTO settings(setting_key, setting_value, scope, updated_at) VALUES (?, ?, 'local', '2026-01-01T00:00:00')",
            [("rounding_rule", "nearest_6_minutes"), ("settings_version", "2")],
        )
        conn.commit()
        conn.close()

        db.initialize(self.db, "2026-05-28T09:00:00")

        self.assertEqual(actions.list_settings(self.db)["rounding_rule"], "nearest_6_minutes")


class CaptureStatusMigrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = Path(self.tmp.name) / "timeassist.sqlite"

    def test_initialize_adds_capture_columns_to_legacy_tables(self) -> None:
        conn = sqlite3.connect(self.db)
        conn.executescript(
            """
            CREATE TABLE settings (
                setting_key TEXT PRIMARY KEY,
                setting_value TEXT NOT NULL,
                scope TEXT NOT NULL DEFAULT 'local',
                updated_at TEXT NOT NULL
            );
            CREATE TABLE clients (
                client_key TEXT PRIMARY KEY,
                display_name TEXT NOT NULL,
                aliases TEXT NOT NULL DEFAULT '',
                default_billable INTEGER,
                active INTEGER NOT NULL DEFAULT 1,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE active_sessions (
                session_id INTEGER PRIMARY KEY CHECK (session_id = 1),
                client_name TEXT NOT NULL,
                task_text TEXT NOT NULL,
                billable INTEGER NOT NULL DEFAULT 1,
                started_at TEXT NOT NULL,
                last_checkin_at TEXT,
                snoozed_until TEXT,
                status TEXT NOT NULL DEFAULT 'active',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE time_entries (
                entry_id INTEGER PRIMARY KEY AUTOINCREMENT,
                client_name TEXT NOT NULL,
                task_text TEXT NOT NULL,
                billable INTEGER NOT NULL DEFAULT 1,
                start_at TEXT NOT NULL,
                end_at TEXT NOT NULL,
                duration_minutes INTEGER NOT NULL,
                rounded_minutes INTEGER NOT NULL,
                review_status TEXT NOT NULL DEFAULT 'draft',
                exported_at TEXT,
                source TEXT NOT NULL DEFAULT 'manual',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE event_log (
                event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_type TEXT NOT NULL,
                entity_type TEXT NOT NULL,
                entity_id INTEGER,
                occurred_at TEXT NOT NULL,
                before_json TEXT,
                after_json TEXT
            );
            CREATE UNIQUE INDEX one_active_session ON active_sessions(status) WHERE status = 'active';
            CREATE INDEX idx_time_entries_start ON time_entries(start_at);
            CREATE INDEX idx_event_log_time ON event_log(occurred_at);
            """
        )
        conn.execute(
            "INSERT INTO active_sessions(session_id, client_name, task_text, billable, started_at, last_checkin_at, status, created_at, updated_at) "
            "VALUES (1, 'Legacy Client', 'legacy task', 1, '2026-05-28T09:00:00', '2026-05-28T09:00:00', 'active', '2026-05-28T09:00:00', '2026-05-28T09:00:00')"
        )
        conn.execute(
            "INSERT INTO time_entries(client_name, task_text, billable, start_at, end_at, duration_minutes, rounded_minutes, review_status, source, created_at, updated_at) "
            "VALUES ('Legacy Client', 'closed task', 1, '2026-05-28T08:00:00', '2026-05-28T08:30:00', 30, 30, 'draft', 'switch', '2026-05-28T08:30:00', '2026-05-28T08:30:00')"
        )
        conn.commit()
        conn.close()

        db.initialize(self.db, "2026-05-28T09:30:00")

        conn = sqlite3.connect(self.db)
        conn.row_factory = sqlite3.Row
        for table in ("active_sessions", "time_entries"):
            columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
            for column in ("raw_client_name", "raw_task_text", "capture_status", "capture_note", "clarified_at"):
                self.assertIn(column, columns)
        active = conn.execute("SELECT capture_status, raw_client_name FROM active_sessions WHERE session_id = 1").fetchone()
        entry = conn.execute("SELECT capture_status, raw_client_name FROM time_entries WHERE entry_id = 1").fetchone()
        self.assertEqual(active["capture_status"], "resolved")
        self.assertEqual(entry["capture_status"], "resolved")
        self.assertIsNone(active["raw_client_name"])
        conn.close()


class SchemaMigrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.work = Path(self.tmp.name)
        self.db = Path(self.tmp.name) / "timeassist.sqlite"

    def test_new_columns_and_seeds_are_idempotent(self) -> None:
        actions.ensure_initialized(self.db)
        actions.ensure_initialized(self.db)  # second run must not raise

        conn = sqlite3.connect(self.db)
        conn.row_factory = sqlite3.Row
        for table in ("time_entries", "active_sessions"):
            columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
            self.assertIn("job_type", columns)
        client_columns = {row["name"] for row in conn.execute("PRAGMA table_info(clients)")}
        self.assertIn("default_job_type", client_columns)
        self.assertIn("billable_locked", client_columns)

        seeded = conn.execute(
            "SELECT display_name, default_job_type, default_billable, billable_locked "
            "FROM clients WHERE billable_locked = 1 ORDER BY display_name"
        ).fetchall()
        self.assertEqual(
            [tuple(row) for row in seeded],
            [
                ("Admin", "Administrative", 0, 1),
                ("Early Out", "Administrative", 0, 1),
                ("Holiday", "Administrative", 0, 1),
                ("Staff Meeting", "Administrative", 0, 1),
                ("Vacation", "Administrative", 0, 1),
            ],
        )
        conn.close()

    def test_admin_seed_does_not_clobber_operator_roster_edit(self) -> None:
        actions.ensure_initialized(self.db)
        conn = sqlite3.connect(self.db)
        conn.execute("UPDATE clients SET aliases = 'ADM' WHERE display_name = 'Admin'")
        conn.commit()
        conn.close()

        actions.ensure_initialized(self.db)

        conn = sqlite3.connect(self.db)
        aliases = conn.execute(
            "SELECT aliases FROM clients WHERE display_name = 'Admin'"
        ).fetchone()[0]
        conn.close()
        self.assertEqual(aliases, "ADM")

    def test_seed_skipped_when_operator_alias_uses_the_name(self) -> None:
        # Replace-import drops the seeds; the operator's OWN roster row carries
        # alias 'admin'. Re-seeding 'Admin' would shadow that alias (the exact
        # display-name pass beats the alias pass), so the seed must be skipped.
        path = self.work / "clients.csv"
        path.write_text("display_name,aliases,default_billable\nAdministrator,admin,yes\n")
        actions.import_clients(self.db, path, mode="replace")
        session = actions.start_session(self.db, "admin", "internal", None, "2026-05-28T09:00:00")
        self.assertEqual(session["client_name"], "Administrator")
        self.assertEqual(session["billable"], 1)
        with db.connect(self.db) as conn:
            self.assertIsNone(conn.execute(
                "SELECT 1 FROM clients WHERE display_name = 'Admin'").fetchone())

    def test_seed_skipped_when_operator_display_name_reuses_the_name(self) -> None:
        # A replace-import whose OWN row is named 'Holiday' under a different
        # client_key. Re-seeding must not add a second Holiday nor clobber the
        # operator's billable, unlocked row (pins the display-name branch).
        path = self.work / "clients.csv"
        path.write_text(
            "client_key,display_name,aliases,default_billable\n"
            "their_holiday,Holiday,,yes\n"
        )
        actions.import_clients(self.db, path, mode="replace")
        actions.ensure_initialized(self.db)  # the next action re-runs seeding
        with db.connect(self.db) as conn:
            rows = conn.execute(
                "SELECT client_key, default_billable, billable_locked "
                "FROM clients WHERE display_name = 'Holiday'"
            ).fetchall()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["client_key"], "their_holiday")
        self.assertEqual(int(rows[0]["default_billable"]), 1)
        self.assertEqual(int(rows[0]["billable_locked"]), 0)


class ReroundTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = Path(self.tmp.name) / "timeassist.sqlite"
        actions.init_state(self.db, "2026-05-28T09:00:00")
        _seed_roster(self, "Acme Co")

    def _add(self, start: str, end: str, status: str = "draft") -> dict:
        entry = actions.add_missing_entry(self.db, "Acme Co", "work", start, end, "yes")
        if status != "draft":
            actions.set_approval(self.db, entry["entry_id"], True, "2026-05-28T18:00:00")
        return entry

    def test_reround_sets_rule_and_rounds_drafts(self) -> None:
        self._add("2026-05-28T09:00:00", "2026-05-28T09:23:00")  # raw 23
        result = actions.reround_drafts(self.db, "2026-05-28", "nearest_15_minutes", "2026-05-28T19:00:00")
        self.assertEqual(result["rule"], "nearest_15_minutes")
        self.assertEqual(result["rerounded_count"], 1)
        self.assertEqual(result["entries"][0]["rounded_minutes"], 30)  # 23 -> nearest 15

    def test_reround_to_exact_restores_raw(self) -> None:
        entry = self._add("2026-05-28T09:00:00", "2026-05-28T09:23:00")
        actions.reround_drafts(self.db, "2026-05-28", "nearest_15_minutes", "2026-05-28T19:00:00")
        result = actions.reround_drafts(self.db, "2026-05-28", "exact", "2026-05-28T19:05:00")
        self.assertEqual(result["entries"][0]["rounded_minutes"], 23)
        self.assertEqual(result["entries"][0]["duration_minutes"], 23)

    def test_reround_leaves_approved_entries_untouched(self) -> None:
        approved = self._add("2026-05-28T09:00:00", "2026-05-28T09:23:00", status="approved")
        result = actions.reround_drafts(self.db, "2026-05-28", "nearest_15_minutes", "2026-05-28T19:00:00")
        self.assertEqual(result["rerounded_count"], 0)
        review = actions.review_entries(self.db, "2026-05-28")
        locked = next(e for e in review["entries"] if e["entry_id"] == approved["entry_id"])
        self.assertEqual(locked["rounded_minutes"], 23)  # unchanged

    def test_reround_without_rule_uses_current_setting(self) -> None:
        self._add("2026-05-28T09:00:00", "2026-05-28T09:23:00")
        actions.set_setting(self.db, "rounding_rule", "up_15_minutes")
        result = actions.reround_drafts(self.db, "2026-05-28")
        self.assertEqual(result["rule"], "up_15_minutes")
        self.assertEqual(result["entries"][0]["rounded_minutes"], 30)

    def test_reround_rejects_unknown_rule_with_teaching_error(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            actions.reround_drafts(self.db, "2026-05-28", "every_10_minutes")
        self.assertIn("nearest_<N>_minutes", str(ctx.exception))

    def test_reround_with_custom_increment_rounds_drafts(self) -> None:
        self._add("2026-05-28T09:00:00", "2026-05-28T09:23:00")  # raw 23
        result = actions.reround_drafts(self.db, "2026-05-28", "nearest_10_minutes", "2026-05-28T19:00:00")
        self.assertEqual(result["rule"], "nearest_10_minutes")
        self.assertEqual(result["entries"][0]["rounded_minutes"], 20)  # 23 -> nearest 10

    def test_needs_info_resolution_applies_current_rounding_rule(self) -> None:
        # Pin (issue #39, item 3): reround deliberately skips needs_info
        # entries, but resolving one back to draft must re-round it with the
        # day's CURRENT rule — edit_entry always recomputes rounded_minutes
        # from raw. A resolved entry must never land unrounded next to a
        # rounded day.
        unknown = actions.add_missing_entry(
            self.db, "Zed Partners", "quarterly review",
            "2026-05-28T10:00:00", "2026-05-28T10:23:00", "yes",
        )
        self.assertEqual(unknown["review_status"], "needs_info")

        result = actions.reround_drafts(self.db, "2026-05-28", "nearest_15_minutes", "2026-05-28T19:00:00")
        self.assertEqual(result["rerounded_count"], 0)  # needs_info skipped, by design

        # Both resolution paths: confirm-as-is (unknown name kept) …
        resolved = actions.edit_entry(self.db, unknown["entry_id"], client="Zed Partners", at="2026-05-28T19:05:00")
        self.assertEqual(resolved["review_status"], "draft")
        self.assertEqual(resolved["rounded_minutes"], 30)  # 23 -> nearest 15, not raw

        # … and correcting to a roster name.
        other = actions.add_missing_entry(
            self.db, "Zed Grp", "filing", "2026-05-28T11:00:00", "2026-05-28T11:23:00", "yes",
        )
        corrected = actions.edit_entry(self.db, other["entry_id"], client="Acme Co", at="2026-05-28T19:10:00")
        self.assertEqual(corrected["review_status"], "draft")
        self.assertEqual(corrected["rounded_minutes"], 30)

    def test_set_setting_validates_rounding_rule(self) -> None:
        details = actions.set_setting(self.db, "rounding_rule", "up_10_minutes")
        self.assertEqual(details["value"], "up_10_minutes")
        with self.assertRaises(ValueError) as ctx:
            actions.set_setting(self.db, "rounding_rule", "up_600_minutes")
        self.assertIn("up_<N>_minutes", str(ctx.exception))
        # the invalid value must not have been stored
        self.assertEqual(actions.list_settings(self.db)["rounding_rule"], "up_10_minutes")


class RoundingRuleParsingTests(unittest.TestCase):
    def test_parses_free_form_increments(self) -> None:
        self.assertEqual(actions.parse_rounding_rule("nearest_10_minutes"), (10, "nearest"))
        self.assertEqual(actions.parse_rounding_rule("up_30_minutes"), (30, "up"))
        self.assertEqual(actions.parse_rounding_rule("nearest_1_minutes"), (1, "nearest"))
        self.assertEqual(actions.parse_rounding_rule("up_60_minutes"), (60, "up"))

    def test_parses_legacy_named_rules_and_exact(self) -> None:
        self.assertEqual(actions.parse_rounding_rule("nearest_6_minutes"), (6, "nearest"))
        self.assertEqual(actions.parse_rounding_rule("up_6_minutes"), (6, "up"))
        self.assertEqual(actions.parse_rounding_rule("nearest_15_minutes"), (15, "nearest"))
        self.assertEqual(actions.parse_rounding_rule("up_15_minutes"), (15, "up"))
        self.assertEqual(actions.parse_rounding_rule("exact"), (1, "nearest"))

    def test_rejects_malformed_or_out_of_range_rules(self) -> None:
        for bad in (
            None, "", "nearest_0_minutes", "up_61_minutes", "nearest_06_minutes",
            "round_10_minutes", "nearest_10_minute", "10_minutes",
            "nearest_ten_minutes", "up_10_minutes_sharp", "NEAREST_10_MINUTES",
        ):
            self.assertIsNone(actions.parse_rounding_rule(bad), bad)


class ClientRosterTests(unittest.TestCase):
    def setUp(self) -> None:
        # Production path: no local roster escape hatch
        self._prev_local = os.environ.pop("TIMEASSIST_ALLOW_LOCAL_ROSTER", None)

        def _restore() -> None:
            if self._prev_local is not None:
                os.environ["TIMEASSIST_ALLOW_LOCAL_ROSTER"] = self._prev_local
            else:
                os.environ["TIMEASSIST_ALLOW_LOCAL_ROSTER"] = "1"

        self.addCleanup(_restore)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = Path(self.tmp.name) / "timeassist.sqlite"
        actions.init_state(self.db, "2026-05-28T09:00:00")

    def test_import_clients_disabled(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            actions.import_clients(self.db, Path("x.csv"))
        self.assertIn("Supabase", str(ctx.exception))

    def test_add_client_disabled(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            actions.add_client(self.db, "Acme")
        self.assertIn("Supabase", str(ctx.exception))

    def test_refresh_clients_disabled(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            actions.refresh_clients(self.db)
        self.assertIn("Supabase", str(ctx.exception))

    def test_list_clients_live(self) -> None:
        install_live_clients(self, "Acme Co", "Globex")
        names = {c["display_name"] for c in actions.list_clients(self.db, confirm_full_list=True)["clients"]}
        self.assertEqual(names, {"Acme Co", "Globex", "Unassigned"})


class ResolveClientTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.work = Path(self.tmp.name)
        self.db = self.work / "timeassist.sqlite"
        actions.init_state(self.db, "2026-05-28T09:00:00")
        _seed_roster(self, "Acme Co", "Internal Admin")

    def test_resolves_display_name_case_insensitively(self) -> None:
        with db.connect(self.db) as conn:
            name, billable = actions.resolve_client(conn, "acme co")
        self.assertEqual(name, "Acme Co")
        self.assertEqual(billable, 1)


    def test_unknown_client_returns_name_and_none(self) -> None:
        with db.connect(self.db) as conn:
            name, billable = actions.resolve_client(conn, "Wayne Ent")
        self.assertEqual(name, "Wayne Ent")
        self.assertIsNone(billable)



class NameFoldTests(unittest.TestCase):
    def test_comma_swaps_lastname_firstname(self) -> None:
        self.assertEqual(actions.name_fold("Smith, John"), "john smith")

    def test_lowercases_and_collapses_whitespace(self) -> None:
        self.assertEqual(actions.name_fold("  JOHN   SMITH "), "john smith")

    def test_business_name_folds_without_swapping(self) -> None:
        self.assertEqual(actions.name_fold("Acme Holdings LLC"), "acme holdings llc")

    def test_two_commas_do_not_swap(self) -> None:
        self.assertEqual(actions.name_fold("Smith, John, Jr"), "smith john jr")

    def test_trailing_comma_strips_punctuation(self) -> None:
        self.assertEqual(actions.name_fold("Smith,"), "smith")

    def test_entity_comma_does_not_swap_lastname_firstname(self) -> None:
        self.assertEqual(actions.name_fold("tsg2 nc, lp"), "tsg2 nc lp")
        self.assertEqual(actions.name_fold("TSG2 NC LP"), "tsg2 nc lp")
        self.assertEqual(actions.name_fold("tsg2 nc, lp"), actions.name_fold("TSG2 NC LP"))


class ResolveClientFoldTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.work = Path(self.tmp.name)
        self.db = self.work / "timeassist.sqlite"
        actions.init_state(self.db, "2026-05-28T09:00:00")
        _seed_roster(self, "Smith, John", "Acme Holdings LLC")

    def test_typed_firstname_lastname_matches_roster_lastname_firstname(self) -> None:
        with db.connect(self.db) as conn:
            name, billable = actions.resolve_client(conn, "John Smith")
        self.assertEqual(name, "Smith, John")
        self.assertEqual(billable, 1)

    def test_case_and_whitespace_insensitive(self) -> None:
        with db.connect(self.db) as conn:
            name, billable = actions.resolve_client(conn, "  john   SMITH ")
        self.assertEqual(name, "Smith, John")
        self.assertEqual(billable, 1)

    def test_reverse_direction(self) -> None:
        from unittest import mock
        os.environ.pop("TIMEASSIST_ALLOW_LOCAL_ROSTER", None)
        self.addCleanup(lambda: os.environ.__setitem__("TIMEASSIST_ALLOW_LOCAL_ROSTER", "1"))
        rows = [
            {"name": "Unassigned", "office": "GCD", "active": True},
            {"name": "John Smith", "office": "GCD", "active": True},
        ]
        with mock.patch("timeassist.supabase_ref.get_clients", return_value=rows):
            with db.connect(self.db) as conn:
                name, billable = actions.resolve_client(conn, "Smith, John")
        self.assertEqual(name, "John Smith")
        self.assertEqual(billable, 1)

    def test_ambiguous_fold_never_bills_blind(self) -> None:
        from unittest import mock
        os.environ.pop("TIMEASSIST_ALLOW_LOCAL_ROSTER", None)
        self.addCleanup(lambda: os.environ.__setitem__("TIMEASSIST_ALLOW_LOCAL_ROSTER", "1"))
        rows = [
            {"name": "Unassigned", "office": "GCD", "active": True},
            {"name": "Smith, John", "office": "GCD", "active": True},
            {"name": "Smith,John", "office": "GCD", "active": True},
        ]
        with mock.patch("timeassist.supabase_ref.get_clients", return_value=rows):
            with db.connect(self.db) as conn:
                name, billable = actions.resolve_client(conn, "John Smith")
        self.assertEqual(name, "John Smith")
        self.assertIsNone(billable)



class ManagementTiebreakTests(unittest.TestCase):
    # Pilot feedback #34: firms register a near-identical "management" shell
    # company next to the real client (e.g. "Highfield Partners" +
    # "Highfield Partners Management"). Protection is INHERENT in the
    # exact + comma-swap-fold matching passes: a management roster entry is
    # only ever billed on an exact match of its full name, so ambiguous or
    # folded input always lands on the non-management entry or needs_info.
    # A previously-considered explicit fourth "management tiebreak" pass was
    # implemented and then removed as unreachable dead code — do not
    # reintroduce it; these tests pin the outcomes instead.
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.work = Path(self.tmp.name)
        self.db = self.work / "timeassist.sqlite"
        actions.init_state(self.db, "2026-05-28T09:00:00")

    def _seed(self) -> None:
        path = self.work / "clients.csv"
        path.write_text(
            "display_name,aliases,default_billable\n"
            "Highfield Partners,,yes\n"
            "Highfield Partners Management,,no\n"
        )
        actions.import_clients(self.db, path)

    def test_comma_form_bills_non_management(self) -> None:
        self._seed()
        # "Partners, Highfield" exact-misses both but folds to 'highfield
        # partners', matching only the non-management entry.
        with db.connect(self.db) as conn:
            name, billable = actions.resolve_client(conn, "Partners, Highfield")
        self.assertEqual(name, "Highfield Partners")
        self.assertEqual(billable, 1)

    def test_plain_form_bills_non_management(self) -> None:
        self._seed()
        with db.connect(self.db) as conn:
            name, billable = actions.resolve_client(conn, "highfield partners")
        self.assertEqual(name, "Highfield Partners")
        self.assertEqual(billable, 1)

    def test_exact_management_name_honors_operator_intent(self) -> None:
        # Explicit, exact operator intent is the ONLY way the shell is billed.
        self._seed()
        with db.connect(self.db) as conn:
            name, billable = actions.resolve_client(conn, "Highfield Partners Management")
        self.assertEqual(name, "Highfield Partners Management")
        self.assertEqual(billable, 0)

    def test_near_miss_stays_needs_info(self) -> None:
        # Word-order scrambles and other near-misses never guess.
        self._seed()
        with db.connect(self.db) as conn:
            name, billable = actions.resolve_client(conn, "Highfield Management Partners")
        self.assertEqual(name, "Highfield Management Partners")
        self.assertIsNone(billable)

    def test_provenance_preserves_raw_client_name(self) -> None:
        self._seed()
        actions.start_session(self.db, "Acme", "warmup", "yes", "2026-05-28T09:00:00")
        result = actions.switch_session(
            self.db, "Partners, Highfield", "audit", None, "2026-05-28T09:20:00"
        )
        new_session = result["new_active_session"]
        self.assertEqual(new_session["client_name"], "Highfield Partners")
        self.assertEqual(new_session["raw_client_name"], "Partners, Highfield")


class StartSessionFoldTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.work = Path(self.tmp.name)
        self.db = self.work / "timeassist.sqlite"
        actions.init_state(self.db, "2026-05-28T09:00:00")
        path = self.work / "clients.csv"
        path.write_text(
            "client_key,display_name,aliases,default_billable\n"
            "jsmith,\"Smith, John\",,yes\n"
        )
        actions.import_clients(self.db, path)

    def test_start_resolves_folded_individual(self) -> None:
        session = actions.start_session(self.db, "John Smith", "kickoff", None, "2026-05-28T09:00:00")
        self.assertEqual(session["client_name"], "Smith, John")
        self.assertEqual(session["billable"], 1)
        self.assertEqual((session.get("capture_status") or "resolved"), "resolved")

    def test_switch_to_unknown_individual_needs_info(self) -> None:
        actions.start_session(self.db, "Smith, John", "kickoff", "yes", "2026-05-28T09:00:00")
        result = actions.switch_session(self.db, "Jane Doe", "misc", None, "2026-05-28T09:20:00")
        new_session = result["new_active_session"]
        self.assertEqual(new_session["capture_status"], "needs_info")


class CaptureRosterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.work = Path(self.tmp.name)
        self.db = self.work / "timeassist.sqlite"
        actions.init_state(self.db, "2026-05-28T09:00:00")
        path = self.work / "clients.csv"
        path.write_text(
            "client_key,display_name,aliases,default_billable\n"
            "acme,Acme Co,\"ACME;Acme Inc\",yes\n"
            "internal,Internal Admin,intadmin,no\n"
        )
        actions.import_clients(self.db, path)

    def test_add_missing_canonicalizes_client_name(self) -> None:
        entry = actions.add_missing_entry(
            self.db, "acme", "work", "2026-05-28T09:00:00", "2026-05-28T09:20:00", None,
        )
        self.assertEqual(entry["client_name"], "Acme Co")

    def test_add_missing_applies_roster_billable_default(self) -> None:
        entry = actions.add_missing_entry(
            self.db, "intadmin", "internal cleanup", "2026-05-28T09:00:00", "2026-05-28T09:20:00", None,
        )
        self.assertEqual(entry["client_name"], "Internal Admin")
        self.assertEqual(entry["billable"], 0)  # roster default for internal is no

    def test_explicit_billable_overrides_roster(self) -> None:
        entry = actions.add_missing_entry(
            self.db, "intadmin", "billable exception", "2026-05-28T09:00:00", "2026-05-28T09:20:00", "yes",
        )
        self.assertEqual(entry["billable"], 1)

    def test_unknown_client_defaults_billable_to_yes(self) -> None:
        entry = actions.add_missing_entry(
            self.db, "Wayne Ent", "work", "2026-05-28T09:00:00", "2026-05-28T09:20:00", None,
        )
        self.assertEqual(entry["client_name"], "Wayne Ent")
        self.assertEqual(entry["billable"], 1)

    def test_start_canonicalizes_and_applies_default(self) -> None:
        session = actions.start_session(self.db, "ACME", "kickoff", None, "2026-05-28T09:00:00")
        self.assertEqual(session["client_name"], "Acme Co")
        self.assertEqual(session["billable"], 1)

    def test_switch_canonicalizes_and_applies_default(self) -> None:
        actions.start_session(self.db, "Acme Co", "kickoff", "yes", "2026-05-28T09:00:00")
        result = actions.switch_session(self.db, "intadmin", "internal cleanup", None, "2026-05-28T09:20:00")
        new_session = result["new_active_session"]
        self.assertEqual(new_session["client_name"], "Internal Admin")
        self.assertEqual(new_session["billable"], 0)
        self.assertEqual(new_session["capture_status"], "resolved")
        self.assertEqual(new_session["raw_client_name"], "intadmin")
        self.assertEqual(new_session["raw_task_text"], "internal cleanup")
        self.assertIsNone(new_session["capture_note"])

    def test_switch_unknown_client_starts_immediately_and_marks_needs_info(self) -> None:
        actions.start_session(self.db, "Acme Co", "kickoff", "yes", "2026-05-28T09:00:00")

        result = actions.switch_session(self.db, "Henderson", "tax return", None, "2026-05-28T09:20:00")

        new_session = result["new_active_session"]
        self.assertEqual(new_session["client_name"], "Henderson")
        self.assertEqual(new_session["task_text"], "tax return")
        self.assertEqual(new_session["started_at"], "2026-05-28T09:20:00")
        self.assertEqual(new_session["capture_status"], "needs_info")
        self.assertEqual(new_session["raw_client_name"], "Henderson")
        self.assertEqual(new_session["raw_task_text"], "tax return")
        self.assertEqual(new_session["capture_note"], "client_not_in_roster")

        conn = sqlite3.connect(self.db)
        conn.row_factory = sqlite3.Row
        event = conn.execute("SELECT after_json FROM event_log WHERE event_type = 'switch' ORDER BY event_id DESC LIMIT 1").fetchone()
        conn.close()
        after = json.loads(event["after_json"])
        self.assertEqual(after["new_active_session"]["capture_status"], "needs_info")
        self.assertEqual(after["new_active_session"]["started_at"], "2026-05-28T09:20:00")

    def test_end_session_preserves_needs_info_for_review(self) -> None:
        actions.start_session(self.db, "Acme Co", "kickoff", "yes", "2026-05-28T09:00:00")
        actions.switch_session(self.db, "Henderson", "tax return", None, "2026-05-28T09:20:00")

        entry = actions.end_session(self.db, "2026-05-28T09:40:00")

        self.assertEqual(entry["review_status"], "needs_info")
        self.assertEqual(entry["capture_status"], "needs_info")
        self.assertEqual(entry["raw_client_name"], "Henderson")
        self.assertEqual(entry["capture_note"], "client_not_in_roster")
        review = actions.review_entries(self.db, "2026-05-28", "2026-05-28T10:00:00")
        needs_info = [item for item in review["entries"] if item["review_status"] == "needs_info"]
        self.assertEqual(len(needs_info), 1)
        self.assertEqual(needs_info[0]["needs_review_reason"], "client 'Henderson' is not in the roster")
        self.assertEqual(review["skipped_needs_info_count"], 1)

    def test_clarify_active_session_resolves_pending_capture_without_changing_start_time(self) -> None:
        actions.start_session(self.db, "Acme Co", "kickoff", "yes", "2026-05-28T09:00:00")
        actions.switch_session(self.db, "Henderson", "tax return", None, "2026-05-28T09:20:00")

        session = actions.clarify_active_session(
            self.db,
            client="Henderson LLC",
            task="tax return review",
            billable="yes",
            at="2026-05-28T09:25:00",
        )

        self.assertEqual(session["client_name"], "Henderson LLC")
        self.assertEqual(session["task_text"], "tax return review")
        self.assertEqual(session["started_at"], "2026-05-28T09:20:00")
        self.assertEqual(session["capture_status"], "resolved")
        self.assertEqual(session["clarified_at"], "2026-05-28T09:25:00")
        entry = actions.end_session(self.db, "2026-05-28T09:40:00")
        self.assertEqual(entry["review_status"], "draft")
        self.assertEqual(entry["capture_status"], "resolved")

    def test_edit_needs_info_entry_resolves_it_to_draft(self) -> None:
        actions.start_session(self.db, "Acme Co", "kickoff", "yes", "2026-05-28T09:00:00")
        actions.switch_session(self.db, "Henderson", "tax return", None, "2026-05-28T09:20:00")
        entry = actions.end_session(self.db, "2026-05-28T09:40:00")

        edited = actions.edit_entry(
            self.db,
            entry["entry_id"],
            client="Henderson LLC",
            task="tax return review",
            billable="yes",
            at="2026-05-28T09:45:00",
        )

        self.assertEqual(edited["review_status"], "draft")
        self.assertEqual(edited["capture_status"], "resolved")
        self.assertEqual(edited["client_name"], "Henderson LLC")
        self.assertEqual(edited["clarified_at"], "2026-05-28T09:45:00")

    def test_approval_and_export_skip_entries_that_still_need_info(self) -> None:
        actions.start_session(self.db, "Acme Co", "kickoff", "yes", "2026-05-28T09:00:00")
        actions.switch_session(self.db, "Henderson", "tax return", None, "2026-05-28T09:30:00")
        needs_info = actions.end_session(self.db, "2026-05-28T10:00:00")

        with self.assertRaisesRegex(ValueError, "needs clarification before approval"):
            actions.set_approval(self.db, needs_info["entry_id"], True, "2026-05-28T10:05:00")

        result = actions.approve_all(self.db, "2026-05-28", "2026-05-28T10:10:00")
        self.assertEqual(result["approved_count"], 1)
        self.assertEqual(result["skipped_needs_info_count"], 1)
        self.assertEqual(result["skipped_needs_info_minutes"], 30)
        export_path = self.work / "exports" / "qb.csv"
        export = actions.export_entries(self.db, "2026-05-28", export_path, at="2026-05-28T10:15:00")
        self.assertEqual(export["exported_count"], 1)
        self.assertEqual(export["skipped_needs_info_count"], 1)

    def test_switch_minutes_ago_closes_old_timer_and_starts_new_timer_at_relative_time(self) -> None:
        actions.start_session(self.db, "Acme Co", "kickoff", "yes", "2026-05-28T09:00:00")

        result = actions.switch_session(
            self.db,
            "intadmin",
            "internal cleanup",
            None,
            "2026-05-28T10:00:00",
            minutes_ago=20,
        )

        closed = result["closed_entry"]
        new_session = result["new_active_session"]
        self.assertEqual(closed["end_at"], "2026-05-28T09:40:00")
        self.assertEqual(closed["duration_minutes"], 40)
        self.assertEqual(new_session["started_at"], "2026-05-28T09:40:00")
        self.assertEqual(new_session["last_checkin_at"], "2026-05-28T09:40:00")
        self.assertEqual(new_session["client_name"], "Internal Admin")
        self.assertEqual(new_session["billable"], 0)
        self.assertEqual(new_session["capture_status"], "resolved")
        self.assertEqual(new_session["raw_client_name"], "intadmin")
        self.assertEqual(new_session["raw_task_text"], "internal cleanup")

    def test_switch_minutes_ago_rejects_negative_values(self) -> None:
        actions.start_session(self.db, "Acme Co", "kickoff", "yes", "2026-05-28T09:00:00")
        with self.assertRaises(ValueError):
            actions.switch_session(self.db, "admin", "internal cleanup", None, "2026-05-28T10:00:00", minutes_ago=-1)

    def test_switch_minutes_ago_rejects_zero_values(self) -> None:
        actions.start_session(self.db, "Acme Co", "kickoff", "yes", "2026-05-28T09:00:00")
        with self.assertRaisesRegex(ValueError, "minutes_ago must be greater than zero"):
            actions.switch_session(self.db, "admin", "internal cleanup", None, "2026-05-28T10:00:00", minutes_ago=0)

    def test_switch_minutes_ago_rejects_values_before_active_session_start(self) -> None:
        actions.start_session(self.db, "Acme Co", "kickoff", "yes", "2026-05-28T09:00:00")
        with self.assertRaisesRegex(ValueError, "is before the current timer started"):
            actions.switch_session(self.db, "admin", "internal cleanup", None, "2026-05-28T10:00:00", minutes_ago=90)

    def test_edit_canonicalizes_new_client_and_applies_default_when_billable_omitted(self) -> None:
        entry = actions.add_missing_entry(
            self.db, "acme", "move me", "2026-05-28T09:00:00", "2026-05-28T09:20:00", None,
        )
        edited = actions.edit_entry(self.db, entry["entry_id"], client="intadmin")
        self.assertEqual(edited["client_name"], "Internal Admin")
        self.assertEqual(edited["billable"], 0)

    def test_edit_preserves_explicit_billable_override_when_client_changes(self) -> None:
        entry = actions.add_missing_entry(
            self.db, "acme", "move me", "2026-05-28T09:00:00", "2026-05-28T09:20:00", None,
        )
        edited = actions.edit_entry(self.db, entry["entry_id"], client="intadmin", billable="yes")
        self.assertEqual(edited["client_name"], "Internal Admin")
        self.assertEqual(edited["billable"], 1)


class TimeMathHardeningTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = Path(self.tmp.name) / "timeassist.sqlite"
        actions.init_state(self.db, "2026-05-28T09:00:00")
        _seed_roster(self, "Acme")

    def test_parse_at_normalizes_aware_to_naive(self) -> None:
        # Offset-aware inputs must be folded to local naive so they never mix
        # with the naive timestamps now_iso() stores.
        self.assertIsNone(actions.parse_at("2026-05-29T17:00:00+00:00").tzinfo)
        self.assertIsNone(actions.parse_at("2026-05-29T17:00:00Z").tzinfo)
        self.assertIsNone(actions.parse_at("2026-05-29T17:00:00").tzinfo)

    def test_minutes_between_handles_mixed_awareness(self) -> None:
        # Previously raised TypeError (can't subtract naive and aware).
        result = actions.minutes_between("2026-05-29T09:00:00", "2026-05-29T09:30:00Z")
        self.assertIsInstance(result, int)

    def test_end_session_with_offset_at_does_not_crash(self) -> None:
        actions.start_session(self.db, "Acme", "x", "yes", "2026-05-29T09:00:00")
        entry = actions.end_session(self.db, "2026-05-29T09:30:00Z")
        self.assertEqual(entry["review_status"], "draft")

    def test_sub_minute_session_bills_at_least_one_minute(self) -> None:
        # A 20-second billable task must not vanish (was duration 0, rounded 0).
        entry = actions.add_missing_entry(
            self.db, "Acme", "quick call", "2026-05-29T09:00:00", "2026-05-29T09:00:20", "yes",
        )
        self.assertEqual(entry["duration_minutes"], 1)
        self.assertEqual(entry["rounded_minutes"], 1)

    def test_zero_length_block_stays_zero(self) -> None:
        # Truly instantaneous (end == start) is still 0 — only positive elapsed is floored to 1.
        entry = actions.add_missing_entry(
            self.db, "Acme", "noop", "2026-05-29T09:00:00", "2026-05-29T09:00:00", "yes",
        )
        self.assertEqual(entry["duration_minutes"], 0)

    def test_nearest_rounding_never_drops_positive_work_to_zero(self) -> None:
        # Billing floor: a positive entry must never round to 0 and silently
        # vanish from the export. 2 raw minutes under nearest_6 bills one
        # full increment (6), matching the sub-30s -> 1 raw minute rule.
        self.assertEqual(actions.round_minutes(2, 6, "nearest"), 6)
        self.assertEqual(actions.round_minutes(2, 15, "nearest"), 15)
        self.assertEqual(actions.round_minutes(2, 45, "nearest"), 45)  # custom increments keep the floor
        self.assertEqual(actions.round_minutes(0, 6, "nearest"), 0)


class DateValidationTests(unittest.TestCase):
    def test_today_and_blank_resolve_to_today(self) -> None:
        self.assertRegex(actions.normalize_date("today"), r"^\d{4}-\d{2}-\d{2}$")
        self.assertRegex(actions.normalize_date(None), r"^\d{4}-\d{2}-\d{2}$")

    def test_valid_date_passes_through(self) -> None:
        self.assertEqual(actions.normalize_date("2026-05-28"), "2026-05-28")

    def test_malformed_dates_raise(self) -> None:
        for bad in ["2026-5-1", "2026-13-99", "../../tmp/x", "May 1", "2026/05/28"]:
            with self.assertRaises(ValueError, msg=bad):
                actions.normalize_date(bad)


class MigrationAuditTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = Path(self.tmp.name) / "timeassist.sqlite"

    def test_legacy_rounding_migration_is_logged(self) -> None:
        conn = sqlite3.connect(self.db)
        conn.executescript(db.SCHEMA)
        conn.execute(
            "INSERT INTO settings(setting_key, setting_value, scope, updated_at) "
            "VALUES ('rounding_rule', 'nearest_6_minutes', 'local', '2026-01-01T00:00:00')"
        )
        conn.commit()
        conn.close()
        db.initialize(self.db, "2026-05-28T09:00:00")
        with db.connect(self.db) as c:
            n = c.execute("SELECT COUNT(*) AS n FROM event_log WHERE event_type = 'migration'").fetchone()["n"]
        self.assertEqual(n, 1)


class ExportHardeningTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.work = Path(self.tmp.name)
        self.db = self.work / "timeassist.sqlite"
        self.profile = self.work / "profile"
        self._old_userprofile = os.environ.get("USERPROFILE")
        os.environ["USERPROFILE"] = str(self.profile)
        self.addCleanup(self._restore_userprofile)
        actions.init_state(self.db, "2026-05-28T09:00:00")
        _seed_roster(self, "Acme Co")

    def _restore_userprofile(self) -> None:
        if self._old_userprofile is None:
            os.environ.pop("USERPROFILE", None)
        else:
            os.environ["USERPROFILE"] = self._old_userprofile

    def _approved_entry(self, client: str, task: str) -> int:
        # Seed the client so the capture resolves (roster gate #34) and can be
        # approved; the export-sanitizer assertions still see the same values.
        _seed_roster(self, client)
        entry = actions.add_missing_entry(self.db, client, task, "2026-05-28T09:00:00", "2026-05-28T09:30:00", "yes")
        actions.set_approval(self.db, entry["entry_id"], True, "2026-05-28T10:00:00")
        return entry["entry_id"]

    def test_export_neutralizes_csv_formula_injection(self) -> None:
        self._approved_entry("+cmd|calc", '=HYPERLINK("http://evil","x")')
        out = self.work / "qb.csv"
        actions.export_entries(self.db, "2026-05-28", out, at="2026-05-28T10:05:00")
        rows = list(csv.DictReader(out.read_text().splitlines()))
        self.assertTrue(rows[0]["Client"].startswith("'+"))
        self.assertTrue(rows[0]["Notes"].startswith("'="))

    def test_export_without_user_export_dir_uses_default_documents_copy(self) -> None:
        self._approved_entry("Acme Co", "work")
        out = self.work / "qb.csv"
        default_documents = self.profile / "Documents"

        with mock.patch.object(paths, "_documents_dir", return_value=default_documents):
            result = actions.export_entries(self.db, "2026-05-28", out, at="2026-05-28T10:05:00")

        default_dir = default_documents / "TimeAssist Exports"
        default_copy = default_dir / "qb.csv"
        self.assertEqual(result["user_export_dir"], str(default_dir.resolve()))
        self.assertEqual(result["user_visible_output"], str(default_copy.resolve()))
        self.assertIsNone(result["user_visible_copy_error"])
        self.assertTrue(default_copy.exists())
        self.assertEqual(default_copy.read_bytes(), out.read_bytes())

    def test_windows_uses_known_folder_documents_when_available(self) -> None:
        redirected = self.work / "OneDrive - Acme" / "Documents"

        with (
            mock.patch.object(paths, "_is_windows", return_value=True),
            mock.patch.object(paths, "_windows_known_documents_dir", return_value=redirected),
        ):
            result = paths.default_user_export_dir()

        self.assertEqual(result, (redirected / "TimeAssist Exports").resolve())
        self.assertNotEqual(result, (self.profile / "Documents" / "TimeAssist Exports").resolve())

    def test_windows_falls_back_to_userprofile_when_known_folder_fails(self) -> None:
        with (
            mock.patch.object(paths, "_is_windows", return_value=True),
            mock.patch.object(paths, "_windows_known_documents_dir", return_value=None),
        ):
            result = paths.default_user_export_dir()

        self.assertEqual(result, (self.profile / "Documents" / "TimeAssist Exports").resolve())

    def test_non_windows_default_unchanged(self) -> None:
        with mock.patch.object(paths, "_is_windows", return_value=False):
            result = paths.default_user_export_dir()

        self.assertEqual(result, (self.profile / "Documents" / "TimeAssist Exports").resolve())

    def test_known_folder_helper_returns_none_off_windows(self) -> None:
        with mock.patch.object(paths, "_is_windows", return_value=False):
            self.assertIsNone(paths._windows_known_documents_dir())

    def test_export_copies_exact_official_bytes_to_user_export_dir(self) -> None:
        self._approved_entry("+cmd|calc", '=HYPERLINK("http://evil","x")')
        out = self.work / "plugin-data" / "exports" / "qb.csv"
        user_dir = self.work / "operator-folder"
        actions.set_setting(self.db, "user_export_dir", str(user_dir))

        result = actions.export_entries(self.db, "2026-05-28", out, at="2026-05-28T10:05:00")

        user_copy = user_dir / "qb.csv"
        self.assertEqual(result["user_export_dir"], str(user_dir.resolve()))
        self.assertEqual(result["user_visible_output"], str(user_copy.resolve()))
        self.assertIsNone(result["user_visible_copy_error"])
        self.assertEqual(user_copy.read_bytes(), out.read_bytes())
        self.assertIn(b"'+cmd|calc", user_copy.read_bytes())
        self.assertIn(b"'=HYPERLINK", user_copy.read_bytes())

    def test_user_visible_copy_failure_does_not_rollback_official_export(self) -> None:
        entry_id = self._approved_entry("Acme Co", "work")
        out = self.work / "plugin-data" / "exports" / "qb.csv"
        user_dir = self.work / "operator-folder"
        actions.set_setting(self.db, "user_export_dir", str(user_dir))
        user_dir.write_text("not a directory\n")

        result = actions.export_entries(self.db, "2026-05-28", out, at="2026-05-28T10:05:00")

        self.assertTrue(out.exists())
        self.assertIsNone(result["user_visible_output"])
        self.assertIn("not a directory", result["user_visible_copy_error"])
        review = actions.review_entries(self.db, "2026-05-28")
        exported = next(entry for entry in review["entries"] if entry["entry_id"] == entry_id)
        self.assertEqual(exported["review_status"], "exported")

    def test_export_neutralizes_formula_after_leading_whitespace_or_newline(self) -> None:
        # Capture now strips leading whitespace/newlines (start/add_missing route
        # through the same resolver as switch), so feed the export sanitizer the
        # raw whitespace-prefixed payload directly — legacy or hand-edited rows
        # can still carry it, and the sanitizer must neutralize a formula that
        # follows whitespace.
        entry = actions.add_missing_entry(self.db, "Acme Co", "placeholder",
                                          "2026-05-28T09:00:00", "2026-05-28T09:30:00", "yes")
        with db.connect(self.db) as conn:
            conn.execute(
                "UPDATE time_entries SET client_name = ?, task_text = ? WHERE entry_id = ?",
                (" =2+2", "\n=HYPERLINK('http://evil')", entry["entry_id"]),
            )
            conn.commit()
        actions.set_approval(self.db, entry["entry_id"], True, "2026-05-28T10:00:00")
        out = self.work / "qb.csv"
        actions.export_entries(self.db, "2026-05-28", out, at="2026-05-28T10:05:00")
        text = out.read_text()
        self.assertIn("' =2+2", text)
        self.assertIn("'\n=HYPERLINK", text)

    def test_exported_entry_approval_is_idempotent_and_stays_exported(self) -> None:
        entry_id = self._approved_entry("Acme Co", "work")
        out = self.work / "qb.csv"
        actions.export_entries(self.db, "2026-05-28", out, at="2026-05-28T10:05:00")

        after = actions.set_approval(self.db, entry_id, True, "2026-05-28T10:10:00")

        self.assertEqual(after["review_status"], "exported")
        review = actions.review_entries(self.db, "2026-05-28")
        self.assertEqual(review["entries"][0]["review_status"], "exported")

    def test_empty_export_does_not_overwrite_existing_csv(self) -> None:
        actions.add_missing_entry(self.db, "Acme Co", "draft only", "2026-05-28T09:00:00", "2026-05-28T09:30:00", "yes")
        out = self.work / "qb.csv"
        out.write_text("PREVIOUS_GOOD_EXPORT\n")

        with self.assertRaises(ValueError):
            actions.export_entries(self.db, "2026-05-28", out, at="2026-05-28T10:05:00")

        self.assertEqual(out.read_text(), "PREVIOUS_GOOD_EXPORT\n")

    def test_reexport_keeps_already_exported_entries(self) -> None:
        self._approved_entry("Acme Co", "work")
        out = self.work / "qb.csv"
        actions.export_entries(self.db, "2026-05-28", out, at="2026-05-28T10:05:00")
        # Re-running export for the same date must not produce a header-only file
        # that drops the now-'exported' entry.
        actions.export_entries(self.db, "2026-05-28", out, at="2026-05-28T10:10:00")
        rows = list(csv.DictReader(out.read_text().splitlines()))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["Client"], "Acme Co")

    def test_export_returns_post_export_entry_statuses(self) -> None:
        self._approved_entry("Acme Co", "work")
        out = self.work / "qb.csv"
        result = actions.export_entries(self.db, "2026-05-28", out, at="2026-05-28T10:05:00")
        self.assertEqual(result["entries"][0]["review_status"], "exported")
        self.assertEqual(result["entries"][0]["export_path"], str(out.resolve()))

    def test_sanitize_packet_redacts_task_text(self) -> None:
        actions.add_missing_entry(
            self.db, "Acme Co", "Reconcile Acme Q3 payroll for jane@acme.com",
            "2026-05-28T09:00:00", "2026-05-28T09:30:00", "yes",
        )
        out = self.work / "packet.md"
        actions.write_sanitized_packet(self.db, "2026-05-28", out)
        text = out.read_text()
        self.assertNotIn("payroll", text)
        self.assertNotIn("jane@acme.com", text)
        self.assertIn("Client 1", text)
        self.assertIn("Task 1", text)

    def test_sanitize_packet_uses_notes_and_job_type_columns(self) -> None:
        actions.add_missing_entry(
            self.db, "Acme Co", "Reconcile payroll",
            "2026-05-28T09:00:00", "2026-05-28T09:30:00", "yes", job_type="Tax",
        )
        out = self.work / "packet.md"
        actions.write_sanitized_packet(self.db, "2026-05-28", out)
        text = out.read_text()
        self.assertIn("| Date | Client | Job Code | Notes | Duration | Status |", text)
        self.assertNotIn("| Entry | Client | Task | Minutes | Status |", text)
        # job_type is free text that can embed real client detail, so the packet
        # redacts it to a sequential label (review finding I1).
        self.assertNotIn("Tax", text)
        self.assertIn("| Client 1 | Job Code 1 |", text)

    def test_sanitized_packet_redacts_job_type(self) -> None:
        actions.add_missing_entry(
            self.db, "Real Client", "notes about a person",
            "2026-05-28T10:00:00", "2026-05-28T10:30:00",
            job_type="Tax prep for Smith Family Trust")
        out = self.work / "packet.md"
        actions.write_sanitized_packet(self.db, "2026-05-28", out)
        packet = out.read_text()
        self.assertNotIn("Smith Family Trust", packet)
        self.assertIn("Job Code 1", packet)

    def test_sanitized_packet_shares_job_type_label_and_keeps_blank(self) -> None:
        # Two entries with the SAME job_type share one label; an entry with an
        # empty job_type keeps an empty cell.
        actions.add_missing_entry(
            self.db, "Real Client", "first", "2026-05-28T10:00:00",
            "2026-05-28T10:30:00", job_type="Tax prep for Smith Family Trust")
        actions.add_missing_entry(
            self.db, "Real Client", "second", "2026-05-28T11:00:00",
            "2026-05-28T11:30:00", job_type="Tax prep for Smith Family Trust")
        actions.add_missing_entry(
            self.db, "Real Client", "third", "2026-05-28T12:00:00",
            "2026-05-28T12:30:00")
        out = self.work / "packet.md"
        actions.write_sanitized_packet(self.db, "2026-05-28", out)
        packet = out.read_text()
        self.assertNotIn("Smith Family Trust", packet)
        # same job_type => one shared label, no second label generated
        self.assertEqual(packet.count("Job Code 1"), 2)
        self.assertNotIn("Job Code 2", packet)
        # empty job_type renders an empty cell (double-space between the pipes)
        self.assertIn("| Client 1 |  | Task 3 |", packet)

    def test_review_html_uses_notes_and_job_type_headers(self) -> None:
        actions.add_missing_entry(
            self.db, "Acme Co", "Reconcile payroll",
            "2026-05-28T09:00:00", "2026-05-28T09:30:00", "yes", job_type="Tax",
        )
        review = actions.review_entries(self.db, "2026-05-28")
        out = self.work / "review.html"
        actions.render_review_html(review, out)
        text = out.read_text()
        self.assertIn("<th>Job Code</th>", text)
        self.assertIn("<th>Date</th>", text)
        self.assertIn("<th>Notes</th>", text)
        self.assertIn("<th>Duration</th>", text)
        self.assertNotIn("<th>Task</th>", text)
        self.assertNotIn("<th>Entry</th>", text)
        self.assertNotIn("<th>Entry ID</th>", text)
        self.assertIn(">Tax<", text)
        self.assertIn(">0:30<", text)


class ExportFormatTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.work = Path(self.tmp.name)
        self.db = self.work / "timeassist.sqlite"
        actions.init_state(self.db, "2026-05-28T09:00:00")
        _seed_roster(self, "Acme Co")

    def _approve(self, entry_id: int) -> None:
        actions.set_approval(self.db, entry_id, True, "2026-05-28T10:00:00")

    def test_format_hhmm(self) -> None:
        self.assertEqual(actions.format_hhmm(0), "0:00")
        self.assertEqual(actions.format_hhmm(5), "0:05")
        self.assertEqual(actions.format_hhmm(90), "1:30")
        self.assertEqual(actions.format_hhmm(600), "10:00")
        self.assertEqual(actions.format_hhmm(1500), "25:00")

    def test_export_columns_and_hhmm(self) -> None:
        entry = actions.add_missing_entry(
            self.db, "Acme Co", "Reconcile Q3 payroll",
            "2026-05-28T09:00:00", "2026-05-28T10:30:00", "yes", job_type="Tax",
        )
        self._approve(entry["entry_id"])
        out = self.work / "qb.csv"
        actions.export_entries(self.db, "2026-05-28", out, at="2026-05-28T10:05:00")
        rows = list(csv.DictReader(out.read_text().splitlines()))
        self.assertEqual(
            list(rows[0].keys()),
            ["Date", "Client", "Job Code", "Notes", "Duration", "Billable"],
        )
        self.assertEqual(rows[0]["Date"], "2026-05-28")
        self.assertEqual(rows[0]["Client"], "Acme Co")
        self.assertEqual(rows[0]["Job Code"], "Tax")
        self.assertEqual(rows[0]["Notes"], "Reconcile Q3 payroll")
        self.assertEqual(rows[0]["Duration"], "1:30")
        self.assertEqual(rows[0]["Billable"], "Yes")

    def test_export_empty_job_type(self) -> None:
        # Approve normally requires a Job Code; seed an approved blank-code row
        # so the CSV formatter still emits an empty Job Code cell.
        entry = actions.add_missing_entry(
            self.db, "Acme Co", "work",
            "2026-05-28T09:00:00", "2026-05-28T09:30:00", "yes",
        )
        with db.connect(self.db) as conn:
            conn.execute(
                "UPDATE time_entries SET review_status = 'approved', updated_at = ? WHERE entry_id = ?",
                ("2026-05-28T10:00:00", entry["entry_id"]),
            )
            conn.commit()
        out = self.work / "qb.csv"
        actions.export_entries(self.db, "2026-05-28", out, at="2026-05-28T10:05:00")
        rows = list(csv.DictReader(out.read_text().splitlines()))
        self.assertEqual(rows[0]["Job Code"], "")


class DurabilityFoundationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = Path(self.tmp.name) / "timeassist.sqlite"

    def test_connection_uses_wal(self) -> None:
        actions.init_state(self.db, "2026-05-28T09:00:00")
        with db.connect(self.db) as conn:
            mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        self.assertEqual(mode.lower(), "wal")

    def test_audit_retention_default_is_90(self) -> None:
        actions.init_state(self.db, "2026-05-28T09:00:00")
        self.assertEqual(actions.list_settings(self.db)["audit_retention_days"], "90")

    def test_database_enforces_one_active_session(self) -> None:
        actions.init_state(self.db, "2026-05-28T09:00:00")
        with db.connect(self.db) as conn:
            conn.execute(
                """
                INSERT INTO active_sessions(client_name, task_text, billable, started_at, last_checkin_at, status, created_at, updated_at)
                VALUES ('Alpha', 'work', 1, '2026-05-28T09:00:00', '2026-05-28T09:00:00', 'active', '2026-05-28T09:00:00', '2026-05-28T09:00:00')
                """
            )
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute(
                    """
                    INSERT INTO active_sessions(client_name, task_text, billable, started_at, last_checkin_at, status, created_at, updated_at)
                    VALUES ('Bravo', 'work', 1, '2026-05-28T09:01:00', '2026-05-28T09:01:00', 'active', '2026-05-28T09:01:00', '2026-05-28T09:01:00')
                    """
                )


class CancelSessionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = Path(self.tmp.name) / "timeassist.sqlite"

    def test_cancel_discards_active_session_without_entry(self) -> None:
        actions.start_session(self.db, "Acme Co", "x", "yes", "2026-05-28T09:00:00")
        result = actions.cancel_session(self.db, "2026-05-28T09:05:00")
        self.assertEqual(result["status"], "canceled")
        review = actions.review_entries(self.db, "2026-05-28")
        self.assertEqual(review["entries"], [])
        self.assertIsNone(review["active_session"])

    def test_cancel_without_active_raises(self) -> None:
        actions.init_state(self.db, "2026-05-28T09:00:00")
        with self.assertRaises(ValueError):
            actions.cancel_session(self.db)


class LastActivityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = Path(self.tmp.name) / "timeassist.sqlite"

    def test_review_reports_last_activity_when_events_exist(self) -> None:
        actions.add_missing_entry(self.db, "Acme Co", "x", "2026-05-28T09:00:00", "2026-05-28T09:30:00", "yes")
        review = actions.review_entries(self.db, "2026-05-28")
        self.assertIsNotNone(review["last_activity_at"])

    def test_review_last_activity_none_when_no_events(self) -> None:
        # review_entries auto-initializes but does NOT log an event, so a DB
        # touched only by review has an empty event_log.
        review = actions.review_entries(self.db, "2026-05-28")
        self.assertIsNone(review["last_activity_at"])


class ReviewWarningTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = Path(self.tmp.name) / "timeassist.sqlite"

    def test_review_warns_when_timer_is_still_active(self) -> None:
        actions.start_session(self.db, "Acme Co", "cleanup", "yes", "2026-05-28T09:00:00")

        review = actions.review_entries(self.db, "2026-05-28", at="2026-05-28T09:30:00")

        warning = review["active_timer_warning"]
        self.assertTrue(warning["has_active_timer"])
        self.assertFalse(warning["is_stale"])
        self.assertEqual(warning["prompt_reason"], "active_timer_open")
        self.assertEqual(warning["open_minutes"], 30)
        self.assertEqual(warning["client_name"], "Acme Co")
        self.assertIn("end", warning["suggested_actions"])
        self.assertIn("switch", warning["suggested_actions"])

    def test_review_marks_active_timer_stale_without_changing_review_token(self) -> None:
        actions.start_session(self.db, "Acme Co", "cleanup", "yes", "2026-05-28T09:00:00")
        actions.add_missing_entry(self.db, "Acme Co", "already captured", "2026-05-28T08:00:00", "2026-05-28T08:20:00", "yes")

        early = actions.review_entries(self.db, "2026-05-28", at="2026-05-28T09:30:00")
        stale = actions.review_entries(self.db, "2026-05-28", at="2026-05-28T18:00:00")

        self.assertEqual(stale["active_timer_warning"]["prompt_reason"], "stale_active_timer")
        self.assertTrue(stale["active_timer_warning"]["is_stale"])
        self.assertEqual(stale["active_timer_warning"]["open_minutes"], 540)
        self.assertEqual(stale["review_token"], early["review_token"])

    def test_review_has_no_active_timer_warning_when_idle(self) -> None:
        review = actions.review_entries(self.db, "2026-05-28", at="2026-05-28T09:30:00")

        warning = review["active_timer_warning"]
        self.assertFalse(warning["has_active_timer"])
        self.assertEqual(warning["prompt_reason"], "idle")
        self.assertEqual(warning["suggested_actions"], [])


class CheckinTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = Path(self.tmp.name) / "timeassist.sqlite"

    def test_checkin_status_reports_open_session(self) -> None:
        actions.start_session(self.db, "Acme Co", "cleanup", "yes", "2026-05-28T09:00:00")
        st = actions.checkin_status(self.db)
        self.assertTrue(st["active"])
        self.assertEqual(st["session"]["client_name"], "Acme Co")
        self.assertIsInstance(st["open_minutes"], int)

    def test_checkin_status_does_not_prompt_before_default_interval(self) -> None:
        actions.start_session(self.db, "Acme Co", "cleanup", "yes", "2026-05-28T09:00:00")

        st = actions.checkin_status(self.db, "2026-05-28T09:10:00")

        self.assertTrue(st["active"])
        self.assertFalse(st["should_prompt"])
        self.assertIsNone(st["prompt_reason"])
        self.assertEqual(st["minutes_since_checkin"], 10)
        self.assertEqual(st["checkin_interval_minutes"], 45)
        self.assertFalse(st["is_stale"])
        self.assertIn("still", st["suggested_actions"])

    def test_checkin_status_marks_reminder_due_at_default_interval(self) -> None:
        actions.start_session(self.db, "Acme Co", "cleanup", "yes", "2026-05-28T09:00:00")

        st = actions.checkin_status(self.db, "2026-05-28T09:45:00")

        self.assertTrue(st["active"])
        self.assertTrue(st["should_prompt"])
        self.assertEqual(st["prompt_reason"], "interval_elapsed")
        self.assertEqual(st["minutes_since_checkin"], 45)
        self.assertEqual(st["checkin_interval_minutes"], 45)
        self.assertFalse(st["is_stale"])

    def test_checkin_status_resets_after_checkin(self) -> None:
        actions.start_session(self.db, "Acme Co", "cleanup", "yes", "2026-05-28T09:00:00")
        actions.checkin(self.db, "2026-05-28T09:30:00")

        st = actions.checkin_status(self.db, "2026-05-28T09:50:00")

        self.assertFalse(st["should_prompt"])
        self.assertEqual(st["minutes_since_checkin"], 20)

    def test_snooze_checkin_suppresses_due_prompt_until_snooze_expires(self) -> None:
        actions.start_session(self.db, "Acme Co", "cleanup", "yes", "2026-05-28T09:00:00")

        snoozed = actions.snooze_checkin(self.db, 30, "2026-05-28T09:45:00")

        self.assertEqual(snoozed["snoozed_until"], "2026-05-28T10:15:00")
        st = actions.checkin_status(self.db, "2026-05-28T10:00:00")
        self.assertFalse(st["should_prompt"])
        self.assertEqual(st["prompt_reason"], "snoozed")
        self.assertEqual(st["snoozed_until"], "2026-05-28T10:15:00")

        due = actions.checkin_status(self.db, "2026-05-28T10:16:00")
        self.assertTrue(due["should_prompt"])
        self.assertEqual(due["prompt_reason"], "interval_elapsed")

    def test_snooze_checkin_logs_event(self) -> None:
        actions.start_session(self.db, "Acme Co", "cleanup", "yes", "2026-05-28T09:00:00")

        actions.snooze_checkin(self.db, 15, "2026-05-28T09:45:00")

        with db.connect(self.db) as conn:
            event = conn.execute("SELECT event_type, input_summary FROM event_log ORDER BY event_id DESC LIMIT 1").fetchone()
        self.assertEqual(event["event_type"], "snooze_checkin")
        self.assertIn("15 minutes", event["input_summary"])

    def test_snooze_checkin_requires_active_session(self) -> None:
        actions.init_state(self.db, "2026-05-28T09:00:00")
        with self.assertRaises(ValueError):
            actions.snooze_checkin(self.db, 30, "2026-05-28T09:45:00")

    def test_snooze_checkin_rejects_invalid_minutes(self) -> None:
        actions.start_session(self.db, "Acme Co", "cleanup", "yes", "2026-05-28T09:00:00")
        with self.assertRaisesRegex(ValueError, "minutes must be greater than zero"):
            actions.snooze_checkin(self.db, 0, "2026-05-28T09:45:00")

    def test_checkin_status_marks_long_running_session_stale(self) -> None:
        actions.start_session(self.db, "Acme Co", "cleanup", "yes", "2026-05-28T09:00:00")

        st = actions.checkin_status(self.db, "2026-05-28T17:00:00")

        self.assertTrue(st["should_prompt"])
        self.assertEqual(st["prompt_reason"], "stale_session")
        self.assertEqual(st["open_minutes"], 480)
        self.assertEqual(st["stale_session_minutes"], 480)
        self.assertTrue(st["is_stale"])

    def test_checkin_status_none_when_idle(self) -> None:
        actions.init_state(self.db, "2026-05-28T09:00:00")
        st = actions.checkin_status(self.db, "2026-05-28T09:10:00")
        self.assertFalse(st["active"])
        self.assertIsNone(st["session"])
        self.assertIsNone(st["open_minutes"])
        self.assertFalse(st["should_prompt"])
        self.assertEqual(st["prompt_reason"], "idle")

    def test_checkin_updates_last_checkin(self) -> None:
        actions.start_session(self.db, "Acme Co", "cleanup", "yes", "2026-05-28T09:00:00")
        after = actions.checkin(self.db, "2026-05-28T09:30:00")
        self.assertEqual(after["last_checkin_at"], "2026-05-28T09:30:00")

    def test_checkin_without_active_raises(self) -> None:
        actions.init_state(self.db, "2026-05-28T09:00:00")
        with self.assertRaises(ValueError):
            actions.checkin(self.db)


class DatabaseStatusTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = Path(self.tmp.name) / "timeassist.sqlite"
        _seed_roster(self, "Acme Co")

    def test_status_reports_counts_size_and_retention(self) -> None:
        entry = actions.add_missing_entry(self.db, "Acme Co", "x", "2026-05-28T09:00:00", "2026-05-28T09:30:00", "yes")
        actions.set_approval(self.db, entry["entry_id"], True, "2026-05-28T10:00:00")
        st = actions.database_status(self.db)
        self.assertEqual(st["entries"]["approved"], 1)
        self.assertEqual(st["entries"]["total"], 1)
        self.assertGreater(st["size_bytes"], 0)
        self.assertEqual(st["audit_retention_days"], 90)
        self.assertEqual(st["backup_count"], 0)


class CleanupTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = Path(self.tmp.name) / "timeassist.sqlite"

    def _insert_old_event(self) -> None:
        with db.connect(self.db) as conn:
            conn.execute(
                "INSERT INTO event_log(event_type, actor, input_summary, created_at) VALUES ('test', 't', 'old', '2020-01-01T00:00:00')"
            )

    def test_cleanup_prunes_old_events_but_keeps_entries(self) -> None:
        actions.add_missing_entry(self.db, "Acme Co", "x", "2026-05-28T09:00:00", "2026-05-28T09:30:00", "yes")
        self._insert_old_event()
        result = actions.cleanup_database(self.db, retention_days=90, vacuum=True, at="2026-05-29T12:00:00")
        self.assertGreaterEqual(result["pruned_events"], 1)
        self.assertTrue(result["vacuumed"])
        status = actions.database_status(self.db)
        self.assertEqual(status["entries"]["total"], 1)  # entry untouched
        with db.connect(self.db) as conn:
            n_old = conn.execute("SELECT COUNT(*) AS c FROM event_log WHERE created_at < '2021-01-01'").fetchone()["c"]
        self.assertEqual(n_old, 0)

    def test_cleanup_no_vacuum(self) -> None:
        actions.init_state(self.db, "2026-05-28T09:00:00")
        result = actions.cleanup_database(self.db, vacuum=False, at="2026-05-29T12:00:00")
        self.assertFalse(result["vacuumed"])

    def test_cleanup_rejects_nonpositive_retention(self) -> None:
        actions.init_state(self.db, "2026-05-28T09:00:00")
        for retention in (0, -1):
            with self.assertRaises(ValueError, msg=retention):
                actions.cleanup_database(self.db, retention_days=retention, vacuum=False, at="2026-05-29T12:00:00")


class DailyPruneTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = Path(self.tmp.name) / "timeassist.sqlite"
        actions.init_state(self.db, "2026-05-29T08:00:00")  # init_state does NOT trigger the prune

    def _insert_old_event(self) -> None:
        with db.connect(self.db) as conn:
            conn.execute(
                "INSERT INTO event_log(event_type, actor, input_summary, created_at) VALUES ('test', 't', 'old', '2020-01-01T00:00:00')"
            )

    def test_first_action_prunes_old_events_and_stamps_marker(self) -> None:
        self._insert_old_event()
        actions.review_entries(self.db, "2026-05-29")  # calls ensure_initialized -> prune
        with db.connect(self.db) as conn:
            n_old = conn.execute("SELECT COUNT(*) AS c FROM event_log WHERE created_at = '2020-01-01T00:00:00'").fetchone()["c"]
            marker = conn.execute("SELECT setting_value FROM settings WHERE setting_key = 'last_maintenance_at'").fetchone()
        self.assertEqual(n_old, 0)
        self.assertIsNotNone(marker)

    def test_last_maintenance_at_hidden_from_settings_readout(self) -> None:
        actions.review_entries(self.db, "2026-05-29")  # triggers prune -> stamps marker
        self.assertNotIn("last_maintenance_at", actions.list_settings(self.db))
        with db.connect(self.db) as conn:
            raw = conn.execute("SELECT 1 FROM settings WHERE setting_key = 'last_maintenance_at'").fetchone()
        self.assertIsNotNone(raw)  # still stored, just hidden from the readout

    def test_prune_gated_within_24h(self) -> None:
        actions.review_entries(self.db, "2026-05-29")  # first prune stamps marker = now
        self._insert_old_event()
        actions.review_entries(self.db, "2026-05-29")  # gated: marker is recent, no prune
        with db.connect(self.db) as conn:
            n_old = conn.execute("SELECT COUNT(*) AS c FROM event_log WHERE created_at = '2020-01-01T00:00:00'").fetchone()["c"]
        self.assertEqual(n_old, 1)


class BackupTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.work = Path(self.tmp.name)
        self.db = self.work / "timeassist.sqlite"

    def test_backup_creates_readable_copy(self) -> None:
        actions.add_missing_entry(self.db, "Acme Co", "x", "2026-05-28T09:00:00", "2026-05-28T09:30:00", "yes")
        result = actions.backup_database(self.db, at="2026-05-28T10:00:00")
        self.assertTrue(Path(result["path"]).exists())
        copy = sqlite3.connect(result["path"])
        copy.row_factory = sqlite3.Row
        n = copy.execute("SELECT COUNT(*) AS c FROM time_entries").fetchone()["c"]
        copy.close()
        self.assertEqual(n, 1)

    def test_backup_rotation_keeps_n(self) -> None:
        actions.init_state(self.db, "2026-05-28T08:00:00")
        for i in range(7):
            actions.backup_database(self.db, keep=5, at=f"2026-05-28T10:0{i}:00")
        backups = list((self.work / "backups").glob("timeassist-*.sqlite"))
        self.assertEqual(len(backups), 5)

    def test_same_second_backups_do_not_overwrite_each_other(self) -> None:
        actions.init_state(self.db, "2026-05-28T08:00:00")
        first = actions.backup_database(self.db, keep=5, at="2026-05-28T10:00:00")
        second = actions.backup_database(self.db, keep=5, at="2026-05-28T10:00:00")
        self.assertNotEqual(first["path"], second["path"])
        self.assertTrue(Path(first["path"]).exists())
        self.assertTrue(Path(second["path"]).exists())

    def test_same_second_backup_rotation_keeps_newest_suffixes(self) -> None:
        actions.init_state(self.db, "2026-05-28T08:00:00")
        created = [actions.backup_database(self.db, keep=5, at="2026-05-28T10:00:00")["path"] for _ in range(12)]

        for path in created[-5:]:
            self.assertTrue(Path(path).exists(), f"expected newest backup to remain: {path}")
        for path in created[:-5]:
            self.assertFalse(Path(path).exists(), f"expected older backup to rotate out: {path}")

    def test_export_writes_backup(self) -> None:
        _seed_roster(self, "Acme Co")
        entry = actions.add_missing_entry(self.db, "Acme Co", "x", "2026-05-28T09:00:00", "2026-05-28T09:30:00", "yes")
        actions.set_approval(self.db, entry["entry_id"], True, "2026-05-28T10:00:00")
        out = self.work / "qb.csv"
        result = actions.export_entries(self.db, "2026-05-28", out, at="2026-05-28T10:05:00")
        self.assertIsNotNone(result["backup"])
        self.assertTrue(Path(result["backup"]).exists())


class DiscardEntryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = str(Path(self.tmp.name) / "t.sqlite")
        actions.init_state(self.db, "2026-05-28T08:00:00")
        _seed_roster(self, "Client A")
        actions.start_session(self.db, "Client A", "cleanup", at="2026-05-28T09:00:00")
        self.entry = actions.end_session(self.db, at="2026-05-28T09:30:00")

    def test_discard_hides_entry_from_review_and_export(self) -> None:
        result = actions.discard_entry(self.db, self.entry["entry_id"], at="2026-05-28T09:31:00")
        self.assertEqual(result["review_status"], "discarded")
        review = actions.review_entries(self.db, "2026-05-28")
        self.assertEqual(review["entries"], [])
        with self.assertRaises(ValueError):
            actions.export_entries(self.db, "2026-05-28", str(Path(self.tmp.name) / "out.csv"))

    def test_discarded_entry_cannot_be_approved_or_edited(self) -> None:
        actions.discard_entry(self.db, self.entry["entry_id"])
        with self.assertRaisesRegex(ValueError, "discarded"):
            actions.set_approval(self.db, self.entry["entry_id"], True)
        with self.assertRaisesRegex(ValueError, "discarded"):
            actions.edit_entry(self.db, self.entry["entry_id"], task="nope")

    def test_only_draft_or_needs_info_can_be_discarded(self) -> None:
        actions.set_approval(self.db, self.entry["entry_id"], True)
        with self.assertRaisesRegex(ValueError, "approved"):
            actions.discard_entry(self.db, self.entry["entry_id"])

    def test_discard_is_audit_logged_and_row_kept(self) -> None:
        actions.discard_entry(self.db, self.entry["entry_id"])
        with actions.connect(self.db) as conn:
            row = conn.execute("SELECT review_status FROM time_entries WHERE entry_id = ?", (self.entry["entry_id"],)).fetchone()
            event = conn.execute("SELECT COUNT(*) AS c FROM event_log WHERE event_type = 'discard'").fetchone()
        self.assertEqual(row["review_status"], "discarded")
        self.assertEqual(event["c"], 1)
        self.assertEqual(actions.database_status(self.db)["entries"]["discarded"], 1)

    def test_discard_invalidates_outstanding_review_token(self) -> None:
        token = actions.review_entries(self.db, "2026-05-28")["review_token"]
        actions.discard_entry(self.db, self.entry["entry_id"])
        with self.assertRaisesRegex(ValueError, "stale"):
            actions.validate_review_token(self.db, "2026-05-28", token)

    def test_discarded_needs_info_entry_not_counted_as_skipped(self) -> None:
        # Switching to an unknown client marks the resulting entry needs_info.
        actions.start_session(self.db, "Client A", "kickoff", "yes", "2026-05-28T09:40:00")
        actions.switch_session(self.db, "Unknown Co", "tax return", None, "2026-05-28T09:50:00")
        needs_info_entry = actions.end_session(self.db, "2026-05-28T10:00:00")
        self.assertEqual(needs_info_entry["capture_status"], "needs_info")

        actions.discard_entry(self.db, needs_info_entry["entry_id"])

        result = actions.approve_all(self.db, "2026-05-28")
        self.assertEqual(result["skipped_needs_info_count"], 0)
        self.assertEqual(result["skipped_needs_info_minutes"], 0)


class NeedsInfoConfirmationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = str(Path(self.tmp.name) / "t.sqlite")
        actions.init_state(self.db, "2026-05-28T08:00:00")
        actions.start_session(self.db, "Client A", "cleanup", at="2026-05-28T09:00:00")
        switched = actions.switch_session(self.db, "acme", "test2", at="2026-05-28T09:10:00")
        self.entry = actions.end_session(self.db, at="2026-05-28T09:20:00")
        self.assertEqual(self.entry["capture_status"], "needs_info")

    def test_edit_reasserting_same_client_confirms_entry(self) -> None:
        resolved = actions.edit_entry(self.db, self.entry["entry_id"], client="acme")
        self.assertEqual(resolved["review_status"], "draft")
        self.assertEqual(resolved["capture_status"], "resolved")
        self.assertIsNone(resolved["capture_note"])
        self.assertEqual(resolved["billable"], self.entry["billable"])  # kept, not re-asked
        self.assertIsNotNone(resolved["clarified_at"])

    def test_edit_correcting_to_other_unknown_client_also_confirms(self) -> None:
        resolved = actions.edit_entry(self.db, self.entry["entry_id"], client="bobco")
        self.assertEqual(resolved["capture_status"], "resolved")
        self.assertEqual(resolved["client_name"], "bobco")

    def test_edit_without_client_keeps_needs_info_open(self) -> None:
        edited = actions.edit_entry(self.db, self.entry["entry_id"], task="better notes")
        self.assertEqual(edited["review_status"], "needs_info")
        self.assertEqual(edited["capture_status"], "needs_info")

    def test_explicit_billable_still_resolves_as_before(self) -> None:
        resolved = actions.edit_entry(self.db, self.entry["entry_id"], client="acme", billable="no")
        self.assertEqual(resolved["capture_status"], "resolved")
        self.assertEqual(resolved["billable"], 0)

    def test_correcting_to_known_client_applies_roster_default(self) -> None:
        # Import a roster where the known client is non-billable, then correct
        # the needs_info entry to it WITHOUT passing billable. The roster default
        # (no) must win over the entry's kept capture-time billable (yes).
        roster = Path(self.tmp.name) / "clients.csv"
        roster.write_text(
            "client_key,display_name,aliases,default_billable\n"
            "internal,Internal Admin,admin,no\n"
        )
        actions.import_clients(self.db, roster)
        self.assertEqual(self.entry["billable"], 1)  # captured needs_info default
        resolved = actions.edit_entry(self.db, self.entry["entry_id"], client="Internal Admin")
        self.assertEqual(resolved["capture_status"], "resolved")
        self.assertEqual(resolved["billable"], 0)  # roster default wins, not the kept 1

    def test_confirming_unknown_client_keeps_current_billable(self) -> None:
        resolved = actions.edit_entry(self.db, self.entry["entry_id"], client="acme")
        self.assertEqual(resolved["billable"], self.entry["billable"])

    def test_clarify_active_with_client_alone_resolves(self) -> None:
        # start_session never marks needs_info; switching to an unknown client
        # produces a needs_info ACTIVE session (matches existing test fixtures).
        actions.start_session(self.db, "Client A", "kickoff", at="2026-05-28T10:00:00")
        switched = actions.switch_session(self.db, "bob", "taxes", at="2026-05-28T10:05:00")
        self.assertEqual(switched["new_active_session"]["capture_status"], "needs_info")
        session = actions.clarify_active_session(self.db, client="bob", at="2026-05-28T10:10:00")
        self.assertEqual(session["capture_status"], "resolved")

    def test_clarify_active_to_known_client_applies_roster_default(self) -> None:
        # Mirror of test_correcting_to_known_client_applies_roster_default, but
        # for the open timer: correcting a needs_info ACTIVE session to a known
        # non-billable client WITHOUT passing billable must let the roster
        # default (no) win over the session's kept capture-time billable (yes).
        roster = Path(self.tmp.name) / "clients.csv"
        roster.write_text(
            "client_key,display_name,aliases,default_billable\n"
            "internal,Internal Admin,admin,no\n"
        )
        actions.import_clients(self.db, roster)
        actions.start_session(self.db, "Client A", "kickoff", at="2026-05-28T11:00:00")
        switched = actions.switch_session(self.db, "mystery", "taxes", at="2026-05-28T11:05:00")
        self.assertEqual(switched["new_active_session"]["capture_status"], "needs_info")
        self.assertEqual(switched["new_active_session"]["billable"], 1)  # kept needs_info default
        session = actions.clarify_active_session(
            self.db, client="Internal Admin", at="2026-05-28T11:10:00"
        )
        self.assertEqual(session["capture_status"], "resolved")
        self.assertEqual(session["billable"], 0)  # roster default wins, not the kept 1

    def test_approval_rejection_teaches_the_recipe(self) -> None:
        with self.assertRaisesRegex(ValueError, r"client 'acme' is not in the roster.*edit"):
            actions.set_approval(self.db, self.entry["entry_id"], True)


class BillableLockTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.work = Path(self.tmp.name)
        self.db = self.work / "timeassist.sqlite"
        actions.init_state(self.db, "2026-05-28T09:00:00")
        # A billable roster client with an explicit default_job_type (set via SQL,
        # mirroring an operator roster edit) so job_type inheritance can be pinned.
        roster = self.work / "clients.csv"
        roster.write_text(
            "client_key,display_name,aliases,default_billable\n"
            "acme,Acme Co,ACME,yes\n"
        )
        actions.import_clients(self.db, roster, mode="merge")
        with db.connect(self.db) as conn:
            conn.execute(
                "UPDATE clients SET default_job_type = 'Tax' WHERE client_key = 'acme'"
            )
            conn.commit()

    def _entry_row(self, entry_id: int) -> dict:
        with db.connect(self.db) as conn:
            return actions.row_to_dict(
                conn.execute("SELECT * FROM time_entries WHERE entry_id = ?", (entry_id,)).fetchone()
            )

    # --- apply_client_policy helper -------------------------------------
    def test_policy_admin_forces_non_billable_without_auto_job(self) -> None:
        with db.connect(self.db) as conn:
            row = actions.resolve_client_row(conn, "Admin")
        billable, job_type = actions.apply_client_policy(row, None, None)
        self.assertEqual(billable, 0)
        self.assertEqual(job_type, "")

    def test_policy_staff_meeting_auto_sets_administrative(self) -> None:
        with db.connect(self.db) as conn:
            row = actions.resolve_client_row(conn, "Staff Meeting")
        billable, job_type = actions.apply_client_policy(row, None, None)
        self.assertEqual(billable, 0)
        self.assertEqual(job_type, "Administrative")

    def test_policy_vacation_auto_sets_administrative(self) -> None:
        with db.connect(self.db) as conn:
            row = actions.resolve_client_row(conn, "Vacation")
        billable, job_type = actions.apply_client_policy(row, None, None)
        self.assertEqual((billable, job_type), (0, "Administrative"))

    def test_policy_locked_explicit_yes_raises(self) -> None:
        with db.connect(self.db) as conn:
            row = actions.resolve_client_row(conn, "Admin")
        with self.assertRaisesRegex(ValueError, r"administrative and cannot be billable"):
            actions.apply_client_policy(row, "yes", None)

    def test_policy_known_does_not_auto_apply_default_job_type(self) -> None:
        with db.connect(self.db) as conn:
            row = actions.resolve_client_row(conn, "Acme Co")
        billable, job_type = actions.apply_client_policy(row, None, None)
        self.assertEqual(billable, 1)
        self.assertEqual(job_type, "")

    def test_policy_explicit_job_type_wins_for_unlocked(self) -> None:
        with db.connect(self.db) as conn:
            row = actions.resolve_client_row(conn, "Acme Co")
        billable, job_type = actions.apply_client_policy(row, None, "Audit")
        self.assertEqual(job_type, "Audit")

    def test_policy_unknown_client_uses_passed_job_type_or_blank(self) -> None:
        self.assertEqual(actions.apply_client_policy(None, None, None), (1, ""))
        self.assertEqual(actions.apply_client_policy(None, "no", "Bookkeeping"), (0, "Bookkeeping"))

    def test_resolve_client_wrapper_tuple_unchanged(self) -> None:
        with db.connect(self.db) as conn:
            self.assertEqual(actions.resolve_client(conn, "Acme Co"), ("Acme Co", 1))
            self.assertEqual(actions.resolve_client(conn, "Admin"), ("Admin", 0))
            self.assertEqual(actions.resolve_client(conn, "Nobody"), ("Nobody", None))

    # --- start_session --------------------------------------------------
    def test_start_admin_forces_non_billable_and_suggests_job(self) -> None:
        session = actions.start_session(self.db, "Admin", "inbox", at="2026-05-28T10:00:00")
        self.assertEqual(session["billable"], 0)
        self.assertEqual(session["job_type"], "")
        self.assertEqual(session.get("suggested_job_type"), "Administrative")

    def test_start_locked_client_explicit_billable_raises(self) -> None:
        with self.assertRaisesRegex(ValueError, r"administrative and cannot be billable"):
            actions.start_session(self.db, "Holiday", "day off", billable="yes", at="2026-05-28T10:00:00")

    def test_start_roster_suggests_default_job_type_without_applying(self) -> None:
        session = actions.start_session(self.db, "Acme Co", "audit", at="2026-05-28T10:00:00")
        self.assertEqual(session["job_type"], "")
        self.assertEqual(session.get("suggested_job_type"), "Tax")

    def test_start_explicit_job_type_wins(self) -> None:
        session = actions.start_session(self.db, "Acme Co", "audit", at="2026-05-28T10:00:00", job_type="Audit")
        self.assertEqual(session["job_type"], "Audit")

    def test_start_unknown_client_stores_passed_job_type(self) -> None:
        session = actions.start_session(self.db, "Wayne Ent", "consult", at="2026-05-28T10:00:00", job_type="Consulting")
        self.assertEqual(session["job_type"], "Consulting")

    # --- close copies onto entry ---------------------------------------
    def test_start_end_locked_copies_to_entry(self) -> None:
        actions.start_session(self.db, "Staff Meeting", "standup", at="2026-05-28T10:00:00")
        entry = actions.end_session(self.db, "2026-05-28T10:30:00")
        self.assertEqual(entry["billable"], 0)
        self.assertEqual(entry["job_type"], "Administrative")

    # --- switch_session -------------------------------------------------
    def test_switch_threads_job_type(self) -> None:
        actions.start_session(self.db, "Acme Co", "kickoff", at="2026-05-28T10:00:00")
        result = actions.switch_session(
            self.db, "Acme Co", "review", at="2026-05-28T10:20:00", job_type="Audit"
        )
        self.assertEqual(result["new_active_session"]["job_type"], "Audit")

    def test_switch_to_admin_forces_non_billable_suggests_job(self) -> None:
        actions.start_session(self.db, "Acme Co", "kickoff", at="2026-05-28T10:00:00")
        result = actions.switch_session(self.db, "Admin", "email", at="2026-05-28T10:20:00")
        self.assertEqual(result["new_active_session"]["billable"], 0)
        self.assertEqual(result["new_active_session"]["job_type"], "")
        self.assertEqual(result["new_active_session"].get("suggested_job_type"), "Administrative")

    # --- add_missing_entry ---------------------------------------------
    def test_add_missing_threads_job_type(self) -> None:
        entry = actions.add_missing_entry(
            self.db, "Acme Co", "catchup", "2026-05-28T08:00:00", "2026-05-28T09:00:00", job_type="Audit"
        )
        self.assertEqual(entry["job_type"], "Audit")

    def test_add_missing_admin_forces_non_billable_suggests_job(self) -> None:
        entry = actions.add_missing_entry(
            self.db, "Admin", "backfill", "2026-05-28T08:00:00", "2026-05-28T09:00:00"
        )
        self.assertEqual(entry["billable"], 0)
        self.assertEqual(entry["job_type"], "")
        self.assertEqual(entry.get("suggested_job_type"), "Administrative")

    def test_add_missing_vacation_auto_job_and_non_billable(self) -> None:
        entry = actions.add_missing_entry(
            self.db, "Vacation", "vacation", "2026-05-28T08:00:00", "2026-05-28T16:00:00"
        )
        self.assertEqual(entry["billable"], 0)
        self.assertEqual(entry["job_type"], "Administrative")
        self.assertEqual(entry["task_text"], "")  # client-label echo blanked

    def test_add_missing_preserves_real_notes(self) -> None:
        entry = actions.add_missing_entry(
            self.db, "Admin", "email cleanup", "2026-05-28T08:00:00", "2026-05-28T09:00:00"
        )
        self.assertEqual(entry["task_text"], "email cleanup")

    # --- clarify_active_session ----------------------------------------
    def test_clarify_threads_job_type(self) -> None:
        actions.start_session(self.db, "Acme Co", "kickoff", at="2026-05-28T10:00:00")
        session = actions.clarify_active_session(self.db, job_type="Audit", at="2026-05-28T10:05:00")
        self.assertEqual(session["job_type"], "Audit")

    # --- edit_entry ----------------------------------------------------
    def test_edit_sets_and_changes_job_type(self) -> None:
        entry = actions.add_missing_entry(
            self.db, "Acme Co", "work", "2026-05-28T08:00:00", "2026-05-28T09:00:00"
        )
        edited = actions.edit_entry(self.db, entry["entry_id"], job_type="Audit", at="2026-05-28T12:00:00")
        self.assertEqual(edited["job_type"], "Audit")
        edited2 = actions.edit_entry(self.db, entry["entry_id"], job_type="Review", at="2026-05-28T12:05:00")
        self.assertEqual(edited2["job_type"], "Review")

    def test_edit_billable_only_preserves_job_type(self) -> None:
        entry = actions.add_missing_entry(
            self.db, "Acme Co", "work", "2026-05-28T08:00:00", "2026-05-28T09:00:00", job_type="Audit"
        )
        edited = actions.edit_entry(self.db, entry["entry_id"], billable="no", at="2026-05-28T12:00:00")
        self.assertEqual(edited["billable"], 0)
        self.assertEqual(edited["job_type"], "Audit")

    def test_edit_unrelated_field_preserves_blank_job_type(self) -> None:
        # Entry captured while the roster default_job_type was blank; the
        # operator later sets 'Tax' on the roster. Editing an unrelated field
        # (end time) must NOT back-fill the roster default onto the entry.
        with db.connect(self.db) as conn:
            conn.execute("UPDATE clients SET default_job_type = '' WHERE client_key = 'acme'")
            conn.commit()
        entry = actions.add_missing_entry(
            self.db, "Acme Co", "work", "2026-05-28T08:00:00", "2026-05-28T09:00:00"
        )
        self.assertEqual(entry["job_type"], "")
        with db.connect(self.db) as conn:
            conn.execute("UPDATE clients SET default_job_type = 'Tax' WHERE client_key = 'acme'")
            conn.commit()
        edited = actions.edit_entry(self.db, entry["entry_id"], end="2026-05-28T09:30:00", at="2026-05-28T12:00:00")
        self.assertEqual(edited["end_at"], "2026-05-28T09:30:00")
        self.assertEqual(edited["job_type"], "")

    def test_edit_billable_yes_on_locked_raises(self) -> None:
        actions.start_session(self.db, "Admin", "email", at="2026-05-28T10:00:00")
        entry = actions.end_session(self.db, "2026-05-28T10:30:00")
        with self.assertRaisesRegex(ValueError, r"administrative and cannot be billable"):
            actions.edit_entry(self.db, entry["entry_id"], billable="yes", at="2026-05-28T12:00:00")

    def test_edit_client_to_admin_forces_non_billable(self) -> None:
        entry = actions.add_missing_entry(
            self.db, "Acme Co", "work", "2026-05-28T08:00:00", "2026-05-28T09:00:00", job_type="Audit"
        )
        edited = actions.edit_entry(self.db, entry["entry_id"], client="Admin", at="2026-05-28T12:00:00")
        self.assertEqual(edited["client_name"], "Admin")
        self.assertEqual(edited["billable"], 0)
        # Prior job preserved until operator changes it; Admin does not auto-overwrite.
        self.assertEqual(edited["job_type"], "Audit")

    def test_edit_admin_entry_times_still_work(self) -> None:
        actions.start_session(self.db, "Admin", "email", at="2026-05-28T10:00:00")
        entry = actions.end_session(self.db, "2026-05-28T10:30:00")
        edited = actions.edit_entry(self.db, entry["entry_id"], end="2026-05-28T11:00:00", at="2026-05-28T12:00:00")
        self.assertEqual(edited["end_at"], "2026-05-28T11:00:00")
        self.assertEqual(edited["billable"], 0)
        self.assertEqual(edited["job_type"], "")

    def test_edit_fold_resolves_needs_info_client(self) -> None:
        # A needs_info entry captured as 'John Smith' (roster had no match yet).
        # After 'Smith, John' is added, an operator edit that addresses the
        # client resolves it via the comma-swap fold and clears needs_info.
        actions.start_session(self.db, "Acme Co", "hold", at="2026-05-28T10:00:00")
        actions.switch_session(self.db, "John Smith", "advice", at="2026-05-28T10:10:00")
        entry = actions.end_session(self.db, "2026-05-28T10:20:00")
        self.assertEqual(entry["capture_status"], "needs_info")
        roster = self.work / "people.csv"
        roster.write_text(
            "client_key,display_name,aliases,default_billable\n"
            "sj,\"Smith, John\",,yes\n"
        )
        actions.import_clients(self.db, roster, mode="merge")
        edited = actions.edit_entry(self.db, entry["entry_id"], client="John Smith", at="2026-05-28T12:00:00")
        self.assertEqual(edited["client_name"], "Smith, John")
        self.assertEqual(edited["capture_status"], "resolved")
        self.assertEqual(edited["review_status"], "draft")


class ApplyClientPolicyCurrentValueTests(unittest.TestCase):
    def _row(self, **overrides):
        base = {"display_name": "Acme Co", "default_billable": 1,
                "default_job_type": "Bookkeeping", "billable_locked": 0}
        base.update(overrides)
        return base  # dict is fine: policy only uses [] access and int()

    def test_explicit_empty_job_type_clears(self) -> None:
        billable, job_type = actions.apply_client_policy(self._row(), None, "")
        self.assertEqual(job_type, "")

    def test_none_job_type_prefers_current_over_default(self) -> None:
        billable, job_type = actions.apply_client_policy(
            self._row(), None, None, current_job_type="Payroll")
        self.assertEqual(job_type, "Payroll")

    def test_none_job_type_preserves_current_blank(self) -> None:
        billable, job_type = actions.apply_client_policy(
            self._row(), None, None, current_job_type="")
        self.assertEqual(job_type, "")

    def test_fresh_capture_leaves_job_type_blank(self) -> None:
        billable, job_type = actions.apply_client_policy(self._row(), None, None)
        self.assertEqual(job_type, "")

    def test_current_billable_preserved_when_not_requested(self) -> None:
        billable, _ = actions.apply_client_policy(
            self._row(default_billable=1), None, None, current_billable=0)
        self.assertEqual(billable, 0)

    def test_admin_row_forces_billable_preserves_current_job(self) -> None:
        row = self._row(display_name="Admin", default_job_type="Administrative",
                        billable_locked=1)
        billable, job_type = actions.apply_client_policy(
            row, None, None, current_billable=1, current_job_type="X")
        self.assertEqual((billable, job_type), (0, "X"))

    def test_staff_meeting_auto_job_when_unset(self) -> None:
        row = self._row(display_name="Staff Meeting", default_job_type="Administrative",
                        billable_locked=1)
        billable, job_type = actions.apply_client_policy(row, None, None)
        self.assertEqual((billable, job_type), (0, "Administrative"))


class EditPolicyGuardTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.work = Path(self.tmp.name)
        self.db = self.work / "timeassist.sqlite"
        actions.init_state(self.db, "2026-05-28T09:00:00")

    def test_task_only_edit_preserves_legacy_locked_billable(self) -> None:
        # Legacy row: billable=1 on the locked Admin client (pre-upgrade data).
        entry = actions.add_missing_entry(
            self.db, "Some Client", "t", "2026-05-28T10:00:00", "2026-05-28T10:30:00", "yes")
        with db.connect(self.db) as conn:
            conn.execute(
                "UPDATE time_entries SET client_name='Admin', billable=1, "
                "capture_status='resolved', review_status='draft' WHERE entry_id=?",
                (entry["entry_id"],))
            conn.commit()
        after = actions.edit_entry(self.db, entry["entry_id"], task="notes only")
        self.assertEqual(after["billable"], 1)  # preserved; the approve gate owns legacy rows

    def test_explicit_job_type_edit_on_locked_row_applies_policy(self) -> None:
        entry = actions.add_missing_entry(
            self.db, "Some Client", "t", "2026-05-28T10:00:00", "2026-05-28T10:30:00", "yes")
        with db.connect(self.db) as conn:
            conn.execute(
                "UPDATE time_entries SET client_name='Admin', billable=1, "
                "capture_status='resolved', review_status='draft' WHERE entry_id=?",
                (entry["entry_id"],))
            conn.commit()
        after = actions.edit_entry(self.db, entry["entry_id"], job_type="Whatever")
        self.assertEqual(after["billable"], 0)
        # Admin: explicit Job Code wins (suggest-only default; operator may confirm others).
        self.assertEqual(after["job_type"], "Whatever")

    def test_explicit_empty_job_type_edit_clears_it(self) -> None:
        entry = actions.add_missing_entry(
            self.db, "Client Z", "t", "2026-05-28T10:00:00", "2026-05-28T10:30:00",
            "yes", job_type="Payroll")
        after = actions.edit_entry(self.db, entry["entry_id"], job_type="")
        self.assertEqual(after["job_type"], "")


class ClarifyJobTypePreservationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.work = Path(self.tmp.name)
        self.db = self.work / "timeassist.sqlite"
        actions.init_state(self.db, "2026-05-28T09:00:00")

    def test_task_only_clarify_preserves_blank_job_type(self) -> None:
        actions.start_session(self.db, "Client A", "w", "yes", "2026-05-28T09:00:00")
        session = actions.clarify_active_session(self.db, task="better notes",
                                                 at="2026-05-28T09:05:00")
        self.assertEqual(session["job_type"], "")


class UnknownClientCaptureGateTests(unittest.TestCase):
    # Pilot email (#34): a non-roster name is fine as a temporary placeholder,
    # but at approve/export time the name must match the master list. That gate
    # is needs_info — so EVERY capture path must mark unknown clients, not just
    # switch. Pinned per the intentional-but-surprising convention.
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.work = Path(self.tmp.name)
        self.db = self.work / "timeassist.sqlite"
        actions.init_state(self.db, "2026-05-28T09:00:00")

    def test_start_unknown_client_is_needs_info(self) -> None:
        session = actions.start_session(self.db, "Zeta Nowhere Ltd", "mystery", None, "2026-05-28T09:00:00")
        self.assertEqual(session["capture_status"], "needs_info")
        self.assertEqual(session["capture_note"], "client_not_in_roster")
        entry = actions.end_session(self.db, "2026-05-28T09:30:00")
        self.assertEqual(entry["review_status"], "needs_info")

    def test_add_missing_unknown_client_is_needs_info_and_blocked_from_approval(self) -> None:
        entry = actions.add_missing_entry(self.db, "Ghost Client", "phantom",
                                          "2026-05-28T10:00:00", "2026-05-28T10:30:00")
        self.assertEqual(entry["review_status"], "needs_info")
        with self.assertRaises(ValueError):
            actions.set_approval(self.db, entry["entry_id"], True)

    def test_confirm_as_is_edit_still_resolves(self) -> None:
        entry = actions.add_missing_entry(self.db, "Ghost Client", "phantom",
                                          "2026-05-28T10:00:00", "2026-05-28T10:30:00")
        after = actions.edit_entry(self.db, entry["entry_id"], client="Ghost Client")
        self.assertEqual(after["review_status"], "draft")
        self.assertEqual(after["capture_status"], "resolved")
        self.assertEqual(after["billable"], 1)  # unknown-name confirm keeps billable

    def test_start_known_client_stays_resolved(self) -> None:
        path = self.work / "clients.csv"
        path.write_text("display_name,aliases,default_billable\nClient A,,yes\n")
        actions.import_clients(self.db, path)
        session = actions.start_session(self.db, "Client A", "w", None, "2026-05-28T11:00:00")
        self.assertEqual(session["capture_status"], "resolved")


class LockedBillableFinalizeGateTests(unittest.TestCase):
    # Pilot email (#34): admin clients must be IMPOSSIBLE to bill. Capture and
    # edit force billable=0, but pre-upgrade (v0.1.19) rows can carry billable=1
    # on a now-locked client — the finalize gates are the safety net.
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.work = Path(self.tmp.name)
        self.db = self.work / "timeassist.sqlite"
        actions.init_state(self.db, "2026-05-28T09:00:00")

    def _legacy_admin_entry(self) -> int:
        entry = actions.add_missing_entry(self.db, "Placeholder", "internal admin work",
                                          "2026-05-28T10:00:00", "2026-05-28T10:30:00")
        with db.connect(self.db) as conn:
            conn.execute(
                "UPDATE time_entries SET client_name='Admin', billable=1, "
                "capture_status='resolved', review_status='draft' WHERE entry_id=?",
                (entry["entry_id"],))
            conn.commit()
        return entry["entry_id"]

    def test_approve_rejects_locked_billable_entry(self) -> None:
        entry_id = self._legacy_admin_entry()
        with self.assertRaises(ValueError) as ctx:
            actions.set_approval(self.db, entry_id, True)
        self.assertIn("administrative and cannot be billable", str(ctx.exception))

    def test_approve_all_skips_locked_billable_and_counts(self) -> None:
        self._legacy_admin_entry()
        result = actions.approve_all(self.db, "2026-05-28")
        self.assertEqual(result["approved_count"], 0)
        self.assertEqual(result["skipped_locked_count"], 1)
        self.assertEqual(result["skipped_locked_minutes"], 30)

    def test_export_skips_locked_billable_and_counts(self) -> None:
        entry_id = self._legacy_admin_entry()
        with db.connect(self.db) as conn:  # simulate a pre-upgrade approval
            conn.execute("UPDATE time_entries SET review_status='approved' WHERE entry_id=?",
                         (entry_id,))
            conn.commit()
        out = self.work / "out.csv"
        with self.assertRaises(ValueError):
            # only entry of the day is skipped -> nothing to export
            actions.export_entries(self.db, "2026-05-28", out)

    def test_export_mixed_day_skips_locked_and_exports_rest(self) -> None:
        locked_id = self._legacy_admin_entry()
        _seed_roster(self, "Client A")
        ok = actions.add_missing_entry(self.db, "Client A", "real work",
                                       "2026-05-28T11:00:00", "2026-05-28T11:30:00", "yes")
        with db.connect(self.db) as conn:
            conn.execute("UPDATE time_entries SET review_status='approved' WHERE entry_id IN (?, ?)",
                         (locked_id, ok["entry_id"]))
            conn.commit()
        out = self.work / "out.csv"
        result = actions.export_entries(self.db, "2026-05-28", out)
        self.assertEqual(result["exported_count"], 1)
        self.assertEqual(result["skipped_locked_count"], 1)
        self.assertEqual(result["skipped_locked_minutes"], 30)
        text = out.read_text()
        self.assertNotIn("Admin", text)
        self.assertIn("Client A", text)

    def test_non_billable_admin_entry_finalizes_normally(self) -> None:
        session = actions.start_session(self.db, "Admin", "emails", None, "2026-05-28T11:00:00")
        self.assertEqual(session["billable"], 0)
        actions.end_session(self.db, "2026-05-28T11:30:00")
        result = actions.approve_all(self.db, "2026-05-28")
        self.assertEqual(result["approved_count"], 1)


class NotesNudgeTests(unittest.TestCase):
    # Pilot feedback #34: empty Notes should NUDGE (never block). The engine only
    # surfaces the signal; approval must never be gated on notes.
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.work = Path(self.tmp.name)
        self.db = self.work / "timeassist.sqlite"
        actions.init_state(self.db, "2026-05-28T09:00:00")
        _seed_roster(self, "Acme Co")

    def test_end_session_flags_missing_notes(self) -> None:
        actions.start_session(self.db, "Acme Co", "", "yes", "2026-05-28T09:00:00")
        entry = actions.end_session(self.db, "2026-05-28T09:30:00")
        self.assertTrue(entry.get("notes_missing"))

    def test_end_session_no_flag_with_notes(self) -> None:
        actions.start_session(self.db, "Acme Co", "quarterly filing", "yes", "2026-05-28T09:00:00")
        entry = actions.end_session(self.db, "2026-05-28T09:30:00")
        self.assertIsNone(entry.get("notes_missing"))

    def test_end_session_whitespace_notes_counts_as_missing(self) -> None:
        actions.start_session(self.db, "Acme Co", "   ", "yes", "2026-05-28T09:00:00")
        entry = actions.end_session(self.db, "2026-05-28T09:30:00")
        self.assertTrue(entry.get("notes_missing"))

    def test_switch_session_flags_missing_notes_on_closed_entry(self) -> None:
        actions.start_session(self.db, "Acme Co", "", "yes", "2026-05-28T09:00:00")
        result = actions.switch_session(self.db, "Beta LLC", "audit", "yes", "2026-05-28T09:20:00")
        self.assertTrue(result["closed_entry"].get("notes_missing"))

    def test_switch_session_no_flag_with_notes(self) -> None:
        actions.start_session(self.db, "Acme Co", "kickoff", "yes", "2026-05-28T09:00:00")
        result = actions.switch_session(self.db, "Beta LLC", "audit", "yes", "2026-05-28T09:20:00")
        self.assertIsNone(result["closed_entry"].get("notes_missing"))

    def test_review_counts_missing_notes(self) -> None:
        actions.start_session(self.db, "Acme Co", "", "yes", "2026-05-28T09:00:00")
        actions.switch_session(self.db, "Beta LLC", "real notes", "yes", "2026-05-28T09:20:00")
        actions.end_session(self.db, "2026-05-28T09:40:00")
        review = actions.review_entries(self.db, "2026-05-28")
        self.assertEqual(review["missing_notes_count"], 1)

    def test_review_excludes_discarded_from_missing_notes(self) -> None:
        actions.start_session(self.db, "Acme Co", "", "yes", "2026-05-28T09:00:00")
        entry = actions.end_session(self.db, "2026-05-28T09:30:00")
        actions.discard_entry(self.db, entry["entry_id"], "2026-05-28T09:35:00")
        review = actions.review_entries(self.db, "2026-05-28")
        self.assertEqual(review["missing_notes_count"], 0)

    def test_review_missing_notes_count_present_when_zero(self) -> None:
        actions.start_session(self.db, "Acme Co", "quarterly filing", "yes", "2026-05-28T09:00:00")
        actions.end_session(self.db, "2026-05-28T09:30:00")
        review = actions.review_entries(self.db, "2026-05-28")
        self.assertEqual(review["missing_notes_count"], 0)

    def test_switch_audit_log_never_persists_notes_missing(self) -> None:
        # notes_missing is a result signal only — it must not leak into event_log
        # via switch_session's after={"closed_entry": ...} snapshot.
        actions.start_session(self.db, "Acme Co", "", "yes", "2026-05-28T09:00:00")
        result = actions.switch_session(self.db, "Beta LLC", "audit", "yes", "2026-05-28T09:20:00")
        self.assertTrue(result["closed_entry"].get("notes_missing"))
        conn = sqlite3.connect(self.db)
        conn.row_factory = sqlite3.Row
        event = conn.execute("SELECT after_json FROM event_log WHERE event_type = 'switch' ORDER BY event_id DESC LIMIT 1").fetchone()
        conn.close()
        after = json.loads(event["after_json"])
        self.assertNotIn("notes_missing", after["closed_entry"])

    def test_end_audit_log_never_persists_notes_missing(self) -> None:
        actions.start_session(self.db, "Client A", "", None, "2026-05-28T09:00:00")
        entry = actions.end_session(self.db, "2026-05-28T09:30:00")
        self.assertTrue(entry.get("notes_missing"))
        with db.connect(self.db) as conn:
            leaked = conn.execute(
                "SELECT 1 FROM event_log WHERE COALESCE(after_json,'') LIKE '%notes_missing%' "
                "OR COALESCE(before_json,'') LIKE '%notes_missing%'").fetchone()
        self.assertIsNone(leaked)

    def test_missing_notes_never_blocks_approval(self) -> None:
        # #34: nudge, do not gate — approval succeeds on an empty-notes draft.
        actions.start_session(self.db, "Acme Co", "", "yes", "2026-05-28T09:00:00")
        entry = actions.end_session(self.db, "2026-05-28T09:30:00")
        approved = actions.set_approval(self.db, entry["entry_id"], True, "2026-05-28T10:00:00")
        self.assertEqual(approved["review_status"], "approved")

    def test_missing_notes_never_blocks_approve_all(self) -> None:
        actions.start_session(self.db, "Acme Co", "", "yes", "2026-05-28T09:00:00")
        actions.end_session(self.db, "2026-05-28T09:30:00")
        result = actions.approve_all(self.db, "2026-05-28", "2026-05-28T10:00:00")
        self.assertEqual(result["approved_count"], 1)


class StrictRosterSettingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = Path(self.tmp.name) / "timeassist.sqlite"
        actions.init_state(self.db, "2026-05-28T09:00:00")

    def test_set_setting_normalizes_truthy_and_falsy_values(self) -> None:
        actions.set_setting(self.db, "strict_roster", "on")
        self.assertEqual(actions.list_settings(self.db)["strict_roster"], "yes")
        actions.set_setting(self.db, "strict_roster", "0")
        self.assertEqual(actions.list_settings(self.db)["strict_roster"], "no")

    def test_set_setting_rejects_unrecognized_values(self) -> None:
        with self.assertRaisesRegex(ValueError, "yes or no"):
            actions.set_setting(self.db, "strict_roster", "maybe")
        self.assertNotIn("strict_roster", actions.list_settings(self.db))

    def test_defaults_off_and_reads_stored_value(self) -> None:
        with db.connect(self.db) as conn:
            self.assertFalse(actions.strict_roster_enabled(conn))
        actions.set_setting(self.db, "strict_roster", "yes")
        with db.connect(self.db) as conn:
            self.assertTrue(actions.strict_roster_enabled(conn))


class StrictRosterEnforcementTests(unittest.TestCase):
    """Decision 1 = C (issue #39 item 1): strict_roster disables confirm-as-is
    at resolution time while capture stays non-blocking."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = Path(self.tmp.name) / "timeassist.sqlite"
        actions.init_state(self.db, "2026-05-28T08:55:00")
        _seed_roster(self, "Client A")
        actions.set_setting(self.db, "strict_roster", "yes")

    def _needs_info_entry(self) -> dict:
        return actions.add_missing_entry(
            self.db, "Mystery Co", "call notes",
            "2026-05-28T09:00:00", "2026-05-28T09:23:00",
        )

    def test_confirm_as_is_edit_raises_and_entry_stays_needs_info(self) -> None:
        entry = self._needs_info_entry()
        self.assertEqual(entry["review_status"], "needs_info")
        with self.assertRaisesRegex(ValueError, "strict roster"):
            actions.edit_entry(self.db, entry["entry_id"], client="Mystery Co")
        after = actions.review_entries(self.db, "2026-05-28")["entries"][0]
        self.assertEqual(after["review_status"], "needs_info")

    def test_explicit_billable_confirm_raises_under_strict(self) -> None:
        entry = self._needs_info_entry()
        with self.assertRaisesRegex(ValueError, "strict roster"):
            actions.edit_entry(self.db, entry["entry_id"], billable="yes")

    def test_clarify_active_confirm_as_is_raises(self) -> None:
        actions.start_session(self.db, "Mystery Co", "call", None, "2026-05-28T10:00:00")
        with self.assertRaisesRegex(ValueError, "strict roster"):
            actions.clarify_active_session(self.db, client="Mystery Co")

    def test_correcting_to_roster_name_still_resolves(self) -> None:
        entry = self._needs_info_entry()
        fixed = actions.edit_entry(self.db, entry["entry_id"], client="Client A")
        self.assertEqual(fixed["review_status"], "draft")
        self.assertEqual(fixed["client_name"], "Client A")
        self.assertEqual(fixed["billable"], 1)

    def test_capture_never_blocks_under_strict(self) -> None:
        entry = self._needs_info_entry()
        self.assertEqual(entry["review_status"], "needs_info")
        session = actions.start_session(self.db, "Another Unknown", "work", None, "2026-05-28T11:00:00")
        self.assertEqual(session["capture_status"], "needs_info")

    def test_strict_off_keeps_confirm_as_is(self) -> None:
        actions.set_setting(self.db, "strict_roster", "no")
        entry = self._needs_info_entry()
        confirmed = actions.edit_entry(self.db, entry["entry_id"], client="Mystery Co")
        self.assertEqual(confirmed["review_status"], "draft")
        self.assertEqual(confirmed["client_name"], "Mystery Co")


class AddClientTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = Path(self.tmp.name) / "timeassist.sqlite"
        actions.init_state(self.db, "2026-05-28T08:55:00")
        _seed_roster(self, "Client A")

    def test_adds_one_client_with_defaults(self) -> None:
        result = actions.add_client(self.db, "Acme Widgets")
        client = result["client"]
        self.assertEqual(client["client_key"], "acme_widgets")
        self.assertEqual(client["display_name"], "Acme Widgets")
        self.assertEqual(client["default_billable"], 1)
        self.assertEqual(client["default_job_type"], "")
        self.assertEqual(client["billable_locked"], 0)
        with db.connect(self.db) as conn:
            keys = {r["client_key"] for r in conn.execute("SELECT client_key FROM clients")}
        self.assertIn("acme_widgets", keys)
        self.assertEqual(result["client_count"], len(keys))

    def test_persists_optional_fields(self) -> None:
        result = actions.add_client(
            self.db, "Smith, John", aliases="John Smith;JS",
            default_billable="no", default_job_type="Payroll", client_key="smith_j",
        )
        client = result["client"]
        self.assertEqual(client["client_key"], "smith_j")
        self.assertEqual(client["aliases"], "John Smith;JS")
        self.assertEqual(client["default_billable"], 0)
        self.assertEqual(client["default_job_type"], "Payroll")

    def test_rejects_existing_client_key(self) -> None:
        actions.add_client(self.db, "Acme Widgets")
        with self.assertRaisesRegex(ValueError, "import_clients"):
            actions.add_client(self.db, "Acme Widgets Renamed", client_key="acme_widgets")

    def test_rejects_label_colliding_with_existing_client(self) -> None:
        with self.assertRaisesRegex(ValueError, "unambiguous"):
            actions.add_client(self.db, "Fresh Co", aliases="Client A")

    def test_rejects_blank_display_name(self) -> None:
        with self.assertRaisesRegex(ValueError, "display_name"):
            actions.add_client(self.db, "   ")

    def test_resolution_preserves_typed_job_type(self) -> None:
        actions.add_client(self.db, "Acme Widgets", default_job_type="Bookkeeping")
        entry = actions.add_missing_entry(
            self.db, "Mystery Co", "advisory call",
            "2026-05-28T09:00:00", "2026-05-28T09:23:00", job_type="Consulting",
        )
        fixed = actions.edit_entry(self.db, entry["entry_id"], client="Acme Widgets")
        self.assertEqual(fixed["review_status"], "draft")
        # Typed at capture; the roster default must not clobber it.
        self.assertEqual(fixed["job_type"], "Consulting")

    def test_strict_needs_info_resolves_after_add_client(self) -> None:
        actions.set_setting(self.db, "strict_roster", "yes")
        entry = actions.add_missing_entry(
            self.db, "Acme Widgets", "setup call",
            "2026-05-28T09:00:00", "2026-05-28T09:23:00",
        )
        self.assertEqual(entry["review_status"], "needs_info")
        with self.assertRaisesRegex(ValueError, "strict roster"):
            actions.edit_entry(self.db, entry["entry_id"], client="Acme Widgets")
        actions.add_client(self.db, "Acme Widgets", default_job_type="Bookkeeping")
        fixed = actions.edit_entry(self.db, entry["entry_id"], client="Acme Widgets")
        self.assertEqual(fixed["review_status"], "draft")
        self.assertEqual(fixed["job_type"], "")
        self.assertEqual(fixed.get("suggested_job_type"), "Bookkeeping")
        self.assertEqual(fixed["billable"], 1)


class OperatorCodeSettingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = Path(self.tmp.name) / "timeassist.sqlite"
        actions.init_state(self.db, "2026-07-08T09:00:00")

    def test_set_setting_strips_and_uppercases(self) -> None:
        actions.set_setting(self.db, "operator_code", " avd ")
        self.assertEqual(actions.list_settings(self.db)["operator_code"], "AVD")

    def test_set_setting_two_letter_code(self) -> None:
        actions.set_setting(self.db, "operator_code", "bb")
        self.assertEqual(actions.list_settings(self.db)["operator_code"], "BB")

    def test_set_setting_rejects_single_letter(self) -> None:
        with self.assertRaisesRegex(ValueError, "2-4 letters"):
            actions.set_setting(self.db, "operator_code", "A")
        self.assertNotIn("operator_code", actions.list_settings(self.db))

    def test_set_setting_rejects_five_letters(self) -> None:
        with self.assertRaisesRegex(ValueError, "2-4 letters"):
            actions.set_setting(self.db, "operator_code", "ABCDE")
        self.assertNotIn("operator_code", actions.list_settings(self.db))

    def test_set_setting_rejects_alphanumeric(self) -> None:
        with self.assertRaisesRegex(ValueError, "2-4 letters"):
            actions.set_setting(self.db, "operator_code", "A1")
        self.assertNotIn("operator_code", actions.list_settings(self.db))

    def test_set_setting_rejects_empty(self) -> None:
        with self.assertRaisesRegex(ValueError, "2-4 letters"):
            actions.set_setting(self.db, "operator_code", "")
        self.assertNotIn("operator_code", actions.list_settings(self.db))

    def test_get_operator_code_fresh_db_is_none(self) -> None:
        with db.connect(self.db) as conn:
            self.assertIsNone(actions.get_operator_code(conn))

    def test_get_operator_code_after_set(self) -> None:
        actions.set_setting(self.db, "operator_code", "AVD")
        with db.connect(self.db) as conn:
            self.assertEqual(actions.get_operator_code(conn), "AVD")

    def test_get_operator_code_after_clear_is_none(self) -> None:
        actions.set_setting(self.db, "operator_code", "AVD")
        actions.clear_setting(self.db, "operator_code")
        with db.connect(self.db) as conn:
            self.assertIsNone(actions.get_operator_code(conn))

    def test_set_setting_four_letter_code(self) -> None:
        # Four-letter code is the upper boundary of the {2,4} range; must be accepted.
        actions.set_setting(self.db, "operator_code", "ABCD")
        self.assertEqual(actions.list_settings(self.db)["operator_code"], "ABCD")

    def test_set_setting_rejects_non_ascii_letters(self) -> None:
        # Non-ASCII letters are not valid operator codes; reject with a clear message.
        with self.assertRaisesRegex(ValueError, "2-4 letters"):
            actions.set_setting(self.db, "operator_code", "ävd")
        self.assertNotIn("operator_code", actions.list_settings(self.db))

    def test_get_operator_code_read_side_uppercases(self) -> None:
        # Pins the read-side .upper(): a lowercase value written directly to the DB
        # (bypassing set_setting's write-side normalisation) must still come back upper.
        actions.set_setting(self.db, "operator_code", "AVD")
        with db.connect(self.db) as conn:
            conn.execute("UPDATE settings SET setting_value = 'avd' WHERE setting_key = 'operator_code'")
            conn.commit()
        with db.connect(self.db) as conn:
            self.assertEqual(actions.get_operator_code(conn), "AVD")


class DefaultExportFilenameTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = Path(self.tmp.name) / "timeassist.sqlite"
        actions.init_state(self.db, "2026-07-08T09:00:00")

    def test_fresh_db_no_code_no_range(self) -> None:
        # No operator_code set; single date — legacy filename unchanged.
        result = actions.default_export_filename(self.db, "2026-06-30")
        self.assertEqual(result, "quickbooks-time-2026-06-30.csv")

    def test_with_operator_code_single_date(self) -> None:
        actions.set_setting(self.db, "operator_code", "AVD")
        result = actions.default_export_filename(self.db, "2026-06-30")
        self.assertEqual(result, "quickbooks-time-AVD-2026-06-30.csv")

    def test_end_date_equal_to_date_is_single_day(self) -> None:
        # end_date equal to date → same as no end_date (no range suffix).
        actions.set_setting(self.db, "operator_code", "AVD")
        result = actions.default_export_filename(self.db, "2026-06-30", end_date="2026-06-30")
        self.assertEqual(result, "quickbooks-time-AVD-2026-06-30.csv")

    def test_date_range_produces_span_suffix(self) -> None:
        actions.set_setting(self.db, "operator_code", "AVD")
        result = actions.default_export_filename(self.db, "2026-06-01", end_date="2026-06-30")
        self.assertEqual(result, "quickbooks-time-AVD-2026-06-01_to_2026-06-30.csv")

    def test_date_range_no_operator_code(self) -> None:
        result = actions.default_export_filename(self.db, "2026-06-01", end_date="2026-06-30")
        self.assertEqual(result, "quickbooks-time-2026-06-01_to_2026-06-30.csv")


class RangeReviewTests(unittest.TestCase):
    """Tests for date-range review: review_entries(db, start, end_date=end),
    per-day summaries, token compat, and validate_review_token with end_date."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = Path(self.tmp.name) / "timeassist.sqlite"
        # Seed roster so clients resolve (not needs_info) except the unknown one.
        _seed_roster(self, "Acme Co", "Beta Corp")
        # 2026-06-01: one 30-min entry
        self.e1 = actions.add_missing_entry(
            self.db, "Acme Co", "June first work",
            "2026-06-01T09:00:00", "2026-06-01T09:30:00", "yes",
        )
        # 2026-06-02: one needs_info entry (unknown client)
        self.e2 = actions.add_missing_entry(
            self.db, "Unknown Client XYZ", "mystery work",
            "2026-06-02T10:00:00", "2026-06-02T10:45:00", "yes",
        )
        # 2026-06-03: one 60-min entry
        self.e3 = actions.add_missing_entry(
            self.db, "Beta Corp", "June third work",
            "2026-06-03T14:00:00", "2026-06-03T15:00:00", "yes",
        )

    # ------------------------------------------------------------------
    # Basic range coverage
    # ------------------------------------------------------------------

    def test_range_returns_all_three_days_entries(self) -> None:
        result = actions.review_entries(self.db, "2026-06-01", end_date="2026-06-03")
        entry_ids = {e["entry_id"] for e in result["entries"]}
        self.assertIn(self.e1["entry_id"], entry_ids)
        self.assertIn(self.e2["entry_id"], entry_ids)
        self.assertIn(self.e3["entry_id"], entry_ids)
        self.assertEqual(len(result["entries"]), 3)

    def test_range_result_has_end_date_key(self) -> None:
        result = actions.review_entries(self.db, "2026-06-01", end_date="2026-06-03")
        self.assertEqual(result["end_date"], "2026-06-03")

    def test_range_result_has_days_list(self) -> None:
        result = actions.review_entries(self.db, "2026-06-01", end_date="2026-06-03")
        self.assertIn("days", result)
        self.assertEqual(len(result["days"]), 3)

    def test_days_are_in_ascending_order(self) -> None:
        result = actions.review_entries(self.db, "2026-06-01", end_date="2026-06-03")
        dates = [d["date"] for d in result["days"]]
        self.assertEqual(dates, sorted(dates))

    def test_days_keys_are_exactly_as_specified(self) -> None:
        result = actions.review_entries(self.db, "2026-06-01", end_date="2026-06-03")
        required = {"date", "entry_count", "draft_minutes", "approved_minutes",
                    "exported_minutes", "needs_info_count"}
        for day in result["days"]:
            self.assertEqual(set(day.keys()), required)

    def test_days_entry_counts_are_correct(self) -> None:
        result = actions.review_entries(self.db, "2026-06-01", end_date="2026-06-03")
        by_date = {d["date"]: d for d in result["days"]}
        self.assertEqual(by_date["2026-06-01"]["entry_count"], 1)
        self.assertEqual(by_date["2026-06-02"]["entry_count"], 1)
        self.assertEqual(by_date["2026-06-03"]["entry_count"], 1)

    def test_days_needs_info_count(self) -> None:
        result = actions.review_entries(self.db, "2026-06-01", end_date="2026-06-03")
        by_date = {d["date"]: d for d in result["days"]}
        self.assertEqual(by_date["2026-06-01"]["needs_info_count"], 0)
        self.assertEqual(by_date["2026-06-02"]["needs_info_count"], 1)  # unknown client
        self.assertEqual(by_date["2026-06-03"]["needs_info_count"], 0)

    def test_days_draft_minutes_correct(self) -> None:
        result = actions.review_entries(self.db, "2026-06-01", end_date="2026-06-03")
        by_date = {d["date"]: d for d in result["days"]}
        # days has NO needs_info minutes bucket: the 06-02 needs_info entry's
        # minutes land in no per-day bucket (only needs_info_count marks it),
        # so its draft_minutes stays 0. Span-wide needs_info minutes live in totals.
        self.assertEqual(by_date["2026-06-01"]["draft_minutes"], 30)
        self.assertEqual(by_date["2026-06-02"]["draft_minutes"], 0)
        self.assertEqual(by_date["2026-06-03"]["draft_minutes"], 60)

    def test_range_span_totals(self) -> None:
        result = actions.review_entries(self.db, "2026-06-01", end_date="2026-06-03")
        # totals should cover the entire span (30 + 45 + 60 = 135 total)
        total = (result["totals"]["draft_minutes"]
                 + result["totals"]["needs_info_minutes"]
                 + result["totals"]["approved_minutes"]
                 + result["totals"]["exported_minutes"])
        self.assertEqual(total, 135)

    # ------------------------------------------------------------------
    # Token compat: single-day end_date=date equals no end_date
    # ------------------------------------------------------------------

    def test_single_day_end_date_equals_no_end_date_token(self) -> None:
        d = "2026-06-01"
        token_no_end = actions.review_entries(self.db, d)["review_token"]
        token_same_end = actions.review_entries(self.db, d, end_date=d)["review_token"]
        self.assertEqual(token_no_end, token_same_end)

    def test_single_day_no_end_date_has_no_end_date_key(self) -> None:
        result = actions.review_entries(self.db, "2026-06-01")
        self.assertNotIn("end_date", result)

    def test_single_day_same_end_date_has_no_end_date_key(self) -> None:
        # end_date == date → treated as single-day, no end_date key
        result = actions.review_entries(self.db, "2026-06-01", end_date="2026-06-01")
        self.assertNotIn("end_date", result)

    def test_single_day_no_days_key(self) -> None:
        result = actions.review_entries(self.db, "2026-06-01")
        self.assertNotIn("days", result)

    # ------------------------------------------------------------------
    # Range token stability and staleness
    # ------------------------------------------------------------------

    def test_range_token_changes_when_entry_in_span_changes(self) -> None:
        old_result = actions.review_entries(self.db, "2026-06-01", end_date="2026-06-03")
        old_token = old_result["review_token"]
        # Edit the e3 entry (on 03rd)
        actions.edit_entry(self.db, self.e3["entry_id"], task="updated notes")
        new_result = actions.review_entries(self.db, "2026-06-01", end_date="2026-06-03")
        self.assertNotEqual(old_token, new_result["review_token"])

    def test_validate_review_token_range_raises_when_stale(self) -> None:
        result = actions.review_entries(self.db, "2026-06-01", end_date="2026-06-03")
        old_token = result["review_token"]
        actions.edit_entry(self.db, self.e3["entry_id"], task="changed again")
        with self.assertRaisesRegex(ValueError, "stale"):
            actions.validate_review_token(
                self.db, "2026-06-01", old_token, end_date="2026-06-03"
            )

    def test_validate_review_token_stale_message_is_range_scoped(self) -> None:
        # The ranged stale message must talk about the range, not "the day",
        # and differ from the (pinned) single-day wording.
        result = actions.review_entries(self.db, "2026-06-01", end_date="2026-06-03")
        old_token = result["review_token"]
        actions.edit_entry(self.db, self.e3["entry_id"], task="changed again")
        with self.assertRaises(ValueError) as ranged_ctx:
            actions.validate_review_token(
                self.db, "2026-06-01", old_token, end_date="2026-06-03"
            )
        ranged_message = str(ranged_ctx.exception)
        self.assertIn("date range's entries changed", ranged_message)
        self.assertIn("refreshed range", ranged_message)
        # Single-day wording stays as shipped and differs from the ranged one.
        day_token = actions.review_entries(self.db, "2026-06-03")["review_token"]
        actions.edit_entry(self.db, self.e3["entry_id"], task="changed once more")
        with self.assertRaises(ValueError) as day_ctx:
            actions.validate_review_token(self.db, "2026-06-03", day_token)
        day_message = str(day_ctx.exception)
        self.assertIn("day's entries changed", day_message)
        self.assertIn("refreshed day", day_message)
        self.assertNotEqual(ranged_message, day_message)

    def test_validate_review_token_range_passes_when_fresh(self) -> None:
        result = actions.review_entries(self.db, "2026-06-01", end_date="2026-06-03")
        # Should not raise
        actions.validate_review_token(
            self.db, "2026-06-01", result["review_token"], end_date="2026-06-03"
        )

    # ------------------------------------------------------------------
    # Validation errors
    # ------------------------------------------------------------------

    def test_end_date_before_date_raises(self) -> None:
        with self.assertRaises(ValueError):
            actions.review_entries(self.db, "2026-06-03", end_date="2026-06-01")

    def test_malformed_end_date_raises(self) -> None:
        with self.assertRaises(ValueError):
            actions.review_entries(self.db, "2026-06-01", end_date="not-a-date")

    def test_engine_does_not_validate_start_format(self) -> None:
        # Start-date normalization belongs to the CLI/MCP surface (normalize_date);
        # the engine accepts any start string without raising. "06/01/2026" sorts
        # lexically below every "2026-*" date, so the BETWEEN bound matches all
        # three seeded entries — exactly why the surface must normalize first.
        result = actions.review_entries(self.db, "06/01/2026", end_date="2026-06-03")
        self.assertEqual(len(result["entries"]), 3)

    # ------------------------------------------------------------------
    # Days only for dates with entries (no zero-filled gaps)
    # ------------------------------------------------------------------

    def test_days_skips_gap_dates_with_no_entries(self) -> None:
        # There's no entry on 2026-06-02 in a sub-range if we only look 01-03.
        # But the gap test: query a range that includes a date with no entries.
        # 2026-06-04 has no entries, so range 01-04 should still show 3 days.
        result = actions.review_entries(self.db, "2026-06-01", end_date="2026-06-04")
        dates = [d["date"] for d in result["days"]]
        self.assertNotIn("2026-06-04", dates)
        self.assertEqual(len(result["days"]), 3)

    def test_ranged_review_over_empty_span(self) -> None:
        # A range with no entries on any day is still a valid review scope:
        # days is empty (no zero-filled rows), end_date is reported, and the
        # token round-trips through validate_review_token without raising.
        result = actions.review_entries(self.db, "2026-07-01", end_date="2026-07-03")
        self.assertEqual(result["entries"], [])
        self.assertEqual(result["days"], [])
        self.assertEqual(result["end_date"], "2026-07-03")
        actions.validate_review_token(
            self.db, "2026-07-01", result["review_token"], end_date="2026-07-03"
        )


class RangeExportTests(unittest.TestCase):
    """Tests for date-range export: export_entries(db, start, output, end_date=end)."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.work = Path(self.tmp.name)
        self.db = self.work / "timeassist.sqlite"
        self.out = self.work / "out.csv"
        _seed_roster(self, "Acme Co", "Beta Corp")
        # 2026-06-01: one 30-min entry
        self.e1 = actions.add_missing_entry(
            self.db, "Acme Co", "June first work",
            "2026-06-01T09:00:00", "2026-06-01T09:30:00", "yes",
        )
        # 2026-06-02: one needs_info entry (unknown client — will be skipped)
        self.e2 = actions.add_missing_entry(
            self.db, "Unknown Client XYZ", "mystery work",
            "2026-06-02T10:00:00", "2026-06-02T10:45:00", "yes",
        )
        # 2026-06-03: one 60-min entry + one legacy locked-billable row
        self.e3 = actions.add_missing_entry(
            self.db, "Beta Corp", "June third work",
            "2026-06-03T14:00:00", "2026-06-03T15:00:00", "yes",
        )
        # Legacy locked-billable entry on 2026-06-03 (pre-upgrade data recipe from
        # LockedBillableFinalizeGateTests._legacy_admin_entry)
        placeholder = actions.add_missing_entry(
            self.db, "Placeholder", "internal admin work",
            "2026-06-03T16:00:00", "2026-06-03T16:30:00",
        )
        self.locked_id = placeholder["entry_id"]
        with db.connect(self.db) as conn:
            conn.execute(
                "UPDATE time_entries SET client_name='Admin', billable=1, "
                "capture_status='resolved', review_status='draft' WHERE entry_id=?",
                (self.locked_id,),
            )
            conn.commit()
        # Approve e1 and e3 (and locked_id is left approved-ish via direct SQL below)
        # so that each day has at least one approvable entry.
        actions.set_approval(self.db, self.e1["entry_id"], True, "2026-06-01T12:00:00")
        actions.set_approval(self.db, self.e3["entry_id"], True, "2026-06-03T18:00:00")
        # Simulate pre-upgrade approval on locked entry (like in the locked tests)
        with db.connect(self.db) as conn:
            conn.execute(
                "UPDATE time_entries SET review_status='approved' WHERE entry_id=?",
                (self.locked_id,),
            )
            conn.commit()

    # ------------------------------------------------------------------
    # Core range export
    # ------------------------------------------------------------------

    def test_range_export_rows_for_all_three_days(self) -> None:
        actions.export_entries(
            self.db, "2026-06-01", self.out,
            at="2026-06-03T20:00:00", end_date="2026-06-03",
        )
        rows = list(csv.DictReader(self.out.read_text().splitlines()))
        dates = [r["Date"] for r in rows]
        self.assertIn("2026-06-01", dates)
        self.assertIn("2026-06-03", dates)
        # needs_info (e2) and locked-billable are skipped — only e1 + e3
        self.assertEqual(len(rows), 2)

    def test_range_export_rows_in_start_at_entry_id_order(self) -> None:
        # Add a second day-3 entry with an earlier start_at than e3 (inserted
        # after it) so ORDER BY start_at, entry_id is actually exercised — without
        # this the insertion order coincidentally matches chronological order.
        e3b = actions.add_missing_entry(
            self.db, "Beta Corp", "June third early work",
            "2026-06-03T11:00:00", "2026-06-03T11:30:00", "yes",
        )
        actions.set_approval(self.db, e3b["entry_id"], True, "2026-06-03T18:00:00")
        actions.export_entries(
            self.db, "2026-06-01", self.out,
            at="2026-06-03T20:00:00", end_date="2026-06-03",
        )
        rows = list(csv.DictReader(self.out.read_text().splitlines()))
        # Assert on (Date, Notes) tuples so ordering is meaningful even with same date
        pairs = [(r["Date"], r["Notes"]) for r in rows]
        self.assertEqual(pairs, sorted(pairs))

    def test_range_export_result_carries_end_date(self) -> None:
        result = actions.export_entries(
            self.db, "2026-06-01", self.out,
            at="2026-06-03T20:00:00", end_date="2026-06-03",
        )
        self.assertEqual(result["end_date"], "2026-06-03")

    def test_range_export_result_carries_exported_count(self) -> None:
        result = actions.export_entries(
            self.db, "2026-06-01", self.out,
            at="2026-06-03T20:00:00", end_date="2026-06-03",
        )
        # e1 + e3; e2 is needs_info, locked_id is locked-billable
        self.assertEqual(result["exported_count"], 2)

    def test_range_export_result_carries_operator_code_when_set(self) -> None:
        actions.set_setting(self.db, "operator_code", "JW", at="2026-06-01T08:00:00")
        result = actions.export_entries(
            self.db, "2026-06-01", self.out,
            at="2026-06-03T20:00:00", end_date="2026-06-03",
        )
        self.assertEqual(result["operator_code"], "JW")

    def test_range_export_result_no_operator_code_when_unset(self) -> None:
        result = actions.export_entries(
            self.db, "2026-06-01", self.out,
            at="2026-06-03T20:00:00", end_date="2026-06-03",
        )
        self.assertNotIn("operator_code", result)

    # ------------------------------------------------------------------
    # needs_info and locked-billable skips span-wide
    # ------------------------------------------------------------------

    def test_range_export_skips_needs_info_entry_on_day2(self) -> None:
        result = actions.export_entries(
            self.db, "2026-06-01", self.out,
            at="2026-06-03T20:00:00", end_date="2026-06-03",
        )
        self.assertEqual(result["skipped_needs_info_count"], 1)

    def test_range_export_skips_locked_billable_on_day3(self) -> None:
        result = actions.export_entries(
            self.db, "2026-06-01", self.out,
            at="2026-06-03T20:00:00", end_date="2026-06-03",
        )
        self.assertEqual(result["skipped_locked_count"], 1)

    # ------------------------------------------------------------------
    # Re-export regenerates the complete file (approved+exported)
    # ------------------------------------------------------------------

    def test_range_reexport_regenerates_full_span(self) -> None:
        actions.export_entries(
            self.db, "2026-06-01", self.out,
            at="2026-06-03T20:00:00", end_date="2026-06-03",
        )
        result2 = actions.export_entries(
            self.db, "2026-06-01", self.out,
            at="2026-06-03T21:00:00", end_date="2026-06-03",
        )
        rows = list(csv.DictReader(self.out.read_text().splitlines()))
        dates = [r["Date"] for r in rows]
        self.assertIn("2026-06-01", dates)
        self.assertIn("2026-06-03", dates)
        self.assertEqual(result2["exported_count"], 2)

    # ------------------------------------------------------------------
    # Empty span error
    # ------------------------------------------------------------------

    def test_range_export_empty_span_raises_with_range_message(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            actions.export_entries(
                self.db, "2026-06-10", self.out,
                at="2026-06-10T10:00:00", end_date="2026-06-12",
            )
        self.assertIn(
            "no approved or previously exported entries for 2026-06-10..2026-06-12; nothing to export",
            str(ctx.exception),
        )

    def test_range_export_all_skipped_span_raises_with_range_message(self) -> None:
        # A range containing ONLY skipped entries (a needs_info entry plus a locked-
        # billable row, no approved entries anywhere in the span) raises the span-
        # labelled error — pinning that skip counts are discarded when nothing
        # exports (intentional-but-surprising behaviour; repo convention: pin it).
        # Add a locked-billable entry on day 5 (approved-ish via direct SQL) so
        # the span 2026-06-05..2026-06-06 contains only skips and no approved rows.
        actions.add_missing_entry(
            self.db, "Unknown Skipped Client", "unknown work",
            "2026-06-05T09:00:00", "2026-06-05T09:30:00", "yes",
        )
        locked_e = actions.add_missing_entry(
            self.db, "Placeholder2", "admin work",
            "2026-06-05T10:00:00", "2026-06-05T10:30:00",
        )
        with db.connect(self.db) as conn:
            conn.execute(
                "UPDATE time_entries SET client_name='Admin', billable=1, "
                "capture_status='resolved', review_status='approved' WHERE entry_id=?",
                (locked_e["entry_id"],),
            )
            conn.commit()
        with self.assertRaises(ValueError) as ctx:
            actions.export_entries(
                self.db, "2026-06-05", self.out,
                at="2026-06-06T10:00:00", end_date="2026-06-06",
            )
        self.assertIn(
            "no approved or previously exported entries for 2026-06-05..2026-06-06; nothing to export",
            str(ctx.exception),
        )

    # ------------------------------------------------------------------
    # Single-day compat (end_date=None): no end_date or operator_code keys when unset
    # ------------------------------------------------------------------

    def test_single_day_export_no_end_date_key(self) -> None:
        result = actions.export_entries(
            self.db, "2026-06-01", self.out,
            at="2026-06-01T12:30:00",
        )
        self.assertNotIn("end_date", result)

    def test_single_day_export_no_operator_code_key_when_unset(self) -> None:
        result = actions.export_entries(
            self.db, "2026-06-01", self.out,
            at="2026-06-01T12:30:00",
        )
        self.assertNotIn("operator_code", result)

    def test_single_day_export_same_end_date_collapses_to_single(self) -> None:
        # end_date == date_value → treated as single-day, no end_date key
        result = actions.export_entries(
            self.db, "2026-06-01", self.out,
            at="2026-06-01T12:30:00", end_date="2026-06-01",
        )
        self.assertNotIn("end_date", result)

    def test_single_day_export_error_message_no_range(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            actions.export_entries(
                self.db, "2026-06-10", self.out,
                at="2026-06-10T10:00:00",
            )
        self.assertIn(
            "no approved or previously exported entries for 2026-06-10; nothing to export",
            str(ctx.exception),
        )
        # Must NOT contain the ".." range notation
        self.assertNotIn("..", str(ctx.exception))

    # ------------------------------------------------------------------
    # Validation: end_date ordering mirrors review_entries
    # ------------------------------------------------------------------

    def test_range_export_end_date_before_date_raises(self) -> None:
        with self.assertRaises(ValueError):
            actions.export_entries(
                self.db, "2026-06-03", self.out, end_date="2026-06-01",
            )

    def test_range_export_malformed_end_date_raises(self) -> None:
        with self.assertRaises(ValueError):
            actions.export_entries(
                self.db, "2026-06-01", self.out, end_date="not-a-date",
            )


class JobCodeGateAndDurationCaptureTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = Path(self.tmp.name) / "timeassist.sqlite"
        actions.init_state(self.db, "2026-05-28T09:00:00")
        _seed_roster(self, "Acme Co")

    def test_approve_refuses_blank_job_code(self) -> None:
        entry = actions.add_missing_entry(
            self.db, "Acme Co", "work", "2026-05-28T09:00:00", "2026-05-28T09:30:00", "yes",
        )
        self.assertEqual(entry["job_type"], "")
        with self.assertRaisesRegex(ValueError, "no Job Code"):
            _raw_set_approval(self.db, entry["entry_id"], True)

    def test_approve_all_skips_missing_job_code(self) -> None:
        actions.add_missing_entry(
            self.db, "Acme Co", "a", "2026-05-28T09:00:00", "2026-05-28T09:30:00", "yes",
        )
        actions.add_missing_entry(
            self.db, "Acme Co", "b", "2026-05-28T10:00:00", "2026-05-28T10:30:00", "yes",
            job_type="Tax",
        )
        result = _raw_approve_all(self.db, "2026-05-28")
        self.assertEqual(result["approved_count"], 1)
        self.assertEqual(result["skipped_missing_job_code_count"], 1)
        self.assertEqual(result["skipped_missing_job_code_minutes"], 30)

    def test_duration_only_add_missing_packs_from_midnight(self) -> None:
        entry = actions.add_missing_entry(
            self.db, "Acme Co", "tax prep", billable="yes", job_type="1065",
            date="2026-05-28", duration_minutes=105,
        )
        self.assertTrue(entry.get("duration_only"))
        self.assertEqual(entry["duration_minutes"], 105)
        self.assertEqual(entry["start_at"], "2026-05-28T00:00:00")
        self.assertEqual(entry["end_at"], "2026-05-28T01:45:00")
        self.assertEqual(actions.format_hhmm(105), "1:45")

    def test_duration_only_packs_after_existing_block(self) -> None:
        actions.add_missing_entry(
            self.db, "Acme Co", "first", "2026-05-28T00:00:00", "2026-05-28T01:00:00",
            "yes", job_type="Tax",
        )
        second = actions.add_missing_entry(
            self.db, "Acme Co", "second", billable="yes", job_type="Tax",
            date="2026-05-28", duration_minutes=30,
        )
        self.assertEqual(second["start_at"], "2026-05-28T01:00:00")
        self.assertEqual(second["end_at"], "2026-05-28T01:30:00")


if __name__ == "__main__":
    unittest.main()
