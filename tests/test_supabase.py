from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import os
from timeassist import actions
from tests.remote_roster import install_live_clients

os.environ.setdefault("TIMEASSIST_ALLOW_LOCAL_ROSTER", "1")
from timeassist import mcp_server
from timeassist import pay_period
from timeassist import reception_email_draft
from timeassist import supabase_ref
from timeassist.supabase_submit import submit_entry, time_entry_payload, update_submitted_entry


ENV = {
    "SUPABASE_URL": "https://example.supabase.co",
    "SUPABASE_KEY": "anon-test-key",
}

JOB_CODES = [
    {"job_code": "Email", "description": "Answering client emails", "account": "Accounting Services:Hourly"},
]


class FakeResponse:
    def __init__(self, body: bytes | str = b"", status: int = 200):
        self._body = body.encode("utf-8") if isinstance(body, str) else body
        self.status = status

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, *exc: object) -> bool:
        return False


def http_error(status: int, body: str) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(
        "https://example.supabase.co/rest/v1/time_entries",
        status,
        "Conflict",
        {},
        io.BytesIO(body.encode("utf-8")),
    )


class HeaderTests(unittest.TestCase):
    def test_anon_key_sends_bearer(self) -> None:
        headers = supabase_ref.rest_headers("anon-test-key")
        self.assertEqual(headers["apikey"], "anon-test-key")
        self.assertEqual(headers["Authorization"], "Bearer anon-test-key")
        self.assertTrue(headers["User-Agent"].startswith("curl/"))

    def test_secret_key_skips_bearer(self) -> None:
        headers = supabase_ref.rest_headers("sb_secret_abc")
        self.assertEqual(headers["apikey"], "sb_secret_abc")
        self.assertNotIn("Authorization", headers)

    def test_credentials_prefer_supabase_key(self) -> None:
        url, key = supabase_ref.credentials_from_env({
            "SUPABASE_URL": "https://example.supabase.co/",
            "SUPABASE_KEY": "k1",
            "SUPABASE_ANON_KEY": "k2",
        })
        self.assertEqual(url, "https://example.supabase.co")
        self.assertEqual(key, "k1")

    def test_missing_env_raises_without_guessing_key(self) -> None:
        with self.assertRaises(ValueError) as caught:
            supabase_ref.credentials_from_env({})
        self.assertNotIn("sb_secret_", str(caught.exception))


class MappingTests(unittest.TestCase):
    def test_maps_local_row_to_supabase_columns(self) -> None:
        payload = time_entry_payload(
            {
                "client_name": "Acme Co",
                "task_text": "answered emails",
                "job_type": "Email",
                "billable": 1,
                "start_at": "2026-05-28T09:00:00",
                "end_at": "2026-05-28T10:00:00",
                "rounded_minutes": 60,
            },
            staff_name="Jane Doe",
            office="GCD",
            account="Accounting Services:Hourly",
        )
        self.assertEqual(payload["staff_name"], "Jane Doe")
        self.assertEqual(payload["office"], "GCD")
        self.assertEqual(payload["client"], "Acme Co")
        self.assertEqual(payload["job_code"], "Email")
        self.assertEqual(payload["account"], "Accounting Services:Hourly")
        self.assertEqual(payload["notes"], "answered emails")
        self.assertEqual(payload["task"], "answered emails")
        self.assertEqual(payload["entry_date"], "2026-05-28")
        self.assertEqual(payload["start_time"], "09:00:00")
        self.assertEqual(payload["end_time"], "10:00:00")
        self.assertEqual(payload["hours"], 1.0)
        self.assertTrue(payload["billable"])
        self.assertEqual(payload["source_file"], "timmy")

    def test_unassigned_new_client_forces_payload(self) -> None:
        payload = time_entry_payload(
            {
                "client_name": "Unassigned",
                "task_text": "NEW CLIENT: Brand New LLC | tax setup",
                "job_type": "Email",
                "billable": 1,
                "start_at": "2026-08-12T09:00:00",
                "end_at": "2026-08-12T10:00:00",
                "rounded_minutes": 60,
            },
            staff_name="Jane Doe",
            office="GCD",
            account="Accounting Services:Hourly",
        )
        self.assertEqual(payload["client"], "Unassigned")
        self.assertTrue(payload["notes"].startswith("NEW CLIENT:"))
        self.assertIn("Brand New LLC", payload["notes"])


