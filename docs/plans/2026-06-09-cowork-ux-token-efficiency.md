# Cowork UX & Token Efficiency Implementation Plan

> **Status: SHIPPED** in v0.1.19-prototype (PR #25, merged 2026-06-09; CI assertion fix in PR #26). Kept for reference — do not execute.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Cut MCP tool-result and per-session token cost by ~50–70% and remove the worst conversational UX friction for accountants using TimeAssist through Claude Cowork — without weakening the human-approval gate or touching the deterministic core's full-fidelity outputs.

**Architecture:** All output trimming happens at the **MCP boundary** in a new `timeassist/mcp_views.py` module: `actions.py` and the CLI keep returning full row dicts (audit/debug fidelity, existing action tests untouched), while `mcp_server.py` shapes each tool result into a compact model-facing view before serializing it **without indentation**. UX work is plain-language error messages in `actions.py`, one new `discard_entry` tool (soft delete via a `discarded` review_status — entries are never hard-deleted), and a tightened SKILL.md that documents the new view shapes.

**Tech Stack:** Python 3 stdlib only (hard constraint — the PyInstaller exe build forbids third-party deps). Tests via `python3 -m unittest discover -s tests -v`.

**Decisions locked during planning (do not relitigate):**
- Shaping at MCP boundary, not in `actions.py` — CLI/demo/action-tests stay stable.
- `discard_entry` is a soft delete (`review_status='discarded'`, audit-logged), preserving the "time entries are kept forever" invariant. Recovery = `add_missing` re-create; no undiscard tool in this pass.
- The `review_token` gate stays exactly as is. Mutations do NOT return fresh tokens (the gate exists so approval acts on state the human saw). We only improve the stale-token error message.
- `round_minutes`'s `max(increment, lower)` floor (actions.py:89) is **intentional** (a positive entry never rounds to 0 and silently drops from billing). Pin it with a test + comment; do not "fix" it.

**Worker rules for every task:**
- Run the full suite before claiming done: `python3 -m unittest discover -s tests -v` (expect all pass, ~190+ tests).
- Never add a third-party import.
- Commit per task with the message given in the task.

---

### Task 1: Compact JSON serialization at the MCP boundary

**Files:**
- Modify: `timeassist/mcp_server.py:479`
- Test: `tests/test_mcp_server.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_mcp_server.py` (inside the existing test class that has the `call`/`payload` helpers; reuse its setup):

```python
    def test_tool_results_are_serialized_compact(self) -> None:
        self.payload("init_state", {"at": "2026-05-28T09:00:00"})
        result = self.call("status", {})
        text = result["content"][0]["text"]
        parsed = json.loads(text)
        self.assertEqual(text, json.dumps(parsed, separators=(",", ":"), sort_keys=True))
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python3 -m unittest tests.test_mcp_server -k compact -v` (or the full module if `-k` is unavailable: `python3 -m unittest tests.test_mcp_server -v`)
Expected: FAIL — current output is `indent=2` pretty-printed.

- [ ] **Step 3: Implement**

In `timeassist/mcp_server.py`, in `handle_message`, change:

```python
            result = call_tool(name, arguments, db_path)
            text = json.dumps(result, indent=2, sort_keys=True)
```

to:

```python
            result = call_tool(name, arguments, db_path)
            text = json.dumps(result, separators=(",", ":"), sort_keys=True)
```

Also make the two error paths in the same function consistent (they already use compact dumps via default separators; leave them, but add `separators=(",", ":")` to both `json.dumps({"ok": False, ...})` calls for byte-stability).

- [ ] **Step 4: Run the full suite**

Run: `python3 -m unittest discover -s tests -v`
Expected: all pass (existing tests parse the text with `json.loads`, so formatting doesn't break them).

- [ ] **Step 5: Commit**

```bash
git add timeassist/mcp_server.py tests/test_mcp_server.py
git commit -m "perf: serialize MCP tool results compact (no indent)"
```

---

### Task 2: Create `timeassist/mcp_views.py` (model-facing result views)

**Files:**
- Create: `timeassist/mcp_views.py`
- Create: `tests/test_mcp_views.py`

Context for the engineer: `actions.py` returns full SQLite row dicts (17–19 fields per entry: `created_at`, `updated_at`, `raw_client_name`, `raw_task_text`, `clarified_at`, `export_path`, …). The model needs ~8 of them. `review_entries` additionally returns a fully-duplicated `active_timer_warning` (flat copies of every session field — see `actions.py:838-876`) plus `event_count`/`last_activity_at` which the assistant never uses.

- [ ] **Step 1: Write failing unit tests**

Create `tests/test_mcp_views.py`:

```python
import unittest

from timeassist import mcp_views


FULL_ENTRY = {
    "entry_id": 7, "client_name": "Client A", "task_text": "monthly cleanup",
    "billable": 1, "start_at": "2026-05-28T09:00:00", "end_at": "2026-05-28T09:23:00",
    "duration_minutes": 23, "rounded_minutes": 30, "review_status": "draft",
    "raw_client_name": "client a", "raw_task_text": "monthly cleanup",
    "capture_status": "resolved", "capture_note": None, "clarified_at": None,
    "export_path": None, "created_at": "2026-05-28T09:23:00", "updated_at": "2026-05-28T09:23:00",
}

FULL_SESSION = {
    "session_id": 3, "client_name": "Client B", "task_text": "tax question",
    "billable": 1, "started_at": "2026-05-28T10:00:00", "last_checkin_at": "2026-05-28T10:00:00",
    "snoozed_until": None, "status": "active", "raw_client_name": "Client B",
    "raw_task_text": "tax question", "capture_status": "needs_info",
    "capture_note": "client not in roster", "clarified_at": None,
    "created_at": "2026-05-28T10:00:00", "updated_at": "2026-05-28T10:00:00",
}


class SlimEntryTests(unittest.TestCase):
    def test_keeps_model_relevant_fields_only(self) -> None:
        slim = mcp_views.slim_entry(FULL_ENTRY)
        self.assertEqual(slim["entry_id"], 7)
        self.assertEqual(slim["client"], "Client A")
        self.assertEqual(slim["task"], "monthly cleanup")
        self.assertEqual(slim["billable"], "yes")
        self.assertEqual(slim["minutes"], 30)
        self.assertEqual(slim["status"], "draft")
        self.assertEqual(slim["raw_minutes"], 23)  # differs from rounded -> included
        for dropped in ("created_at", "updated_at", "raw_client_name", "export_path", "capture_status"):
            self.assertNotIn(dropped, slim)

    def test_raw_minutes_omitted_when_equal(self) -> None:
        entry = dict(FULL_ENTRY, duration_minutes=30)
        self.assertNotIn("raw_minutes", mcp_views.slim_entry(entry))

    def test_needs_info_surfaces_note(self) -> None:
        entry = dict(FULL_ENTRY, capture_status="needs_info", capture_note="client not in roster")
        self.assertEqual(mcp_views.slim_entry(entry)["needs_info"], "client not in roster")


class SlimSessionTests(unittest.TestCase):
    def test_active_session_shape(self) -> None:
        slim = mcp_views.slim_session(FULL_SESSION)
        self.assertEqual(slim["client"], "Client B")
        self.assertEqual(slim["task"], "tax question")
        self.assertEqual(slim["started_at"], "2026-05-28T10:00:00")
        self.assertEqual(slim["needs_info"], "client not in roster")
        self.assertNotIn("status", slim)  # 'active' is implied
        self.assertNotIn("snoozed_until", slim)  # None -> omitted

    def test_non_active_status_included(self) -> None:
        slim = mcp_views.slim_session(dict(FULL_SESSION, status="canceled", capture_status="resolved"))
        self.assertEqual(slim["status"], "canceled")

    def test_none_session(self) -> None:
        self.assertIsNone(mcp_views.slim_session(None))


class ShapeTests(unittest.TestCase):
    def test_review_view_slims_entries_and_drops_audit_fields(self) -> None:
        result = {
            "date": "2026-05-28",
            "entries": [dict(FULL_ENTRY, needs_review_reason=None)],
            "active_session": FULL_SESSION,
            "active_timer_warning": {
                "has_active_timer": True, "session": {}, "client_name": "Client B",
                "task_text": "tax question", "started_at": "2026-05-28T10:00:00",
                "last_checkin_at": "2026-05-28T10:00:00", "snoozed_until": None,
                "open_minutes": 47, "is_stale": False, "prompt_reason": "active_timer_open",
                "suggested_actions": ["checkin", "end", "switch", "snooze", "cancel"],
            },
            "totals": {"draft_minutes": 30, "approved_minutes": 0, "exported_minutes": 0,
                       "needs_info_minutes": 0, "skipped_needs_info_minutes": 0},
            "skipped_needs_info_count": 0,
            "skipped_needs_info_minutes": 0,
            "event_count": 12,
            "last_activity_at": "2026-05-28T10:00:00",
            "review_token": "abc123",
        }
        shaped = mcp_views.shape("review", result)
        self.assertEqual(shaped["review_token"], "abc123")
        self.assertEqual(shaped["entries"][0]["minutes"], 30)
        self.assertNotIn("event_count", shaped)
        self.assertNotIn("last_activity_at", shaped)
        self.assertNotIn("active_session", shaped)
        self.assertNotIn("active_timer_warning", shaped)
        timer = shaped["active_timer"]
        self.assertEqual(timer["open_minutes"], 47)
        self.assertFalse(timer["is_stale"])
        self.assertEqual(timer["session"]["client"], "Client B")
        self.assertEqual(timer["suggested_actions"], ["checkin", "end", "switch", "snooze", "cancel"])

    def test_review_view_omits_timer_when_idle(self) -> None:
        result = {
            "date": "2026-05-28", "entries": [], "active_session": None,
            "active_timer_warning": {"has_active_timer": False, "session": None,
                                     "prompt_reason": "idle", "suggested_actions": []},
            "totals": {"draft_minutes": 0}, "skipped_needs_info_count": 0,
            "skipped_needs_info_minutes": 0, "event_count": 1,
            "last_activity_at": None, "review_token": "t",
        }
        shaped = mcp_views.shape("review", result)
        self.assertNotIn("active_timer", shaped)

    def test_approve_all_view_drops_entries(self) -> None:
        shaped = mcp_views.shape("approve_all", {
            "date": "2026-05-28", "approved_count": 3,
            "skipped_needs_info_count": 1, "skipped_needs_info_minutes": 12,
            "entries": [FULL_ENTRY] * 3,
        })
        self.assertEqual(shaped["approved_count"], 3)
        self.assertNotIn("entries", shaped)

    def test_reround_view_returns_total_instead_of_entries(self) -> None:
        shaped = mcp_views.shape("reround", {
            "date": "2026-05-28", "rule": "nearest_15_minutes", "rerounded_count": 2,
            "entries": [dict(FULL_ENTRY, rounded_minutes=30), dict(FULL_ENTRY, rounded_minutes=15)],
        })
        self.assertEqual(shaped["total_draft_minutes"], 45)
        self.assertNotIn("entries", shaped)

    def test_export_view_consolidates_paths(self) -> None:
        shaped = mcp_views.shape("export", {
            "date": "2026-05-28", "format": "quickbooks-csv",
            "output": "/data/exports/q.csv", "exported_count": 2,
            "skipped_needs_info_count": 0, "skipped_needs_info_minutes": 0,
            "entries": [FULL_ENTRY] * 2, "backup": "/data/backups/b.sqlite",
            "user_export_dir": "/home/u/Documents/TimeAssist Exports",
            "user_visible_output": "/home/u/Documents/TimeAssist Exports/q.csv",
            "user_visible_copy_error": None,
        })
        self.assertEqual(shaped["csv"], "/home/u/Documents/TimeAssist Exports/q.csv")
        self.assertEqual(shaped["official_csv"], "/data/exports/q.csv")
        self.assertEqual(shaped["exported_count"], 2)
        self.assertNotIn("entries", shaped)
        self.assertNotIn("backup", shaped)
        self.assertNotIn("backup_warning", shaped)

    def test_export_view_warns_when_backup_failed(self) -> None:
        shaped = mcp_views.shape("export", {
            "date": "2026-05-28", "format": "quickbooks-csv", "output": "/data/exports/q.csv",
            "exported_count": 1, "skipped_needs_info_count": 0, "skipped_needs_info_minutes": 0,
            "entries": [FULL_ENTRY], "backup": None,
            "user_export_dir": "/d", "user_visible_output": None,
            "user_visible_copy_error": "disk full",
        })
        self.assertEqual(shaped["csv"], "/data/exports/q.csv")
        self.assertEqual(shaped["copy_error"], "disk full")
        self.assertIn("backup_warning", shaped)

    def test_checkin_status_idle_is_tiny(self) -> None:
        shaped = mcp_views.shape("checkin_status", {
            "active": False, "session": None, "open_minutes": None,
            "minutes_since_checkin": None, "snoozed_until": None, "should_prompt": False,
            "prompt_reason": "idle", "is_stale": False, "checkin_interval_minutes": 45,
            "stale_session_minutes": 480, "suggested_actions": [],
        })
        self.assertEqual(shaped, {"active": False, "should_prompt": False})

    def test_status_view_drops_db_path(self) -> None:
        shaped = mcp_views.shape("status", {"db_path": "/x.sqlite", "size_bytes": 1, "size_human": "1 B"})
        self.assertNotIn("db_path", shaped)

    def test_unknown_tool_passes_through_with_nones_dropped(self) -> None:
        shaped = mcp_views.shape("config", {"settings": {"rounding_rule": "exact"}, "noise": None})
        self.assertEqual(shaped, {"settings": {"rounding_rule": "exact"}})


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run to verify failure**

Run: `python3 -m unittest tests.test_mcp_views -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'timeassist.mcp_views'` (or ImportError).

- [ ] **Step 3: Implement `timeassist/mcp_views.py`**

```python
"""Model-facing views of action results for the MCP server.

The deterministic core (actions.py) and the CLI return full row dicts for
audit and debugging. Every byte of an MCP tool result is read by the model in
Cowork, so this module trims each result to what the assistant actually needs:
audit metadata is dropped, null fields are omitted, and entry lists the model
has already seen in `review` are summarized to counts. Shaping must only ever
remove or rename fields for the model — never alter the engine's stored state.
"""

from __future__ import annotations

from typing import Any


def drop_nones(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: drop_nones(item) for key, item in value.items() if item is not None}
    if isinstance(value, list):
        return [drop_nones(item) for item in value]
    return value


def slim_entry(entry: dict[str, Any]) -> dict[str, Any]:
    slim: dict[str, Any] = {
        "entry_id": entry.get("entry_id"),
        "client": entry.get("client_name"),
        "task": entry.get("task_text"),
        "billable": "yes" if entry.get("billable") else "no",
        "start": entry.get("start_at"),
        "end": entry.get("end_at"),
        "minutes": entry.get("rounded_minutes"),
        "status": entry.get("review_status"),
    }
    if entry.get("duration_minutes") != entry.get("rounded_minutes"):
        slim["raw_minutes"] = entry.get("duration_minutes")
    if entry.get("capture_status") == "needs_info":
        slim["needs_info"] = entry.get("capture_note") or entry.get("needs_review_reason") or "needs_info"
    return slim


def slim_session(session: dict[str, Any] | None) -> dict[str, Any] | None:
    if not session:
        return None
    slim: dict[str, Any] = {
        "client": session.get("client_name"),
        "task": session.get("task_text"),
        "started_at": session.get("started_at"),
    }
    if session.get("last_checkin_at") and session.get("last_checkin_at") != session.get("started_at"):
        slim["last_checkin_at"] = session["last_checkin_at"]
    if session.get("snoozed_until"):
        slim["snoozed_until"] = session["snoozed_until"]
    if session.get("status") and session.get("status") != "active":
        slim["status"] = session["status"]
    if session.get("capture_status") == "needs_info":
        slim["needs_info"] = session.get("capture_note") or "needs_info"
    return slim


def _view_review(result: dict[str, Any]) -> dict[str, Any]:
    shaped: dict[str, Any] = {
        "date": result["date"],
        "entries": [slim_entry(entry) for entry in result["entries"]],
        "totals": result["totals"],
        "skipped_needs_info_count": result["skipped_needs_info_count"],
        "review_token": result["review_token"],
    }
    warning = result.get("active_timer_warning") or {}
    if warning.get("has_active_timer"):
        shaped["active_timer"] = {
            "session": slim_session(result.get("active_session")),
            "open_minutes": warning.get("open_minutes"),
            "is_stale": warning.get("is_stale"),
            "suggested_actions": warning.get("suggested_actions"),
        }
    if "html_output" in result:
        shaped["html_output"] = result["html_output"]
    return shaped


def _view_approve_all(result: dict[str, Any]) -> dict[str, Any]:
    return {
        "date": result["date"],
        "approved_count": result["approved_count"],
        "skipped_needs_info_count": result["skipped_needs_info_count"],
        "skipped_needs_info_minutes": result["skipped_needs_info_minutes"],
    }


def _view_reround(result: dict[str, Any]) -> dict[str, Any]:
    return {
        "date": result["date"],
        "rule": result["rule"],
        "rerounded_count": result["rerounded_count"],
        "total_draft_minutes": sum(int(entry["rounded_minutes"]) for entry in result["entries"]),
    }


def _view_export(result: dict[str, Any]) -> dict[str, Any]:
    shaped: dict[str, Any] = {
        "date": result["date"],
        "exported_count": result["exported_count"],
        "skipped_needs_info_count": result["skipped_needs_info_count"],
        "skipped_needs_info_minutes": result["skipped_needs_info_minutes"],
        "csv": result.get("user_visible_output") or result["output"],
    }
    if result.get("user_visible_output") and result["user_visible_output"] != result["output"]:
        shaped["official_csv"] = result["output"]
    if result.get("user_visible_copy_error"):
        shaped["copy_error"] = result["user_visible_copy_error"]
    if not result.get("backup"):
        shaped["backup_warning"] = "database backup failed at export time; export itself succeeded"
    return shaped


def _view_checkin_status(result: dict[str, Any]) -> dict[str, Any]:
    if not result.get("active"):
        return {"active": False, "should_prompt": False}
    shaped: dict[str, Any] = {
        "active": True,
        "session": result["session"],
        "open_minutes": result["open_minutes"],
        "minutes_since_checkin": result["minutes_since_checkin"],
        "should_prompt": result["should_prompt"],
        "prompt_reason": result["prompt_reason"],
        "is_stale": result["is_stale"],
    }
    if result.get("snoozed_until"):
        shaped["snoozed_until"] = result["snoozed_until"]
    return shaped


def _view_status(result: dict[str, Any]) -> dict[str, Any]:
    shaped = dict(result)
    shaped.pop("db_path", None)
    return shaped


def _view_entry(result: dict[str, Any]) -> dict[str, Any]:
    return slim_entry(result)


def _view_session(result: dict[str, Any]) -> dict[str, Any]:
    return slim_session(result) or {}


def _view_switch(result: dict[str, Any]) -> dict[str, Any]:
    return {
        "closed_entry": slim_entry(result["closed_entry"]),
        "new_session": slim_session(result["new_active_session"]),
    }


def _view_list_clients(result: dict[str, Any]) -> dict[str, Any]:
    return {
        "clients": [
            {key: client[key] for key in ("client_key", "display_name", "aliases", "default_billable") if key in client}
            for client in result.get("clients", [])
        ]
    }


_VIEWS = {
    "review": _view_review,
    "approve_all": _view_approve_all,
    "reround": _view_reround,
    "export": _view_export,
    "checkin_status": _view_checkin_status,
    "status": _view_status,
    "list_clients": _view_list_clients,
    "switch": _view_switch,
    "start": _view_session,
    "clarify_active": _view_session,
    "cancel": _view_session,
    "checkin": _view_session,
    "snooze_checkin": _view_session,
    "end": _view_entry,
    "add_missing": _view_entry,
    "edit": _view_entry,
    "approve": _view_entry,
    "unapprove": _view_entry,
    "discard_entry": _view_entry,
}


def shape(tool_name: str, result: dict[str, Any]) -> dict[str, Any]:
    """Return the compact model-facing view of a tool result."""
    view = _VIEWS.get(tool_name)
    shaped = view(result) if view else result
    return drop_nones(shaped)
```

(Note: the `discard_entry` view entry is forward-compatible with Task 5; harmless before then.)

- [ ] **Step 4: Run the new tests**

Run: `python3 -m unittest tests.test_mcp_views -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add timeassist/mcp_views.py tests/test_mcp_views.py
git commit -m "feat: add model-facing MCP result views (compact entry/session shapes)"
```

---

### Task 3: Wire views into the MCP server and update existing MCP tests

**Files:**
- Modify: `timeassist/mcp_server.py` (import + `handle_message` tools/call branch)
- Modify: `tests/test_mcp_server.py` (assertions on old full-row keys)
- Modify: `tests/test_prototype_workflow.py` ONLY if it parses MCP output (it drives the CLI, so it should not need changes — verify, don't assume)

- [ ] **Step 1: Wire in the shaping**

In `timeassist/mcp_server.py`, add to the imports:

```python
from . import mcp_views
```

In `handle_message`, change the success path of `tools/call` to:

```python
            result = call_tool(name, arguments, db_path)
            result = mcp_views.shape(name, result)
            text = json.dumps(result, separators=(",", ":"), sort_keys=True)
```

Do NOT shape inside `call_tool` — `call_tool` is the raw dispatch and its full results stay available to any future caller.

- [ ] **Step 2: Run the MCP test module and inventory failures**

Run: `python3 -m unittest tests.test_mcp_server -v`
Expected: several FAILs where tests assert old full-row keys. Known ones (verify each, there may be more):
- `tests/test_mcp_server.py:351` — `edited["rounded_minutes"]` → change to `edited["minutes"]`
- `tests/test_mcp_server.py:375` — `added["rounded_minutes"]` → `added["minutes"]`
- `tests/test_mcp_server.py:396` — reround `result["entries"][0]["rounded_minutes"] == 30` → `result["total_draft_minutes"] == 30`
- Any assertion on `review_status` in a tool payload → key is now `status`
- Any assertion on `client_name`/`task_text` in a tool payload → keys are now `client`/`task` (entries) or `client`/`task` (sessions)
- Export assertions on `result["output"]` → now `result["csv"]` (and `official_csv` when a user-visible copy exists)
- `review` payload assertions on `active_timer_warning` → now `active_timer` (present only when a timer is open)

Update each failing assertion to the new view contract from Task 2. The view module is the source of truth; do not weaken assertions to `assertIn` just to pass.

- [ ] **Step 3: Add a regression test for review slimness**

Add to `tests/test_mcp_server.py`:

```python
    def test_review_payload_is_slim(self) -> None:
        self.payload("init_state", {"at": "2026-05-28T09:00:00"})
        self.payload("start", {"client": "Client A", "task": "cleanup", "at": "2026-05-28T09:00:00"})
        self.payload("end", {"at": "2026-05-28T09:30:00"})
        review = self.payload("review", {"date": "2026-05-28"})
        self.assertNotIn("event_count", review)
        self.assertNotIn("last_activity_at", review)
        self.assertNotIn("active_session", review)
        self.assertNotIn("active_timer", review)  # idle: omitted entirely
        entry = review["entries"][0]
        self.assertEqual(sorted(entry), ["billable", "client", "end", "entry_id", "minutes", "start", "status", "task"])
```

(If the class helpers differ, adapt the calls to the file's existing helper style — read the top of the test class first.)

- [ ] **Step 4: Run the full suite**

Run: `python3 -m unittest discover -s tests -v`
Expected: all PASS. If `test_prototype_workflow.py` fails, it means CLI output leaked through MCP shaping — that must NOT happen; re-check that shaping only occurs in `handle_message`.

- [ ] **Step 5: Commit**

```bash
git add timeassist/mcp_server.py tests/test_mcp_server.py
git commit -m "perf: shape MCP tool results through model-facing views"
```

---

### Task 4: Plain-language error messages in the engine

**Files:**
- Modify: `timeassist/actions.py` lines 638, 720-721, 1161, 1163-1164, 1224-1225
- Test: `tests/test_actions.py`, `tests/test_mcp_server.py` (existing message assertions)

- [ ] **Step 1: Find existing assertions on the old messages**

Run: `grep -rn "already exists for\|cannot move the switch\|run review first\|is stale; run review\|clarify or edit it before approval" tests/`
Note each hit; they will be updated in Step 3.

- [ ] **Step 2: Apply the five message changes in `timeassist/actions.py`**

1. Line 638 (`start_session`):
```python
            raise ValueError(
                f"a timer is already running for {active['client_name']} — {active['task_text']} "
                f"(started {active['started_at']}); use switch to change clients or end to stop it"
            )
```

2. Lines 720-721 (`switch_session`):
```python
        if active and parse_at(switched_at) < parse_at(active["started_at"]):
            raise ValueError(
                f"that switch time ({switched_at}) is before the current timer started "
                f"({active['started_at']}); confirm when the switch actually happened"
            )
```

3. Line 1161 (`validate_review_token`, missing token):
```python
        raise ValueError("review_token is required: call review for this date first and pass back its review_token")
```

4. Lines 1163-1164 (stale token):
```python
        raise ValueError(
            "review_token is stale because the day's entries changed after that review; "
            "call review again, show the operator the refreshed day, then retry"
        )
```

5. Lines 1224-1225 (`set_approval` needs_info rejection):
```python
        if before["review_status"] == "needs_info" or before.get("capture_status") == "needs_info":
            note = before.get("capture_note") or "missing client/task details"
            raise ValueError(f"entry {entry_id} needs clarification before approval ({note}); fix it with edit")
```

- [ ] **Step 3: Update the test assertions found in Step 1**

Update each assertion to match the new wording. Keep `assertIn("review_token", ...)`-style substring checks as-is where they still pass (e.g., `tests/test_mcp_server.py:173,182,207` check only for the substring `review_token`, which survives).

- [ ] **Step 4: Run the full suite**

Run: `python3 -m unittest discover -s tests -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add timeassist/actions.py tests/
git commit -m "feat: plain-language engine errors an assistant can relay verbatim"
```

---

### Task 5: `discard_entry` — soft-delete mistaken captures

**Files:**
- Modify: `timeassist/actions.py` (new function after `edit_entry`; one query change in `list_entries_for_date`; one guard in `set_approval` and `edit_entry`)
- Modify: `timeassist/mcp_server.py` (new TOOLS def + `call_tool` dispatch)
- Test: `tests/test_actions.py`, `tests/test_mcp_server.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_actions.py` (new test class, using the same temp-db setup pattern as neighbouring classes):

```python
class DiscardEntryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = str(Path(self.tmp.name) / "t.sqlite")
        actions.init_state(self.db, "2026-05-28T08:00:00")
        actions.start_session(self.db, "Client A", "cleanup", at="2026-05-28T09:00:00")
        self.entry = actions.end_session(self.db, at="2026-05-28T09:30:00")

    def test_discard_hides_entry_from_review_and_export(self) -> None:
        result = actions.discard_entry(self.db, self.entry["entry_id"], at="2026-05-28T09:31:00")
        self.assertEqual(result["review_status"], "discarded")
        review = actions.review_entries(self.db, "2026-05-28")
        self.assertEqual(review["entries"], [])
        with self.assertRaises(ValueError):
            actions.export_entries(self.db, "2026-05-28", str(Path(self.tmp.name) / "out.csv"))

    def test_discarded_entry_cannot_be_approved_or_edited(self) -> None:
        actions.discard_entry(self.db, self.entry["entry_id"])
        with self.assertRaisesRegex(ValueError, "discarded"):
            actions.set_approval(self.db, self.entry["entry_id"], True)
        with self.assertRaisesRegex(ValueError, "discarded"):
            actions.edit_entry(self.db, self.entry["entry_id"], task="nope")

    def test_only_draft_or_needs_info_can_be_discarded(self) -> None:
        review = actions.review_entries(self.db, "2026-05-28")
        actions.set_approval(self.db, self.entry["entry_id"], True)
        with self.assertRaisesRegex(ValueError, "approved"):
            actions.discard_entry(self.db, self.entry["entry_id"])

    def test_discard_is_audit_logged_and_row_kept(self) -> None:
        actions.discard_entry(self.db, self.entry["entry_id"])
        with actions.connect(self.db) as conn:
            row = conn.execute("SELECT review_status FROM time_entries WHERE entry_id = ?", (self.entry["entry_id"],)).fetchone()
            event = conn.execute("SELECT COUNT(*) AS c FROM event_log WHERE event_type = 'discard'").fetchone()
        self.assertEqual(row["review_status"], "discarded")
        self.assertEqual(event["c"], 1)
```

(Match the import style at the top of `tests/test_actions.py` — it already imports `actions`, `tempfile`, `Path`, `unittest`; reuse, don't duplicate.)

Add to `tests/test_mcp_server.py`:

```python
    def test_discard_entry_requires_confirm(self) -> None:
        self.payload("init_state", {"at": "2026-05-28T09:00:00"})
        self.payload("start", {"client": "Client A", "task": "cleanup", "at": "2026-05-28T09:00:00"})
        entry = self.payload("end", {"at": "2026-05-28T09:30:00"})
        result = self.call("discard_entry", {"entry_id": entry["entry_id"]})
        self.assertTrue(result.get("isError"))
        discarded = self.payload("discard_entry", {"entry_id": entry["entry_id"], "confirm": True})
        self.assertEqual(discarded["status"], "discarded")
```

- [ ] **Step 2: Run to verify failure**

Run: `python3 -m unittest tests.test_actions.DiscardEntryTests tests.test_mcp_server -v`
Expected: FAIL with `AttributeError: ... no attribute 'discard_entry'` and unknown-tool error.

- [ ] **Step 3: Implement in `timeassist/actions.py`**

Insert after `edit_entry` (~line 1118):

```python
def discard_entry(db_path: str | Path, entry_id: int, at: str | None = None) -> dict[str, Any]:
    """Soft-delete a mistaken capture. The row is kept forever (review_status
    'discarded') so billing history is never destroyed; it is hidden from
    review and can never be approved or exported. Recovery is add_missing."""
    ensure_initialized(db_path)
    changed_at = iso(parse_at(at)) if at else now_iso()
    with connect(db_path) as conn:
        before = row_to_dict(conn.execute("SELECT * FROM time_entries WHERE entry_id = ?", (entry_id,)).fetchone())
        if not before:
            raise ValueError(f"entry {entry_id} not found")
        if before["review_status"] not in {"draft", "needs_info"}:
            raise ValueError(
                f"entry {entry_id} is {before['review_status']}; only draft or needs_info entries "
                "can be discarded (unapprove an approved entry first)"
            )
        conn.execute(
            "UPDATE time_entries SET review_status = 'discarded', updated_at = ? WHERE entry_id = ?",
            (changed_at, entry_id),
        )
        after = row_to_dict(conn.execute("SELECT * FROM time_entries WHERE entry_id = ?", (entry_id,)).fetchone())
        log_event(conn, "discard", f"discarded entry {entry_id} (never billed)", "time_entry", entry_id, before=before, after=after, at=changed_at)
        conn.commit()
    return after
```

Change `list_entries_for_date` (line 1120) to exclude discarded rows:

```python
        SELECT * FROM time_entries
        WHERE substr(start_at, 1, 10) = ? AND review_status != 'discarded'
        ORDER BY start_at, entry_id
```

Add a guard at the top of `set_approval` (after the not-found check, before the `exported` check):

```python
        if before["review_status"] == "discarded":
            raise ValueError(f"entry {entry_id} was discarded; use add_missing to recreate it if it should be billed")
```

And in `edit_entry`, the existing guard already rejects non-draft statuses, but its message says "unapprove first", which is wrong for discarded entries. Change line 1054-1055 to:

```python
        if before["review_status"] not in {"draft", "needs_info"}:
            if before["review_status"] == "discarded":
                raise ValueError(f"entry {entry_id} was discarded; use add_missing to recreate it")
            raise ValueError(f"entry {entry_id} is {before['review_status']}; only draft entries can be edited (unapprove first)")
```

Note: `approve_all` and `export_entries` filter on `review_status IN ('draft'/'approved'/'exported')`, so discarded rows are already excluded there — no change needed. `review_token` is computed from `list_entries_for_date` output, so discarding an entry correctly invalidates outstanding tokens.

- [ ] **Step 4: Implement in `timeassist/mcp_server.py`**

Append to `TOOLS` (after the `cleanup` entry):

```python
    {
        "name": "discard_entry",
        "description": "Discard a mistaken draft/needs_info capture so it is never billed. Kept in the database for audit but hidden from review and export. Requires explicit operator confirmation.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "entry_id": {"type": "integer"},
                "confirm": {"type": "boolean", "description": "Required true after the operator confirms the discard."},
                "at": {"type": "string", "description": "Optional ISO timestamp."},
            },
            "required": ["entry_id"],
        },
    },
