from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from timeassist import actions
from timeassist import supabase_config
from timeassist import supabase_ref
from timeassist.supabase_submit import submit_entry


ENV = {
    "SUPABASE_URL": "https://example.supabase.co",
    "SUPABASE_KEY": "anon-test-key",
}


class LoadConfigTests(unittest.TestCase):
    def test_defaults_match_shipped_config(self) -> None:
        cfg = supabase_config.load_supabase_config(environ={})
        self.assertEqual(cfg["tables"]["time_entries"], "time_entries_timmy_v2")
        self.assertEqual(cfg["tables"]["clients"], "clients")
        self.assertEqual(cfg["tables"]["job_codes"], "job_codes")
        self.assertEqual(cfg["tables"]["currently_working"], "currently_working")
        self.assertEqual(cfg["unassigned_client_name"], "Unassigned")

    def test_loads_plugin_layout_config_next_to_exe(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            plugin = Path(tmp) / "timeassist"
            bin_dir = plugin / "bin"
            cfg_dir = plugin / "config"
            bin_dir.mkdir(parents=True)
            cfg_dir.mkdir(parents=True)
            exe = bin_dir / "timeassist.exe"
            exe.write_bytes(b"MZ")
            (cfg_dir / "supabase.json").write_text(
                json.dumps({"tables": {"time_entries": "from_plugin_zip"}}),
                encoding="utf-8",
            )
            with patch.object(supabase_config.sys, "frozen", True, create=True), patch.object(
                supabase_config.sys, "executable", str(exe)
            ):
                cfg = supabase_config.load_supabase_config(environ={})
        self.assertEqual(cfg["tables"]["time_entries"], "from_plugin_zip")

    def test_load_from_supabase_json_beside_db(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "timeassist.sqlite"
            db.write_text("", encoding="utf-8")
            (Path(tmp) / "supabase.json").write_text(
                json.dumps(
                    {
                        "tables": {"time_entries": "time_entries_sandbox"},
                        "unassigned_client_name": "Unassigned",
                    }
                ),
                encoding="utf-8",
            )
            cfg = supabase_config.load_supabase_config(db_path=db, environ={})
        self.assertEqual(cfg["tables"]["time_entries"], "time_entries_sandbox")
        self.assertEqual(cfg["tables"]["clients"], "clients")

    def test_env_override_beats_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "timeassist.sqlite"
            db.write_text("", encoding="utf-8")
            (Path(tmp) / "supabase.json").write_text(
                json.dumps({"tables": {"time_entries": "from_file"}}),
                encoding="utf-8",
            )
            cfg = supabase_config.load_supabase_config(
                db_path=db,
                environ={"TIMEASSIST_SUPABASE_TABLE_TIME_ENTRIES": "from_env"},
            )
        self.assertEqual(cfg["tables"]["time_entries"], "from_env")

    def test_config_path_env_wins_over_beside_db(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "timeassist.sqlite"
            db.write_text("", encoding="utf-8")
            (Path(tmp) / "supabase.json").write_text(
                json.dumps({"tables": {"clients": "beside_clients"}}),
                encoding="utf-8",
            )
            other = Path(tmp) / "other.json"
            other.write_text(
                json.dumps({"tables": {"clients": "path_clients"}}),
                encoding="utf-8",
            )
            cfg = supabase_config.load_supabase_config(
                db_path=db,
                environ={"TIMEASSIST_SUPABASE_CONFIG": str(other)},
            )
        self.assertEqual(cfg["tables"]["clients"], "path_clients")

    def test_rejects_illegal_table_names(self) -> None:
        with self.assertRaises(ValueError) as caught:
            supabase_config.validate_table_name("time-entries", label="time_entries")
        self.assertIn("letters, digits, or underscore", str(caught.exception))
        with self.assertRaises(ValueError):
            supabase_config.load_supabase_config(
                environ={"TIMEASSIST_SUPABASE_TABLE_CLIENTS": "clients;drop"}
            )


class ConfiguredTableCallSites(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = Path(self.tmp.name) / "timeassist.sqlite"
        actions.init_state(self.db, "2026-05-28T08:00:00")
        (Path(self.tmp.name) / "supabase.json").write_text(
            json.dumps(
                {
                    "tables": {
                        "time_entries": "time_entries_pilot",
                        "clients": "clients_pilot",
                        "job_codes": "job_codes_pilot",
                    }
                }
            ),
            encoding="utf-8",
        )

    def test_get_clients_uses_configured_table(self) -> None:
        seen: list[str] = []

        def fake_request(method, table, **kwargs):  # noqa: ANN001
            seen.append(table)
            return []

        with patch("timeassist.supabase_ref.request_json", side_effect=fake_request):
            supabase_ref.get_clients(environ=ENV, db_path=self.db)
        self.assertEqual(seen, ["clients_pilot"])

    def test_get_job_codes_uses_configured_table(self) -> None:
        seen: list[str] = []

        def fake_request(method, table, **kwargs):  # noqa: ANN001
            seen.append(table)
            return []

        with patch("timeassist.supabase_ref.request_json", side_effect=fake_request):
            supabase_ref.get_job_codes(environ=ENV, db_path=self.db)
        self.assertEqual(seen, ["job_codes_pilot"])

    def test_submit_posts_to_configured_time_entries_table(self) -> None:
        import os

        os.environ.setdefault("TIMEASSIST_ALLOW_LOCAL_ROSTER", "1")
        roster = Path(self.tmp.name) / "roster.csv"
        roster.write_text("display_name,aliases,default_billable\nAcme Co,,yes\n", encoding="utf-8")
        actions.import_clients(self.db, roster, "merge")
        actions.add_missing_entry(
            self.db,
            "Acme Co",
            "answered emails",
            "2026-05-28T09:00:00",
            "2026-05-28T10:00:00",
            "yes",
            job_type="Email",
        )
        actions.set_setting(self.db, "staff_name", "Jane Doe")
        actions.set_setting(self.db, "office", "GCD")
        actions.set_approval(self.db, 1, True, "2026-05-28T10:05:00")
        posts: list[str] = []

        def fake_request(method, table, **kwargs):  # noqa: ANN001
            if method.upper() == "GET":
                return [{"job_code": "Email", "account": "Accounting Services:Hourly"}]
            posts.append(table)
            return [{"id": "sb-pilot-1"}]

        with patch("timeassist.supabase_submit.request_json", side_effect=fake_request):
            with patch("timeassist.supabase_ref.request_json", side_effect=fake_request):
                result = submit_entry(self.db, 1, environ=ENV, at="2026-05-28T10:06:00")
        self.assertEqual(posts, ["time_entries_pilot"])
        self.assertEqual(result["supabase_id"], "sb-pilot-1")


if __name__ == "__main__":
    unittest.main()
