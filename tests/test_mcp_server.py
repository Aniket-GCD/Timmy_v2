from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from timeassist import mcp_server


class McpServerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.workdir = Path(self.tmp.name)
        self.db = self.workdir / "timeassist.sqlite"

    def call(self, name: str, arguments: dict, msg_id: int = 1) -> dict:
        msg = {"jsonrpc": "2.0", "id": msg_id, "method": "tools/call", "params": {"name": name, "arguments": arguments}}
        response = mcp_server.handle_message(msg, self.db)
        self.assertIsNotNone(response)
        return response["result"]

    def payload(self, name: str, arguments: dict) -> dict:
        result = self.call(name, arguments)
        self.assertNotIn("isError", result, f"unexpected tool error: {result}")
        return json.loads(result["content"][0]["text"])

    def token(self, date: str = "2026-05-28") -> str:
        return self.payload("review", {"date": date})["review_token"]

    def seed_roster(self, *names: str) -> None:
        # Register synthetic clients so captures resolve instead of going
        # needs_info (the #34 roster gate). merge mode keeps the seeded admin
        # clients and needs no confirm_replace; the MCP arg is `path`.
        path = Path(self.tmp.name) / "roster-seed.csv"
        path.write_text(
            "display_name,aliases,default_billable\n"
            + "".join(f"{name},,yes\n" for name in names)
        )
        self.payload("import_clients", {"path": str(path), "mode": "merge"})

    def test_initialize_echoes_protocol_and_advertises_server(self) -> None:
        msg = {"jsonrpc": "2.0", "id": 0, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}}
        result = mcp_server.handle_message(msg, self.db)["result"]
        self.assertEqual(result["protocolVersion"], "2025-06-18")
        self.assertEqual(result["serverInfo"]["name"], "timeassist")
        self.assertIn("tools", result["capabilities"])

    def test_initialized_notification_has_no_response(self) -> None:
        msg = {"jsonrpc": "2.0", "method": "notifications/initialized"}
        self.assertIsNone(mcp_server.handle_message(msg, self.db))

    def test_tools_list_exposes_all_actions(self) -> None:
        msg = {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
        tools = mcp_server.handle_message(msg, self.db)["result"]["tools"]
        names = {tool["name"] for tool in tools}
        self.assertEqual(
            names,
            {"init_state", "start", "switch", "clarify_active", "end", "add_missing", "edit", "review", "approve", "approve_all", "unapprove", "export", "sanitize_packet", "config", "reround", "import_clients", "add_client", "list_clients", "list_job_codes", "refresh_clients", "submit", "update_submitted", "draft_reception_email", "cancel", "checkin_status", "checkin", "snooze_checkin", "status", "cleanup", "discard_entry"},
        )
        switch_tool = next(tool for tool in tools if tool["name"] == "switch")
        minutes_ago_schema = switch_tool["inputSchema"]["properties"]["minutes_ago"]
        self.assertEqual(minutes_ago_schema["minimum"], 1)

    def test_capture_tools_expose_optional_job_type(self) -> None:
        msg = {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
        tools = mcp_server.handle_message(msg, self.db)["result"]["tools"]
        by_name = {tool["name"]: tool for tool in tools}
        for name in ("start", "switch", "add_missing", "edit", "clarify_active"):
            schema = by_name[name]["inputSchema"]
            self.assertIn("job_type", schema["properties"], f"{name} missing job_type property")
            self.assertEqual(schema["properties"]["job_type"]["type"], "string")
            self.assertNotIn("job_type", schema.get("required", []), f"{name} must not require job_type")

    def test_start_round_trips_job_type(self) -> None:
        self.payload("init_state", {"at": "2026-05-28T08:55:00"})
        session = self.payload("start", {
            "client": "Client A", "task": "monthly cleanup", "job_type": "Tax", "at": "2026-05-28T09:00:00",
        })
        self.assertEqual(session["job_type"], "Tax")

    def test_edit_round_trips_job_type(self) -> None:
        self.payload("init_state", {"at": "2026-05-28T08:55:00"})
        self.payload("add_missing", {
            "client": "Client A", "task": "cleanup", "start": "2026-05-28T10:00:00", "end": "2026-05-28T10:24:00",
        })
        edited = self.payload("edit", {"entry_id": 1, "job_type": "Administrative"})
        self.assertEqual(edited["job_type"], "Administrative")

    def test_switch_minutes_ago_tool_uses_relative_correction_time(self) -> None:
        self.payload("init_state", {"at": "2026-05-28T08:55:00"})
        self.payload("start", {"client": "Client A", "task": "monthly cleanup", "billable": "yes", "at": "2026-05-28T09:00:00"})

        switched = self.payload("switch", {
            "client": "Client B",
            "task": "tax question",
            "at": "2026-05-28T10:00:00",
            "minutes_ago": 20,
        })

        self.assertEqual(switched["closed_entry"]["end"], "2026-05-28T09:40:00")
        self.assertEqual(switched["closed_entry"]["minutes"], 40)
        self.assertEqual(switched["new_session"]["started_at"], "2026-05-28T09:40:00")

    def test_clarify_active_tool_resolves_pending_switch_metadata(self) -> None:
        self.payload("init_state", {"at": "2026-05-28T08:55:00"})
        self.payload("start", {"client": "Client A", "task": "monthly cleanup", "billable": "yes", "at": "2026-05-28T09:00:00"})
        switched = self.payload("switch", {"client": "Henderson", "task": "tax return", "at": "2026-05-28T09:30:00"})
        self.assertEqual(switched["new_session"]["needs_info"], "client 'Henderson' is not in the roster")

        clarified = self.payload(
            "clarify_active",
            {
                "client": "Henderson LLC",
                "task": "tax return review",
                "billable": "yes",
                "at": "2026-05-28T09:35:00",
            },
        )

        self.assertNotIn("needs_info", clarified)  # resolved: no longer flagged
        self.assertEqual(clarified["client"], "Henderson LLC")
        self.assertEqual(clarified["started_at"], "2026-05-28T09:30:00")

    def test_switch_minutes_ago_tool_rejects_zero_values(self) -> None:
        self.payload("init_state", {"at": "2026-05-28T08:55:00"})
        self.payload("start", {"client": "Client A", "task": "monthly cleanup", "billable": "yes", "at": "2026-05-28T09:00:00"})

        result = self.call("switch", {
            "client": "Client B",
            "task": "tax question",
            "at": "2026-05-28T10:00:00",
            "minutes_ago": 0,
        })

        self.assertTrue(result.get("isError"))
        self.assertIn("minutes_ago must be greater than zero", json.loads(result["content"][0]["text"])["error"])

    def test_full_capture_review_approve_export_flow(self) -> None:
        self.payload("init_state", {"at": "2026-05-28T08:55:00"})
        self.seed_roster("Client A")  # Client B stays off-roster -> needs_info

        self.payload("start", {"client": "Client A", "task": "monthly cleanup", "billable": "yes", "at": "2026-05-28T09:00:00"})
        switched = self.payload("switch", {"client": "Client B", "task": "tax question", "at": "2026-05-28T09:24:00"})
        self.assertEqual(switched["closed_entry"]["minutes"], 24)

        ended = self.payload("end", {"at": "2026-05-28T09:42:00"})
        self.assertEqual(ended["minutes"], 18)

        added = self.payload("add_missing", {
            "client": "Client A", "task": "call notes", "start": "2026-05-28T10:00:00", "end": "2026-05-28T10:18:00",
        })
        self.assertEqual(added["minutes"], 18)

        review = self.payload("review", {"date": "2026-05-28"})
        self.assertEqual(review["totals"]["draft_minutes"], 42)
        self.assertEqual(review["totals"]["needs_info_minutes"], 18)
        self.assertEqual(review["skipped_needs_info_count"], 1)
        self.assertEqual([e["status"] for e in review["entries"]], ["draft", "needs_info", "draft"])
        self.assertEqual(review["entries"][1]["needs_info"], "client 'Client B' is not in the roster")

        resolved = self.payload("edit", {"entry_id": 2, "client": "Client B", "task": "tax question", "billable": "yes", "at": "2026-05-28T10:44:00"})
        self.assertEqual(resolved["status"], "draft")
        self.assertNotIn("needs_info", resolved)  # resolved: no longer flagged

        review = self.payload("review", {"date": "2026-05-28"})
        self.assertEqual(review["totals"]["draft_minutes"], 60)
        self.assertEqual([e["status"] for e in review["entries"]], ["draft", "draft", "draft"])

        self.payload("approve", {"entry_id": 1, "review_token": review["review_token"], "at": "2026-05-28T10:45:00"})
        review = self.payload("review", {"date": "2026-05-28"})
        self.payload("approve", {"entry_id": 2, "review_token": review["review_token"], "at": "2026-05-28T10:46:00"})

        export_path = self.workdir / "exports" / "qb.csv"
        review = self.payload("review", {"date": "2026-05-28"})
        export = self.payload("export", {"date": "2026-05-28", "output": str(export_path), "review_token": review["review_token"], "at": "2026-05-28T10:50:00"})
        self.assertEqual(export["exported_count"], 2)
        self.assertTrue(export_path.exists())

        after = self.payload("review", {"date": "2026-05-28"})
        statuses = {e["entry_id"]: e["status"] for e in after["entries"]}
        self.assertEqual(statuses, {1: "exported", 2: "exported", 3: "draft"})

    def test_operator_confirms_unknown_client_in_one_edit(self) -> None:
        self.payload("init_state", {"at": "2026-05-28T08:55:00"})
        self.payload("start", {"client": "Client A", "task": "test1", "at": "2026-05-28T09:00:00"})
        self.payload("switch", {"client": "acme", "task": "test2", "at": "2026-05-28T09:10:00"})
        entry = self.payload("end", {"at": "2026-05-28T09:20:00"})
        review = self.payload("review", {"date": "2026-05-28"})
        rejected = self.call("approve", {"entry_id": entry["entry_id"], "review_token": review["review_token"]})
        self.assertTrue(rejected.get("isError"))
        confirmed = self.payload("edit", {"entry_id": entry["entry_id"], "client": "acme"})
        self.assertEqual(confirmed["status"], "draft")
        self.assertNotIn("needs_info", confirmed)
        review = self.payload("review", {"date": "2026-05-28"})
        approved = self.payload("approve", {"entry_id": entry["entry_id"], "review_token": review["review_token"]})
        self.assertEqual(approved["status"], "approved")

    def test_approve_all_approves_every_draft_for_the_date(self) -> None:
        self.payload("init_state", {"at": "2026-05-28T08:55:00"})
        self.seed_roster("Client 0", "Client 1", "Client 2")
        for i in range(3):
            self.payload("add_missing", {
                "client": f"Client {i}", "task": "work",
                "start": f"2026-05-28T1{i}:00:00", "end": f"2026-05-28T1{i}:24:00",
            })
        review = self.payload("review", {"date": "2026-05-28"})
        result = self.payload("approve_all", {"date": "2026-05-28", "review_token": review["review_token"], "at": "2026-05-28T17:00:00"})
        self.assertEqual(result["approved_count"], 3)
        after = self.payload("review", {"date": "2026-05-28"})
        self.assertEqual({e["status"] for e in after["entries"]}, {"approved"})

    def test_approve_all_requires_current_review_token(self) -> None:
        self.payload("init_state", {"at": "2026-05-28T08:55:00"})
        self.payload("add_missing", {
            "client": "Client A", "task": "work", "start": "2026-05-28T10:00:00", "end": "2026-05-28T10:24:00",
        })
        result = self.call("approve_all", {"date": "2026-05-28"})
        self.assertTrue(result.get("isError"))
        self.assertIn("review_token", json.loads(result["content"][0]["text"])["error"])

    def test_approve_requires_current_review_token(self) -> None:
        self.payload("init_state", {"at": "2026-05-28T08:55:00"})
        self.payload("add_missing", {
            "client": "Client A", "task": "work", "start": "2026-05-28T10:00:00", "end": "2026-05-28T10:24:00",
        })
        result = self.call("approve", {"entry_id": 1})
        self.assertTrue(result.get("isError"))
        self.assertIn("review_token", json.loads(result["content"][0]["text"])["error"])

    def test_approve_rejects_token_stale_after_same_timestamp_edit(self) -> None:
        self.payload("init_state", {"at": "2026-05-28T08:55:00"})
        self.payload("add_missing", {
            "client": "Client A", "task": "original task", "start": "2026-05-28T10:00:00", "end": "2026-05-28T10:24:00",
        })
        review = self.payload("review", {"date": "2026-05-28"})

        # Hold updated_at at the pre-edit value (add_missing stamps it with the
        # entry's end time) so the token goes stale from content alone.
        self.payload("edit", {"entry_id": 1, "task": "changed after review", "at": "2026-05-28T10:24:00"})
        result = self.call("approve", {"entry_id": 1, "review_token": review["review_token"]})

        self.assertTrue(result.get("isError"))
        self.assertIn("stale", json.loads(result["content"][0]["text"])["error"])

    def test_export_requires_current_review_token(self) -> None:
        self.payload("init_state", {"at": "2026-05-28T08:55:00"})
        self.seed_roster("Client A")
        self.payload("add_missing", {
            "client": "Client A", "task": "work", "start": "2026-05-28T10:00:00", "end": "2026-05-28T10:24:00",
        })
        review = self.payload("review", {"date": "2026-05-28"})
        self.payload("approve", {"entry_id": 1, "review_token": review["review_token"]})
        result = self.call("export", {"date": "2026-05-28", "output": "qb.csv"})
        self.assertTrue(result.get("isError"))
        self.assertIn("review_token", json.loads(result["content"][0]["text"])["error"])

    def test_config_change_requires_confirmation(self) -> None:
        self.payload("init_state", {"at": "2026-05-28T08:55:00"})
        result = self.call("config", {"rounding_rule": "up_15_minutes"})
        self.assertTrue(result.get("isError"))
        self.assertIn("confirm", json.loads(result["content"][0]["text"])["error"])

    def test_init_state_surfaces_first_run_export_folder_survey(self) -> None:
        initialized = self.payload("init_state", {"at": "2026-05-28T08:55:00"})

        export_folder = initialized["export_folder"]
        self.assertTrue(export_folder["survey_required"])
        self.assertEqual(export_folder["preference"], "default_unconfirmed")
        self.assertEqual(export_folder["user_export_dir"], export_folder["default_user_export_dir"])
        self.assertEqual(Path(export_folder["user_export_dir"]).name, "TimeAssist Exports")
        self.assertIn("Documents", export_folder["prompt"])

    def test_config_can_confirm_default_export_folder_survey(self) -> None:
        self.payload("init_state", {"at": "2026-05-28T08:55:00"})

        missing_confirm = self.call("config", {"confirm_default_user_export_dir": True})
        self.assertTrue(missing_confirm.get("isError"))
        self.assertIn("confirm", json.loads(missing_confirm["content"][0]["text"])["error"])

        confirmed = self.payload("config", {"confirm_default_user_export_dir": True, "confirm": True})
        export_folder = confirmed["export_folder"]
        self.assertFalse(export_folder["survey_required"])
        self.assertEqual(export_folder["preference"], "default_confirmed")
        self.assertEqual(export_folder["user_export_dir"], export_folder["default_user_export_dir"])
        self.assertIsNotNone(export_folder["confirmed_at"])

        initialized_again = self.payload("init_state", {"at": "2026-05-28T08:56:00"})
        self.assertFalse(initialized_again["export_folder"]["survey_required"])

    def test_custom_export_dir_satisfies_first_run_export_folder_survey(self) -> None:
        self.payload("init_state", {"at": "2026-05-28T08:55:00"})
        custom_dir = self.workdir / "client exports"

        configured = self.payload("config", {"user_export_dir": str(custom_dir), "confirm": True})

        export_folder = configured["export_folder"]
        self.assertFalse(export_folder["survey_required"])
        self.assertEqual(export_folder["preference"], "custom")
        self.assertEqual(export_folder["user_export_dir"], str(custom_dir.resolve()))
        self.assertEqual(export_folder["custom_user_export_dir"], str(custom_dir.resolve()))
        self.assertIsNotNone(export_folder["confirmed_at"])

        current = self.payload("config", {})["export_folder"]
        self.assertFalse(current["survey_required"])
        self.assertEqual(current["preference"], "custom")

    def test_cleanup_requires_confirmation_and_positive_retention(self) -> None:
        self.payload("init_state", {"at": "2026-05-28T08:55:00"})
        missing_confirm = self.call("cleanup", {"retention_days": 90})
        self.assertTrue(missing_confirm.get("isError"))
        self.assertIn("confirm", json.loads(missing_confirm["content"][0]["text"])["error"])

        bad_retention = self.call("cleanup", {"retention_days": 0, "confirm": True})
        self.assertTrue(bad_retention.get("isError"))
        self.assertIn("retention_days", json.loads(bad_retention["content"][0]["text"])["error"])

    def test_export_only_writes_approved_entries(self) -> None:
        self.payload("init_state", {"at": "2026-05-28T08:55:00"})
        self.payload("add_missing", {
            "client": "Client A", "task": "draft only", "start": "2026-05-28T10:00:00", "end": "2026-05-28T10:30:00",
        })
        export_path = self.workdir / "exports" / "empty.csv"
        review = self.payload("review", {"date": "2026-05-28"})
        export = self.call("export", {"date": "2026-05-28", "output": str(export_path), "review_token": review["review_token"]})
        self.assertTrue(export.get("isError"))
        self.assertFalse(export_path.exists())

    def test_review_can_render_html(self) -> None:
        self.payload("init_state", {"at": "2026-05-28T08:55:00"})
        self.payload("add_missing", {
            "client": "Client A", "task": "monthly cleanup", "start": "2026-05-28T10:00:00", "end": "2026-05-28T10:24:00",
        })
        html_path = self.workdir / "reviews" / "review.html"
        review = self.payload("review", {"date": "2026-05-28", "html_output": str(html_path)})
        self.assertEqual(Path(review["html_output"]).resolve(), html_path.resolve())
        self.assertIn("TimeAssist Stakeholder Review", html_path.read_text())

    def test_review_tool_surfaces_active_timer_warning(self) -> None:
        self.payload("init_state", {"at": "2026-05-28T08:55:00"})
        self.payload("start", {"client": "Client A", "task": "monthly cleanup", "at": "2026-05-28T09:00:00"})

        review = self.payload("review", {"date": "2026-05-28", "at": "2026-05-28T09:50:00"})

        timer = review["active_timer"]
        self.assertEqual(timer["session"]["client"], "Client A")
        self.assertEqual(timer["open_minutes"], 50)
        self.assertIn("checkin", timer["suggested_actions"])

    def test_review_payload_is_slim(self) -> None:
        self.payload("init_state", {"at": "2026-05-28T09:00:00"})
        self.seed_roster("Client A")
        self.payload("start", {"client": "Client A", "task": "cleanup", "at": "2026-05-28T09:00:00"})
        self.payload("end", {"at": "2026-05-28T09:30:00"})
        review = self.payload("review", {"date": "2026-05-28"})
        self.assertNotIn("event_count", review)
        self.assertNotIn("last_activity_at", review)
        self.assertNotIn("active_session", review)
        self.assertNotIn("active_timer", review)  # idle: omitted entirely
        entry = review["entries"][0]
        self.assertEqual(sorted(entry), ["billable", "client", "end", "entry_id", "hours", "minutes", "notes", "start", "status"])

    def test_tool_error_is_reported_as_iserror(self) -> None:
        self.payload("init_state", {"at": "2026-05-28T08:55:00"})
        result = self.call("approve", {"entry_id": 999})
        self.assertTrue(result.get("isError"))
        body = json.loads(result["content"][0]["text"])
        self.assertFalse(body["ok"])
        self.assertIn("not found", body["error"])

    def test_unknown_tool_is_iserror(self) -> None:
        result = self.call("delete_everything", {})
        self.assertTrue(result.get("isError"))

    def test_unknown_method_returns_jsonrpc_error(self) -> None:
        msg = {"jsonrpc": "2.0", "id": 7, "method": "resources/list"}
        response = mcp_server.handle_message(msg, self.db)
        self.assertEqual(response["error"]["code"], -32601)

    def test_non_dict_arguments_is_iserror(self) -> None:
        msg = {"jsonrpc": "2.0", "id": 9, "method": "tools/call", "params": {"name": "start", "arguments": [1, 2]}}
        result = mcp_server.handle_message(msg, self.db)["result"]
        self.assertTrue(result.get("isError"))
        self.assertIn("object", json.loads(result["content"][0]["text"])["error"])

    def test_serve_replies_to_unparseable_line(self) -> None:
        import io

        original_stdin, original_stdout = sys.stdin, sys.stdout
        sys.stdin = io.StringIO("this is not json\n")
        sys.stdout = io.StringIO()
        try:
            mcp_server.serve(self.db)
            out = sys.stdout.getvalue()
        finally:
            sys.stdin, sys.stdout = original_stdin, original_stdout
        reply = json.loads(out.strip())
        self.assertIsNone(reply["id"])
        self.assertEqual(reply["error"]["code"], -32700)

    def test_edit_corrects_a_draft_and_recomputes_rounding(self) -> None:
        self.payload("init_state", {"at": "2026-05-28T08:55:00"})
        self.payload("add_missing", {
            "client": "Cleint A", "task": "montly cleanup", "start": "2026-05-28T10:00:00", "end": "2026-05-28T10:24:00",
        })
        edited = self.payload("edit", {
            "entry_id": 1, "client": "Acme Co", "task": "monthly cleanup", "end": "2026-05-28T10:30:00",
        })
        self.assertEqual(edited["client"], "Acme Co")
        self.assertEqual(edited["notes"], "monthly cleanup")
        self.assertEqual(edited["minutes"], 30)
        self.assertEqual(edited["status"], "draft")

    def test_edit_rejects_non_draft_entries(self) -> None:
        self.payload("init_state", {"at": "2026-05-28T08:55:00"})
        self.seed_roster("Client A")
        self.payload("add_missing", {
            "client": "Client A", "task": "cleanup", "start": "2026-05-28T10:00:00", "end": "2026-05-28T10:24:00",
        })
        review = self.payload("review", {"date": "2026-05-28"})
        self.payload("approve", {"entry_id": 1, "review_token": review["review_token"], "at": "2026-05-28T10:45:00"})
        result = self.call("edit", {"entry_id": 1, "task": "too late"})
        self.assertTrue(result.get("isError"))
        self.assertIn("only draft entries", json.loads(result["content"][0]["text"])["error"])

    def test_config_changes_the_rounding_rule(self) -> None:
        self.payload("init_state", {"at": "2026-05-28T08:55:00"})
        settings = self.payload("config", {})["settings"]
        self.assertEqual(settings["rounding_rule"], "exact")

        self.payload("config", {"rounding_rule": "up_15_minutes", "confirm": True})
        added = self.payload("add_missing", {
            "client": "Client A", "task": "cleanup", "start": "2026-05-28T10:00:00", "end": "2026-05-28T10:24:00",
        })
        self.assertEqual(added["raw_minutes"], 24)
        self.assertEqual(added["minutes"], 30)  # 24 rounded up to the next 15

    def test_config_applies_custom_rounding_increment(self) -> None:
        self.payload("init_state", {"at": "2026-05-28T08:55:00"})
        self.payload("config", {"rounding_rule": "nearest_10_minutes", "confirm": True})
        added = self.payload("add_missing", {
            "client": "Client A", "task": "cleanup", "start": "2026-05-28T10:00:00", "end": "2026-05-28T10:24:00",
        })
        self.assertEqual(added["raw_minutes"], 24)
        self.assertEqual(added["minutes"], 20)  # 24 rounded to the nearest 10

    def test_config_rejects_invalid_rounding_rule_with_teaching_error(self) -> None:
        self.payload("init_state", {"at": "2026-05-28T08:55:00"})
        result = self.call("config", {"rounding_rule": "nearest_0_minutes", "confirm": True})
        self.assertTrue(result.get("isError"))
        self.assertIn("nearest_<N>_minutes", json.loads(result["content"][0]["text"])["error"])
        settings = self.payload("config", {})["settings"]
        self.assertEqual(settings["rounding_rule"], "exact")  # invalid value never stored

    def test_reround_with_rule_requires_confirmation(self) -> None:
        self.payload("init_state", {"at": "2026-05-28T08:55:00"})
        self.payload("add_missing", {
            "client": "Acme Co", "task": "work", "start": "2026-05-28T09:00:00", "end": "2026-05-28T09:23:00",
        })

        result = self.call("reround", {"date": "2026-05-28", "rule": "nearest_15_minutes", "at": "2026-05-28T19:00:00"})

        self.assertTrue(result.get("isError"))
        self.assertIn("confirm", json.loads(result["content"][0]["text"])["error"])

    def test_reround_applies_rule_to_drafts(self) -> None:
        self.payload("init_state", {"at": "2026-05-28T08:55:00"})
        self.seed_roster("Acme Co")
        self.payload("add_missing", {
            "client": "Acme Co", "task": "work", "start": "2026-05-28T09:00:00", "end": "2026-05-28T09:23:00",
        })
        result = self.payload("reround", {"date": "2026-05-28", "rule": "nearest_15_minutes", "confirm": True, "at": "2026-05-28T19:00:00"})
        self.assertEqual(result["rule"], "nearest_15_minutes")
        self.assertEqual(result["rerounded_count"], 1)
        self.assertEqual(result["total_draft_minutes"], 30)

    def test_import_and_list_clients(self) -> None:
        self.payload("init_state", {"at": "2026-05-28T08:55:00"})
        csv_path = self.workdir / "clients.csv"
        csv_path.write_text(
            "client_key,display_name,aliases,default_billable\n"
            "acme,Acme Co,ACME,yes\n"
        )
        imported = self.payload("import_clients", {"path": str(csv_path), "confirm_replace": True})
        self.assertEqual(imported["imported_count"], 1)
        listed = self.payload("list_clients", {})
        self.assertEqual(listed["clients"][0]["display_name"], "Acme Co")

    def test_start_uses_imported_roster(self) -> None:
        self.payload("init_state", {"at": "2026-05-28T08:55:00"})
        csv_path = self.workdir / "clients.csv"
        csv_path.write_text(
            "client_key,display_name,aliases,default_billable\n"
            "acme,Acme Co,ACME,yes\n"
        )
        self.payload("import_clients", {"path": str(csv_path), "confirm_replace": True})
        session = self.payload("start", {"client": "ACME", "task": "kickoff", "at": "2026-05-28T09:00:00"})
        self.assertEqual(session["client"], "Acme Co")

    def test_now_iso_is_local_and_internally_consistent(self) -> None:
        from timeassist import actions

        now = actions.now_iso()
        self.assertFalse(now.endswith("Z"), "timestamps must be local wall-clock, not UTC 'Z'")
        self.assertEqual(now[:10], actions.iso(actions.parse_at(None))[:10])

    def test_cancel_drops_active_session(self) -> None:
        self.payload("init_state", {"at": "2026-05-28T08:55:00"})
        self.payload("start", {"client": "Acme Co", "task": "x", "at": "2026-05-28T09:00:00"})
        canceled = self.payload("cancel", {"at": "2026-05-28T09:05:00"})
        self.assertEqual(canceled["status"], "canceled")
        review = self.payload("review", {"date": "2026-05-28"})
        self.assertEqual(review["entries"], [])

    def test_checkin_status_and_checkin(self) -> None:
        self.payload("init_state", {"at": "2026-05-28T08:55:00"})
        idle = self.payload("checkin_status", {})
        self.assertFalse(idle["active"])
        self.assertFalse(idle["should_prompt"])
        self.assertNotIn("prompt_reason", idle)  # idle view is just active/should_prompt
        self.payload("start", {"client": "Acme Co", "task": "cleanup", "at": "2026-05-28T09:00:00"})
        self.assertTrue(self.payload("checkin_status", {})["active"])
        after = self.payload("checkin", {"at": "2026-05-28T09:30:00"})
        self.assertEqual(after["last_checkin_at"], "2026-05-28T09:30:00")

    def test_snooze_checkin_tool_updates_active_session(self) -> None:
        self.payload("init_state", {"at": "2026-05-28T08:55:00"})
        self.payload("start", {"client": "Acme Co", "task": "cleanup", "at": "2026-05-28T09:00:00"})

        result = self.payload("snooze_checkin", {"minutes": 30, "at": "2026-05-28T09:45:00"})

        self.assertEqual(result["snoozed_until"], "2026-05-28T10:15:00")
        self.assertEqual(result["client"], "Acme Co")

    def test_snooze_checkin_tool_rejects_invalid_minutes(self) -> None:
        self.payload("init_state", {"at": "2026-05-28T08:55:00"})
        self.payload("start", {"client": "Acme Co", "task": "cleanup", "at": "2026-05-28T09:00:00"})

        result = self.call("snooze_checkin", {"minutes": 0, "at": "2026-05-28T09:45:00"})

        self.assertTrue(result.get("isError"))
        self.assertIn("minutes must be greater than zero", json.loads(result["content"][0]["text"])["error"])


    def test_status_reports_footprint(self) -> None:
        self.payload("init_state", {"at": "2026-05-28T08:55:00"})
        st = self.payload("status", {})
        self.assertIn("size_bytes", st)
        self.assertEqual(st["entries"]["total"], 0)

    def test_tool_results_are_serialized_compact(self) -> None:
        self.payload("init_state", {"at": "2026-05-28T09:00:00"})
        result = self.call("status", {})
        text = result["content"][0]["text"]
        parsed = json.loads(text)
        self.assertEqual(text, json.dumps(parsed, separators=(",", ":"), sort_keys=True))

    def test_cleanup_runs(self) -> None:
        self.payload("init_state", {"at": "2026-05-28T08:55:00"})
        result = self.payload("cleanup", {"vacuum": True, "confirm": True})
        self.assertIn("pruned_events", result)
        self.assertTrue(result["vacuumed"])

    def test_discard_entry_requires_confirm(self) -> None:
        self.payload("init_state", {"at": "2026-05-28T09:00:00"})
        self.payload("start", {"client": "Client A", "task": "cleanup", "at": "2026-05-28T09:00:00"})
        entry = self.payload("end", {"at": "2026-05-28T09:30:00"})
        result = self.call("discard_entry", {"entry_id": entry["entry_id"]})
        self.assertTrue(result.get("isError"))
        discarded = self.payload("discard_entry", {"entry_id": entry["entry_id"], "confirm": True})
        self.assertEqual(discarded["status"], "discarded")

    def test_add_client_round_trips_slim_view(self) -> None:
        self.payload("init_state", {"at": "2026-05-28T08:55:00"})
        result = self.payload("add_client", {
            "display_name": "Acme Widgets", "default_job_type": "Bookkeeping",
            "at": "2026-05-28T09:00:00",
        })
        self.assertEqual(result["client"]["client_key"], "acme_widgets")
        self.assertEqual(result["client"]["display_name"], "Acme Widgets")
        self.assertEqual(result["client"]["default_job_type"], "Bookkeeping")
        self.assertNotIn("aliases", result["client"])
        self.assertNotIn("billable_locked", result["client"])
        self.assertIn("client_count", result)
        duplicate = self.call("add_client", {"display_name": "Acme Widgets"}, msg_id=2)
        self.assertTrue(duplicate.get("isError"))

    def test_config_sets_strict_roster_and_edit_relays_strict_error(self) -> None:
        self.payload("init_state", {"at": "2026-05-28T08:55:00"})
        self.seed_roster("Client A")
        unconfirmed = self.call("config", {"strict_roster": "yes"})
        self.assertTrue(unconfirmed.get("isError"))
        self.payload("config", {"strict_roster": "yes", "confirm": True})
        settings = self.payload("config", {})["settings"]
        self.assertEqual(settings["strict_roster"], "yes")
        entry = self.payload("add_missing", {
            "client": "Mystery Co", "task": "call",
            "start": "2026-05-28T09:00:00", "end": "2026-05-28T09:23:00",
        })
        self.assertEqual(entry["status"], "needs_info")
        result = self.call("edit", {"entry_id": entry["entry_id"], "client": "Mystery Co"}, msg_id=3)
        self.assertTrue(result.get("isError"))
        self.assertIn("strict roster", result["content"][0]["text"])

    # --- Task 6: MCP range review/export and operator_code config ---

    def test_tools_list_name_set_is_unchanged(self) -> None:
        """Tool-name set must not grow or shrink — explicitly asserted per plan."""
        msg = {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
        tools = mcp_server.handle_message(msg, self.db)["result"]["tools"]
        names = {tool["name"] for tool in tools}
        self.assertEqual(
            names,
            {
                "init_state", "start", "switch", "clarify_active", "cancel",
                "checkin", "snooze_checkin", "checkin_status", "end",
                "add_missing", "edit", "review", "approve", "approve_all",
                "unapprove", "export", "sanitize_packet", "config", "reround",
                "cleanup", "status", "list_clients", "list_job_codes",
                "refresh_clients", "submit", "update_submitted", "draft_reception_email",
                "import_clients",
                "add_client", "discard_entry",
            },
        )

    def test_review_tool_schema_exposes_end_date(self) -> None:
        msg = {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
        tools = mcp_server.handle_message(msg, self.db)["result"]["tools"]
        review_tool = next(t for t in tools if t["name"] == "review")
        props = review_tool["inputSchema"]["properties"]
        self.assertIn("end_date", props)
        self.assertEqual(props["end_date"]["type"], "string")

    def test_export_tool_schema_exposes_end_date(self) -> None:
        msg = {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
        tools = mcp_server.handle_message(msg, self.db)["result"]["tools"]
        export_tool = next(t for t in tools if t["name"] == "export")
        props = export_tool["inputSchema"]["properties"]
        self.assertIn("end_date", props)
        self.assertEqual(props["end_date"]["type"], "string")

    def test_config_tool_schema_exposes_operator_code_and_clear(self) -> None:
        msg = {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
        tools = mcp_server.handle_message(msg, self.db)["result"]["tools"]
        config_tool = next(t for t in tools if t["name"] == "config")
        props = config_tool["inputSchema"]["properties"]
        self.assertIn("operator_code", props)
        self.assertEqual(props["operator_code"]["type"], "string")
        self.assertIn("clear_operator_code", props)
        self.assertEqual(props["clear_operator_code"]["type"], "boolean")

    def test_range_review_returns_days_summary_not_entries(self) -> None:
        self.payload("init_state", {"at": "2026-05-27T08:55:00"})
        self.seed_roster("Client A")
        self.payload("add_missing", {
            "client": "Client A", "task": "day1 work",
            "start": "2026-05-27T09:00:00", "end": "2026-05-27T09:30:00",
        })
        self.payload("add_missing", {
            "client": "Client A", "task": "day2 work",
            "start": "2026-05-28T10:00:00", "end": "2026-05-28T10:30:00",
        })
        review = self.payload("review", {"date": "2026-05-27", "end_date": "2026-05-28"})
        self.assertEqual(review["date"], "2026-05-27")
        self.assertEqual(review["end_date"], "2026-05-28")
        self.assertIn("days", review)
        self.assertNotIn("entries", review)
        self.assertIn("review_token", review)
        self.assertIn("totals", review)
        self.assertIn("skipped_needs_info_count", review)
        self.assertEqual(len(review["days"]), 2)
        self.assertEqual(review["days"][0]["date"], "2026-05-27")
        self.assertEqual(review["days"][1]["date"], "2026-05-28")

    def test_range_review_html_output_rejected(self) -> None:
        self.payload("init_state", {"at": "2026-05-27T08:55:00"})
        html_path = self.workdir / "range_review.html"
        result = self.call("review", {
            "date": "2026-05-27", "end_date": "2026-05-28",
            "html_output": str(html_path),
        })
        self.assertTrue(result.get("isError"))
        error_text = json.loads(result["content"][0]["text"])["error"]
        self.assertIn("end_date", error_text)
        self.assertIn("html_output", error_text)

    def test_range_review_equal_dates_treated_as_single_day(self) -> None:
        """end_date == date collapses to single-day; html_output must work."""
        self.payload("init_state", {"at": "2026-05-28T08:55:00"})
        self.payload("add_missing", {
            "client": "Client A", "task": "work",
            "start": "2026-05-28T09:00:00", "end": "2026-05-28T09:30:00",
        })
        html_path = self.workdir / "reviews" / "eq.html"
        review = self.payload("review", {
            "date": "2026-05-28", "end_date": "2026-05-28",
            "html_output": str(html_path),
        })
        # Collapsed: single-day shape (entries present, no end_date/days),
        # and html_output is NOT refused — the collapse happens first.
        self.assertIn("entries", review)
        self.assertNotIn("end_date", review)
        self.assertNotIn("days", review)
        self.assertEqual(Path(review["html_output"]).resolve(), html_path.resolve())
        self.assertTrue(html_path.exists())

    def test_range_review_blank_end_date_means_absent(self) -> None:
        """end_date '' must behave exactly like no end_date, never 'today'."""
        self.payload("init_state", {"at": "2026-05-28T08:55:00"})
        self.payload("add_missing", {
            "client": "Client A", "task": "work",
            "start": "2026-05-28T09:00:00", "end": "2026-05-28T09:30:00",
        })
        review = self.payload("review", {"date": "2026-05-28", "end_date": ""})
        self.assertIn("entries", review)
        self.assertNotIn("end_date", review)
        self.assertNotIn("days", review)
        self.assertEqual(
            review["review_token"],
            self.payload("review", {"date": "2026-05-28"})["review_token"],
        )

    def test_range_export_uses_range_token(self) -> None:
        self.payload("init_state", {"at": "2026-05-27T08:55:00"})
        self.seed_roster("Client A")
        self.payload("add_missing", {
            "client": "Client A", "task": "day1",
            "start": "2026-05-27T09:00:00", "end": "2026-05-27T09:30:00",
        })
        self.payload("add_missing", {
            "client": "Client A", "task": "day2",
            "start": "2026-05-28T10:00:00", "end": "2026-05-28T10:30:00",
        })
        # Approve each day using its single-day token
        tok27 = self.payload("review", {"date": "2026-05-27"})["review_token"]
        self.payload("approve_all", {"date": "2026-05-27", "review_token": tok27})
        tok28 = self.payload("review", {"date": "2026-05-28"})["review_token"]
        self.payload("approve_all", {"date": "2026-05-28", "review_token": tok28})
        # Now get a range token and export the span
        review = self.payload("review", {"date": "2026-05-27", "end_date": "2026-05-28"})
        tok = review["review_token"]
        export_path = self.workdir / "exports" / "range_export.csv"
        export = self.payload("export", {
            "date": "2026-05-27", "end_date": "2026-05-28",
            "output": str(export_path), "review_token": tok,
        })
        self.assertEqual(export["exported_count"], 2)
        self.assertEqual(export["end_date"], "2026-05-28")
        self.assertTrue(export_path.exists())

    def test_config_sets_operator_code(self) -> None:
        self.payload("init_state", {"at": "2026-05-28T08:55:00"})
        unconfirmed = self.call("config", {"operator_code": "JW"})
        self.assertTrue(unconfirmed.get("isError"))
        self.assertIn("confirm", json.loads(unconfirmed["content"][0]["text"])["error"])
        self.payload("config", {"operator_code": "JW", "confirm": True})
        settings = self.payload("config", {})["settings"]
        self.assertEqual(settings["operator_code"], "JW")

    def test_config_clears_operator_code(self) -> None:
        self.payload("init_state", {"at": "2026-05-28T08:55:00"})
        self.payload("config", {"operator_code": "JW", "confirm": True})
        self.payload("config", {"clear_operator_code": True, "confirm": True})
        settings = self.payload("config", {})["settings"]
        self.assertNotIn("operator_code", settings)

    def test_config_two_args_still_error(self) -> None:
        self.payload("init_state", {"at": "2026-05-28T08:55:00"})
        result = self.call("config", {
            "operator_code": "JW", "rounding_rule": "exact", "confirm": True,
        })
        self.assertTrue(result.get("isError"))
        self.assertIn("one", json.loads(result["content"][0]["text"])["error"])

    def test_config_operator_code_and_clear_are_exclusive(self) -> None:
        self.payload("init_state", {"at": "2026-05-28T08:55:00"})
        result = self.call("config", {
            "operator_code": "JW", "clear_operator_code": True, "confirm": True,
        })
        self.assertTrue(result.get("isError"))
        self.assertIn("one", json.loads(result["content"][0]["text"])["error"])

    def test_export_view_has_operator_code_when_set(self) -> None:
        self.payload("init_state", {"at": "2026-05-28T08:55:00"})
        self.seed_roster("Client A")
        self.payload("config", {"operator_code": "JW", "confirm": True})
        self.payload("add_missing", {
            "client": "Client A", "task": "work",
            "start": "2026-05-28T09:00:00", "end": "2026-05-28T09:30:00",
        })
        review = self.payload("review", {"date": "2026-05-28"})
        self.payload("approve", {"entry_id": 1, "review_token": review["review_token"]})
        review = self.payload("review", {"date": "2026-05-28"})
        export_path = self.workdir / "exports" / "jw_export.csv"
        export = self.payload("export", {
            "date": "2026-05-28", "output": str(export_path),
            "review_token": review["review_token"],
        })
        self.assertEqual(export["operator_code"], "JW")
        self.assertNotIn("end_date", export)

    def test_export_view_no_operator_code_when_not_set(self) -> None:
        self.payload("init_state", {"at": "2026-05-28T08:55:00"})
        self.seed_roster("Client A")
        self.payload("add_missing", {
            "client": "Client A", "task": "work",
            "start": "2026-05-28T09:00:00", "end": "2026-05-28T09:30:00",
        })
        review = self.payload("review", {"date": "2026-05-28"})
        self.payload("approve", {"entry_id": 1, "review_token": review["review_token"]})
        review = self.payload("review", {"date": "2026-05-28"})
        export_path = self.workdir / "exports" / "no_code_export.csv"
        export = self.payload("export", {
            "date": "2026-05-28", "output": str(export_path),
            "review_token": review["review_token"],
        })
        self.assertNotIn("operator_code", export)


if __name__ == "__main__":
    unittest.main()