```

Add to `call_tool` (next to the other entry tools):

```python
    if name == "discard_entry":
        _require_confirm(arguments, "discarding an entry")
        return actions.discard_entry(db_path, int(arguments["entry_id"]), arguments.get("at"))
```

If `tests/test_mcp_server.py:48` (`test_tools_list_exposes_all_actions`) asserts a tool count or name list, add `discard_entry` there.

- [ ] **Step 5: Run the full suite**

Run: `python3 -m unittest discover -s tests -v`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add timeassist/actions.py timeassist/mcp_server.py tests/
git commit -m "feat: add discard_entry soft delete for mistaken captures"
```

---

### Task 6: Pin the never-round-to-zero billing floor

**Files:**
- Modify: `timeassist/actions.py:84-89` (comment only)
- Test: `tests/test_actions.py`

- [ ] **Step 1: Write the pinning test**

Add to the existing rounding test class in `tests/test_actions.py`:

```python
    def test_nearest_rounding_never_drops_positive_work_to_zero(self) -> None:
        # Billing floor: a positive entry must never round to 0 and silently
        # vanish from the export. 2 raw minutes under nearest_6 bills one
        # full increment (6), matching the sub-30s -> 1 raw minute rule.
        self.assertEqual(actions.round_minutes(2, 6, "nearest"), 6)
        self.assertEqual(actions.round_minutes(2, 15, "nearest"), 15)
        self.assertEqual(actions.round_minutes(0, 6, "nearest"), 0)
```

