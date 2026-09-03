from __future__ import annotations

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
from timeassist import mcp_views
from timeassist import supabase_config
from timeassist import supabase_ref

ENV = {
    "SUPABASE_URL": "https://example.supabase.co",
    "SUPABASE_KEY": "anon-test-key",
}

EMPLOYEES = [
    {"staff_name": "Hannah Curtis", "office": "GCD", "first_name": "Hannah", "last_name": "Curtis", "active": True},
    {"staff_name": "Aniket", "office": "GCD", "first_name": "Aniket", "last_name": "", "active": True},
    {"staff_name": "Alex Daley", "office": "GCD", "first_name": "Alex", "last_name": "Daley", "active": True},
]


class EmployeesConfigTests(unittest.TestCase):
    def test_default_employees_table(self) -> None:
        cfg = supabase_config.load_supabase_config(environ={})
        self.assertEqual(cfg["tables"]["employees"], "employees")


class EmployeesResolveTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = Path(self.tmp.name) / "timeassist.sqlite"
        actions.init_state(self.db, "2026-05-28T08:00:00")
        self.patcher = patch(
            "timeassist.supabase_ref.get_employees",
            return_value=EMPLOYEES,
        )
        self.patcher.start()
        self.addCleanup(self.patcher.stop)

    def test_exact_match_sets_canonical_name_and_office(self) -> None:
        result = actions.configure_staff_name(
            self.db, "hannah curtis", environ=ENV,
        )
        self.assertFalse(result.get("needs_staff_confirm"))
        self.assertEqual(result["value"], "Hannah Curtis")
        self.assertEqual(result["office"]["value"], "GCD")
        settings = actions.list_settings(self.db)
        self.assertEqual(settings["staff_name"], "Hannah Curtis")
        self.assertEqual(settings["office"], "GCD")

    def test_soft_match_asks_before_write(self) -> None:
        result = actions.configure_staff_name(self.db, "Hannah", environ=ENV)
        self.assertTrue(result["needs_staff_confirm"])
        self.assertEqual(result["suggested_staff_name"], "Hannah Curtis")
        self.assertNotIn("staff_name", actions.list_settings(self.db))

    def test_soft_match_confirm_writes(self) -> None:
        result = actions.configure_staff_name(
            self.db, "Hannah", confirm_staff=True, environ=ENV,
        )
        self.assertEqual(result["value"], "Hannah Curtis")
        self.assertEqual(actions.list_settings(self.db)["staff_name"], "Hannah Curtis")

    def test_unknown_name_does_not_write(self) -> None:
        result = actions.configure_staff_name(self.db, "Totally Fake", environ=ENV)
        self.assertTrue(result["needs_staff_confirm"])
        self.assertEqual(result["match_kind"], "none")
        self.assertNotIn("staff_name", actions.list_settings(self.db))

    def test_fold_last_first(self) -> None:
        result = actions.configure_staff_name(self.db, "Curtis, Hannah", environ=ENV)
        self.assertEqual(result["value"], "Hannah Curtis")

    def test_offline_set_setting_still_works_without_credentials(self) -> None:
        details = actions.set_setting(self.db, "staff_name", "Jane Doe")
        self.assertEqual(details["value"], "Jane Doe")

    def test_staff_setup_hint(self) -> None:
        status = actions.staff_setup_status(self.db)
        self.assertTrue(status["required"])
        actions.configure_staff_name(self.db, "Aniket", environ=ENV)
        status = actions.staff_setup_status(self.db)
        self.assertFalse(status["required"])

    def test_list_employees_query(self) -> None:
        listed = actions.list_employees(self.db, query="Hannah", environ=ENV)
        self.assertEqual(listed["employee_count"], 1)
        self.assertEqual(listed["employees"][0]["staff_name"], "Hannah Curtis")

    def test_mcp_config_view_confirm(self) -> None:
        payload = actions.configure_staff_name(self.db, "Hannah", environ=ENV)
        shaped = mcp_views.shape("config", payload)
        self.assertTrue(shaped["needs_staff_confirm"])
        self.assertEqual(shaped["suggested_staff_name"], "Hannah Curtis")

    def test_classify_employee_remote(self) -> None:
        hit = supabase_ref.classify_employee_remote("aniket", environ=ENV)
        self.assertEqual(hit["kind"], "exact")
        self.assertEqual(hit["staff_name"], "Aniket")


if __name__ == "__main__":
    unittest.main()
