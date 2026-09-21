from __future__ import annotations

import os
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from timeassist import actions
from timeassist import currently_working
from timeassist import tray
from tests.remote_roster import install_live_clients

os.environ.setdefault("TIMEASSIST_ALLOW_LOCAL_ROSTER", "1")

ENV = {
    "SUPABASE_URL": "https://example.supabase.co",
    "SUPABASE_KEY": "anon-test-key",
}


class FormatClockLineTests(unittest.TestCase):
    def test_idle(self) -> None:
        self.assertEqual(tray.format_clock_line(None, datetime(2026, 5, 28, 10, 0)), tray.IDLE_LINE)

    def test_elapsed_and_countdown(self) -> None:
        now = datetime(2026, 5, 28, 10, 15, 0)
        line = tray.format_clock_line(
            {
                "client": "Acme Co",
                "started_at": "2026-05-28T09:00:00",
                "planned_end_at": "2026-05-28T11:00:00",
            },
            now,
        )
        self.assertEqual(line, "Acme Co  1:15  0:45 left")

    def test_overdue_countdown(self) -> None:
        now = datetime(2026, 5, 28, 11, 10, 0)
        line = tray.format_clock_line(
            {
                "client": "Acme Co",
                "started_at": "2026-05-28T09:00:00",
                "planned_end_at": "2026-05-28T11:00:00",
            },
            now,
        )
        self.assertEqual(line, "Acme Co  2:10  overdue -0:10")

    def test_clock_display_live(self) -> None:
        now = datetime(2026, 5, 28, 10, 15, 0)
        display = tray.clock_display(
            {
                "client": "Acme Co",
                "job_code": "books",
                "started_at": "2026-05-28T09:00:00",
                "planned_end_at": "2026-05-28T11:00:00",
            },
            now,
        )
        self.assertEqual(display["client"], "Acme Co")
        self.assertEqual(display["elapsed"], "1:15")
        self.assertEqual(display["status"], "live")
        self.assertEqual(display["job"], "books")

    def test_clock_display_idle(self) -> None:
        display = tray.clock_display(None, datetime(2026, 5, 28, 10, 0))
        self.assertEqual(display["client"], tray.IDLE_LINE)
        self.assertEqual(display["status"], "idle")
        self.assertEqual(display["elapsed"], "")
        self.assertEqual(display["job"], "")

    def test_clock_display_overdue_status(self) -> None:
        now = datetime(2026, 5, 28, 11, 10, 0)
        display = tray.clock_display(
            {
                "client": "Acme Co",
                "job_code": "1040",
                "started_at": "2026-05-28T09:00:00",
                "planned_end_at": "2026-05-28T11:00:00",
            },
            now,
        )
        self.assertEqual(display["status"], "overdue")
        self.assertEqual(display["job"], "1040")
        self.assertEqual(display["elapsed"], "2:10")

    def test_idle_dot_color_is_red(self) -> None:
        self.assertEqual(tray._COLOR_DOT_IDLE, "#c62828")

    def test_session_elapsed_seconds(self) -> None:
        now = datetime(2026, 5, 28, 9, 2, 0)
        self.assertIsNone(tray.session_elapsed_seconds(None, now))
        self.assertEqual(
            tray.session_elapsed_seconds(
                {"started_at": "2026-05-28T09:00:00"},
                now,
            ),
            120,
        )

    def test_idle_check_action_thresholds(self) -> None:
        self.assertEqual(tray.idle_check_action(None, prompted=False), "none")
        self.assertEqual(tray.idle_check_action(7199, prompted=False), "none")
        self.assertEqual(tray.idle_check_action(7200, prompted=False), "prompt")
        self.assertEqual(tray.idle_check_action(28799, prompted=True), "none")
        self.assertEqual(tray.idle_check_action(28800, prompted=True), "force_stop")
        self.assertEqual(tray.idle_check_action(28800, prompted=False), "force_stop")

    def test_prompt_job_label(self) -> None:
        self.assertEqual(tray.prompt_job_label({"job_code": "books"}), "books")
        self.assertEqual(tray.prompt_job_label({"client": "Acme Co"}), "Acme Co")
        self.assertEqual(tray.prompt_job_label({}), "this task")

    def test_clock_display_empty_job_placeholder(self) -> None:
        now = datetime(2026, 5, 28, 10, 0, 0)
        display = tray.clock_display(
            {"client": "Admin", "started_at": "2026-05-28T09:58:00"},
            now,
        )
        self.assertEqual(display["job"], "—")
        self.assertEqual(display["client"], "Admin")

    def test_should_ignore_live_row(self) -> None:
        row = {"started_at": "2026-05-28T09:00:00", "client": "Acme"}
        self.assertTrue(tray.should_ignore_live_row(row, "2026-05-28T09:00:00"))
        self.assertFalse(tray.should_ignore_live_row(row, "2026-05-28T10:00:00"))
        self.assertFalse(tray.should_ignore_live_row(row, None))
        self.assertFalse(tray.should_ignore_live_row(None, "2026-05-28T09:00:00"))

    def test_wall_clock_z_matches_naive(self) -> None:
        """Z / offset must not shift elapsed (dashboard parseLocalStartMs parity)."""
        now = datetime(2026, 5, 28, 10, 15, 0)
        naive = tray.clock_display(
            {"client": "Acme Co", "started_at": "2026-05-28T09:00:00"},
            now,
        )
        with_z = tray.clock_display(
            {"client": "Acme Co", "started_at": "2026-05-28T09:00:00Z"},
            now,
        )
        with_offset = tray.clock_display(
            {"client": "Acme Co", "started_at": "2026-05-28T09:00:00+00:00"},
            now,
        )
        self.assertEqual(naive["elapsed"], "1:15")
        self.assertEqual(with_z["elapsed"], naive["elapsed"])
        self.assertEqual(with_offset["elapsed"], naive["elapsed"])

    def test_wall_clock_clamps_negative_elapsed(self) -> None:
        now = datetime(2026, 5, 28, 8, 0, 0)
        display = tray.clock_display(
            {"client": "Acme Co", "started_at": "2026-05-28T09:00:00"},
            now,
        )
        self.assertEqual(display["elapsed"], "0:00")


class TrayFetchTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = Path(self.tmp.name) / "timeassist.sqlite"
        install_live_clients(self, "Acme Co")
        actions.init_state(self.db, "2026-05-28T08:00:00")
        actions.set_setting(self.db, "staff_name", "Jane Doe")
        actions.set_setting(self.db, "office", "GCD")

    def test_identity_is_local_staff_name(self) -> None:
        self.assertEqual(tray.local_staff_name(self.db), "Jane Doe")

    def test_fetch_filters_this_staff_active_only(self) -> None:
        seen: dict[str, str] = {}

        def fake_request(method, table, **kwargs):  # noqa: ANN001
            seen["method"] = method.upper()
            seen["table"] = table
            seen.update(kwargs.get("query") or {})
            return [
                {
                    "client": "Acme Co",
                    "started_at": "2026-05-28T09:00:00",
                    "planned_end_at": "2026-05-28T10:30:00",
                    "status": "active",
                    "staff_name": "Jane Doe",
                }
            ]

        with patch("timeassist.tray.request_json", side_effect=fake_request):
            row = tray.fetch_live_row(self.db, environ=ENV)
        self.assertEqual(seen["method"], "GET")
        self.assertEqual(seen["table"], "currently_working")
        self.assertEqual(seen["staff_name"], "eq.Jane Doe")
        self.assertEqual(seen["status"], "eq.active")
        self.assertEqual(row["client"], "Acme Co")

    def test_fetch_idle_when_empty(self) -> None:
        with patch("timeassist.tray.request_json", return_value=[]):
            self.assertIsNone(tray.fetch_live_row(self.db, environ=ENV))

    def test_stop_ends_local_draft(self) -> None:
        with patch("timeassist.currently_working.request_json", return_value=[]):
            actions.start_session(self.db, "Acme Co", "books", "yes", "2026-05-28T09:00:00")
            currently_working.cancel_auto_end()
            entry = tray.stop_session(self.db)
        self.assertIsNotNone(entry)
        self.assertIn(entry["review_status"], ("draft", "needs_info"))
        self.assertEqual(entry["client_name"], "Acme Co")
        self.assertFalse(entry.get("submitted_at"))
        with patch("timeassist.tray.request_json", return_value=[]):
            snap = tray.snapshot(self.db, now=datetime(2026, 5, 28, 9, 20), environ=ENV)
        self.assertEqual(snap["line"], tray.IDLE_LINE)
        self.assertFalse(snap["can_stop"])

    def test_stop_with_no_session_is_noop(self) -> None:
        self.assertIsNone(tray.stop_session(self.db))

    def test_cli_tray_help(self) -> None:
        import subprocess

        result = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "timeassist.py"), "tray", "--help"],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("currently_working", result.stdout)


if __name__ == "__main__":
    unittest.main()
