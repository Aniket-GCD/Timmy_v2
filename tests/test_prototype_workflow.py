from __future__ import annotations

import csv
import json
import subprocess
import sys
import tempfile
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "timeassist.py"


class _CliHarness(unittest.TestCase):
    """Shared temp-DB harness for CLI subprocess tests."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.workdir = Path(self.tmp.name)
        self.db = self.workdir / "timeassist.sqlite"

    def run_cli(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(SCRIPT), "--db", str(self.db), *args],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )

    def json_cli(self, *args: str) -> dict:
        result = self.run_cli(*args)
        if result.returncode != 0:
            self.fail(f"command failed: {args}\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}")
        return json.loads(result.stdout)


class PrototypeWorkflowTests(_CliHarness):
    def test_full_capture_review_approve_export_and_sanitize_flow(self) -> None:
        init = self.json_cli("init")
        self.assertEqual(init["status"], "initialized")
        self.assertTrue(self.db.exists())

        # Register Client A so its captures resolve (the #34 roster gate). Client
        # B stays off-roster so the switch still demonstrates needs_info below.
        roster = self.workdir / "roster-seed.csv"
        roster.write_text("display_name,aliases,default_billable\nClient A,,yes\n")
        self.json_cli("import-clients", "--file", str(roster), "--mode", "merge")

        start = self.json_cli(
            "start",
            "--client",
            "Client A",
            "--task",
            "monthly cleanup",
            "--billable",
            "yes",
            "--at",
            "2026-05-28T09:00:00",
        )
        self.assertEqual(start["status"], "started")
        self.assertEqual(start["details"]["active_session"]["client_name"], "Client A")

        switch = self.json_cli(
            "switch",
            "--client",
            "Client B",
            "--task",
            "tax question",
            "--billable",
            "yes",
            "--at",
            "2026-05-28T09:24:00",
        )
        self.assertEqual(switch["status"], "switched")
        self.assertEqual(switch["details"]["closed_entry"]["duration_minutes"], 24)
        self.assertEqual(switch["details"]["new_active_session"]["client_name"], "Client B")
        self.assertEqual(switch["details"]["new_active_session"]["capture_status"], "needs_info")

        clarify = self.json_cli(
            "clarify-active",
            "--client",
            "Client B",
            "--task",
            "tax question",
            "--billable",
            "yes",
            "--at",
            "2026-05-28T09:30:00",
        )
        self.assertEqual(clarify["status"], "clarified")
        self.assertEqual(clarify["details"]["active_session"]["capture_status"], "resolved")
        self.assertEqual(clarify["details"]["active_session"]["started_at"], "2026-05-28T09:24:00")

        end = self.json_cli("end", "--at", "2026-05-28T09:42:00")
        self.assertEqual(end["status"], "ended")
        self.assertEqual(end["details"]["closed_entry"]["duration_minutes"], 18)

        review = self.json_cli("review", "--date", "2026-05-28")
        self.assertEqual(review["status"], "review-ready")
        entries = review["details"]["entries"]
        self.assertEqual([entry["client_name"] for entry in entries], ["Client A", "Client B"])
        self.assertEqual([entry["review_status"] for entry in entries], ["draft", "draft"])
        self.assertEqual(review["details"]["totals"]["draft_minutes"], 42)
        self.assertGreaterEqual(review["details"]["event_count"], 4)

        approval = self.json_cli(
            "approve",
            "--entry-id",
            "1",
            "--review-token",
            review["details"]["review_token"],
            "--at",
            "2026-05-28T10:45:00",
        )
        self.assertEqual(approval["status"], "approved")
        self.assertEqual(approval["details"]["entry"]["updated_at"], "2026-05-28T10:45:00")

        export_review = self.json_cli("review", "--date", "2026-05-28")
        export_path = self.workdir / "qb-export.csv"
        export = self.json_cli(
            "export",
            "--date",
            "2026-05-28",
            "--format",
            "quickbooks-csv",
            "--output",
            str(export_path),
            "--review-token",
            export_review["details"]["review_token"],
            "--at",
            "2026-05-28T10:50:00",
        )
        self.assertEqual(export["status"], "exported")
        self.assertTrue(export_path.exists())
        rows = list(csv.DictReader(export_path.read_text().splitlines()))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["Client"], "Client A")
        self.assertEqual(rows[0]["Duration"], "0:24")
        self.assertNotIn("Service", rows[0])
        self.assertEqual(
            list(rows[0].keys()),
            ["Date", "Client", "Job Type", "Notes", "Duration", "Billable"],
        )

        packet_path = self.workdir / "sanitized-packet.md"
        packet = self.json_cli(
            "sanitize-packet",
            "--date",
            "2026-05-28",
            "--output",
            str(packet_path),
        )
        self.assertEqual(packet["status"], "packet-created")
        packet_text = packet_path.read_text()
        self.assertIn("Client 1", packet_text)
        self.assertIn("Client 2", packet_text)
        self.assertNotIn("Client A", packet_text)
        self.assertNotIn("Client B", packet_text)

    def test_cli_switch_minutes_ago_uses_relative_correction_time(self) -> None:
        self.json_cli("init", "--at", "2026-05-28T08:55:00")
        self.json_cli(
            "start",
            "--client",
            "Client A",
            "--task",
            "monthly cleanup",
            "--billable",
            "yes",
            "--at",
            "2026-05-28T09:00:00",
        )

        switched = self.json_cli(
            "switch",
            "--client",
            "Client B",
            "--task",
            "tax question",
            "--billable",
            "yes",
            "--at",
            "2026-05-28T10:00:00",
            "--minutes-ago",
            "20",
        )

        self.assertEqual(switched["status"], "switched")
        self.assertEqual(switched["details"]["closed_entry"]["end_at"], "2026-05-28T09:40:00")
        self.assertEqual(switched["details"]["closed_entry"]["duration_minutes"], 40)
        self.assertEqual(switched["details"]["new_active_session"]["started_at"], "2026-05-28T09:40:00")

    def test_cli_snooze_checkin_sets_snoozed_until(self) -> None:
        self.json_cli("init", "--at", "2026-05-28T08:55:00")
        self.json_cli(
            "start",
            "--client",
            "Client A",
            "--task",
            "monthly cleanup",
            "--billable",
            "yes",
            "--at",
            "2026-05-28T09:00:00",
        )

        snoozed = self.json_cli("snooze-checkin", "--minutes", "30", "--at", "2026-05-28T09:45:00")

        self.assertEqual(snoozed["status"], "snoozed")
        self.assertEqual(snoozed["details"]["session"]["snoozed_until"], "2026-05-28T10:15:00")

    def test_cli_review_at_surfaces_active_timer_warning(self) -> None:
        self.json_cli("init", "--at", "2026-05-28T08:55:00")
        self.json_cli(
            "start",
            "--client",
            "Client A",
            "--task",
            "monthly cleanup",
            "--billable",
            "yes",
            "--at",
            "2026-05-28T09:00:00",
        )

        review = self.json_cli("review", "--date", "2026-05-28", "--at", "2026-05-28T17:05:00")

        warning = review["details"]["active_timer_warning"]
        self.assertTrue(warning["has_active_timer"])
        self.assertTrue(warning["is_stale"])
        self.assertEqual(warning["client_name"], "Client A")
        self.assertIn("switch", warning["suggested_actions"])

    def test_cli_approve_and_export_require_review_token(self) -> None:
        self.json_cli("init", "--at", "2026-05-28T08:55:00")
        roster = self.workdir / "roster-seed.csv"
        roster.write_text("display_name,aliases,default_billable\nClient A,,yes\n")
        self.json_cli("import-clients", "--file", str(roster), "--mode", "merge")
        self.json_cli(
            "add-missing",
            "--client",
            "Client A",
            "--task",
            "work",
            "--start",
            "2026-05-28T10:00:00",
            "--end",
            "2026-05-28T10:24:00",
        )

        missing_approve_token = self.run_cli("approve", "--entry-id", "1")
        self.assertNotEqual(missing_approve_token.returncode, 0)
        self.assertIn("review_token", missing_approve_token.stdout)

        review = self.json_cli("review", "--date", "2026-05-28")
        self.json_cli("approve", "--entry-id", "1", "--review-token", review["details"]["review_token"])

        missing_export_token = self.run_cli("export", "--date", "2026-05-28", "--output", str(self.workdir / "qb.csv"))
        self.assertNotEqual(missing_export_token.returncode, 0)
        self.assertIn("review_token", missing_export_token.stdout)

    def test_cli_approve_all_requires_review_token(self) -> None:
        self.json_cli("init", "--at", "2026-05-28T08:55:00")
        self.json_cli(
            "add-missing",
            "--client",
            "Client A",
            "--task",
            "work",
            "--start",
            "2026-05-28T10:00:00",
            "--end",
            "2026-05-28T10:24:00",
        )

        result = self.run_cli("approve", "--all", "--date", "2026-05-28")

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("review_token", result.stdout)

    def test_cli_approve_rejects_all_with_entry_id(self) -> None:
        self.json_cli("init", "--at", "2026-05-28T08:55:00")
        self.json_cli(
            "add-missing",
            "--client",
            "Client A",
            "--task",
            "work",
            "--start",
            "2026-05-28T10:00:00",
            "--end",
            "2026-05-28T10:24:00",
        )
        review = self.json_cli("review", "--date", "2026-05-28")

        result = self.run_cli("approve", "--all", "--entry-id", "1", "--date", "2026-05-28", "--review-token", review["details"]["review_token"])

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("not both", result.stdout)

    def test_cli_admin_changes_require_confirmation_flags(self) -> None:
        self.json_cli("init", "--at", "2026-05-28T08:55:00")
        clients = self.workdir / "clients.csv"
        clients.write_text("client_key,display_name,aliases,default_billable\nacme,Acme Co,,yes\n")

        cases = [
            ("config", "--rounding-rule", "up_15_minutes"),
            ("config", "--confirm-default-user-export-dir"),
            ("reround", "--date", "2026-05-28", "--rounding-rule", "up_15_minutes"),
            ("cleanup", "--retention-days", "90"),
            ("import-clients", "--file", str(clients), "--mode", "replace"),
        ]
        for args in cases:
            with self.subTest(args=args):
                result = self.run_cli(*args)
                self.assertNotEqual(result.returncode, 0)
                self.assertRegex(result.stdout, "confirm|confirm_replace")

    def test_cli_can_confirm_default_export_folder_survey(self) -> None:
        self.json_cli("init", "--at", "2026-05-28T08:55:00")

        current = self.json_cli("config")
        self.assertTrue(current["details"]["export_folder"]["survey_required"])
        self.assertEqual(current["details"]["export_folder"]["preference"], "default_unconfirmed")

        confirmed = self.json_cli("config", "--confirm-default-user-export-dir", "--confirm")
        export_folder = confirmed["details"]["export_folder"]
        self.assertFalse(export_folder["survey_required"])
        self.assertEqual(export_folder["preference"], "default_confirmed")
        self.assertEqual(export_folder["user_export_dir"], export_folder["default_user_export_dir"])

        current_again = self.json_cli("config")
        self.assertFalse(current_again["details"]["export_folder"]["survey_required"])

    def test_review_html_output_is_stakeholder_readable(self) -> None:
        self.json_cli("init")
        self.json_cli(
            "add-missing",
            "--client",
            "Client A",
            "--task",
            "monthly cleanup",
            "--start",
            "2026-05-28T10:00:00",
            "--end",
            "2026-05-28T10:24:00",
            "--billable",
            "yes",
        )
        html_path = self.workdir / "review.html"
        review = self.json_cli(
            "review",
            "--date",
            "2026-05-28",
            "--format",
            "html",
            "--output",
            str(html_path),
        )
        self.assertEqual(review["status"], "review-ready")
        html = html_path.read_text()
        self.assertIn("TimeAssist Stakeholder Review", html)
        self.assertIn("Human review before export to QuickBooks", html)
        self.assertIn("Approve draft", html)
        self.assertIn("Client A", html)
        self.assertIn("monthly cleanup", html)

    def test_demo_command_generates_stakeholder_artifacts(self) -> None:
        output_dir = self.workdir / "generated-demo"
        demo = self.json_cli("demo", "--output", str(output_dir))
        self.assertEqual(demo["status"], "demo-generated")
        details = demo["details"]
        self.assertEqual(details["commands_run"], 14)  # +1 for the roster import step
        artifacts = details["artifacts"]
        expected = [
            "stakeholder_review_html",
            "review_before_approval_html",
            "quickbooks_csv",
            "sanitized_packet",
            "transcript",
            "database",
        ]
        for key in expected:
            self.assertTrue(Path(artifacts[key]).exists(), f"missing generated artifact: {key}")
        html = Path(artifacts["stakeholder_review_html"]).read_text()
        self.assertIn("Draft first. You decide.", html)
        self.assertIn("Client A", html)
        self.assertIn("Exported", html)
        readme = output_dir / "README.md"
        self.assertTrue(readme.exists(), "demo output should explain that artifacts are synthetic")
        self.assertIn("Curated synthetic demo output", readme.read_text())
        transcript = Path(artifacts["transcript"]).read_text()
        self.assertNotIn(Path.home().as_posix(), transcript)
        self.assertIn("~/Documents/TimeAssist Exports", transcript)

    def test_demo_command_refuses_to_clear_unowned_existing_directory(self) -> None:
        output_dir = self.workdir / "real-folder"
        output_dir.mkdir()
        sentinel = output_dir / "keep-me.txt"
        sentinel.write_text("do not delete")

        result = self.run_cli("demo", "--output", str(output_dir))

        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(sentinel.exists())
        self.assertIn("refusing to clear", result.stdout.lower())

    def test_demo_command_rejects_symlink_ownership_marker(self) -> None:
        output_dir = self.workdir / "attacker-folder"
        output_dir.mkdir()
        sentinel = output_dir / "keep-me.txt"
        sentinel.write_text("do not delete")
        target = self.workdir / "outside-target.txt"
        target.write_text("do not overwrite")
        (output_dir / ".timeassist-demo-output").symlink_to(target)

        result = self.run_cli("demo", "--output", str(output_dir))

        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(sentinel.exists())
        self.assertEqual(target.read_text(), "do not overwrite")
        self.assertIn("ownership marker", result.stdout.lower())


class RangeCLITests(_CliHarness):
    """CLI tests for --to range flags and --operator-code config."""

    def _seed_db_with_range_entries(self) -> None:
        """Init DB with two approved entries on different days (2026-06-01, 2026-06-30)."""
        self.json_cli("init", "--at", "2026-06-01T08:00:00")
        roster = self.workdir / "roster.csv"
        roster.write_text("display_name,aliases,default_billable\nAcme Co,,yes\n")
        self.json_cli("import-clients", "--file", str(roster), "--mode", "merge")
        self.json_cli(
            "add-missing", "--client", "Acme Co", "--task", "June first work",
            "--start", "2026-06-01T09:00:00", "--end", "2026-06-01T09:30:00",
        )
        self.json_cli(
            "add-missing", "--client", "Acme Co", "--task", "June last work",
            "--start", "2026-06-30T14:00:00", "--end", "2026-06-30T15:00:00",
        )

    # ------------------------------------------------------------------
    # review --to: range token
    # ------------------------------------------------------------------

    def test_review_to_returns_range_details_and_token(self) -> None:
        self._seed_db_with_range_entries()
        result = self.json_cli(
            "review", "--date", "2026-06-01", "--to", "2026-06-30",
            "--at", "2026-06-30T18:00:00",
        )
        self.assertEqual(result["status"], "review-ready")
        self.assertIn("end_date", result["details"])
        self.assertEqual(result["details"]["end_date"], "2026-06-30")
        self.assertIn("review_token", result["details"])
        # range review carries a "days" breakdown
        self.assertIn("days", result["details"])

    def test_review_today_keyword_in_to_is_normalised(self) -> None:
        self._seed_db_with_range_entries()
        # "today" in --to should be normalised; just ensure it doesn't raise
        # (entries are seeded on 2026-06-01, safely earlier than any test run date)
        result = self.json_cli("review", "--date", "2026-06-01", "--to", "today")
        self.assertEqual(result["status"], "review-ready")

    # ------------------------------------------------------------------
    # export --to: range CSV, stale single-day token rejected
    # ------------------------------------------------------------------

    def test_export_to_with_range_token_writes_range_csv(self) -> None:
        self._seed_db_with_range_entries()
        # Approve day-1 entry with its own single-day token
        rev1 = self.json_cli("review", "--date", "2026-06-01", "--at", "2026-06-01T12:00:00")
        self.json_cli("approve", "--all", "--date", "2026-06-01",
                      "--review-token", rev1["details"]["review_token"],
                      "--at", "2026-06-01T12:00:00")
        # Approve day-30 entry with its own single-day token
        rev30 = self.json_cli("review", "--date", "2026-06-30", "--at", "2026-06-30T19:00:00")
        self.json_cli("approve", "--all", "--date", "2026-06-30",
                      "--review-token", rev30["details"]["review_token"],
                      "--at", "2026-06-30T19:00:00")
        # Now get a fresh range token covering the whole month
        review_range = self.json_cli(
            "review", "--date", "2026-06-01", "--to", "2026-06-30",
            "--at", "2026-06-30T20:00:00",
        )
        range_token = review_range["details"]["review_token"]
        out = self.workdir / "out.csv"
        result = self.json_cli(
            "export",
            "--date", "2026-06-01",
            "--to", "2026-06-30",
            "--output", str(out),
            "--review-token", range_token,
            "--at", "2026-06-30T20:00:00",
        )
        self.assertEqual(result["status"], "exported")
        self.assertEqual(result["details"]["exported_count"], 2)
        self.assertIn("end_date", result["details"])
        self.assertEqual(result["details"]["end_date"], "2026-06-30")
        rows = list(csv.DictReader(out.read_text().splitlines()))
        self.assertEqual(len(rows), 2)

    def test_export_to_single_day_token_rejected_as_stale_for_range(self) -> None:
        self._seed_db_with_range_entries()
        # Approve the first-day entry (this consumes its original token)
        first_review = self.json_cli(
            "review", "--date", "2026-06-01", "--at", "2026-06-01T12:00:00",
        )
        self.json_cli("approve", "--all", "--date", "2026-06-01",
                      "--review-token", first_review["details"]["review_token"],
                      "--at", "2026-06-01T12:00:00")
        # Mint a FRESH single-day token after the approval, so it is genuinely
        # valid for the plain single day right now.
        fresh_review = self.json_cli(
            "review", "--date", "2026-06-01", "--at", "2026-06-01T13:00:00",
        )
        fresh_token = fresh_review["details"]["review_token"]
        # That currently-valid single-day token must still be rejected when the
        # export uses --to: the range covers a different span, so its token is
        # different. Pin the range-scoped wording at the CLI boundary.
        out = self.workdir / "out.csv"
        result = self.run_cli(
            "export",
            "--date", "2026-06-01",
            "--to", "2026-06-30",
            "--output", str(out),
            "--review-token", fresh_token,
            "--at", "2026-06-30T12:00:00",
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("stale", result.stdout.lower())
        self.assertIn("date range", result.stdout)
        # Sanity: the same token still succeeds for the plain single day (the
        # failed range export mutated nothing), proving the rejection above came
        # from the range wiring and not from the token being stale everywhere.
        single_out = self.workdir / "single.csv"
        single_result = self.json_cli(
            "export",
            "--date", "2026-06-01",
            "--output", str(single_out),
            "--review-token", fresh_token,
            "--at", "2026-06-01T14:00:00",
        )
        self.assertEqual(single_result["status"], "exported")

    # ------------------------------------------------------------------
    # html + --to raises a plain-language error
    # ------------------------------------------------------------------

    def test_review_html_with_to_raises_plain_error(self) -> None:
        self._seed_db_with_range_entries()
        result = self.run_cli(
            "review", "--date", "2026-06-01", "--to", "2026-06-30",
            "--format", "html",
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("not supported with --format html", result.stdout)

    def test_review_html_with_to_equal_to_date_collapses_to_single_day(self) -> None:
        # --to equal to --date collapses to the single-day path everywhere
        # downstream, so the html guard must not fire.
        self._seed_db_with_range_entries()
        html_path = self.workdir / "review.html"
        result = self.json_cli(
            "review", "--date", "2026-06-01", "--to", "2026-06-01",
            "--format", "html", "--output", str(html_path),
        )
        self.assertEqual(result["status"], "review-ready")
        self.assertTrue(html_path.exists())

    # ------------------------------------------------------------------
    # config --operator-code / --clear-operator-code
    # ------------------------------------------------------------------

    def test_config_operator_code_stores_and_shows_in_readout(self) -> None:
        self.json_cli("init")
        self.json_cli("config", "--operator-code", "AVD", "--confirm")
        readout = self.json_cli("config")
        settings = readout["details"]["settings"]
        self.assertEqual(settings["operator_code"], "AVD")

    def test_config_clear_operator_code_removes_it(self) -> None:
        self.json_cli("init")
        self.json_cli("config", "--operator-code", "AVD", "--confirm")
        self.json_cli("config", "--clear-operator-code", "--confirm")
        readout = self.json_cli("config")
        settings = readout["details"]["settings"]
        self.assertNotIn("operator_code", settings)

    def test_config_operator_code_with_another_flag_rejected(self) -> None:
        self.json_cli("init")
        result = self.run_cli(
            "config", "--operator-code", "AVD",
            "--rounding-rule", "exact", "--confirm",
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("one", result.stdout.lower())

    def test_config_clear_operator_code_with_another_flag_rejected(self) -> None:
        self.json_cli("init")
        result = self.run_cli(
            "config", "--clear-operator-code",
            "--rounding-rule", "exact", "--confirm",
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("one", result.stdout.lower())

    # ------------------------------------------------------------------
    # Integration: operator_code shapes default export filename
    # ------------------------------------------------------------------

    def test_export_default_filename_uses_operator_code(self) -> None:
        """Set operator_code via CLI config, approve + export without --output,
        assert the reported output path ends with quickbooks-time-AVD-<date>.csv."""
        self.json_cli("init", "--at", "2026-06-01T08:00:00")
        roster = self.workdir / "roster.csv"
        roster.write_text("display_name,aliases,default_billable\nAcme Co,,yes\n")
        self.json_cli("import-clients", "--file", str(roster), "--mode", "merge")
        self.json_cli(
            "add-missing", "--client", "Acme Co", "--task", "billable work",
            "--start", "2026-06-01T09:00:00", "--end", "2026-06-01T10:00:00",
        )
        # Set operator code
        self.json_cli("config", "--operator-code", "AVD", "--confirm")
        # Approve
        review = self.json_cli("review", "--date", "2026-06-01", "--at", "2026-06-01T12:00:00")
        self.json_cli("approve", "--all", "--date", "2026-06-01",
                      "--review-token", review["details"]["review_token"],
                      "--at", "2026-06-01T12:00:00")
        # Export without --output
        review2 = self.json_cli("review", "--date", "2026-06-01", "--at", "2026-06-01T13:00:00")
        export = self.json_cli(
            "export", "--date", "2026-06-01",
            "--review-token", review2["details"]["review_token"],
            "--at", "2026-06-01T13:00:00",
        )
        self.assertEqual(export["status"], "exported")
        output_path = export["details"]["output"]
        self.assertTrue(
            output_path.endswith("quickbooks-time-AVD-2026-06-01.csv"),
            f"Expected filename ending 'quickbooks-time-AVD-2026-06-01.csv', got: {output_path}",
        )


if __name__ == "__main__":
    unittest.main()
