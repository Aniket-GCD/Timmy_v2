"""Guard the Windows build workflow's PowerShell smoke test against MCP view drift.

The v0.1.19 tag build failed because the workflow's "Smoke-test packaged EXE
file safety" step dereferenced `$safePayload.output`, a key the view layer
(timeassist/mcp_views.py) had renamed to `csv`/`official_csv`. The local
unittest suite could not catch it: the workflow's PowerShell assertions live
outside Python.

This test re-derives the keys the workflow reads off each ConvertFrom-Json'd
tool payload, drives the real MCP server through the same smoke sequence to
produce the actually shaped payloads, and asserts every dereferenced key is
present. If the workflow grows a new payload variable the mapping does not
know about, the test fails and tells the maintainer to extend the mapping.
"""

from __future__ import annotations

import json
import os
import re
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from timeassist import mcp_server

WORKFLOW = ROOT / ".github" / "workflows" / "windows-build.yml"

# Each PowerShell variable assigned from a `... | ConvertFrom-Json` of a tool
# result maps to the MCP tool whose shaped payload it holds. When the workflow
# grows a new such variable, add it here (or the guard below fails on purpose).
VARIABLE_TO_TOOL = {
    "review": "review",
    "postApproveReview": "review",
    "safePayload": "export",
    # `.error` payloads from failed exports; any isError result carries `error`.
    "outsideExport": "error",
    "traversalExport": "error",
}


