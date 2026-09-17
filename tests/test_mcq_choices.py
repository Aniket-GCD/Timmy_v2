from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from timeassist import supabase_ref


class TopClientChoicesTests(unittest.TestCase):
    def test_prefers_and_ranks_closest(self) -> None:
        names = [
            "EXPRESS 3G TRUCKING, LLC",
            "EXPRESS CONCRETE MGMT LLC",
            "3GH1, LLC",
            "Acme Co",
        ]
        choices = supabase_ref.top_client_choices(
            "express 3g trucking",
            names,
            limit=3,
            prefer="EXPRESS 3G TRUCKING, LLC",
        )
        self.assertEqual(choices[0], "EXPRESS 3G TRUCKING, LLC")
        self.assertEqual(len(choices), 3)
        self.assertIn("EXPRESS CONCRETE MGMT LLC", choices)


class SuggestJobCodesTests(unittest.TestCase):
    def test_fallback_to_catalog_when_no_history(self) -> None:
        catalog = [
            {"job_code": "Consulting"},
            {"job_code": "Acct"},
            {"job_code": "Financial Stmts"},
            {"job_code": "Admin"},
        ]
        with patch("timeassist.supabase_ref.request_json", side_effect=ValueError("offline")):
            suggested = supabase_ref.suggest_job_codes_for_client(
                "Acme",
                "GCD",
                limit=3,
                catalog=catalog,
            )
        self.assertEqual(suggested, ["Acct", "Admin", "Consulting"])


class EmployeeAmbiguousTests(unittest.TestCase):
    def test_same_name_two_offices_is_ambiguous(self) -> None:
        rows = [
            {"staff_name": "Alex Daley", "office": "GCD", "active": True},
            {"staff_name": "Alex Daley", "office": "MH", "active": True},
        ]
        with patch("timeassist.supabase_ref.get_employees", return_value=rows):
            hit = supabase_ref.classify_employee_remote(
                "Alex Daley",
                environ={"SUPABASE_URL": "https://example.supabase.co", "SUPABASE_KEY": "k"},
            )
        self.assertEqual(hit["kind"], "ambiguous")
        self.assertEqual(len(hit["choices"]), 2)

    def test_office_hint_disambiguates(self) -> None:
        rows = [
            {"staff_name": "Alex Daley", "office": "GCD", "active": True},
            {"staff_name": "Alex Daley", "office": "MH", "active": True},
        ]
        with patch("timeassist.supabase_ref.get_employees", return_value=rows):
            hit = supabase_ref.classify_employee_remote(
                "Alex Daley",
                environ={"SUPABASE_URL": "https://example.supabase.co", "SUPABASE_KEY": "k"},
                office_hint="MH",
            )
        self.assertEqual(hit["kind"], "exact")
        self.assertEqual(hit["office"], "MH")


if __name__ == "__main__":
    unittest.main()
