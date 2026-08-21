"""Drive eval conversations through Claude Code headless mode.

Why this exists: `claude -p` bills the operator's Claude subscription seat
instead of Console API credits. Claude Code spawns the real timeassist MCP
server itself (via --mcp-config), runs the agentic loop, and emits a
stream-json transcript we parse tool calls out of. Assertions stay identical
to the API driver: tool names/args, forbidden calls, SQLite end state.

Fidelity notes vs the API driver (harness.run_conversation):
- `--system-prompt` fully replaces Claude Code's default prompt with the
  harness preamble + SKILL.md, so the contract under test is the same.
- `--tools ""` removes every built-in tool; only mcp__timeassist__* exist.
- `--strict-mcp-config` + hooks disabled isolate the run from local config.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable

from evals.harness import HarnessError, ToolCall

DEFAULT_CC_MODEL = "claude-sonnet-5"
_REPO_ROOT = Path(__file__).resolve().parent.parent
_MCP_ENTRY = _REPO_ROOT / "scripts" / "timeassist_mcp.py"
_TOOL_PREFIX = "mcp__timeassist__"


def build_mcp_config(db_path: str | Path) -> dict[str, Any]:
    return {
        "mcpServers": {
            "timeassist": {
                "command": sys.executable,
                "args": [str(_MCP_ENTRY), "--db", str(db_path)],
            }
        }
    }


def build_command(
    *,
    prompt: str,
    system: str,
    mcp_config_path: str | Path,
    model: str,
    session_id: str | None = None,
    claude_bin: str = "claude",
) -> list[str]:
    cmd = [
        claude_bin, "-p", prompt,
        "--output-format", "stream-json", "--verbose",
        "--system-prompt", system,
        "--model", model,
        "--mcp-config", str(mcp_config_path),
        "--strict-mcp-config",
        "--tools", "",
        "--allowedTools", f"{_TOOL_PREFIX}*",
        # NB: do not add --settings or --safe-mode here — both silently break
        # --mcp-config server connection (verified empirically on CLI 2.x:
        # the server stays "pending" and the model gets zero tools).
    ]
    if session_id:
        cmd += ["--resume", session_id]
    return cmd


def parse_stream_events(lines: list[str]) -> tuple[list[ToolCall], str | None, bool, bool]:
    """Returns (timeassist calls, session_id, turn ok, mcp server connected).

    `connected` is False only when the init event explicitly reports a
    non-connected server — `claude -p` doesn't always wait for MCP startup,
    and a turn that ran with the server pending never saw any tools.
    """
    calls: list[ToolCall] = []
    by_id: dict[str, ToolCall] = {}
    session_id: str | None = None
    ok = False
    connected = True
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("session_id"):
            session_id = event["session_id"]
        if event.get("type") == "system" and event.get("subtype") == "init":
            servers = event.get("mcp_servers") or []
            if any(s.get("status") != "connected" for s in servers):
                connected = False
        if event.get("type") == "result":
            ok = not event.get("is_error", False)
            continue
        message = event.get("message") or {}
        for block in message.get("content") or []:
            if not isinstance(block, dict):
                continue
            if event.get("type") == "assistant" and block.get("type") == "tool_use":
                name = block.get("name", "")
                if not name.startswith(_TOOL_PREFIX):
                    continue
                call = ToolCall(
                    name=name[len(_TOOL_PREFIX):],
                    arguments=block.get("input") or {},
                    result_text="",
                    is_error=False,
                )
                calls.append(call)
                by_id[block.get("id", "")] = call
            elif event.get("type") == "user" and block.get("type") == "tool_result":
                call = by_id.get(block.get("tool_use_id", ""))
                if call is None:
                    continue
                content = block.get("content")
                if isinstance(content, list):
                    call.result_text = "".join(
                        part.get("text", "") for part in content
                        if isinstance(part, dict) and part.get("type") == "text"
                    )
                elif isinstance(content, str):
                    call.result_text = content
                call.is_error = bool(block.get("is_error"))
    return calls, session_id, ok, connected


def _subprocess_runner(cmd: list[str], cwd: Path) -> tuple[str, int]:
    env = {k: v for k, v in os.environ.items()
           if k not in ("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT")}
    completed = subprocess.run(
        cmd, cwd=cwd, env=env, capture_output=True, text=True, timeout=600,
    )
    return completed.stdout + ("\n" + completed.stderr if completed.returncode else ""), completed.returncode


def run_conversation_via_claude_code(
    *,
    system: str,
    turns: list[str],
    db_path: str | Path,
    model: str,
    workdir: Path,
    runner: Callable[[list[str], Path], tuple[str, int]] | None = None,
    claude_bin: str = "claude",
    retry_delay: float = 3.0,
) -> tuple[list[ToolCall], list[str]]:
    """Plays scripted operator turns; returns (tool calls, raw event lines).

    MCP-race handling: `claude -p` may start the model turn before the MCP
    server finishes connecting, leaving the model toolless. If that happens
    on the FIRST turn nothing touched the database, so the conversation
    restarts from scratch (up to 3 attempts). On a later turn the database
    is already mutated, so it surfaces as a HarnessError instead of being
    silently scored against the model.
    """
    runner = runner or _subprocess_runner
    mcp_config_path = Path(workdir) / "mcp-config.json"
    mcp_config_path.write_text(json.dumps(build_mcp_config(db_path)))

    for attempt in range(4):
        if attempt:
            time.sleep(retry_delay * attempt)  # let the racy startup settle
        session_id: str | None = None
        calls: list[ToolCall] = []
        transcript: list[str] = []
        restart = False

        for index, turn in enumerate(turns):
            cmd = build_command(
                prompt=turn, system=system, mcp_config_path=mcp_config_path,
                model=model, session_id=session_id, claude_bin=claude_bin,
            )
            output, returncode = runner(cmd, Path(workdir))
            lines = output.splitlines()
            transcript.extend(lines)
            if returncode != 0:
                raise HarnessError(
                    f"claude exited {returncode} on turn {turn!r}: {output[-500:]}"
                )
            turn_calls, new_session, ok, connected = parse_stream_events(lines)
            if not connected and not turn_calls:
                if index == 0 and not calls:
                    restart = True  # infra race, db untouched: retry fresh
                    break
                raise HarnessError(f"MCP server raced on resumed turn: {turn!r}")
            calls.extend(turn_calls)
            if new_session:
                session_id = new_session
            if not ok:
                raise HarnessError(f"turn did not complete cleanly: {turn!r}")

        if not restart:
            return calls, transcript

    raise HarnessError("MCP server never connected after 4 attempts")