- [ ] **Step 2: Run it (expected PASS — behavior already exists)**

Run: `python3 -m unittest tests.test_actions -v`
Expected: PASS. This test pins intentional behavior; it is documentation, not a bug fix.

- [ ] **Step 3: Add the explaining comment in `actions.py`**

Change lines 87-89 to:

```python
    lower = minutes - remainder
    upper = lower + increment
    # Billing floor: when "nearest" would round a positive entry down to 0,
    # bill one full increment instead — work done must never silently vanish
    # from the export (mirrors the >=1 raw-minute rule in minutes_between).
    return upper if remainder >= increment / 2 else max(increment, lower)
```

- [ ] **Step 4: Run suite and commit**

Run: `python3 -m unittest discover -s tests -v` — all PASS.

```bash
git add timeassist/actions.py tests/test_actions.py
git commit -m "test: pin never-round-to-zero billing floor with test and comment"
```

---

### Task 7: Trim MCP tool descriptions (per-session schema cost)

**Files:**
- Modify: `timeassist/mcp_server.py` `TOOLS` list

- [ ] **Step 1: Apply exact replacement descriptions**

Replace these `description` strings (tool-level and the repeated property-level ones). Keep everything not listed here unchanged.

1. The `billable` property description, which appears in `start`, `switch`, and `add_missing`:
   - Old: `"Omit to use the client roster's billable default (falls back to yes)."`
   - New: `"Omit to use roster default (else yes)."`
