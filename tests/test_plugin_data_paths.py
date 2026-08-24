from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from dataclasses import asdict
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import timeassist
from timeassist import cli
from timeassist import mcp_server

# Legacy CSV seeding for path/security tests; production roster is live Supabase.
os.environ.setdefault("TIMEASSIST_ALLOW_LOCAL_ROSTER", "1")


class PluginMcpConfigTests(unittest.TestCase):
    def test_release_version_surfaces_match_manifest_semver(self) -> None:
        manifest = json.loads((ROOT / "plugin" / "timeassist" / ".claude-plugin" / "plugin.json").read_text())

        major, minor, patch = manifest["version"].split(".")
        self.assertTrue(all(part.isdigit() for part in (major, minor, patch)))
        self.assertEqual(manifest["version"], timeassist.__version__)
        self.assertEqual(manifest["version"], mcp_server.SERVER_VERSION)

        parser = cli.build_parser()
        stdout = StringIO()
        with redirect_stdout(stdout), self.assertRaises(SystemExit) as caught:
            parser.parse_args(["--version"])
        self.assertEqual(caught.exception.code, 0)
        self.assertEqual(stdout.getvalue().strip(), f"timeassist {manifest['version']}")

    def test_marketplace_has_release_description_for_strict_validation(self) -> None:
        marketplace = json.loads((ROOT / ".claude-plugin" / "marketplace.json").read_text())
        self.assertIn("description", marketplace)
        self.assertGreaterEqual(len(marketplace["description"].strip()), 20)

    def test_release_workflow_runs_strict_plugin_validation(self) -> None:
        workflow = (ROOT / ".github" / "workflows" / "windows-build.yml").read_text()
        self.assertIn("claude plugin validate --strict ./plugin/timeassist", workflow)
        self.assertIn("claude plugin validate --strict ./.claude-plugin/marketplace.json", workflow)

    def test_mcp_config_pins_state_to_claude_plugin_data(self) -> None:
        config = json.loads((ROOT / "plugin" / "timeassist" / ".mcp.json").read_text())
        server = config["mcpServers"]["timeassist"]

        self.assertEqual(server["command"], "${CLAUDE_PLUGIN_ROOT}/bin/timeassist.exe")
        self.assertEqual(server["args"], ["--db", "${CLAUDE_PLUGIN_DATA}/timeassist.sqlite", "mcp"])
        self.assertEqual(server["cwd"], "${CLAUDE_PLUGIN_DATA}")

    def test_plugin_skill_documents_server_side_gates(self) -> None:
        skill = (ROOT / "plugin" / "timeassist" / "skills" / "billable-time-assistant" / "SKILL.md").read_text()

        for required_text in [
            "review_token",
            "list_clients",
            "Supabase",
            "Unassigned",
            "confirm=true",
            "run `review` first",
            "paths must stay under `${CLAUDE_PLUGIN_DATA}`",
            "user_export_dir",
            "Documents/TimeAssist Exports",
            "do not manually recreate",
            "switch immediately",
            "clarify_active",
            "needs_info",
            # Timmy persona + Task 9 behavior contracts
            "Timmy",
            "Never block or refuse approval over missing notes",
            "Surface `needs_info` before approval",
            "must match the",
            "administrative",
            "prefer the non-management near-twin",
            "skipped_locked_count",
            # free-form rounding increments (any 1-60 minutes)
            "nearest_<N>_minutes",
            # strict roster policy + one-call roster add (issue #39 item 1 = C)
            "strict_roster",
            "add_client",
            # billing-sheet alignment: range review/export + operator_code (issue #34)
            "end_date",
            "range `review_token`",
            "never loop per-day exports",
            "Approval stays per-day",
            "one day at a time",
            "operator_code",
            "set once during setup",
        ]:
            self.assertIn(required_text, skill)


class PluginArtifactPathTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.data_dir = self.base / "plugin-data"
        self.launch_dir = self.base / "launch-dir"
        self.profile = self.base / "profile"
        self._old_userprofile = os.environ.get("USERPROFILE")
        os.environ["USERPROFILE"] = str(self.profile)
        self.addCleanup(self._restore_userprofile)
        self.data_dir.mkdir()
        self.launch_dir.mkdir()
        self.db = self.data_dir / "timeassist.sqlite"

    def _restore_userprofile(self) -> None:
        if self._old_userprofile is None:
            os.environ.pop("USERPROFILE", None)
        else:
            os.environ["USERPROFILE"] = self._old_userprofile

    def call(self, name: str, arguments: dict, msg_id: int = 1) -> dict:
        msg = {"jsonrpc": "2.0", "id": msg_id, "method": "tools/call", "params": {"name": name, "arguments": arguments}}
        response = mcp_server.handle_message(msg, self.db)
        self.assertIsNotNone(response)
        return response["result"]

    def payload(self, name: str, arguments: dict) -> dict:
        result = self.call(name, arguments)
        self.assertNotIn("isError", result, f"unexpected tool error: {result}")
        return json.loads(result["content"][0]["text"])

    def cli_payload(self, *args: str) -> dict:
        parser = cli.build_parser()
        namespace = parser.parse_args(["--db", str(self.db), *args])
        result = cli.run_command(namespace)
        payload = asdict(result)
        self.assertTrue(payload["ok"], f"unexpected CLI error: {payload}")
        return payload

    def seed_approved_entry(self) -> None:
        self.payload("init_state", {"at": "2026-05-28T08:55:00"})
        # Register the client so the capture resolves instead of going
        # needs_info (the #34 roster gate) and can be approved below. The roster
        # CSV lives under the plugin data dir so the MCP input-path guard allows
        # it; merge mode needs no confirm_replace.
        roster = self.data_dir / "roster-seed.csv"
        roster.write_text("display_name,aliases,default_billable\nClient A,,yes\n")
        self.payload("import_clients", {"path": str(roster), "mode": "merge"})
        self.payload(
            "add_missing",
            {
                "client": "Client A",
                "task": "monthly cleanup",
                "start": "2026-05-28T09:00:00",
                "end": "2026-05-28T09:30:00",
            },
        )
        review = self.payload("review", {"date": "2026-05-28"})
        self.payload("approve", {"entry_id": 1, "review_token": review.get("review_token"), "at": "2026-05-28T10:00:00"})

    def run_from_launch_dir(self, fn):
        original = Path.cwd()
        os.chdir(self.launch_dir)
        try:
            return fn()
        finally:
            os.chdir(original)

    def test_mcp_default_export_uses_database_directory_and_reports_full_path(self) -> None:
        self.seed_approved_entry()
        review = self.payload("review", {"date": "2026-05-28"})

        export = self.run_from_launch_dir(lambda: self.payload("export", {"date": "2026-05-28", "review_token": review["review_token"]}))

        expected = (self.data_dir / "exports" / "quickbooks-time-2026-05-28.csv").resolve()
        self.assertEqual(export["official_csv"], str(expected))
        self.assertTrue(expected.exists())
        self.assertFalse((self.launch_dir / "quickbooks-time-2026-05-28.csv").exists())
        self.assertFalse((self.data_dir / "quickbooks-time-2026-05-28.csv").exists())

    def test_mcp_bare_export_filename_is_routed_to_exports_directory(self) -> None:
        self.seed_approved_entry()
        review = self.payload("review", {"date": "2026-05-28"})

        result = self.call("export", {"date": "2026-05-28", "output": "qb.csv", "review_token": review["review_token"]})

        self.assertNotIn("isError", result, f"unexpected tool error: {result}")
        payload = json.loads(result["content"][0]["text"])
        expected = (self.data_dir / "exports" / "qb.csv").resolve()
        self.assertEqual(payload["official_csv"], str(expected))
        self.assertTrue(expected.exists())
        self.assertFalse((self.data_dir / "qb.csv").exists())

    def test_explicit_relative_export_subdir_stays_in_database_directory(self) -> None:
        self.seed_approved_entry()
        review = self.payload("review", {"date": "2026-05-28"})

        export = self.run_from_launch_dir(lambda: self.payload("export", {"date": "2026-05-28", "output": "exports/qb.csv", "review_token": review["review_token"]}))

        expected = (self.data_dir / "exports" / "qb.csv").resolve()
        self.assertEqual(export["official_csv"], str(expected))
        self.assertTrue(expected.exists())
        self.assertFalse((self.launch_dir / "exports" / "qb.csv").exists())

    def test_mcp_rejects_parent_traversal_output(self) -> None:
        self.seed_approved_entry()
        review = self.payload("review", {"date": "2026-05-28"})

        result = self.run_from_launch_dir(lambda: self.call("export", {"date": "2026-05-28", "output": "../escape.csv", "review_token": review["review_token"]}))

        self.assertTrue(result.get("isError"))
        self.assertIn("artifact path must be under", json.loads(result["content"][0]["text"])["error"])
        self.assertFalse((self.base / "escape.csv").exists())

    def test_mcp_rejects_absolute_output_outside_database_directory(self) -> None:
        self.seed_approved_entry()
        review = self.payload("review", {"date": "2026-05-28"})
        outside = self.base / "outside.csv"

        result = self.call("export", {"date": "2026-05-28", "output": str(outside), "review_token": review["review_token"]})

        self.assertTrue(result.get("isError"))
        self.assertIn("artifact path must be under", json.loads(result["content"][0]["text"])["error"])
        self.assertFalse(outside.exists())

    def test_mcp_user_export_dir_can_copy_outside_data_dir_but_output_arg_stays_restricted(self) -> None:
        self.seed_approved_entry()
        review = self.payload("review", {"date": "2026-05-28"})
        user_dir = self.base / "operator-folder"
        outside_output = self.base / "smuggled.csv"

        self.payload("config", {"user_export_dir": str(user_dir), "confirm": True})
        rejected = self.call("export", {"date": "2026-05-28", "output": str(outside_output), "review_token": review["review_token"]})
        self.assertTrue(rejected.get("isError"))
        self.assertIn("artifact path must be under", json.loads(rejected["content"][0]["text"])["error"])
        self.assertFalse(outside_output.exists())

        exported = self.payload("export", {"date": "2026-05-28", "output": "qb.csv", "review_token": review["review_token"]})
        official = self.data_dir / "exports" / "qb.csv"
        user_copy = user_dir / "qb.csv"
        self.assertEqual(exported["official_csv"], str(official.resolve()))
        self.assertEqual(exported["csv"], str(user_copy.resolve()))
        self.assertNotIn("copy_error", exported)  # successful copy: no error key
        self.assertEqual(user_copy.read_bytes(), official.read_bytes())

    def test_mcp_rejects_data_directory_as_output_without_leaking_temp_file(self) -> None:
        self.seed_approved_entry()
        review = self.payload("review", {"date": "2026-05-28"})

        result = self.call("export", {"date": "2026-05-28", "output": ".", "review_token": review["review_token"]})

        self.assertTrue(result.get("isError"))
        self.assertIn("file path", json.loads(result["content"][0]["text"])["error"])
        self.assertFalse((self.base / ".plugin-data.tmp").exists())

    def test_mcp_rejects_existing_directory_output_without_writing_temp_file(self) -> None:
        self.seed_approved_entry()
        review = self.payload("review", {"date": "2026-05-28"})
        output_dir = self.data_dir / "exports"
        output_dir.mkdir()

        result = self.call("export", {"date": "2026-05-28", "output": str(output_dir), "review_token": review["review_token"]})

        self.assertTrue(result.get("isError"))
        self.assertIn("file path", json.loads(result["content"][0]["text"])["error"])
        self.assertFalse((self.data_dir / ".exports.tmp").exists())

    def test_mcp_rejects_export_to_reserved_database_path(self) -> None:
        self.seed_approved_entry()
        review = self.payload("review", {"date": "2026-05-28"})

        result = self.call("export", {"date": "2026-05-28", "output": str(self.db), "review_token": review["review_token"]})

        self.assertTrue(result.get("isError"))
        self.assertIn("artifact path must be under", json.loads(result["content"][0]["text"])["error"])
        self.assertTrue(self.db.exists())

    def test_mcp_rejects_export_to_backups_tree(self) -> None:
        self.seed_approved_entry()
        review = self.payload("review", {"date": "2026-05-28"})

        result = self.call("export", {"date": "2026-05-28", "output": "backups/qb.csv", "review_token": review["review_token"]})

        self.assertTrue(result.get("isError"))
        self.assertIn("artifact path must be under", json.loads(result["content"][0]["text"])["error"])
        self.assertFalse((self.data_dir / "backups" / "qb.csv").exists())

    def test_mcp_rejects_symlinked_artifact_root_back_to_data_dir(self) -> None:
        self.seed_approved_entry()
        review = self.payload("review", {"date": "2026-05-28"})
        (self.data_dir / "exports").symlink_to(self.data_dir, target_is_directory=True)

        result = self.call("export", {"date": "2026-05-28", "output": "timeassist.sqlite", "review_token": review["review_token"]})

        self.assertTrue(result.get("isError"))
        self.assertIn("artifact directory must not be a symlink", json.loads(result["content"][0]["text"])["error"])
        self.assertGreater(self.db.stat().st_size, 0)

    def test_mcp_rejects_symlinked_artifact_root_to_outside_directory(self) -> None:
        self.seed_approved_entry()
        review = self.payload("review", {"date": "2026-05-28"})
        outside = self.base / "outside-artifacts"
        outside.mkdir()
        (self.data_dir / "exports").symlink_to(outside, target_is_directory=True)

        result = self.call("export", {"date": "2026-05-28", "output": "qb.csv", "review_token": review["review_token"]})

        self.assertTrue(result.get("isError"))
        self.assertIn("artifact directory must not be a symlink", json.loads(result["content"][0]["text"])["error"])
        self.assertFalse((outside / "qb.csv").exists())

    def test_mcp_rejects_dangling_symlinked_artifact_root(self) -> None:
        self.seed_approved_entry()
        review = self.payload("review", {"date": "2026-05-28"})
        outside_missing = self.base / "outside-missing"
        (self.data_dir / "exports").symlink_to(outside_missing, target_is_directory=True)

        result = self.call("export", {"date": "2026-05-28", "output": "qb.csv", "review_token": review["review_token"]})

        self.assertTrue(result.get("isError"))
        self.assertIn("artifact directory must not be a symlink", json.loads(result["content"][0]["text"])["error"])
        self.assertFalse(outside_missing.exists())

    def test_direct_cli_default_export_stays_next_to_database_not_launch_cwd(self) -> None:
        self.seed_approved_entry()
        review = self.payload("review", {"date": "2026-05-28"})

        export = self.run_from_launch_dir(lambda: self.cli_payload("export", "--date", "2026-05-28", "--review-token", review["review_token"]))

        expected = (self.data_dir / "quickbooks-time-2026-05-28.csv").resolve()
        self.assertEqual(export["details"]["output"], str(expected))
        self.assertTrue(expected.exists())
        self.assertFalse((self.launch_dir / "exports" / "quickbooks-time-2026-05-28.csv").exists())

    def test_cli_config_sets_lists_and_clears_user_export_dir_with_confirmation(self) -> None:
        user_dir = self.base / "operator-folder"

        parser = cli.build_parser()
        namespace = parser.parse_args(["--db", str(self.db), "config", "--user-export-dir", str(user_dir)])
        with self.assertRaises(ValueError) as missing_confirm:
            cli.run_command(namespace)
        self.assertIn("confirm", str(missing_confirm.exception))

        updated = self.cli_payload("config", "--user-export-dir", str(user_dir), "--confirm")
        self.assertEqual(updated["details"]["key"], "user_export_dir")
        self.assertEqual(updated["details"]["value"], str(user_dir.resolve()))

        listed = self.cli_payload("config")
        self.assertEqual(listed["details"]["settings"]["user_export_dir"], str(user_dir.resolve()))

        cleared = self.cli_payload("config", "--clear-user-export-dir", "--confirm")
        self.assertEqual(cleared["details"]["key"], "user_export_dir")
        self.assertIsNone(cleared["details"]["value"])
        self.assertNotIn("user_export_dir", self.cli_payload("config")["details"]["settings"])

    def test_mcp_rejects_client_import_outside_database_directory(self) -> None:
        outside = self.base / "outside-clients.csv"
        outside.write_text("client_key,display_name,aliases,default_billable\nacme,Acme Co,,yes\n")

        result = self.call("import_clients", {"path": str(outside), "confirm_replace": True})

        self.assertTrue(result.get("isError"))
        self.assertIn("outside TimeAssist data directory", json.loads(result["content"][0]["text"])["error"])

    def test_mcp_default_sanitized_packet_uses_database_directory_and_reports_full_path(self) -> None:
        self.seed_approved_entry()

        packet = self.run_from_launch_dir(lambda: self.payload("sanitize_packet", {"date": "2026-05-28"}))

        expected = (self.data_dir / "packets" / "sanitized-collaboration-packet-2026-05-28.md").resolve()
        self.assertEqual(packet["output"], str(expected))
        self.assertTrue(expected.exists())
        self.assertFalse((self.launch_dir / "sanitized-collaboration-packet-2026-05-28.md").exists())

    def test_mcp_relative_review_html_output_uses_database_directory_and_reports_full_path(self) -> None:
        self.seed_approved_entry()

        review = self.run_from_launch_dir(lambda: self.payload("review", {"date": "2026-05-28", "html_output": "review.html"}))

        expected = (self.data_dir / "reviews" / "review.html").resolve()
        self.assertEqual(review["html_output"], str(expected))
        self.assertTrue(expected.exists())
        self.assertFalse((self.launch_dir / "review.html").exists())


if __name__ == "__main__":
    unittest.main()
