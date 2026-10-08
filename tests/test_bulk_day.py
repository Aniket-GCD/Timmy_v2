"""Bulk spreadsheet save, one-shot approve, and overlap rejection."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("TIMEASSIST_ALLOW_LOCAL_ROSTER", "1")

from timeassist import actions, mcp_views
from timeassist.db import connect
from timeassist.supabase_ref import DuplicateTimeEntryError
from timeassist.supabase_submit import submit_approved_batch

ENV = {
    "SUPABASE_URL": "https://example.supabase.co",
    "SUPABASE_KEY": "anon-test-key",
}
JOB_CODES = [{"job_code": "Tax", "account": "Accounting Services:Hourly"}]


def _rows(count: int, *, job: str = "Tax", client: str = "Acme Co") -> list[dict]:
    start = datetime(2026, 10, 1, 0, 0, 0)
    rows = []
    for index in range(count):
        begin = start + timedelta(minutes=5 * index)
        end = begin + timedelta(minutes=5)
        rows.append({
            "client": client,
            "task": f"row {index}",
            "job_type": job,
            "start": begin.strftime("%Y-%m-%dT%H:%M:%S"),
            "end": end.strftime("%Y-%m-%dT%H:%M:%S"),
        })
    return rows


class BulkDayTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = Path(self.tmp.name) / "timeassist.sqlite"
        actions.init_state(self.db, "2026-10-01T08:00:00")
        roster = Path(self.tmp.name) / "roster.csv"
        roster.write_text("display_name,aliases,default_billable\nAcme Co,,yes\nAdmin,,yes\n", encoding="utf-8")
        actions.import_clients(self.db, roster, "merge")

    def test_batch_of_100_fetches_the_roster_once_and_returns_counts(self) -> None:
        calls = {"n": 0}

        def getter(**_kwargs):
            calls["n"] += 1
            return [{"display_name": "Acme Co", "office": "GCD", "active": True}]

        with mock.patch.dict(os.environ, ENV, clear=False):
            with mock.patch("timeassist.supabase_ref.get_clients", side_effect=getter):
                result = actions.add_missing_batch(self.db, _rows(100))
        self.assertEqual(calls["n"], 1)
        self.assertEqual(result["added_count"], 100)
        self.assertEqual(result["needs_attention"], [])
        self.assertIn("review_token", result)
        self.assertNotIn("entries", result)
        shaped = mcp_views.shape("add_missing_batch", result)
        self.assertNotIn("entries", shaped)

    def test_batch_lists_unmatched_and_blank_job_codes_without_saving_them(self) -> None:
        result = actions.add_missing_batch(self.db, [
            {"client": "Nope LLC", "task": "mystery", "job_type": "Tax", "start": "2026-10-01T08:00:00", "end": "2026-10-01T08:30:00"},
            {"client": "Acme Co", "task": "no code", "start": "2026-10-01T09:00:00", "end": "2026-10-01T09:30:00"},
            {"client": "Acme Co", "task": "kept", "job_type": "Tax", "start": "2026-10-01T10:00:00", "end": "2026-10-01T10:30:00"},
        ])
        self.assertEqual(result["added_count"], 1)
        reasons = {item["reason"] for item in result["needs_attention"]}
        self.assertIn("not an exact client match", reasons)
        self.assertIn("no job code", reasons)

    def test_review_of_30_does_not_download_clients_per_row(self) -> None:
        actions.add_missing_batch(self.db, _rows(28))
        actions.add_missing_entry(
            self.db, "Acme Co", "blank one",
            "2026-10-01T08:00:00", "2026-10-01T08:05:00",
        )
        actions.add_missing_entry(
            self.db, "Acme Co", "blank two",
            "2026-10-01T08:05:00", "2026-10-01T08:10:00",
        )
        calls = {"n": 0}

        def getter(**_kwargs):
            calls["n"] += 1
            return [{"display_name": "Acme Co", "active": True}]

        with mock.patch.dict(os.environ, ENV, clear=False):
            with mock.patch("timeassist.supabase_ref.get_clients", side_effect=getter):
                review = actions.review_entries(self.db, "2026-10-01")
        self.assertEqual(calls["n"], 0)
        self.assertGreater(len(review["entries"]), actions.REVIEW_FULL_BODY_LIMIT)
        shaped = mcp_views.shape("review", review)
        self.assertEqual(shaped["entry_count"], len(review["entries"]))
        self.assertLess(len(shaped["entries"]), shaped["entry_count"])
        self.assertTrue(all(not (row.get("job_type") or "").strip() or row.get("needs_info") for row in shaped["entries"]))
        self.assertIn("review_token", shaped)

    def test_approve_of_100_fetches_job_codes_once_and_posts_once(self) -> None:
        actions.set_setting(self.db, "staff_name", "Jane Doe")
        actions.set_setting(self.db, "office", "GCD")
        actions.add_missing_batch(self.db, _rows(100))
        approved = actions.approve_all(self.db, "2026-10-01")
        self.assertEqual(approved["approved_count"], 100)
        posts: list[object] = []

        def fake_request(method, table, body=None, environ=None, prefer=None, **_kwargs):
            if method == "POST":
                posts.append(body)
                return [{"id": f"sb-{index}"} for index in range(len(body))]
            raise AssertionError(method)

        roster = [{"name": "Acme Co", "office": "GCD", "active": True}]
        with mock.patch("timeassist.supabase_submit.get_job_codes", return_value=JOB_CODES) as codes:
            with mock.patch("timeassist.supabase_submit.get_clients", return_value=roster):
                with mock.patch("timeassist.supabase_submit.request_json", side_effect=fake_request):
                    posted = submit_approved_batch(self.db, approved["entries"], environ=ENV)
        self.assertEqual(codes.call_count, 1)
        self.assertEqual(len(posts), 1)
        self.assertEqual(len(posts[0]), 100)
        self.assertEqual(posted["submitted_count"], 100)
        shaped = mcp_views.shape("approve_all", {**approved, **posted})
        self.assertNotIn("entries", shaped)
        self.assertEqual(shaped["submitted_count"], 100)

    def test_duplicate_key_retries_the_rest_once(self) -> None:
        actions.set_setting(self.db, "staff_name", "Jane Doe")
        actions.set_setting(self.db, "office", "GCD")
        actions.add_missing_batch(self.db, _rows(2))
        approved = actions.approve_all(self.db, "2026-10-01")
        first = approved["entries"][0]
        detail = (
            "Key (staff_name, office, entry_date, start_time, end_time)="
            f"(Jane Doe, GCD, {first['start_at'][:10]}, {first['start_at'][11:19]}, {first['end_at'][11:19]}) already exists."
        )
        calls = {"n": 0}

        def fake_request(method, table, body=None, environ=None, prefer=None, **_kwargs):
            calls["n"] += 1
            if calls["n"] == 1:
                raise DuplicateTimeEntryError("already recorded", detail=detail)
            return [{"id": "sb-kept"}]

        roster = [{"name": "Acme Co", "office": "GCD", "active": True}]
        with mock.patch("timeassist.supabase_submit.get_job_codes", return_value=JOB_CODES):
            with mock.patch("timeassist.supabase_submit.get_clients", return_value=roster):
                with mock.patch("timeassist.supabase_submit.request_json", side_effect=fake_request):
                    posted = submit_approved_batch(self.db, approved["entries"], environ=ENV)
        self.assertEqual(calls["n"], 2)
        self.assertEqual(posted["submitted_count"], 1)
        self.assertEqual(len(posted["skipped_duplicates"]), 1)
        self.assertEqual(posted["skipped_duplicates"][0]["entry_id"], first["entry_id"])

    def test_discard_drafts_clears_the_backlog_in_one_update(self) -> None:
        day_one = _rows(50)
        day_two = _rows(50)
        for row in day_two:
            row["start"] = row["start"].replace("2026-10-01", "2026-10-02")
            row["end"] = row["end"].replace("2026-10-01", "2026-10-02")
        actions.add_missing_batch(self.db, day_one + day_two + [
            {"client": "Acme Co", "task": "needs info", "job_type": "Tax", "start": "2026-10-03T08:00:00", "end": "2026-10-03T08:30:00"},
            {"client": "Acme Co", "task": "keep approved", "job_type": "Tax", "start": "2026-10-03T09:00:00", "end": "2026-10-03T09:30:00"},
            {"client": "Acme Co", "task": "keep exported", "job_type": "Tax", "start": "2026-10-03T10:00:00", "end": "2026-10-03T10:30:00"},
        ])
        with connect(self.db) as conn:
            conn.execute("UPDATE time_entries SET review_status = 'needs_info' WHERE task_text = 'needs info'")
            conn.execute("UPDATE time_entries SET review_status = 'approved' WHERE task_text = 'keep approved'")
            conn.execute("UPDATE time_entries SET review_status = 'exported' WHERE task_text = 'keep exported'")

        def boom(*_args, **_kwargs):
            raise AssertionError("discard_drafts must not touch the network")

        with mock.patch("timeassist.supabase_ref.get_clients", side_effect=boom):
            with mock.patch("timeassist.supabase_ref.request_json", side_effect=boom):
                with mock.patch("timeassist.supabase_submit.request_json", side_effect=boom):
                    with mock.patch("timeassist.actions.review_entries", side_effect=boom):
                        result = actions.discard_drafts(self.db, "2026-10-03T18:00:00")
        self.assertEqual(result["discarded_draft_count"], 100)
        self.assertEqual(result["discarded_needs_info_count"], 1)
        self.assertEqual(result["discarded_count"], 101)
        self.assertEqual(result["left_approved_count"], 1)
        self.assertEqual(result["left_exported_count"], 1)
        self.assertNotIn("entries", result)
        shaped = mcp_views.shape("discard_drafts", {**result, "entries": [{"entry_id": 1}]})
        self.assertNotIn("entries", shaped)
        self.assertEqual(shaped["discarded_count"], 101)
        with connect(self.db) as conn:
            statuses = {
                row["review_status"]: row["c"]
                for row in conn.execute("SELECT review_status, COUNT(*) AS c FROM time_entries GROUP BY review_status")
            }
            discard_events = conn.execute(
                "SELECT COUNT(*) AS c FROM event_log WHERE event_type = 'discard'"
            ).fetchone()["c"]
            kept = conn.execute("SELECT COUNT(*) AS c FROM time_entries").fetchone()["c"]
        self.assertEqual(statuses["discarded"], 101)
        self.assertEqual(statuses["approved"], 1)
        self.assertEqual(statuses["exported"], 1)
        self.assertEqual(discard_events, 1)
        self.assertEqual(kept, 103)
        again = actions.add_missing_batch(self.db, [day_one[0]])
        self.assertEqual(again["added_count"], 1)
        self.assertEqual(again["needs_attention"], [])

    def test_overlap_is_rejected_and_touching_endpoints_are_allowed(self) -> None:
        actions.add_missing_entry(
            self.db, "Admin", "front desk",
            "2026-10-01T08:30:00", "2026-10-01T14:30:00",
            job_type="Administrative",
        )
        with self.assertRaises(ValueError) as caught:
            actions.add_missing_entry(
                self.db, "Acme Co", "IRS call",
                "2026-10-01T10:30:00", "2026-10-01T11:00:00",
                job_type="Tax",
            )
        self.assertIn("Split the stretch", str(caught.exception))
        actions.add_missing_entry(
            self.db, "Acme Co", "after",
            "2026-10-01T14:30:00", "2026-10-01T15:00:00",
            job_type="Tax",
        )


if __name__ == "__main__":
    unittest.main()