class PayPeriodTests(unittest.TestCase):
    def test_aug_9_23_editable_through_aug_24(self) -> None:
        self.assertTrue(pay_period.editable_now("2026-08-10", now="2026-08-24T23:59:59"))
        self.assertFalse(pay_period.editable_now("2026-08-10", now="2026-08-25T00:00:00"))

    def test_aug_24_through_sep_8_editable_through_sep_9(self) -> None:
        self.assertTrue(pay_period.editable_now("2026-08-24", now="2026-09-09T23:59:59"))
        self.assertTrue(pay_period.editable_now("2026-09-08", now="2026-09-09T12:00:00"))
        self.assertFalse(pay_period.editable_now("2026-08-24", now="2026-09-10T00:00:00"))

    def test_superuser_always_can_edit(self) -> None:
        self.assertTrue(
            pay_period.can_edit_entry("2026-08-10", "Nathan Moorhead", now="2026-08-25T12:00:00")
        )
        self.assertFalse(
            pay_period.can_edit_entry("2026-08-10", "Jane Doe", now="2026-08-25T12:00:00")
        )


class ReceptionDraftTests(unittest.TestCase):
    def test_draft_contents(self) -> None:
        draft = reception_email_draft.draft_reception_email(
            spoken_client_name="Brand New LLC",
            staff_name="Jane Doe",
            office="GCD",
            to_email="front@gcd.example",
        )
        self.assertEqual(draft["to"], "front@gcd.example")
        self.assertIn("Brand New LLC", draft["subject"])
        self.assertIn("Brand New LLC", draft["body"])
        self.assertIn("Jane Doe", draft["body"])
        self.assertFalse(draft["sent"])
        self.assertTrue(draft["mailto"].startswith("mailto:"))


class SubmitGateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = Path(self.tmp.name) / "timeassist.sqlite"
        actions.init_state(self.db, "2026-05-28T08:00:00")
        roster = Path(self.tmp.name) / "roster.csv"
        roster.write_text("display_name,aliases,default_billable\nAcme Co,,yes\n", encoding="utf-8")
        actions.import_clients(self.db, roster, "merge")
        actions.add_missing_entry(
            self.db, "Acme Co", "answered emails",
            "2026-05-28T09:00:00", "2026-05-28T10:00:00",
            "yes", job_type="Email",
        )

    def test_refuses_submit_without_settings(self) -> None:
        actions.set_approval(self.db, 1, True, "2026-05-28T10:05:00")
        with self.assertRaises(ValueError) as caught:
            submit_entry(self.db, 1, environ=ENV)
        self.assertIn("staff_name", str(caught.exception))

    def test_refuses_submit_without_approve(self) -> None:
        actions.set_setting(self.db, "staff_name", "Jane Doe")
        actions.set_setting(self.db, "office", "gcd")
        with self.assertRaises(ValueError) as caught:
            submit_entry(self.db, 1, environ=ENV)
        self.assertIn("submit only after local approve", str(caught.exception))

    def test_posts_once_then_skips(self) -> None:
        actions.set_setting(self.db, "staff_name", "Jane Doe")
        actions.set_setting(self.db, "office", "MH")
        actions.set_approval(self.db, 1, True, "2026-05-28T10:05:00")
        calls: list[str] = []

        def fake_urlopen(request, timeout=30):  # noqa: ANN001
            calls.append(request.method)
            if request.method == "GET":
                return FakeResponse(json.dumps(JOB_CODES))
            self.assertEqual(request.method, "POST")
            prefer = request.headers.get("Prefer") or request.headers.get("prefer")
            self.assertEqual(prefer, "return=representation")
            body = json.loads(request.data.decode("utf-8"))
            self.assertEqual(body["job_code"], "Email")
            self.assertEqual(body["account"], "Accounting Services:Hourly")
            self.assertEqual(body["office"], "MH")
            return FakeResponse(json.dumps([{"id": "sb-row-1"}]), 201)

        with patch("timeassist.supabase_ref.urlopen", side_effect=fake_urlopen):
            first = submit_entry(self.db, 1, environ=ENV, at="2026-05-28T10:06:00")
            second = submit_entry(self.db, 1, environ=ENV, at="2026-05-28T10:07:00")
        self.assertTrue(first["submitted"])
        self.assertFalse(first["skipped"])
        self.assertEqual(first["supabase_id"], "sb-row-1")
        self.assertTrue(second["skipped"])
        self.assertEqual(calls.count("POST"), 1)
        self.assertEqual(calls.count("GET"), 1)

    def test_unassigned_seed_and_submit_payload(self) -> None:
        install_live_clients(self, "Acme Co")
        prev = os.environ.pop("TIMEASSIST_ALLOW_LOCAL_ROSTER", None)
        self.addCleanup(
            lambda: os.environ.__setitem__("TIMEASSIST_ALLOW_LOCAL_ROSTER", prev or "1")
        )
        clients = actions.list_clients(self.db, environ=ENV, confirm_full_list=True)["clients"]
        self.assertTrue(any(c["display_name"] == "Unassigned" for c in clients))
        actions.set_setting(self.db, "staff_name", "Jane Doe")
        actions.set_setting(self.db, "office", "GCD")
        entry = actions.add_missing_entry(
            self.db,
            "Unassigned",
            "NEW CLIENT: Brand New LLC | setup",
            "2026-08-12T09:00:00",
            "2026-08-12T10:00:00",
            "yes",
            job_type="Email",
        )
        self.assertEqual(entry.get("capture_status") or "resolved", "resolved")
        actions.set_approval(self.db, entry["entry_id"], True, "2026-08-12T10:05:00")
        seen: list[dict] = []

        def fake_urlopen(request, timeout=30):  # noqa: ANN001
            if request.method == "GET":
                return FakeResponse(json.dumps(JOB_CODES))
            seen.append(json.loads(request.data.decode("utf-8")))
            return FakeResponse(json.dumps([{"id": "sb-unassigned-1"}]), 201)

        with patch("timeassist.supabase_ref.urlopen", side_effect=fake_urlopen):
            result = submit_entry(self.db, entry["entry_id"], environ=ENV, at="2026-08-12T10:06:00")
        self.assertEqual(seen[0]["client"], "Unassigned")
        self.assertTrue(seen[0]["notes"].startswith("NEW CLIENT:"))
        self.assertEqual(result["supabase_id"], "sb-unassigned-1")

    def test_update_submitted_uses_patch_not_post(self) -> None:
        actions.set_setting(self.db, "staff_name", "Jane Doe")
        actions.set_setting(self.db, "office", "GCD")
        actions.set_approval(self.db, 1, True, "2026-05-28T10:05:00")
        methods: list[str] = []

        def fake_urlopen(request, timeout=30):  # noqa: ANN001
            methods.append(request.method)
            if request.method == "GET":
                return FakeResponse(json.dumps(JOB_CODES))
            if request.method == "POST":
                return FakeResponse(json.dumps([{"id": "sb-row-9"}]), 201)
            self.assertEqual(request.method, "PATCH")
            self.assertIn("id=eq.sb-row-9", request.full_url)
            return FakeResponse(json.dumps([{"id": "sb-row-9"}]), 200)

        with patch("timeassist.supabase_ref.urlopen", side_effect=fake_urlopen):
            submit_entry(self.db, 1, environ=ENV, at="2026-05-28T10:06:00")
            # In-window edit + patch (May 28 is days 24–end → window through June 9)
            actions.edit_entry(self.db, 1, task="fixed notes", at="2026-05-28T11:00:00")
            updated = update_submitted_entry(self.db, 1, environ=ENV, at="2026-05-28T11:01:00")
        self.assertEqual(methods.count("POST"), 1)
        self.assertEqual(methods.count("PATCH"), 1)
        self.assertTrue(updated["updated"])
        self.assertEqual(updated["supabase_id"], "sb-row-9")

    def test_normal_staff_refuses_out_of_window_update(self) -> None:
        actions.set_setting(self.db, "staff_name", "Jane Doe")
        actions.set_setting(self.db, "office", "GCD")
        actions.set_approval(self.db, 1, True, "2026-05-28T10:05:00")

        def fake_urlopen(request, timeout=30):  # noqa: ANN001
            if request.method == "GET":
                return FakeResponse(json.dumps(JOB_CODES))
            return FakeResponse(json.dumps([{"id": "sb-row-2"}]), 201)

        with patch("timeassist.supabase_ref.urlopen", side_effect=fake_urlopen):
            submit_entry(self.db, 1, environ=ENV, at="2026-05-28T10:06:00")
        with self.assertRaises(ValueError) as caught:
            update_submitted_entry(self.db, 1, environ=ENV, at="2026-06-15T12:00:00")
        self.assertIn("pay-period", str(caught.exception))

    def test_superuser_can_update_out_of_window(self) -> None:
        actions.set_setting(self.db, "staff_name", "Hannah Curtis")
        actions.set_setting(self.db, "office", "GCD")
        actions.set_approval(self.db, 1, True, "2026-05-28T10:05:00")
        methods: list[str] = []

        def fake_urlopen(request, timeout=30):  # noqa: ANN001
            methods.append(request.method)
            if request.method == "GET":
                return FakeResponse(json.dumps(JOB_CODES))
            if request.method == "POST":
                return FakeResponse(json.dumps([{"id": "sb-row-3"}]), 201)
            return FakeResponse(json.dumps([{"id": "sb-row-3"}]), 200)

        with patch("timeassist.supabase_ref.urlopen", side_effect=fake_urlopen):
            submit_entry(self.db, 1, environ=ENV, at="2026-05-28T10:06:00")
            update_submitted_entry(self.db, 1, environ=ENV, at="2026-06-15T12:00:00")
        self.assertIn("PATCH", methods)

    def test_duplicate_unique_violation_is_friendly(self) -> None:
        actions.set_setting(self.db, "staff_name", "Jane Doe")
        actions.set_setting(self.db, "office", "GCD")
        actions.set_approval(self.db, 1, True, "2026-05-28T10:05:00")

        def fake_urlopen(request, timeout=30):  # noqa: ANN001
            if request.method == "GET":
                return FakeResponse(json.dumps(JOB_CODES))
            raise http_error(409, '{"code":"23505","message":"duplicate key value violates unique constraint"}')

        with patch("timeassist.supabase_ref.urlopen", side_effect=fake_urlopen):
            with self.assertRaises(supabase_ref.DuplicateTimeEntryError) as caught:
                submit_entry(self.db, 1, environ=ENV)
        self.assertIn("already recorded", str(caught.exception))
        self.assertIn("9-10 and 10-11", str(caught.exception))

    def test_mcp_submit_refuses_draft(self) -> None:
        actions.set_setting(self.db, "staff_name", "Jane Doe")
        actions.set_setting(self.db, "office", "GCD")
        msg = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "submit", "arguments": {"entry_id": 1}},
        }
        result = mcp_server.handle_message(msg, self.db)["result"]
        self.assertTrue(result.get("isError"))
        self.assertIn("submit only after local approve", result["content"][0]["text"])

    def test_secret_key_post_omits_authorization(self) -> None:
        actions.set_setting(self.db, "staff_name", "Jane Doe")
        actions.set_setting(self.db, "office", "GCD")
        actions.set_approval(self.db, 1, True, "2026-05-28T10:05:00")
        seen: list[dict] = []

        def fake_urlopen(request, timeout=30):  # noqa: ANN001
            seen.append(dict(request.headers))
            if request.method == "GET":
                return FakeResponse(json.dumps(JOB_CODES))
            return FakeResponse(json.dumps([{"id": "sb-secret-1"}]), 201)

        secret_env = {"SUPABASE_URL": "https://example.supabase.co", "SUPABASE_KEY": "sb_secret_test"}
        with patch("timeassist.supabase_ref.urlopen", side_effect=fake_urlopen):
            submit_entry(self.db, 1, environ=secret_env, at="2026-05-28T10:06:00")
        for headers in seen:
            lowered = {k.lower(): v for k, v in headers.items()}
            self.assertIn("apikey", lowered)
            self.assertNotIn("authorization", lowered)


