"""Deterministic tests for the model-behavior eval harness (evals/).

Everything here runs offline: the Anthropic API transport is faked, while the
MCP executor and scenario seeds run against the real engine on throwaway
databases. The live loop (evals/run.py) is exercised manually with an API key.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from datetime import date
from pathlib import Path

from evals import claude_code_driver as ccd
from evals import harness, scenarios
from evals.harness import HarnessError, McpToolExecutor, ToolCall, run_conversation
from evals.scenarios import Expect, Forbid, match_expectations, match_forbidden


def _call(name: str, arguments: dict | None = None) -> ToolCall:
    return ToolCall(name=name, arguments=arguments or {}, result_text="{}", is_error=False)


class ExpectationMatcherTests(unittest.TestCase):
    def test_ordered_subsequence_passes(self) -> None:
        calls = [_call("review"), _call("approve_all", {"review_token": "tok-1"})]
        expects = [Expect("review"), Expect("approve_all", {"review_token": lambda v: bool(v)})]
        self.assertEqual(match_expectations(calls, expects), [])

    def test_order_violation_fails(self) -> None:
        calls = [_call("approve_all", {"review_token": "tok-1"}), _call("review")]
        expects = [Expect("review"), Expect("approve_all")]
        errors = match_expectations(calls, expects)
        self.assertEqual(len(errors), 1)
        self.assertIn("approve_all", errors[0])

    def test_argument_value_mismatch_fails(self) -> None:
        calls = [_call("switch", {"client": "Bell Co", "minutes_ago": 15})]
        errors = match_expectations(calls, [Expect("switch", {"minutes_ago": 20})])
        self.assertEqual(len(errors), 1)
        self.assertIn("switch", errors[0])

    def test_argument_predicate_and_extra_args_ignored(self) -> None:
        calls = [_call("reround", {"rule": "nearest_10_minutes", "confirm": True, "date": "today"})]
        expects = [Expect("reround", {"rule": lambda v: v == "nearest_10_minutes", "confirm": True})]
        self.assertEqual(match_expectations(calls, expects), [])

    def test_forbidden_tool_reported(self) -> None:
        calls = [_call("review"), _call("export", {"date": "today"})]
        errors = match_forbidden(calls, [Forbid("export")])
        self.assertEqual(len(errors), 1)
        self.assertIn("export", errors[0])
        self.assertEqual(match_forbidden([_call("review")], [Forbid("export")]), [])

    def test_forbidden_with_where_only_matches_matching_args(self) -> None:
        forbids = [Forbid("edit", {"client": lambda v: "management" in str(v).lower()})]
        ok = [_call("edit", {"entry_id": 1, "client": "Acme Co"})]
        bad = [_call("edit", {"entry_id": 1, "client": "Acme Co Management"})]
        self.assertEqual(match_forbidden(ok, forbids), [])
        self.assertEqual(len(match_forbidden(bad, forbids)), 1)


class _FakeTransport:
    """Returns queued Messages-API responses and records request payloads."""

    def __init__(self, responses: list[dict]):
        self.responses = list(responses)
        self.requests: list[dict] = []

    def __call__(self, payload: dict) -> dict:
        self.requests.append(payload)
        if not self.responses:
            raise AssertionError("fake transport exhausted")
        return self.responses.pop(0)


class _FakeExecutor:
    def __init__(self, result_text: str = '{"ok":true}', is_error: bool = False):
        self.calls: list[tuple[str, dict]] = []
        self.result_text = result_text
        self.is_error = is_error

    def call(self, name: str, arguments: dict) -> tuple[str, bool]:
        self.calls.append((name, arguments))
        return self.result_text, self.is_error


def _text_response(text: str = "done") -> dict:
    return {"stop_reason": "end_turn", "content": [{"type": "text", "text": text}]}

def _tool_response(name: str, tool_input: dict, tool_id: str = "toolu_01") -> dict:
    return {
        "stop_reason": "tool_use",
        "content": [
            {"type": "text", "text": "on it"},
            {"type": "tool_use", "id": tool_id, "name": name, "input": tool_input},
        ],
    }


class ConversationLoopTests(unittest.TestCase):
    def test_payload_carries_model_system_tools_and_turn(self) -> None:
        transport = _FakeTransport([_text_response()])
        tools = [{"name": "start", "description": "d", "input_schema": {"type": "object"}}]
        run_conversation(
            system="SYS-MARKER", tools=tools, turns=["hello"],
            executor=_FakeExecutor(), transport=transport, model="claude-sonnet-5",
        )
        payload = transport.requests[0]
        self.assertEqual(payload["model"], "claude-sonnet-5")
        self.assertEqual(payload["system"], "SYS-MARKER")
        self.assertEqual(payload["tools"], tools)
        self.assertEqual(payload["messages"], [{"role": "user", "content": "hello"}])
        self.assertNotIn("thinking", payload)
        self.assertNotIn("temperature", payload)

    def test_tool_use_is_executed_and_result_fed_back(self) -> None:
        transport = _FakeTransport([
            _tool_response("start", {"client": "Acme Co", "task": "books"}, "toolu_42"),
            _text_response("started"),
        ])
        executor = _FakeExecutor(result_text='{"session_id":1}')
        calls, messages = run_conversation(
            system="s", tools=[], turns=["start acme"],
            executor=executor, transport=transport, model="m",
        )
        self.assertEqual(executor.calls, [("start", {"client": "Acme Co", "task": "books"})])
        self.assertEqual([c.name for c in calls], ["start"])
        self.assertEqual(calls[0].result_text, '{"session_id":1}')
        # the follow-up request must carry a tool_result matching the tool_use id
        followup = transport.requests[1]["messages"][-1]
        self.assertEqual(followup["role"], "user")
        self.assertEqual(followup["content"][0]["type"], "tool_result")
        self.assertEqual(followup["content"][0]["tool_use_id"], "toolu_42")
        # full transcript is returned for debugging
        self.assertEqual(messages[0], {"role": "user", "content": "start acme"})

    def test_tool_error_sets_is_error_on_result_block(self) -> None:
        transport = _FakeTransport([
            _tool_response("approve", {"entry_id": 1}),
            _text_response(),
        ])
        executor = _FakeExecutor(result_text='{"ok":false,"error":"review_token required"}', is_error=True)
        calls, _ = run_conversation(
            system="s", tools=[], turns=["approve"],
            executor=executor, transport=transport, model="m",
        )
        self.assertTrue(calls[0].is_error)
        block = transport.requests[1]["messages"][-1]["content"][0]
        self.assertTrue(block["is_error"])

    def test_pause_turn_resends_without_new_user_content(self) -> None:
        transport = _FakeTransport([
            {"stop_reason": "pause_turn", "content": [{"type": "text", "text": "…"}]},
            _text_response(),
        ])
        run_conversation(
            system="s", tools=[], turns=["go"],
            executor=_FakeExecutor(), transport=transport, model="m",
        )
        second = transport.requests[1]["messages"]
        self.assertEqual(second[-1]["role"], "assistant")  # no extra user turn injected

    def test_refusal_raises_harness_error(self) -> None:
        transport = _FakeTransport([
            {"stop_reason": "refusal", "content": []},
        ])
        with self.assertRaises(HarnessError):
            run_conversation(
                system="s", tools=[], turns=["go"],
                executor=_FakeExecutor(), transport=transport, model="m",
            )

    def test_runaway_loop_hits_step_cap(self) -> None:
        transport = _FakeTransport([_tool_response("review", {})] * 30)
        with self.assertRaises(HarnessError):
            run_conversation(
                system="s", tools=[], turns=["loop"],
                executor=_FakeExecutor(), transport=transport, model="m", max_steps=5,
            )


class AuthHeaderTests(unittest.TestCase):
    def test_api_key_uses_x_api_key(self) -> None:
        headers = harness.auth_headers(api_key="sk-test")
        self.assertEqual(headers["x-api-key"], "sk-test")
        self.assertNotIn("authorization", {k.lower() for k in headers})
        self.assertEqual(headers["anthropic-version"], harness.API_VERSION)

    def test_oauth_token_uses_bearer_and_oauth_beta(self) -> None:
        headers = harness.auth_headers(auth_token="oat-test")
        self.assertEqual(headers["authorization"], "Bearer oat-test")
        self.assertEqual(headers["anthropic-beta"], "oauth-2025-04-20")
        self.assertNotIn("x-api-key", headers)

    def test_both_credentials_is_an_error(self) -> None:
        # The API rejects requests carrying both headers — fail fast instead.
        with self.assertRaises(HarnessError):
            harness.auth_headers(api_key="sk", auth_token="oat")

    def test_no_credentials_is_an_error(self) -> None:
        with self.assertRaises(HarnessError):
            harness.auth_headers()


class McpToolExecutorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = Path(self.tmp.name) / "timeassist.sqlite"

    def test_list_tools_returns_api_ready_schemas(self) -> None:
        executor = McpToolExecutor(self.db)
        tools = executor.list_tools()
        self.assertGreaterEqual(len(tools), 20)
        names = {t["name"] for t in tools}
        self.assertIn("config", names)
        self.assertIn("reround", names)
        for tool in tools:
            self.assertIn("description", tool)
            self.assertEqual(tool["input_schema"]["type"], "object")
            self.assertNotIn("inputSchema", tool)  # MCP key must be renamed for the API

    def test_call_routes_through_real_server(self) -> None:
        executor = McpToolExecutor(self.db)
        text, is_error = executor.call("init_state", {"at": "2026-07-02T08:00:00"})
        self.assertFalse(is_error)
        json.loads(text)  # shaped, compact JSON
        text, is_error = executor.call("no_such_tool", {})
        self.assertTrue(is_error)


def _jsonl(*events: dict) -> str:
    return "\n".join(json.dumps(e) for e in events)


class ClaudeCodeDriverTests(unittest.TestCase):
    def test_mcp_config_points_at_real_server_and_db(self) -> None:
        config = ccd.build_mcp_config("/tmp/x/timeassist.sqlite")
        server = config["mcpServers"]["timeassist"]
        script = Path(server["args"][0])
        self.assertTrue(script.exists(), f"missing MCP entry script: {script}")
        self.assertIn("--db", server["args"])
        self.assertIn("/tmp/x/timeassist.sqlite", server["args"])

    def test_command_isolates_the_session_and_restricts_tools(self) -> None:
        cmd = ccd.build_command(
            prompt="hello", system="SYS", mcp_config_path="/tmp/mcp.json",
            model="claude-sonnet-5",
        )
        joined = " ".join(cmd)
        self.assertEqual(cmd[cmd.index("-p") + 1], "hello")
        self.assertEqual(cmd[cmd.index("--system-prompt") + 1], "SYS")
        self.assertEqual(cmd[cmd.index("--model") + 1], "claude-sonnet-5")
        self.assertIn("--strict-mcp-config", cmd)
        self.assertEqual(cmd[cmd.index("--tools") + 1], "")  # no built-in tools
        self.assertIn("mcp__timeassist__*", joined)          # our server allowed
        self.assertIn("stream-json", joined)
        self.assertNotIn("--resume", cmd)

    def test_command_resumes_prior_session(self) -> None:
        cmd = ccd.build_command(
            prompt="next", system="s", mcp_config_path="/tmp/mcp.json",
            model="m", session_id="sess-1",
        )
        self.assertEqual(cmd[cmd.index("--resume") + 1], "sess-1")

    def test_parse_stream_extracts_timeassist_calls_only(self) -> None:
        lines = _jsonl(
            {"type": "system", "subtype": "init", "session_id": "sess-9"},
            {"type": "assistant", "message": {"content": [
                {"type": "text", "text": "on it"},
                {"type": "tool_use", "id": "t1", "name": "mcp__timeassist__reround",
                 "input": {"rule": "nearest_10_minutes", "confirm": True}},
            ]}},
            {"type": "user", "message": {"content": [
                {"type": "tool_result", "tool_use_id": "t1",
                 "content": [{"type": "text", "text": '{"rerounded_count":1}'}]},
            ]}},
            {"type": "assistant", "message": {"content": [
                {"type": "tool_use", "id": "t2", "name": "TodoWrite", "input": {}},
            ]}},
            {"type": "result", "subtype": "success", "session_id": "sess-9", "is_error": False},
        )
        calls, session_id, ok, connected = ccd.parse_stream_events(lines.splitlines())
        self.assertEqual(session_id, "sess-9")
        self.assertTrue(ok)
        self.assertTrue(connected)  # no mcp_servers info -> assume fine
        self.assertEqual([c.name for c in calls], ["reround"])  # TodoWrite ignored
        self.assertEqual(calls[0].arguments["rule"], "nearest_10_minutes")
        self.assertIn("rerounded_count", calls[0].result_text)
        self.assertFalse(calls[0].is_error)

    def test_parse_stream_propagates_tool_errors_and_string_content(self) -> None:
        lines = _jsonl(
            {"type": "assistant", "message": {"content": [
                {"type": "tool_use", "id": "t1", "name": "mcp__timeassist__approve", "input": {"entry_id": 1}},
            ]}},
            {"type": "user", "message": {"content": [
                {"type": "tool_result", "tool_use_id": "t1",
                 "content": '{"ok":false,"error":"review_token required"}', "is_error": True},
            ]}},
            {"type": "result", "subtype": "success", "session_id": "s", "is_error": False},
        )
        calls, _, _, _ = ccd.parse_stream_events(lines.splitlines())
        self.assertTrue(calls[0].is_error)
        self.assertIn("review_token", calls[0].result_text)

    def test_parse_stream_reports_pending_mcp_server(self) -> None:
        lines = _jsonl(
            {"type": "system", "subtype": "init", "session_id": "s",
             "mcp_servers": [{"name": "timeassist", "status": "pending"}]},
            {"type": "result", "subtype": "success", "session_id": "s", "is_error": False},
        )
        _, _, _, connected = ccd.parse_stream_events(lines.splitlines())
        self.assertFalse(connected)

    def test_first_turn_mcp_race_restarts_the_conversation(self) -> None:
        commands = []
        racy = _jsonl(
            {"type": "system", "subtype": "init", "session_id": "dead",
             "mcp_servers": [{"name": "timeassist", "status": "pending"}]},
            {"type": "result", "subtype": "success", "session_id": "dead", "is_error": False},
        )
        healthy = _jsonl(
            {"type": "system", "subtype": "init", "session_id": "live",
             "mcp_servers": [{"name": "timeassist", "status": "connected"}]},
            {"type": "assistant", "message": {"content": [
                {"type": "tool_use", "id": "t1", "name": "mcp__timeassist__review", "input": {}}]}},
            {"type": "result", "subtype": "success", "session_id": "live", "is_error": False},
        )
        outputs = [racy, healthy]

        def runner(cmd, cwd):
            commands.append(cmd)
            return outputs.pop(0), 0

        with tempfile.TemporaryDirectory() as tmp:
            calls, _ = ccd.run_conversation_via_claude_code(
                system="s", turns=["one"], db_path=Path(tmp) / "db.sqlite",
                model="m", workdir=Path(tmp), runner=runner, retry_delay=0,
            )
        self.assertEqual([c.name for c in calls], ["review"])
        self.assertEqual(len(commands), 2)
        self.assertNotIn("--resume", commands[1])  # fresh session, no dead context

    def test_persistent_mcp_race_raises(self) -> None:
        racy = _jsonl(
            {"type": "system", "subtype": "init", "session_id": "s",
             "mcp_servers": [{"name": "timeassist", "status": "pending"}]},
            {"type": "result", "subtype": "success", "session_id": "s", "is_error": False},
        )

        def runner(cmd, cwd):
            return racy, 0

        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(HarnessError):
                ccd.run_conversation_via_claude_code(
                    system="s", turns=["one"], db_path=Path(tmp) / "db.sqlite",
                    model="m", workdir=Path(tmp), runner=runner, retry_delay=0,
                )

    def test_conversation_threads_session_id_across_turns(self) -> None:
        commands = []

        def fake_runner(cmd, cwd):
            commands.append(cmd)
            sid = "sess-42"
            return _jsonl(
                {"type": "system", "subtype": "init", "session_id": sid},
                {"type": "result", "subtype": "success", "session_id": sid, "is_error": False},
            ), 0

        with tempfile.TemporaryDirectory() as tmp:
            calls, _ = ccd.run_conversation_via_claude_code(
                system="s", turns=["one", "two"], db_path=Path(tmp) / "db.sqlite",
                model="m", workdir=Path(tmp), runner=fake_runner,
            )
        self.assertEqual(len(commands), 2)
        self.assertNotIn("--resume", commands[0])
        self.assertEqual(commands[1][commands[1].index("--resume") + 1], "sess-42")

    def test_conversation_raises_on_nonzero_exit(self) -> None:
        def broken_runner(cmd, cwd):
            return "boom", 1

        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(HarnessError):
                ccd.run_conversation_via_claude_code(
                    system="s", turns=["one"], db_path=Path(tmp) / "db.sqlite",
                    model="m", workdir=Path(tmp), runner=broken_runner, retry_delay=0,
                )


class ScenarioDefinitionTests(unittest.TestCase):
    def test_scenarios_are_well_formed(self) -> None:
        names = [s.name for s in scenarios.SCENARIOS]
        self.assertGreaterEqual(len(names), 8)
        self.assertEqual(len(names), len(set(names)), "duplicate scenario names")
        for s in scenarios.SCENARIOS:
            self.assertTrue(s.turns, f"{s.name} has no turns")
            self.assertTrue(
                s.expects or s.forbids or s.check_state,
                f"{s.name} asserts nothing",
            )

    def test_every_seed_runs_against_the_real_engine(self) -> None:
        day = date.today().isoformat()
        for s in scenarios.SCENARIOS:
            with tempfile.TemporaryDirectory() as tmp:
                db = Path(tmp) / "timeassist.sqlite"
                s.seed(db, day)  # must not raise

    def test_custom_rounding_scenario_end_state_flips_after_expected_call(self) -> None:
        s = next(x for x in scenarios.SCENARIOS if x.name == "custom_rounding_increment")
        day = date.today().isoformat()
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "timeassist.sqlite"
            s.seed(db, day)
            self.assertTrue(s.check_state(db, day), "state check should fail before reround")
            executor = McpToolExecutor(db)
            _, is_error = executor.call(
                "reround", {"date": day, "rule": "nearest_10_minutes", "confirm": True}
            )
            self.assertFalse(is_error)
            self.assertEqual(s.check_state(db, day), [])

    def test_skill_system_prompt_embeds_the_plugin_contract(self) -> None:
        prompt = harness.load_skill_system_prompt()
        self.assertIn("Timmy", prompt)
        self.assertIn("nearest_<N>_minutes", prompt)

    def test_state_checks_leave_no_open_db_handle(self) -> None:
        # Windows CI regression pin (first v0.1.23 tag build): a check_state
        # that leaves a sqlite handle open makes TemporaryDirectory cleanup
        # fail with WinError 32. Deleting the file right after a state check
        # only succeeds if every connection was closed; on Linux the unlink
        # passes regardless, but the release build runs this on Windows.
        day = date.today().isoformat()
        for s in scenarios.SCENARIOS:
            if s.check_state is None:
                continue
            with tempfile.TemporaryDirectory() as tmp:
                db = Path(tmp) / "timeassist.sqlite"
                s.seed(db, day)
                s.check_state(db, day)
                db.unlink()


if __name__ == "__main__":
    unittest.main()
