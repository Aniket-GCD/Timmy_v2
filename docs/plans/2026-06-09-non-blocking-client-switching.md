# Non-Blocking Client Switching Implementation Plan

> **Status: SHIPPED** in v0.1.18-prototype (PR #24, merged 2026-06-09). Kept for reference — do not execute.

> **For Hermes:** Use the `subagent-driven-development` skill to implement this plan task-by-task. Dispatch fresh implementation subagents and require two-stage review: spec compliance first, code quality second.

**Goal:** Make TimeAssist's client-switch flow obey the product rule: when a user tries to switch clients, the timer switches immediately; any clarification happens after capture and never blocks timer creation.

**Architecture:** Keep `timeassist.actions.switch_session()` as the deterministic source of truth for time math. Extend the existing SQLite action contract so unresolved client/service labels are captured as reviewable metadata, then add CLI/MCP affordances and docs that force wrappers, Claude Code, Cowork, Trigger.dev, or a future frontend to call the deterministic switch before asking follow-up questions.

**Tech Stack:** Python 3.11, SQLite, argparse CLI, local MCP server, `unittest`, existing TimeAssist docs/plugin packaging.

**Reference baseline:**
- `timeassist/actions.py:654-679` already closes the old timer and creates the new active timer at the same `switched_at` timestamp.
- `timeassist/actions.py:657-661` already supports `minutes_ago` correction.
- `timeassist/actions.py:677` already writes a `switch` event with `closed_entry` and `new_active_session` in `after_json`.
- `timeassist/db.py` already has `time_entries.review_status` with `draft`, `approved`, and `exported`; review/export display paths have `needs_info` scaffolding, but this plan introduces the first deterministic write path for that status.
- Full baseline validation on 2026-06-09: `python3 -m unittest discover -s tests -v` ran 183 tests and passed.

**Subagent review status:** Codex and Claude Code both reviewed the plan on 2026-06-09 and returned `PASS_WITH_CHANGES`. This revision incorporates their required changes: assistant-facing guidance regression tests, explicit SQLite `ALTER TABLE` migration rules, no core fuzzy/ambiguous matching, deterministic metadata derivation via existing roster helpers, `minutes_ago` metadata coverage, post-close `needs_info` resolution through `edit_entry()`, approval/export skip visibility, exact plugin `SKILL.md` placement, and future-facing AI cost logging language.

## Current repo alignment check — 2026-06-09

Verified against `main` at `v0.1.17-prototype` / `timeassist 0.1.17` before creating `prep/non-blocking-switch-release`.

- Baseline tests still pass: `python3 -m unittest discover -s tests -v` returns 183/183 passing tests.
- `timeassist/actions.py` still has the expected implementation anchors: `close_active_session()` at line 613, `switch_session()` at line 654, `edit_entry()` at line 912, `review_entries()` at line 1007, `approve_all()` at line 1057, and `export_entries()` at line 1079.
- `switch_session()` still closes the old active timer and starts the new active timer in one transaction; `minutes_ago` remains the explicit retroactive correction path.
- `timeassist/db.py` still does **not** have `raw_client_name`, `raw_task_text`, `capture_status`, `capture_note`, or `clarified_at`, so Task 2 remains real work, not duplicate work.
- The Honest Nudge Loop from `v0.1.17` added check-in settings and tools; preserve those paths while adding `clarify_active` and capture-review metadata.
- `review_entries()` already totals `needs_info_minutes`, but no deterministic switch path writes `needs_info` yet.
- `edit_entry()` is still draft-only; Task 4 must expand it to allow `needs_info` entries to be resolved after close.
- `approve_all()` already scopes to `draft`; Task 5 must add skipped-`needs_info` visibility, not loosen approval.
- `export_entries()` already exports only `approved`/`exported`; Task 5 must add unresolved skipped counts/minutes for the date without exporting unresolved entries.
- Docs present for Task 6/7: `README.md`, `docs/accountant-quick-start.md`, `docs/architecture.md`, `docs/wiki/Architecture.md`, `docs/decision-log.md`, `docs/project-board.md`, and `plugin/timeassist/skills/billable-time-assistant/SKILL.md`.
- Release target after implementation should be `0.1.18` / `v0.1.18-prototype`; do not reuse the `0.1.17` nudge release.

---

## Product rule

> When a user tries to switch clients, the timer switches immediately. Any follow-up question is only for labeling/cleanup, never for starting the timer.

Required behavior examples:

- High confidence: `Switch to Acme payroll cleanup` → `Switched to Acme — Payroll Cleanup. Timer running.`
- Possible ambiguity, handled only by the assistant/frontend after deterministic capture: `Switch to Smith` → first call the switch tool and report `Switched to Smith at 2:14 PM. Timer running.` Then, if a wrapper has separately found possible roster candidates, it may ask `Did you mean Smith Payroll or Smith Tax? Reply 1 or 2 when you get a chance — the timer is already running.`
- Unknown client: `Switch to Henderson` → `Started time for “Henderson” at 2:14 PM. I don’t see that client in the roster yet, so I’ll mark it for review.`

The deterministic core does not fuzzy-match, rank, or choose between possible clients in v1. It performs exact display-name/alias matching only; any ambiguity prompt is a wrapper/UI convenience that runs after the new timer already exists.

---

## Non-goals

- Do not put AI in charge of timestamps, durations, rounding, approvals, audit logs, export status, or billing math.
- Do not add QuickBooks writeback.
- Do not require Trigger.dev or a hosted frontend for the local-kit switch fix.
- Do not reject unknown clients or assistant-detected ambiguous labels during switch. Capture first, review later.
- Do not add fuzzy matching that silently chooses a likely client without review evidence.

---

## Implementation sequence

### Task 1: Add explicit regression tests for immediate switch capture

**Objective:** Prove the current switch core starts the new timer before any clarification path can run.

**Files:**
- Modify: `tests/test_actions.py`
- Modify: `tests/test_mcp_server.py`
- Modify: `tests/test_prototype_workflow.py`

**Step 1: Add unit coverage for unknown-client switch**

In `tests/test_actions.py`, add a test near `CaptureRosterTests.test_switch_canonicalizes_and_applies_default`:

```python
def test_switch_unknown_client_starts_immediately_without_roster_match(self) -> None:
    actions.start_session(self.db, "Acme Co", "kickoff", "yes", "2026-05-28T09:00:00")

    result = actions.switch_session(
        self.db,
        "Henderson",
        "tax question",
        None,
        "2026-05-28T09:20:00",
    )

    self.assertEqual(result["closed_entry"]["end_at"], "2026-05-28T09:20:00")
    self.assertEqual(result["new_active_session"]["client_name"], "Henderson")
    self.assertEqual(result["new_active_session"]["started_at"], "2026-05-28T09:20:00")
```

**Step 2: Add MCP coverage for unknown-client switch**

In `tests/test_mcp_server.py`, add a test near `test_switch_minutes_ago_tool_uses_relative_correction_time`:

```python
def test_switch_tool_starts_timer_for_unknown_client_without_confirmation(self) -> None:
    self.payload("init_state", {"at": "2026-05-28T08:55:00"})
    self.payload("start", {"client": "Client A", "task": "cleanup", "billable": "yes", "at": "2026-05-28T09:00:00"})

    switched = self.payload("switch", {
        "client": "Henderson",
        "task": "tax question",
        "at": "2026-05-28T09:20:00",
    })

    self.assertEqual(switched["new_active_session"]["client_name"], "Henderson")
    self.assertEqual(switched["new_active_session"]["started_at"], "2026-05-28T09:20:00")
```

**Step 3: Run focused tests**

Run:

```bash
python3 -m unittest tests.test_actions.CaptureRosterTests tests.test_mcp_server.McpServerTests.test_switch_tool_starts_timer_for_unknown_client_without_confirmation -v
```

Expected: new tests pass against current behavior or fail only because review metadata is not yet present. Do not proceed until the immediate-capture assertions pass.

**Step 4: Commit**

```bash
git add tests/test_actions.py tests/test_mcp_server.py tests/test_prototype_workflow.py
git commit -m "test: lock non-blocking switch capture behavior"
```

---

### Task 2: Add reviewable capture metadata to active sessions and time entries

**Objective:** Preserve raw switch intent and mark unresolved labels for review without blocking active timer creation.

**Files:**
- Modify: `timeassist/db.py`
- Modify: `timeassist/actions.py`
- Test: `tests/test_actions.py`

**Data model:** Add nullable metadata to both `active_sessions` and `time_entries` so metadata survives the active → entry transition:

```sql
raw_client_name TEXT,
raw_task_text TEXT,
capture_status TEXT NOT NULL DEFAULT 'resolved',
capture_note TEXT,
clarified_at TEXT
```

Allowed `capture_status` values for v1:

- `resolved` — roster match or explicit user-approved label.
- `needs_info` — unknown client, assistant/frontend-flagged ambiguous label after capture, or missing task/service detail.

**Step 1: Write migration tests**

Add tests that initialize a new DB and assert the columns exist on both tables. Also create a legacy DB without these columns, run `actions.ensure_initialized()`, and assert migration adds them without losing rows. The legacy test must verify `capture_status` backfills to `'resolved'` on existing rows.

**Step 2: Implement schema/migration in `db.py:initialize()`**

Update `timeassist/db.py` schema for new installs. For existing databases, add explicit idempotent migrations in `initialize()` immediately after `conn.executescript(SCHEMA)` and near the existing settings migration; do not hide this in `actions.py`.

Use a small helper that checks `PRAGMA table_info(<table>)` before running `ALTER TABLE ... ADD COLUMN`, for example:

```python
def _ensure_column(conn, table: str, column_name: str, ddl: str) -> None:
    existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    if column_name not in existing:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {ddl}")
```

Apply it to both `active_sessions` and `time_entries`:

```sql
ALTER TABLE active_sessions ADD COLUMN raw_client_name TEXT;
ALTER TABLE active_sessions ADD COLUMN raw_task_text TEXT;
ALTER TABLE active_sessions ADD COLUMN capture_status TEXT NOT NULL DEFAULT 'resolved';
ALTER TABLE active_sessions ADD COLUMN capture_note TEXT;
ALTER TABLE active_sessions ADD COLUMN clarified_at TEXT;

ALTER TABLE time_entries ADD COLUMN raw_client_name TEXT;
ALTER TABLE time_entries ADD COLUMN raw_task_text TEXT;
ALTER TABLE time_entries ADD COLUMN capture_status TEXT NOT NULL DEFAULT 'resolved';
ALTER TABLE time_entries ADD COLUMN capture_note TEXT;
ALTER TABLE time_entries ADD COLUMN clarified_at TEXT;
```

SQLite allows `ADD COLUMN capture_status TEXT NOT NULL DEFAULT 'resolved'` because the default is a constant. Do not use non-constant defaults such as `CURRENT_TIMESTAMP` in these `ALTER TABLE` statements.

**Step 3: Carry metadata from active session to closed entry**

Update `close_active_session()` so the new metadata fields are copied from `active_sessions` into `time_entries`.

If an active session has `capture_status = 'needs_info'`, the resulting `time_entries.review_status` must be `needs_info` instead of `draft`; otherwise keep the current `draft` behavior. This is the first code path that writes `needs_info`.

**Step 4: Run focused tests**

```bash
python3 -m unittest tests.test_actions.CaptureRosterTests tests.test_actions.DurabilityFoundationTests -v
```

**Step 5: Commit**

```bash
git add timeassist/db.py timeassist/actions.py tests/test_actions.py
git commit -m "feat: persist capture review metadata"
```

---

### Task 3: Make switch metadata deterministic and non-blocking

**Objective:** Ensure `switch_session()` records unresolved switch labels as reviewable state while still returning a new active timer immediately.

**Files:**
- Modify: `timeassist/actions.py:654-679`
- Test: `tests/test_actions.py`

**Behavior:**

1. `switch_session()` parses the timestamp exactly as it does today.
2. It closes the old active session at `switched_at`.
3. It resolves the client using the existing exact display-name/alias roster lookup.
4. If the client is unknown, it still inserts the new active session with the raw client text.
5. Unknown client sets:
   - `raw_client_name = <user input>`
   - `raw_task_text = <user task text>`
   - `capture_status = 'needs_info'`
   - `capture_note = 'client_not_in_roster'`
6. Known client sets:
   - `raw_client_name = <user input>` when different from canonical name, otherwise `NULL`
   - `raw_task_text = <user task text>` always, so the rule is deterministic and the original service/task wording survives cleanup
   - `capture_status = 'resolved'`
7. `minutes_ago` still sets both `closed_entry.end_at` and `new_active_session.started_at` to the same corrected `switched_at` timestamp while metadata is populated in the same transaction.
8. The existing `switch` event should include these fields in `after_json.new_active_session`.

**Step 1: Write failing tests**

Add tests for:

```python
def test_switch_unknown_client_marks_new_active_session_needs_info(self) -> None:
    ...
    self.assertEqual(new_session["client_name"], "Henderson")
    self.assertEqual(new_session["raw_client_name"], "Henderson")
    self.assertEqual(new_session["capture_status"], "needs_info")
    self.assertEqual(new_session["capture_note"], "client_not_in_roster")


def test_switch_known_alias_records_resolved_metadata(self) -> None:
    ...
    self.assertEqual(new_session["client_name"], "Internal Admin")
    self.assertEqual(new_session["raw_client_name"], "admin")
    self.assertEqual(new_session["raw_task_text"], "admin cleanup")
    self.assertEqual(new_session["capture_status"], "resolved")


def test_switch_minutes_ago_preserves_corrected_timestamp_with_metadata(self) -> None:
    ...
    self.assertEqual(result["closed_entry"]["end_at"], "2026-05-28T09:40:00")
    self.assertEqual(result["new_active_session"]["started_at"], "2026-05-28T09:40:00")
    self.assertEqual(result["new_active_session"]["capture_status"], "needs_info")
```

**Step 2: Implement minimal deterministic metadata derivation**

Do not duplicate billable parsing or invent fuzzy helpers. Keep using the existing deterministic functions:

```python
def switch_capture_values(conn, client: str, task: str, billable: str | bool | None) -> dict[str, Any]:
    canonical, default_billable = resolve_client(conn, client)
    canonical_for_insert, billable_int = resolve_capture(conn, client, billable)
    known_client = default_billable is not None
    assert canonical_for_insert == canonical
    return {
        "client_name": canonical,
        "billable": billable_int,
        "raw_client_name": client if client != canonical or not known_client else None,
        "raw_task_text": task,
        "capture_status": "resolved" if known_client else "needs_info",
        "capture_note": None if known_client else "client_not_in_roster",
    }
```

The key rule is `default_billable is None` from `resolve_client()` means the client is not in the roster. Do not add `_client_display_name_exists`, fuzzy matching, ranking, or ambiguity detection in the core. If helper implementation details differ, keep the behavior and tests above as the authority.

**Step 3: Update insert**

Update the `INSERT INTO active_sessions` statement in `switch_session()` to populate metadata atomically in the same DB transaction that closes the old timer.

**Step 4: Run focused tests**

```bash
python3 -m unittest tests.test_actions.CaptureRosterTests -v
```

**Step 5: Commit**

```bash
git add timeassist/actions.py tests/test_actions.py
git commit -m "feat: mark unresolved switch captures for review"
```

---

### Task 4: Add deterministic clarification actions that never alter start time by default

**Objective:** Let a later follow-up update labels on the active session or closed review entry while preserving the original switch timestamp and recording clarification time.

**Files:**
- Modify: `timeassist/actions.py`
- Modify: `timeassist/cli.py`
- Modify: `timeassist/mcp_server.py`
- Test: `tests/test_actions.py`
- Test: `tests/test_mcp_server.py`
- Test: `tests/test_prototype_workflow.py`

**New action contract:**

```python
def clarify_active_session(
    db_path: str | Path,
    client: str | None = None,
    task: str | None = None,
    billable: str | bool | None = None,
    at: str | None = None,
) -> dict[str, Any]:
    ...
```

Rules:

- Requires an active session.
- May update `client_name`, `task_text`, `billable`, `capture_status`, `capture_note`, and `clarified_at`.
- Must not update `started_at`, `created_at`, or the prior closed entry unless the user explicitly uses existing correction commands.
- Logs `clarify_active_session` event with `before_json`, `after_json`, and `created_at = clarified_at`.

**Closed-entry rule:** Extend the existing `edit_entry()` path so a `needs_info` entry is not stranded after the active timer closes. `edit_entry()` should allow entries whose `review_status` is `draft` or `needs_info`. When editing a `needs_info` entry with sufficient labels, it must:

- Set `review_status = 'draft'`.
- Set `capture_status = 'resolved'`.
- Clear `capture_note`.
- Set `clarified_at` to the edit time.
- Preserve `start_at`, `end_at`, `duration_minutes`, and `rounded_minutes` unless the existing edit command explicitly receives `start`/`end` corrections.

**Step 1: Write action tests**

Add tests:

```python
def test_clarify_active_session_updates_label_without_changing_start_time(self) -> None:
    actions.start_session(...)
    actions.switch_session(self.db, "Henderson", "tax question", None, "2026-05-28T09:20:00")

    clarified = actions.clarify_active_session(
        self.db,
        client="Henderson LLC",
        task="tax notice research",
        billable="yes",
        at="2026-05-28T09:25:00",
    )

    self.assertEqual(clarified["started_at"], "2026-05-28T09:20:00")
    self.assertEqual(clarified["client_name"], "Henderson LLC")
    self.assertEqual(clarified["capture_status"], "resolved")
    self.assertEqual(clarified["clarified_at"], "2026-05-28T09:25:00")
```

Also assert an event exists with `event_type = 'clarify_active_session'`.

Add a closed-entry test:

```python
def test_edit_needs_info_entry_resolves_capture_without_changing_time_by_default(self) -> None:
    ...
    edited = actions.edit_entry(
        self.db,
        entry_id,
        client="Henderson LLC",
        task="tax notice research",
        billable="yes",
        at="2026-05-28T09:45:00",
    )
    self.assertEqual(edited["review_status"], "draft")
    self.assertEqual(edited["capture_status"], "resolved")
    self.assertIsNone(edited["capture_note"])
    self.assertEqual(edited["clarified_at"], "2026-05-28T09:45:00")
    self.assertEqual(edited["start_at"], "2026-05-28T09:20:00")
    self.assertEqual(edited["end_at"], "2026-05-28T09:40:00")
```

**Step 2: Implement actions**

Use existing `get_active_session()`, `resolve_capture()`, `row_to_dict()`, and `log_event()` patterns. Keep the update in one transaction.

For `edit_entry()`, keep the existing draft edit behavior, but change the review-status guard from `draft` only to `draft` or `needs_info`. Only clear `needs_info` when the edit supplies enough deterministic fields to treat the entry as resolved; do not allow approval/export to be the implicit clarification mechanism.

**Step 3: Add CLI command**

Add `clarify-active` to `timeassist/cli.py`:

```bash
python3 scripts/timeassist.py clarify-active --client "Henderson LLC" --task "tax notice research" --billable yes --at 2026-05-28T09:25:00 --json
```

**Step 4: Add MCP tool**

Expose `clarify_active` in `timeassist/mcp_server.py` with a plain description:

> Update labels on the active timer after a non-blocking switch. This never changes the active timer start time.

**Step 5: Run focused tests**

```bash
python3 -m unittest tests.test_actions.CaptureRosterTests tests.test_mcp_server.McpServerTests tests.test_prototype_workflow.PrototypeWorkflowTests -v
```

**Step 6: Commit**

```bash
git add timeassist/actions.py timeassist/cli.py timeassist/mcp_server.py tests/test_actions.py tests/test_mcp_server.py tests/test_prototype_workflow.py
git commit -m "feat: clarify active timer labels after switch"
```

---

### Task 5: Surface unresolved switch captures in review/export gates

**Objective:** Make unresolved switch labels visible before approval/export so capture-first does not become bill-bad-data or silent under-billing.

**Files:**
- Modify: `timeassist/actions.py`
- Modify: review HTML renderer if separate from `actions.py`
- Test: `tests/test_actions.py`
- Test: `tests/test_prototype_workflow.py`

**Behavior:**

- When a `needs_info` active session is later closed, the resulting `time_entries.review_status` is `needs_info`.
- `review_entries()` includes `needs_info_minutes` in totals, as it already does today.
- Single-entry approval must reject `needs_info` entries with a clear message to edit/clarify first.
- `approve_all` must only approve `draft` entries and report how many `needs_info` entries were skipped.
- `export_entries()` remains limited to `approved`/`exported` entries, and its result should include skipped unresolved counts for the export date.
- Review output should show a human-readable reason such as `Needs review: client not in roster`.

**Step 1: Add close/review tests**

Test flow:

1. Start Client A.
2. Switch to unknown Henderson at 09:20.
3. End at 09:40.
4. Review day.
5. Assert Henderson entry has `review_status == 'needs_info'` and reason text/metadata.
6. Assert single-entry approval rejects the unresolved entry.
7. Assert approve-all approves only drafts and reports the unresolved entry as skipped.
8. Assert export excludes unresolved entries and reports skipped `needs_info` count/minutes for the date.
9. Assert edit/clarify-then-approve works: after `edit_entry()` resolves the entry to `draft`, normal approval/export can proceed.

**Step 2: Implement close/review surfacing**

Use metadata from Task 2/3. Keep review/export logic conservative.

Add an explicit summary field to review/export payloads so a bookkeeper sees captured-but-unresolved billable time instead of accidentally dropping it:

```python
{
    "skipped_needs_info_count": 1,
    "skipped_needs_info_minutes": 20,
}
```

If this is added under `totals` instead of top-level, keep the field names consistent across review and export. The requirement is visibility; do not rely only on missing CSV rows.

**Step 3: Run focused tests**

```bash
python3 -m unittest tests.test_actions.CaptureRosterTests tests.test_actions.ReviewWarningTests tests.test_prototype_workflow.PrototypeWorkflowTests -v
```

**Step 4: Commit**

```bash
git add timeassist/actions.py tests/test_actions.py tests/test_prototype_workflow.py
git commit -m "feat: surface unresolved switch captures in review"
```

---

### Task 6: Update assistant/plugin guidance so wrappers call switch before follow-up

**Objective:** Prevent Claude/Cowork/plugin prompts from recreating the blocking confirmation bug.

**Files:**
- Modify: `plugin/timeassist/skills/billable-time-assistant/SKILL.md` (required; this is the assistant-facing file Claude/Cowork will actually read)
- Modify: any duplicate plugin skill/instruction files under `.claude-plugin/` if present; keep duplicate copies synchronized
- Modify: `README.md`
- Modify: `docs/accountant-quick-start.md`
- Modify: `docs/decision-log.md`
- Modify: `docs/project-board.md`
- Test: relevant docs/plugin tests in `tests/test_plugin_data_paths.py`

**Required wording for assistant-facing docs:**

```text
For client switching, capture now and clarify later. If the user asks to switch clients, call the deterministic switch tool immediately with the best raw client/task labels available. Do not ask a confirmation question before the switch tool succeeds. If the client or service is uncertain, ask a follow-up only after reporting that the timer is already running.
```

**Required wording for accountant-facing docs:**

```text
If you switch to a client TimeAssist does not recognize, it should still start the timer right away and mark the label for review. You can clarify the name later; the original switch time stays preserved.
```

**Step 1: Locate plugin guidance files**

Run:

```bash
python3 - <<'PY'
from pathlib import Path
for p in Path('.').rglob('*'):
    if p.is_file() and p.suffix in {'.md', '.json'} and ('plugin' in str(p).lower() or 'timeassist' in p.name.lower()):
        print(p)
PY
```

**Step 2: Patch docs**

Update the files above with the product rule and examples.

**Step 3: Add regression assertion for assistant-facing guidance**

In `tests/test_plugin_data_paths.py`, add a real assertion that the bundled plugin skill contains the capture-now directive. This is the recurrence-prevention test for the pilot bug.

```python
def test_plugin_skill_documents_capture_now_switch_rule(self) -> None:
    skill = (REPO_ROOT / "plugin/timeassist/skills/billable-time-assistant/SKILL.md").read_text(encoding="utf-8")
    self.assertIn("capture now and clarify later", skill.lower())
    self.assertIn("call the deterministic switch tool immediately", skill.lower())
    self.assertIn("do not ask a confirmation question before the switch tool succeeds", skill.lower())
```

If a `.claude-plugin/` or packaged duplicate skill copy exists, add the same assertion for that file too, or add a sync assertion that the directive exists in every assistant-facing copy.

**Step 4: Run validation**

```bash
python3 -m unittest tests.test_plugin_data_paths.PluginMcpConfigTests tests.test_cli_help.CliSmokeTests -v
```

**Step 5: Commit**

```bash
git add README.md docs/accountant-quick-start.md docs/decision-log.md docs/project-board.md plugin .claude-plugin tests/test_plugin_data_paths.py
git commit -m "docs: document capture-now switch rule"
```

Adjust `git add` paths to only include files that exist and were modified.

---

### Task 7: Add a no-AI token/cost guardrail note for switch wrappers

**Objective:** Make the token usage boundary explicit: switch capture is zero-token deterministic; optional clarification/suggestions are logged separately.

**Files:**
- Modify: `docs/architecture.md`
- Modify: `docs/wiki/Architecture.md` if current project docs use it
- Modify: `README.md`

**Content to add:**

```text
Token boundary: `start`, `switch`, `end`, `review`, `approve`, and `export` are deterministic app actions and should not call an LLM. If optional AI suggestions are introduced later, they may suggest labels/descriptions only after capture; add an `ai_suggestion_log` table or equivalent before shipping that feature, with model, input tokens, output tokens, estimated cost, and feature name recorded before any suggestion is applied by a user or deterministic action.
```

**Step 1: Patch architecture docs**

Add the boundary near existing AI/wrapper sections.

**Step 2: Run docs-sensitive tests**

```bash
python3 -m unittest tests.test_plugin_data_paths.PluginMcpConfigTests -v
```

**Step 3: Commit**

```bash
git add README.md docs/architecture.md docs/wiki/Architecture.md
git commit -m "docs: define zero-token capture boundary"
```

---

## Final validation

After all tasks pass their focused validations, run:

```bash
git status --short
python3 -m unittest discover -s tests -v
git diff --check
```

Expected:

- Full test suite passes.
- No whitespace errors.
- No unrelated files staged.
- Existing untracked files remain untouched unless explicitly part of this work.

---

## Acceptance criteria traceability

- “Switch to X” always creates a new active timer immediately.
  - Covered by Tasks 1 and 3.
- Follow-up questions never block timer creation.
  - Covered by Tasks 4 and 6.
- Unknown clients and assistant/frontend-detected ambiguous labels are captured first and marked `needs_info`, not rejected. The deterministic core does not perform fuzzy ambiguity detection in v1.
  - Covered by Tasks 2, 3, and 5.
- If the user ignores the follow-up, the time is still captured.
  - Covered by Tasks 1, 3, and 5.
- Review/export surfaces unresolved client/service fields before final approval.
  - Covered by Task 5.
- The event log preserves both original switch request time and later clarification time, if any.
  - Covered by Tasks 3 and 4.
- Start/switch/end remain deterministic zero-token actions.
  - Covered by Task 7.

---

## Reviewer checklist

Codex and Claude Code should review this plan for:

- Whether it preserves the existing deterministic switch behavior.
- Whether schema changes are minimal and migration-safe.
- Whether `needs_info` semantics fit existing approval/export behavior.
- Whether `clarify_active_session` is necessary or whether existing `edit_entry` can cover enough after close.
- Whether the tests prove the pilot bug cannot recur.
- Whether docs/plugin guidance is placed where Claude/Cowork will actually see it.
- Whether the plan overbuilds fuzzy/AI logic instead of keeping v1 deterministic.