if __name__ == "__main__":
    unittest.main()


class LiveClientRosterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.prev = os.environ.pop("TIMEASSIST_ALLOW_LOCAL_ROSTER", None)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = Path(self.tmp.name) / "timeassist.sqlite"
        actions.init_state(self.db, "2026-05-28T09:00:00")
        actions.set_setting(self.db, "office", "GCD")

    def tearDown(self) -> None:
        if self.prev is not None:
            os.environ["TIMEASSIST_ALLOW_LOCAL_ROSTER"] = self.prev
        else:
            os.environ["TIMEASSIST_ALLOW_LOCAL_ROSTER"] = "1"

    def test_list_clients_remote_filters_office(self) -> None:
        rows = [
            {"name": "Unassigned", "office": "GCD", "active": True},
            {"name": "Acme Co", "office": "GCD", "active": True},
            {"name": "Other Office LLC", "office": "MH", "active": True},
            {"name": "Dead Co", "office": "GCD", "active": False},
        ]
        with patch("timeassist.supabase_ref.get_clients", return_value=rows):
            listed = actions.list_clients(self.db, environ=ENV, confirm_full_list=True)["clients"]
        names = {c["display_name"] for c in listed}
        self.assertEqual(names, {"Acme Co", "Unassigned"})

    def test_list_clients_requires_query_or_confirm(self) -> None:
        rows = [
            {"name": "Unassigned", "office": "GCD", "active": True},
            {"name": "0969 Ocean View Road", "office": "GCD", "active": True},
        ]
        with patch("timeassist.supabase_ref.get_clients", return_value=rows):
            result = actions.list_clients(self.db, environ=ENV)
        self.assertEqual(result["clients"], [])
        self.assertEqual(result["client_count"], 2)
        self.assertIn("query", result["message"].lower())

    def test_resolve_soft_street_number_prefix(self) -> None:
        from timeassist import db as tdb
        install_live_clients(self, "0969 Ocean View Road", "Acme Co")
        with tdb.connect(self.db) as conn:
            name, billable = actions.resolve_client(conn, "Ocean View Road", environ=ENV)
        self.assertEqual(name, "0969 Ocean View Road")
        self.assertEqual(billable, 1)

    def test_add_missing_soft_match_asks_before_write(self) -> None:
        install_live_clients(self, "0969 Ocean View Road", "Acme Co")
        pending = actions.add_missing_entry(
            self.db,
            "Ocean View Road",
            "tax prep",
            "2026-08-21T09:00:00",
            "2026-08-21T10:00:00",
            "yes",
        )
        self.assertTrue(pending.get("needs_client_confirm"))
        self.assertEqual(pending["suggested_client"], "0969 Ocean View Road")
        self.assertIn("Did you mean", pending["ask"])
        from timeassist import db as tdb
        with tdb.connect(self.db) as conn:
            n = conn.execute("SELECT COUNT(*) FROM time_entries").fetchone()[0]
        self.assertEqual(n, 0)
        written = actions.add_missing_entry(
            self.db,
            "0969 Ocean View Road",
            "tax prep",
            "2026-08-21T09:00:00",
            "2026-08-21T10:00:00",
            "yes",
        )
        self.assertEqual(written["client_name"], "0969 Ocean View Road")
        self.assertEqual(written.get("capture_status") or "resolved", "resolved")

    def test_add_missing_soft_confirm_client_flag(self) -> None:
        install_live_clients(self, "Bill's Windsurf Shop", "Acme Co")
        written = actions.add_missing_entry(
            self.db,
            "Bill's Shop",
            "work",
            "2026-05-28T09:00:00",
            "2026-05-28T09:30:00",
            "yes",
            confirm_client=True,
        )
        self.assertEqual(written["client_name"], "Bill's Windsurf Shop")

    def test_supabase_creds_force_live_over_local_escape_hatch(self) -> None:
        """Pilot MCP always has Supabase env — never dump the stale SQLite CSV roster."""
        os.environ["TIMEASSIST_ALLOW_LOCAL_ROSTER"] = "1"
        os.environ["SUPABASE_URL"] = ENV["SUPABASE_URL"]
        os.environ["SUPABASE_KEY"] = ENV["SUPABASE_KEY"]
        self.addCleanup(lambda: os.environ.pop("SUPABASE_URL", None))
        self.addCleanup(lambda: os.environ.pop("SUPABASE_KEY", None))
        self.assertFalse(actions._local_roster_allowed())
        rows = [
            {"name": "0969 Ocean View Road", "office": "GCD", "active": True},
            {"name": "Unassigned", "office": "GCD", "active": True},
        ]
        with patch("timeassist.supabase_ref.get_clients", return_value=rows):
            pending = actions.add_missing_entry(
                self.db,
                "Ocean View Road",
                "tax prep",
                "2026-08-21T09:00:00",
                "2026-08-21T10:00:00",
                "yes",
            )
            listed = actions.list_clients(self.db, environ=ENV, query="Ocean View Road")["clients"]
        self.assertTrue(pending.get("needs_client_confirm"))
        self.assertEqual(pending["suggested_client"], "0969 Ocean View Road")
        self.assertEqual([c["display_name"] for c in listed], ["0969 Ocean View Road"])

    def test_resolve_soft_unique_nickname(self) -> None:
        from timeassist import db as tdb
        install_live_clients(self, "Bill's Windsurf Shop", "Acme Co")
        with tdb.connect(self.db) as conn:
            name, billable = actions.resolve_client(conn, "Bill's Shop", environ=ENV)
        self.assertEqual(name, "Bill's Windsurf Shop")
        self.assertEqual(billable, 1)

    def test_resolve_soft_ambiguous_stays_unmatched(self) -> None:
        from timeassist import db as tdb
        install_live_clients(self, "Bill's Windsurf Shop", "Bill's Bike Shop")
        with tdb.connect(self.db) as conn:
            name, billable = actions.resolve_client(conn, "Bill's Shop", environ=ENV)
        self.assertEqual(name, "Bill's Shop")
        self.assertIsNone(billable)

    def test_list_clients_query_filters(self) -> None:
        rows = [
            {"name": "Unassigned", "office": "GCD", "active": True},
            {"name": "Bill's Windsurf Shop", "office": "GCD", "active": True},
            {"name": "Acme Co", "office": "GCD", "active": True},
        ]
        with patch("timeassist.supabase_ref.get_clients", return_value=rows):
            listed = actions.list_clients(self.db, environ=ENV, query="bill shop")["clients"]
        names = {c["display_name"] for c in listed}
        self.assertEqual(names, {"Bill's Windsurf Shop"})

    def test_resolve_miss_returns_none_billable(self) -> None:
        from timeassist import db as tdb
        install_live_clients(self, "Acme Co")
        with tdb.connect(self.db) as conn:
            name, billable = actions.resolve_client(conn, "Nobody LLC", environ=ENV)
        self.assertEqual(name, "Nobody LLC")
        self.assertIsNone(billable)

    def test_fail_closed_when_get_clients_errors(self) -> None:
        with patch("timeassist.supabase_ref.get_clients", side_effect=ValueError("network down")):
            with self.assertRaises(ValueError) as ctx:
                actions.list_clients(self.db, environ=ENV, query="x")
        self.assertIn("client list unavailable", str(ctx.exception))

    def test_import_disabled_without_escape_hatch(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            actions.import_clients(self.db, Path("x.csv"))
        self.assertIn("Supabase", str(ctx.exception))

    def test_capture_uses_live_hit(self) -> None:
        install_live_clients(self, "Acme Co")
        entry = actions.add_missing_entry(
            self.db, "acme co", "work",
            "2026-05-28T09:00:00", "2026-05-28T09:30:00", "yes",
        )
        self.assertEqual(entry["client_name"], "Acme Co")
        self.assertEqual(entry.get("capture_status") or "resolved", "resolved")

