"""Headless harness for testing the model layer of the Timmy skill.

Reproduces the Cowork loop without Cowork: the plugin SKILL.md becomes the
system prompt, the real MCP server supplies the tool schemas and executes the
model's tool calls (through mcp_views shaping, so the model sees exactly what
it sees in production), and the Anthropic Messages API drives the turns.

The transport is injectable so everything except the live HTTP call is
covered by deterministic tests (tests/test_evals.py).
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from timeassist import mcp_server

DEFAULT_MODEL = "claude-sonnet-5"
API_URL = "https://api.anthropic.com/v1/messages"
API_VERSION = "2023-06-01"
_REPO_ROOT = Path(__file__).resolve().parent.parent
SKILL_PATH = _REPO_ROOT / "plugin" / "timeassist" / "skills" / "timmy" / "SKILL.md"

_HARNESS_PREAMBLE = (
    "You are running inside Claude Cowork as the operator's billable-time "
    "assistant. The skill document below is your contract — follow it "
    "exactly. Every message after this one is from the operator.\n\n"
)


class HarnessError(Exception):
    """The conversation could not be completed (refusal, runaway loop, HTTP)."""


@dataclass
class ToolCall:
    name: str
    arguments: dict[str, Any]
    result_text: str
    is_error: bool


class McpToolExecutor:
    """Routes tool calls through the real MCP server surface (shaped views)."""

    def __init__(self, db_path: str | Path):
        self.db_path = db_path
        self._next_id = 0

    def _rpc(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        self._next_id += 1
        msg: dict[str, Any] = {"jsonrpc": "2.0", "id": self._next_id, "method": method}
        if params is not None:
            msg["params"] = params
        response = mcp_server.handle_message(msg, self.db_path)
        return response["result"]

    def list_tools(self) -> list[dict[str, Any]]:
        tools = []
        for tool in self._rpc("tools/list")["tools"]:
            tools.append({
                "name": tool["name"],
                "description": tool["description"],
                "input_schema": tool["inputSchema"],  # MCP key -> Messages API key
            })
        return tools

    def call(self, name: str, arguments: dict[str, Any]) -> tuple[str, bool]:
        result = self._rpc("tools/call", {"name": name, "arguments": arguments})
        text = result["content"][0]["text"]
        return text, bool(result.get("isError"))


def load_skill_system_prompt(skill_path: str | Path | None = None) -> str:
    text = Path(skill_path or SKILL_PATH).read_text()
    # Drop the YAML frontmatter; Cowork consumes it as metadata, not prompt.
    if text.startswith("---"):
        end = text.find("---", 3)
        if end != -1:
            text = text[end + 3:].lstrip("\n")
    return _HARNESS_PREAMBLE + text


def auth_headers(api_key: str | None = None, auth_token: str | None = None) -> dict[str, str]:
    """Request headers for either credential type.

    `api_key` is a Console API key (x-api-key). `auth_token` is a Console
    OAuth access token — e.g. from `ant auth print-credentials --env` — which
    goes on `Authorization: Bearer` and needs the oauth beta header. The API
    rejects requests carrying both, so we fail fast here instead.
    """
    if api_key and auth_token:
        raise HarnessError("set ANTHROPIC_API_KEY or ANTHROPIC_AUTH_TOKEN, not both")
    headers = {"content-type": "application/json", "anthropic-version": API_VERSION}
    if api_key:
        headers["x-api-key"] = api_key
    elif auth_token:
        headers["authorization"] = f"Bearer {auth_token}"
        headers["anthropic-beta"] = "oauth-2025-04-20"
    else:
        raise HarnessError("no credentials: set ANTHROPIC_API_KEY or ANTHROPIC_AUTH_TOKEN")
    return headers


def http_transport(
    api_key: str | None = None,
    timeout: float = 180.0,
    auth_token: str | None = None,
) -> Callable[[dict], dict]:
    """Returns a transport callable posting to the Messages API via stdlib."""
    headers = auth_headers(api_key=api_key, auth_token=auth_token)

    def post(payload: dict[str, Any]) -> dict[str, Any]:
        body = json.dumps(payload).encode("utf-8")
        last_error: Exception | None = None
        for attempt in range(3):
            request = urllib.request.Request(API_URL, data=body, headers=headers)
            try:
                with urllib.request.urlopen(request, timeout=timeout) as response:
                    return json.loads(response.read().decode("utf-8"))
            except urllib.error.HTTPError as exc:
                detail = exc.read().decode("utf-8", "replace")[:500]
                if exc.code in (429, 500, 529) and attempt < 2:
                    last_error = exc
                    time.sleep(2 ** (attempt + 1))
                    continue
                raise HarnessError(f"API error {exc.code}: {detail}") from exc
            except urllib.error.URLError as exc:
                raise HarnessError(f"network error: {exc.reason}") from exc
        raise HarnessError(f"API kept failing after retries: {last_error}")

    return post


def run_conversation(
    *,
    system: str,
    tools: list[dict[str, Any]],
    turns: list[str],
    executor: Any,
    transport: Callable[[dict], dict],
    model: str,
    max_tokens: int = 1500,
    max_steps: int = 14,
) -> tuple[list[ToolCall], list[dict[str, Any]]]:
    """Plays scripted operator turns; returns (recorded tool calls, transcript).

    One "step" is one Messages API request. No `thinking` or sampling params
    are sent so the payload stays valid across the whole current model family.
    """
    messages: list[dict[str, Any]] = []
    calls: list[ToolCall] = []
    steps = 0

    for turn in turns:
        messages.append({"role": "user", "content": turn})
        while True:
            steps += 1
            if steps > max_steps:
                raise HarnessError(
                    f"conversation exceeded {max_steps} API calls; "
                    f"tools so far: {[c.name for c in calls]}"
                )
            response = transport({
                "model": model,
                "max_tokens": max_tokens,
                "system": system,
                "tools": tools,
                "messages": list(messages),  # snapshot: the live list keeps growing
            })
            stop_reason = response.get("stop_reason")
            content = response.get("content", [])
            messages.append({"role": "assistant", "content": content})

            if stop_reason == "tool_use":
                results = []
                for block in content:
                    if block.get("type") != "tool_use":
                        continue
                    text, is_error = executor.call(block["name"], block.get("input") or {})
                    calls.append(ToolCall(
                        name=block["name"],
                        arguments=block.get("input") or {},
                        result_text=text,
                        is_error=is_error,
                    ))
                    result_block: dict[str, Any] = {
                        "type": "tool_result",
                        "tool_use_id": block["id"],
                        "content": text,
                    }
                    if is_error:
                        result_block["is_error"] = True
                    results.append(result_block)
                messages.append({"role": "user", "content": results})
                continue
            if stop_reason == "pause_turn":
                continue
            if stop_reason == "refusal":
                raise HarnessError("model refused mid-scenario")
            break  # end_turn / max_tokens / stop_sequence: operator turn is done

    return calls, messages
