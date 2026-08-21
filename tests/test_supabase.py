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

from timeassist import actions
from timeassist import mcp_server
from timeassist import supabase_ref
from timeassist.supabase_submit import submit_entry, time_entry_payload


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
            body = json.loads(request.data.decode("utf-8"))
            self.assertEqual(body["job_code"], "Email")
            self.assertEqual(body["account"], "Accounting Services:Hourly")
            self.assertEqual(body["office"], "MH")
            return FakeResponse(b"", 201)

        with patch("timeassist.supabase_ref.urlopen", side_effect=fake_urlopen):
            first = submit_entry(self.db, 1, environ=ENV, at="2026-05-28T10:06:00")
            second = submit_entry(self.db, 1, environ=ENV, at="2026-05-28T10:07:00")
        self.assertTrue(first["submitted"])
        self.assertFalse(first["skipped"])
        self.assertTrue(second["skipped"])
        self.assertEqual(calls.count("POST"), 1)
        self.assertEqual(calls.count("GET"), 1)

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
            return FakeResponse(b"", 201)

        secret_env = {"SUPABASE_URL": "https://example.supabase.co", "SUPABASE_KEY": "sb_secret_test"}
        with patch("timeassist.supabase_ref.urlopen", side_effect=fake_urlopen):
            submit_entry(self.db, 1, environ=secret_env, at="2026-05-28T10:06:00")
        for headers in seen:
            lowered = {k.lower(): v for k, v in headers.items()}
            self.assertIn("apikey", lowered)
            self.assertNotIn("authorization", lowered)


if __name__ == "__main__":
    unittest.main()