class WorkflowSmokeContractTests(unittest.TestCase):
    def setUp(self) -> None:
        # Mirror PluginArtifactPathTests.setUp: a real USERPROFILE makes the
        # Documents/TimeAssist Exports copy land, so `export` reports both
        # `csv` (user-visible copy) and `official_csv` (data-dir original) —
        # the two keys the workflow's safe-export assertion dereferences.
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.data_dir = self.base / "plugin-data"
        self.data_dir.mkdir()
        self.profile = self.base / "profile"
        self._old_userprofile = os.environ.get("USERPROFILE")
        os.environ["USERPROFILE"] = str(self.profile)
        self.addCleanup(self._restore_userprofile)
        self.db = self.data_dir / "timeassist.sqlite"

    def _restore_userprofile(self) -> None:
        if self._old_userprofile is None:
            os.environ.pop("USERPROFILE", None)
        else:
            os.environ["USERPROFILE"] = self._old_userprofile

    # --- driving the real MCP server -------------------------------------

    def _call(self, msg_id: int, name: str, arguments: dict) -> dict:
        msg = {
            "jsonrpc": "2.0",
            "id": msg_id,
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        }
        response = mcp_server.handle_message(msg, self.db)
        self.assertIsNotNone(response, f"no response for {name}")
        return response["result"]

    def _payload(self, msg_id: int, name: str, arguments: dict) -> dict:
        result = self._call(msg_id, name, arguments)
        self.assertNotIn("isError", result, f"unexpected tool error from {name}: {result}")
        return json.loads(result["content"][0]["text"])

    def _shaped_payloads(self) -> dict[str, dict]:
        """Replay the workflow smoke sequence and return shaped payloads by tool."""
        self._payload(2, "init_state", {"at": "2026-05-28T08:55:00"})
        self._payload(
            3,
            "add_missing",
            {
                "client": "Client A",
                "task": "packaged exe file-safety smoke",
                "start": "2026-05-28T10:00:00",
                "end": "2026-05-28T10:30:00",
            },
        )
        # "Client A" is not on the roster: add_missing captures it needs_info
        # (the #34 approve/export gate). Confirm-as-is with an edit to draft.
        self._payload(4, "edit", {"entry_id": 1, "client": "Client A"})
        review = self._payload(5, "review", {"date": "2026-05-28"})
        self._payload(
            6,
            "approve",
            {"entry_id": 1, "review_token": review["review_token"], "at": "2026-05-28T10:35:00"},
        )
        post_approve_review = self._payload(7, "review", {"date": "2026-05-28"})

        # A real isError payload: export to an absolute path outside data dir.
        outside = self.base / "outside.csv"
        error_result = self._call(
            8,
            "export",
            {
                "date": "2026-05-28",
                "output": str(outside),
                "review_token": post_approve_review["review_token"],
            },
        )
        self.assertTrue(error_result.get("isError"), "outside export should have failed")
        error_payload = json.loads(error_result["content"][0]["text"])

        # The safe export: bare filename routed under exports/, with the
        # Documents copy made (USERPROFILE set), so official_csv + csv appear.
        safe_payload = self._payload(
            10,
            "export",
            {
                "date": "2026-05-28",
                "output": "safe.csv",
                "review_token": post_approve_review["review_token"],
                "at": "2026-05-28T10:40:00",
            },
        )
        return {
            "review": review,
            "export": safe_payload,
            "error": error_payload,
        }

    # --- extracting key references from the workflow ----------------------

    @staticmethod
    def _extract_key_references(text: str) -> dict[str, set[str]]:
        """Map each ConvertFrom-Json payload variable to the keys dereferenced.

        Two patterns are used by this workflow:
          - direct: `$review.review_token`, `$safePayload.official_csv`
          - parenthesized: `(... | ConvertFrom-Json).error`
        Only variables assigned from a ConvertFrom-Json of a tool result are
        treated as payload variables; control/process variables ($proc, $psi,
        $resp, $msg, $line, etc.) and `.content[0].text` access are excluded.
        """
        # Variables assigned directly from a ConvertFrom-Json'd tool payload.
        payload_vars = set(
            re.findall(r"\$(\w+)\s*=\s*\$\w+\.content\[0\]\.text\s*\|\s*ConvertFrom-Json", text)
        )

        refs: dict[str, set[str]] = {var: set() for var in payload_vars}

        # Direct dereferences `$var.key` for the payload variables we found.
        for var, key in re.findall(r"\$(\w+)\.([A-Za-z_]\w*)", text):
            if var in payload_vars:
                refs[var].add(key)

        # Parenthesized form: `($export.content[0].text | ConvertFrom-Json).error`
        # binds the key to the variable named inside the parentheses.
        for var, key in re.findall(
            r"\(\$(\w+)\.content\[0\]\.text\s*\|\s*ConvertFrom-Json\)\.([A-Za-z_]\w*)",
            text,
        ):
            refs.setdefault(var, set()).add(key)

        return refs

    # --- the guard --------------------------------------------------------

    def test_workflow_smoke_keys_exist_in_shaped_mcp_payloads(self) -> None:
        text = WORKFLOW.read_text()
        refs = self._extract_key_references(text)
        shaped = self._shaped_payloads()

        # Floor against vacuous passes: if the workflow's smoke step is
        # restructured so extraction finds nothing, the guard must fail
        # rather than silently stop protecting anything.
        total_keys = sum(len(keys) for keys in refs.values())
        self.assertGreaterEqual(
            total_keys,
            4,
            f"Extracted only {total_keys} payload-key references from "
            f"{WORKFLOW.name}; the smoke step's ConvertFrom-Json idiom may "
            f"have changed. Update _extract_key_references to match it.",
        )

        for var, keys in refs.items():
            if not keys:
                continue
            self.assertIn(
                var,
                VARIABLE_TO_TOOL,
                f"Workflow smoke test dereferences keys off a ConvertFrom-Json "
                f"variable `${var}` that {WORKFLOW.name}'s guard does not know "
                f"about. Extend VARIABLE_TO_TOOL in {Path(__file__).name} to map "
                f"`{var}` to the MCP tool whose payload it holds.",
            )
            tool = VARIABLE_TO_TOOL[var]
            payload = shaped[tool]
            for key in sorted(keys):
                self.assertIn(
                    key,
                    payload,
                    f"{WORKFLOW.name} reads `${var}.{key}` but the shaped MCP "
                    f"payload for `{tool}` does not contain `{key}` "
                    f"(present keys: {sorted(payload)}). The workflow smoke "
                    f"test and timeassist/mcp_views.py are out of sync.",
                )

    def test_every_payload_variable_is_mapped(self) -> None:
        """Any ConvertFrom-Json'd payload variable must be in the mapping."""
        refs = self._extract_key_references(WORKFLOW.read_text())
        unmapped = sorted(var for var, keys in refs.items() if keys and var not in VARIABLE_TO_TOOL)
        self.assertEqual(
            unmapped,
            [],
            f"Workflow smoke test introduced payload variables not covered by "
            f"the guard: {unmapped}. Extend VARIABLE_TO_TOOL in "
            f"{Path(__file__).name}.",
        )


if __name__ == "__main__":
    unittest.main()