2. `switch` tool description →
   `"Close the active session at the switch time and immediately start a new one. Unknown labels are captured as needs_info, never blocked."`
3. `export` tool description →
   `"Export approved entries for a date to a QuickBooks-ready CSV. Only already-approved entries are written; the official CSV stays under TimeAssist data and is also copied to the operator's export folder."`
4. `reround` tool description →
   `"Re-apply a rounding rule to a date's DRAFT entries from stored raw durations. Approved/exported entries never change. Setting rule requires confirm=true; 'exact' restores raw."`
5. `import_clients` tool description →
   `"Import a client roster CSV (client_key, display_name, aliases, default_billable). mode 'replace' (default, requires confirm_replace=true) reloads the roster; 'merge' upserts by client_key."`
6. `checkin_status` tool description →
   `"Report whether a tracking session is open (read-only). Call when a scheduled reminder fires; stay silent unless should_prompt=true. Reply mapping: still->checkin, switched->switch, done->end, snooze->snooze_checkin, mistake->cancel."`
7. `approve_all` tool description →
   `"Approve ALL draft entries for a date. Only when the operator explicitly asks to approve everything from the current review — never on your own initiative."`
8. `config` property descriptions:
   - `user_export_dir` → `"Persist an operator-chosen folder where each official export is copied (may be outside plugin data)."`
   - `clear_user_export_dir` → `"Reset the export copy folder to the default Documents/TimeAssist Exports."`
   - `confirm_default_user_export_dir` → `"Record that the operator accepted the default Documents/TimeAssist Exports folder."`

