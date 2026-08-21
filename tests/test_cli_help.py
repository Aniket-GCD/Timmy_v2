from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "timeassist.py"


class CliSmokeTests(unittest.TestCase):
    def run_cli(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(SCRIPT), *args],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )

    def test_help(self) -> None:
        result = self.run_cli("--help")
        self.assertEqual(result.returncode, 0)
        self.assertIn("Local, human-reviewed", result.stdout)

    def test_init_dry_run(self) -> None:
        result = self.run_cli("init", "--dry-run")
        self.assertEqual(result.returncode, 0)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["action"], "init")
        self.assertEqual(payload["status"], "dry-run")

    def test_init_accepts_fixed_timestamp_for_deterministic_demo(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "demo.sqlite"
            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--db",
                    str(db),
                    "init",
                    "--at",
                    "2026-05-28T08:55:00",
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["details"]["created_at"], "2026-05-28T08:55:00")

    def test_start_parses_required_fields(self) -> None:
        result = self.run_cli(
            "start",
            "--client",
            "Client A",
            "--task",
            "monthly cleanup",
            "--billable",
            "yes",
            "--dry-run",
        )
        self.assertEqual(result.returncode, 0)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["action"], "start")
        self.assertEqual(payload["details"]["client"], "Client A")

    def test_start_accepts_job_type(self) -> None:
        result = self.run_cli(
            "start",
            "--client",
            "Client A",
            "--task",
            "monthly cleanup",
            "--job-type",
            "Tax",
            "--dry-run",
        )
        self.assertEqual(result.returncode, 0)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["details"]["job_type"], "Tax")

    def test_add_client_parses_fields(self) -> None:
        result = self.run_cli(
            "add-client",
            "--name",
            "Acme Widgets",
            "--default-job-type",
            "Bookkeeping",
            "--dry-run",
        )
        self.assertEqual(result.returncode, 0)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["action"], "add-client")
        self.assertEqual(payload["details"]["name"], "Acme Widgets")
        self.assertEqual(payload["details"]["default_job_type"], "Bookkeeping")

    def test_config_accepts_strict_roster(self) -> None:
        result = self.run_cli("config", "--strict-roster", "yes", "--confirm", "--dry-run")
        self.assertEqual(result.returncode, 0)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["details"]["strict_roster"], "yes")

    def test_review_help_includes_to_flag(self) -> None:
        result = self.run_cli("review", "--help")
        self.assertEqual(result.returncode, 0)
        self.assertIn("--to", result.stdout)

    def test_export_help_includes_to_flag(self) -> None:
        result = self.run_cli("export", "--help")
        self.assertEqual(result.returncode, 0)
        self.assertIn("--to", result.stdout)

    def test_config_help_includes_operator_code_flags(self) -> None:
        result = self.run_cli("config", "--help")
        self.assertEqual(result.returncode, 0)
        self.assertIn("--operator-code", result.stdout)
        self.assertIn("--clear-operator-code", result.stdout)
        self.assertIn("--staff-name", result.stdout)
        self.assertIn("--office", result.stdout)


if __name__ == "__main__":
    unittest.main()
