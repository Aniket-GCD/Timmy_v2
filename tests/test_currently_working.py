from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from timeassist import actions
from timeassist import currently_working
from timeassist import mcp_server
from tests.remote_roster import install_live_clients

os.environ.setdefault("TIMEASSIST_ALLOW_LOCAL_ROSTER", "1")


class PlannedDurationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = Path(self.tmp.name) / "timeassist.sqlite"
        install_live_clients(self, "Acme Co", "Client B")
        actions.init_state(self.db, "2026-05-28T08:00:00")
        roster = Path(self.tmp.name) / "roster.csv"
        roster.write_text("display_name,aliases,default_billable\nAcme Co,,yes\nClient B,,yes\n", encoding="utf-8")
        actions.import_clients(self.db, roster, "merge")

    def tearDown(self) -> None:
        currently_working.cancel_auto_end()

    def test_duration_minutes_sets_planned_end_at(self) -> None:
        session = actions.start_session(
            self.db, "Acme Co", "books", "yes", "2026-05-28T09:00:00",
            duration_minutes=120,
        )
        self.assertEqual(session["planned_end_at"], "2026-05-28T11:00:00")

    def test_explicit_planned_end_at(self) -> None:
        session = actions.start_session(
            self.db, "Acme Co", "books", "yes", "2026-05-28T09:00:00",
            planned_end_at="2026-05-28T10:30:00",
        )
        self.assertEqual(session["planned_end_at"], "2026-05-28T10:30:00")

    def test_rejects_both_duration_and_planned_end(self) -> None:
        with self.assertRaises(ValueError):
            actions.start_session(
                self.db, "Acme Co", "books", "yes", "2026-05-28T09:00:00",
                duration_minutes=60,
                planned_end_at="2026-05-28T10:00:00",
            )

    def test_default_start_gets_eight_hour_cap(self) -> None:
        session = actions.start_session(
            self.db, "Acme Co", "books", "yes", "2026-05-28T09:00:00",
        )
        self.assertEqual(session["planned_end_at"], "2026-05-28T17:00:00")

    def test_short_duration_below_cap_kept(self) -> None:
        session = actions.start_session(
            self.db, "Acme Co", "books", "yes", "2026-05-28T09:00:00",
            duration_minutes=3,
        )
        self.assertEqual(session["planned_end_at"], "2026-05-28T09:03:00")

    def test_long_duration_clamped_to_eight_hours(self) -> None:
        session = actions.start_session(
            self.db, "Acme Co", "books", "yes", "2026-05-28T09:00:00",
            duration_minutes=600,
        )
        self.assertEqual(session["planned_end_at"], "2026-05-28T17:00:00")

    def test_heartbeat_closes_at_planned_end_as_local_draft(self) -> None:
        actions.start_session(
            self.db, "Acme Co", "books", "yes", "2026-05-28T09:00:00",
            duration_minutes=60,
        )
        status = actions.checkin_status(self.db, "2026-05-28T10:05:00")
        self.assertTrue(status["auto_ended"])
        self.assertEqual(status["prompt_reason"], "planned_end_reached")
        entry = status["closed_entry"]
        self.assertEqual(entry["end_at"], "2026-05-28T10:00:00")
        self.assertEqual(entry["review_status"], "draft")
        self.assertFalse(entry.get("submitted_at"))
        idle = actions.checkin_status(self.db, "2026-05-28T10:06:00")
        self.assertFalse(idle["active"])
        self.assertFalse(idle.get("auto_ended"))

    def test_start_after_overdue_auto_closes_then_starts(self) -> None:
        actions.start_session(
            self.db, "Acme Co", "books", "yes", "2026-05-28T09:00:00",
            planned_end_at="2026-05-28T10:00:00",
        )
        nxt = actions.start_session(
            self.db, "Client B", "tax", "yes", "2026-05-28T10:30:00",
        )
        self.assertEqual(nxt["client_name"], "Client B")
        review = actions.review_entries(self.db, "2026-05-28", "2026-05-28T10:31:00")
        self.assertEqual(review["entries"][0]["end_at"], "2026-05-28T10:00:00")
        self.assertEqual(review["entries"][0]["review_status"], "draft")


class CurrentlyWorkingSyncTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = Path(self.tmp.name) / "timeassist.sqlite"
        install_live_clients(self, "Acme Co", "Client B")
        actions.init_state(self.db, "2026-05-28T08:00:00")
        roster = Path(self.tmp.name) / "roster.csv"
        roster.write_text("display_name,aliases,default_billable\nAcme Co,,yes\nClient B,,yes\n", encoding="utf-8")
        actions.import_clients(self.db, roster, "merge")
        actions.set_setting(self.db, "staff_name", "Jane Doe")
        actions.set_setting(self.db, "office", "GCD")
        self.calls: list[tuple[str, str, dict | None]] = []

        def fake_request(method, table, **kwargs):  # noqa: ANN001
            self.calls.append((method.upper(), table, kwargs.get("body")))
            if method.upper() == "GET":
                return []
            return None

        self.patcher = patch("timeassist.currently_working.request_json", side_effect=fake_request)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)
        self.addCleanup(currently_working.cancel_auto_end)

    def test_start_posts_currently_working_not_time_entries(self) -> None:
        session = actions.start_session(
            self.db, "Acme Co", "books", "yes", "2026-05-28T09:00:00",
            duration_minutes=90,
        )
        self.assertTrue(session["currently_working_sync"]["ok"])
        tables = {table for _method, table, _body in self.calls}
        self.assertIn("currently_working", tables)
        self.assertNotIn("time_entries_timmy_v2", tables)
        post = next(body for method, table, body in self.calls if method == "POST" and table == "currently_working")
        self.assertEqual(post["staff_name"], "Jane Doe")
        self.assertEqual(post["client"], "Acme Co")
        self.assertEqual(post["status"], "active")
        self.assertEqual(post["planned_end_at"], "2026-05-28T10:30:00")
        self.assertEqual(post["local_session_id"], "1")

    def test_end_patches_closed(self) -> None:
        actions.start_session(self.db, "Acme Co", "books", "yes", "2026-05-28T09:00:00")
        self.calls.clear()
        entry = actions.end_session(self.db, "2026-05-28T09:20:00")
        self.assertEqual(entry["review_status"], "draft")
        self.assertTrue(entry["currently_working_sync"]["ok"])
        patch_calls = [c for c in self.calls if c[0] == "PATCH"]
        self.assertEqual(patch_calls[0][1], "currently_working")
        self.assertEqual(patch_calls[0][2]["status"], "closed")
        self.assertNotIn("time_entries_timmy_v2", {c[1] for c in self.calls})

    def test_cancel_patches_canceled(self) -> None:
        actions.start_session(self.db, "Acme Co", "books", "yes", "2026-05-28T09:00:00")
        self.calls.clear()
        canceled = actions.cancel_session(self.db, "2026-05-28T09:05:00")
        self.assertEqual(self.calls[0][2]["status"], "canceled")
        self.assertTrue(canceled["currently_working_sync"]["ok"])

    def test_network_failure_does_not_fail_local_timer(self) -> None:
        self.patcher.stop()
        with patch("timeassist.currently_working.request_json", side_effect=ValueError("Supabase request failed (network).")):
            session = actions.start_session(
                self.db, "Acme Co", "books", "yes", "2026-05-28T09:00:00",
            )
        self.assertEqual(session["client_name"], "Acme Co")
        self.assertFalse(session["currently_working_sync"]["ok"])
        self.assertIn("network", session["currently_working_sync"]["error"])
        with patch("timeassist.currently_working.request_json", side_effect=ValueError("boom")):
            ended = actions.end_session(self.db, "2026-05-28T09:10:00")
        self.assertEqual(ended["review_status"], "draft")
        self.assertFalse(ended["currently_working_sync"]["ok"])

    def test_clarify_active_resyncs_currently_working(self) -> None:
        actions.start_session(self.db, "Acme Co", "books", "yes", "2026-05-28T09:00:00")
        self.calls.clear()
        clarified = actions.clarify_active_session(self.db, task="month-end", at="2026-05-28T09:05:00")
        self.assertEqual(clarified["task_text"], "month-end")
        self.assertTrue(clarified["currently_working_sync"]["ok"])
        self.assertTrue(any(method == "POST" or method == "PATCH" for method, table, _ in self.calls if table == "currently_working"))
        notes = [body.get("notes") for method, table, body in self.calls if table == "currently_working" and body]
        self.assertIn("month-end", notes)

    def test_mcp_start_schema_and_round_trip(self) -> None:
        msg = {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
        tools = mcp_server.handle_message(msg, self.db)["result"]["tools"]
        by_name = {tool["name"]: tool for tool in tools}
        for name in ("start", "switch"):
            props = by_name[name]["inputSchema"]["properties"]
            self.assertIn("duration_minutes", props)
            self.assertIn("planned_end_at", props)
            self.assertEqual(props["duration_minutes"]["minimum"], 1)
        start_msg = {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {
                "name": "start",
                "arguments": {
                    "client": "Acme Co",
                    "task": "books",
                    "at": "2026-05-28T09:00:00",
                    "duration_minutes": 45,
                },
            },
        }
        result = mcp_server.handle_message(start_msg, self.db)["result"]
        payload = json.loads(result["content"][0]["text"])
        self.assertEqual(payload["planned_end_at"], "2026-05-28T09:45:00")


if __name__ == "__main__":
    unittest.main()