Rationale for keeping `checkin_status`'s reply mapping in the description: it lets Task 2's view drop the constant `suggested_actions` array from every result.

- [ ] **Step 2: Verify schemas still validate and tests pass**

Run: `python3 -m unittest discover -s tests -v`
Expected: all PASS (`test_tools_list_exposes_all_actions` checks names/shape, not prose — verify no test asserts description text; if one does, update it).

- [ ] **Step 3: Commit**

```bash
git add timeassist/mcp_server.py
git commit -m "perf: trim MCP tool descriptions loaded every session"
```

---

### Task 8: Tighten SKILL.md to the new contract

**Files:**
- Modify: `plugin/timeassist/skills/billable-time-assistant/SKILL.md` (full replacement below)
- Guard: `tests/test_plugin_data_paths.py:56` (`test_plugin_skill_documents_server_side_gates`) greps for required phrases — the replacement below contains all of them; do not edit them out: `review_token`, `confirm_replace`, `confirm=true`, ``run `review` first``, ``paths must stay under `${CLAUDE_PLUGIN_DATA}` ``, `user_export_dir`, `Documents/TimeAssist Exports`, `do not manually recreate`, `switch immediately`, `clarify_active`, `needs_info`.

- [ ] **Step 1: Replace the entire file content with:**

````markdown
---
name: billable-time-assistant
description: Capture, review, correct, approve, and export billable time via the local timeassist MCP server. Use whenever the operator wants to start/switch/end a time block, log forgotten time, edit or review draft entries, approve them, export a QuickBooks-ready CSV, or produce a sanitized packet.
---

# Billable Time Assistant

## Principle

You are not the timer and not the billing authority. The deterministic TimeAssist
engine owns all time math, rounding, approval state, and exports. Map the
operator's intent to one tool call. Never compute durations, totals, or rounding
yourself, and never record anything in prose — every change goes through a tool.

## Tools (timeassist MCP server)

| Intent | Tool | Required args |
|---|---|---|
| Initialize local state | `init_state` | — |
| Begin tracking | `start` | `client`, `task` |
| Move to a new task | `switch` | `client`, `task` (`minutes_ago` for "switched N minutes ago") |
| Clarify active timer labels | `clarify_active` | any of `client`, `task`, `billable` |
| Stop tracking | `end` | — |
| Log forgotten time | `add_missing` | `client`, `task`, `start`, `end` |
| Correct a draft/needs_info entry | `edit` | `entry_id` + fields to change |
| Discard a mistaken capture | `discard_entry` | `entry_id`, `confirm=true` after operator confirms |
| See the day | `review` | — (`date` defaults today) |
| Confirm one entry | `approve` | `entry_id`, current `review_token` |
| Confirm all of a day | `approve_all` | current `review_token` |
| Undo an approval | `unapprove` | `entry_id` |
| Produce QuickBooks CSV | `export` | current `review_token` |
| Anonymized packet | `sanitize_packet` | — |
| Re-round a day's drafts | `reround` | `confirm=true` when setting `rule` |
| Import client roster | `import_clients` | `path` (`confirm_replace=true` for replace) |
| List client roster | `list_clients` | — |
| Discard the active session | `cancel` | — |
| Reminder: session open? | `checkin_status` | — |
| Confirm still working | `checkin` | — |
| Pause reminder prompts | `snooze_checkin` | `minutes` |
| Database footprint | `status` | — |
| Trim audit log | `cleanup` | `confirm=true` |
| Show/set settings | `config` | `confirm=true` when changing anything |

Entries in tool results are compact: `entry_id`, `client`, `task`, `billable`,
`start`, `end`, `minutes` (billable minutes after rounding), `status`
(draft/approved/exported/needs_info), plus `raw_minutes` when rounding changed
the value and `needs_info` (the reason) when clarification is required.

## Workflow

1. Map the intent to one tool. Ask only for genuinely missing required fields,
   one short question at a time.
2. **Capture now, clarify later:** on a client change, **switch immediately**.
   Questions are for labeling cleanup only, never before starting the timer.
   If a result carries `needs_info`, fix labels with `clarify_active` while the
   timer is open, or `edit` after it closed.
3. Report the exact tool result — entry id, `minutes`, `status`. Never
   pre-calculate.
4. Approval and export act on what the operator last saw: run `review` first,
   pass its `review_token`, and re-run `review` whenever entries change or the
   server reports a stale token.
5. Fix mistakes with `edit` (draft/needs_info only; approved entries must be
   unapproved first). For a capture that should never be billed, confirm with
   the operator, then `discard_entry` with `confirm=true`.
6. When `init_state` or `config` returns `export_folder.survey_required=true`:
   explain that the official CSV stays inside plugin data for audit safety and
   a copy goes to `Documents/TimeAssist Exports`. Ask: keep that default or
   choose a folder? Default → `config` with `confirm_default_user_export_dir=true`
   and `confirm=true`; custom → `user_export_dir` with `confirm=true`. Once
   `survey_required=false`, stop asking.

## Rounding (raw by default)

Time records raw. Once per day (first `start` or first `review`), say so and
offer: keep raw, nearest 6, round up 6, nearest 15, round up 15. If the operator
picks one, call `reround` with the matching `rule` (`nearest_6_minutes`,
`up_6_minutes`, `nearest_15_minutes`, `up_15_minutes`, `exact`) and
`confirm=true`, then report `total_draft_minutes` from the result. `exact`
restores raw. Approved/exported entries never re-round. Rounding is always an
explicit, logged operator choice — never silent.

## Client roster

Import once with `import_clients` (CSV: `client_key, display_name, aliases,
default_billable`). In plugin installs, import and output paths must stay under
`${CLAUDE_PLUGIN_DATA}`; ask the helper to place the CSV there. Pass
`confirm_replace` only after the operator confirms replacing the existing
roster. The engine resolves aliases to canonical names and applies billable
defaults, so don't ask about billable for known clients. Unknown clients are
soft: recorded as typed, marked `needs_info`, never blocked — clean up with
`clarify_active` or `edit` before approval/export.

## Recovery (interrupted sessions)

Every action commits to the local database; a crash or closed chat loses
nothing. When `review` returns `active_timer`, surface it before
approval/export: say which client/task is open and for how many minutes
(`open_minutes`), and offer its `suggested_actions`. If `is_stale=true` or
`checkin_status.prompt_reason` is `stale_session`, the timer is likely
forgotten: ask for the honest stop/switch time — never invent it. For a fresh
same-day session, keep the tone light; this is self-report, not monitoring.

## Reminders (Honest Nudge Loop)

When a scheduled reminder fires, call `checkin_status`. If `active=false` or
`should_prompt=false`, say nothing. Otherwise ask one short correction prompt:
"TimeAssist has Client A — monthly cleanup open for 47 minutes. Still the right
timer, or did work shift?" Replies map to tools: "still" → `checkin`;
"switched to X" → `switch` (add `minutes_ago` if they say when); "done" /
"stopped at 10:40" → `end` (with `at`); "pause for 30" → `snooze_checkin`;
"that was a mistake" → `cancel`. Say "TimeAssist has X open", never "I noticed
you working on X". Setup is one-time: walk the operator through a recurring
Cowork task (every 30–60 min) that asks you to run `checkin_status` and prompt
only if `should_prompt=true`.

## Human-approval gate

The operator is the billing authority — act only on what they ask for:

- Approve only what the operator asks: one entry (`approve`) or a whole day
  (`approve_all`) only when they explicitly say to approve everything. Entries
  with `needs_info` must be clarified first — the server skips or rejects them.
  Before either tool, run `review` first and pass the current `review_token`.
- **Never call `export` unless explicitly asked.** Export writes only
  already-approved entries; leftover drafts are expected, not an error to fix
  by approving. Run `review` first and pass the current `review_token`; if it
  is stale, review again and confirm the refreshed state with the operator.
- `discard_entry`, `cleanup`, and `config` changes need explicit operator
  confirmation and `confirm=true`.
- In plugin mode, model-supplied output/import paths must stay under
  `${CLAUDE_PLUGIN_DATA}`. Export results return `csv` — the copy in
  `Documents/TimeAssist Exports` or the operator's `user_export_dir` — and
  `official_csv` for the audit copy; do not manually recreate export CSVs.
- "Just finish the day" → stop at `review`, show what's unapproved, and let
  the operator choose.

## Housekeeping & privacy

- `status` shows the local footprint. Time entries are kept forever; `cleanup`
  trims only the audit log (default 90 days) and also runs automatically about
  daily. Exports back up the database automatically (last 5 kept).
- Synthetic or explicitly approved data only while this is a prototype. Never
  send raw client/work data off this machine; run `sanitize_packet` before
  sharing anything externally. Do not read `.env`, credentials, or unrelated
  folders.
````

- [ ] **Step 2: Run the gate test and full suite**

Run: `python3 -m unittest tests.test_plugin_data_paths -v && python3 -m unittest discover -s tests -v`
Expected: all PASS — especially `test_plugin_skill_documents_server_side_gates`.

- [ ] **Step 3: Commit**

```bash
git add plugin/timeassist/skills/billable-time-assistant/SKILL.md
git commit -m "docs: tighten plugin skill to compact tool contract (~45% smaller)"
```

---

### Task 9: Docs hygiene

**Files:**
- Delete: `docs/architecture.md` (superseded by `docs/wiki/Architecture.md`, still references the dropped `service_codes` table)
- Modify: `README.md` (the paragraph at line ~139)
- Modify: `docs/decision-log.md` (append entry)

- [ ] **Step 1: Remove the stale architecture stub**

```bash
git rm docs/architecture.md
```

Then run `grep -rn "docs/architecture.md" README.md docs/ .github/ plugin/` and update any link to point to `docs/wiki/Architecture.md`.

- [ ] **Step 2: Clarify the README export-folder paragraph**

In `README.md`, replace the paragraph beginning "The plugin pins its database to" with:

```markdown
The plugin pins its database to `${CLAUDE_PLUGIN_DATA}/timeassist.sqlite`. The official export CSV, review HTML, sanitized packets, and backups live in subfolders next to that database (`exports/`, `backups/`, …) — that internal copy is the audit source of truth. Every export also copies the exact CSV bytes to a user-visible folder so the accountant can find it: `Documents/TimeAssist Exports` by default, or the folder chosen via `config` `user_export_dir` (requires `confirm=true`).
```

- [ ] **Step 3: Append to `docs/decision-log.md`**

Read the file's entry format first, then append (match the established format):

```markdown
## 2026-06-09 — MCP results shaped at the boundary; entries soft-delete only

- MCP tool results are shaped in `timeassist/mcp_views.py` (compact JSON, slim
  entries, no echoed entry lists); `actions.py`/CLI keep full-fidelity dicts.
- Mistaken captures are discarded via `review_status='discarded'` (hidden from
  review/approval/export, kept forever, audit-logged) — never hard-deleted.
- The review_token gate is unchanged: mutations do not return fresh tokens;
  the operator must see a refreshed review before approval/export.
```

- [ ] **Step 4: Run suite and commit**

Run: `python3 -m unittest discover -s tests -v` — all PASS.

```bash
git add -A
git commit -m "docs: remove stale architecture stub, clarify export paths, log decisions"
```

---

### Task 10: Version bump, changelog, final verification

**Files:**
- Modify: `timeassist/__init__.py` (`__version__ = "0.1.19"`)
- Modify: `plugin/timeassist/.claude-plugin/plugin.json` (`"version": "0.1.19"`)
- Modify: `CHANGELOG.md`

- [ ] **Step 1: Bump both versions to `0.1.19`** (a test enforces they match: `test_release_version_surfaces_match_manifest_semver`).

- [ ] **Step 2: Add a CHANGELOG entry** (match the file's existing format; read it first):

```markdown
## 0.1.19 — 2026-06-09

Token efficiency and conversational UX for the Cowork pilot.

- MCP tool results are now compact: no pretty-printing, slim entry/session
  shapes, no echoed entry lists from approve_all/reround/export, and null
  fields omitted (~50–70% smaller results on a typical day).
- New `discard_entry` tool: soft-delete a mistaken capture (kept for audit,
  hidden from review/approval/export, requires operator confirmation).
- Plain-language engine errors the assistant can relay verbatim (running-timer
  conflicts, stale review_token, needs_info approval rejections).
- Export results now warn when the automatic database backup failed.
- Trimmed MCP tool descriptions and a ~45% smaller SKILL.md.
```

- [ ] **Step 3: Full verification**

```bash
python3 -m unittest discover -s tests -v
python3 scripts/timeassist.py --version       # expect 0.1.19
printf '%s\n' \
  '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18"}}' \
  '{"jsonrpc":"2.0","id":2,"method":"tools/list"}' \
  | python3 scripts/timeassist_mcp.py --db /tmp/smoke-0119.sqlite
```

Expected: all tests pass; version prints 0.1.19; tools/list includes `discard_entry` (23 tools).

- [ ] **Step 4: Commit**

```bash
git add timeassist/__init__.py plugin/timeassist/.claude-plugin/plugin.json CHANGELOG.md
git commit -m "chore: bump TimeAssist pilot version to 0.1.19"
```

- [ ] **Step 5: Ship per repo workflow** — push the feature branch, open a PR (direct `main` pushes are blocked). Tag `v0.1.19-prototype` only after merge, which triggers the Windows CI build. Watch with `gh run watch <RUN_ID> --exit-status` (read the exit code directly; do not chain commands).

---

## Out of scope for this pass (noted for the roadmap, do not implement)

- Week-level / date-range review and approval (single-day only today).
- Cross-midnight entries appear only under their start date — document, don't change.
- Splitting `actions.py` (HTML rendering, capture helpers) into modules — pure refactor, separate PR.
- Review-token auto-refresh on mutation — rejected; weakens the human gate.
- Pagination for `list_clients` — revisit if a pilot roster exceeds ~100 clients.
