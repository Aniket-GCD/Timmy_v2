# Timmy Review-Fix Round (PR #35) Implementation Plan

> **Status: SHIPPED in v0.1.21-prototype (PR #35) — never execute this plan.**

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps
> use checkbox (`- [ ]`) syntax for tracking. **Subagents must run on Opus (operator
> instruction).**

**Goal:** Fix every finding from the 2026-07-02 max-effort re-review of PR #35 (branch
`feat/timmy-pilot-feedback`): close the placeholder→roster gate for `start`/`add_missing`
captures, stop the sanitized packet leaking free-text Job Type, enforce the admin billable
lock at approve/export (legacy v0.1.19 data), make seeding/merge-import respect operator
roster authority, and land the minor policy/doc/test cleanups.

**Architecture:** All engine changes in `timeassist/actions.py` + `timeassist/db.py`;
MCP shaping only in `timeassist/mcp_views.py`; assistant contract in the single
`plugin/timeassist/skills/billable-time-assistant/SKILL.md`. Stdlib only — never add
third-party deps. The windows-build.yml smoke sequence changes in ONE place (a
confirm-edit step) and `tests/test_workflow_smoke_contract.py` must be updated in the
same commit (CLAUDE.md sync rule — this exact coupling broke the first v0.1.19 build).

**Tech Stack:** Python 3 stdlib, sqlite3, unittest. Work on the existing
`feat/timmy-pilot-feedback` branch (PR #35). `python3 -m unittest discover -s tests`
must pass before every commit. Every commit ends with:
`Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`

---

## Decisions locked (from the review + operator go-ahead)

- **C1 → capture-time gate for all paths.** `start` and `add_missing` route through
  `resolve_capture_with_metadata` so unknown clients are marked `needs_info` exactly like
  `switch`. Capture still never blocks. The confirm-as-is `edit`/`clarify_active` recipe
  is unchanged. SKILL.md's existing claim becomes true; do not weaken it.
- **Job Type semantics (one rule):** explicit `job_type` wins (explicit `""` clears);
  otherwise clarify/edit **preserve** the stored value (even blank); only **fresh
  captures** (start/switch/add_missing) take the roster `default_job_type`. Implemented
  once in `apply_client_policy` via `current_job_type`; the billable machinery in
  clarify/edit (roster-default-on-client-change, confirm-keeps-billable) is pinned and
  must NOT change.
- **I2 → finalize gates.** `approve` raises on a billable entry whose client row is
  `billable_locked`; `approve_all` and `export` skip such entries with
  `skipped_locked_count`/`skipped_locked_minutes` (shown in MCP views only when > 0).
  No silent data mutation; legacy rows are surfaced, never auto-flipped.
- **I3 → seeds never collide with operator labels.** `initialize()` skips seeding an
  admin client whose display name (case-insensitive) is already an operator row's
  display name or alias under a different `client_key`.
- **I4 + M1 → operator import takes ownership.** `import_clients` supports an optional
  `default_job_type` CSV column; its upsert sets `billable_locked = 0` and
  `default_job_type` from the CSV, so merge and replace modes agree ("operator roster
  edits win", decision log).
- **I1 → packet redacts Job Type** to sequential `Job Type N` labels (mirrors clients).
- **M4 → `import_clients` MCP result is counts only** (`mode`, `imported_count`); the
  model can call `list_clients` for the roster.
- `resolve_capture` loses its last production callers in Task 3 → delete it and migrate
  any test callers. `resolve_client` (test-facing wrapper) stays — churn without benefit.
- Push to the existing PR #35 branch when green; no tag, no version bump (release later).

---

### Task 1: `apply_client_policy` current-value semantics + explicit-`""` clear + edit guard

**Files:**
- Modify: `timeassist/actions.py:512-535` (apply_client_policy), `:545-580`
  (resolve_capture_with_metadata), `:855-915` (clarify_active_session),
  `:1148-1260` (edit_entry)
- Test: `tests/test_actions.py`

- [ ] **Step 1: Write the failing tests** (append to the existing policy/edit test area in `tests/test_actions.py`; reuse the module's existing imports and `ClientRosterTests._write_csv`-style CSV helper pattern):

```python
class ApplyClientPolicyCurrentValueTests(unittest.TestCase):
    def _row(self, **overrides):
        base = {"display_name": "Acme Co", "default_billable": 1,
                "default_job_type": "Bookkeeping", "billable_locked": 0}
        base.update(overrides)
        return base  # dict is fine: policy only uses [] access and int()

    def test_explicit_empty_job_type_clears(self) -> None:
        billable, job_type = actions.apply_client_policy(self._row(), None, "")
        self.assertEqual(job_type, "")

    def test_none_job_type_prefers_current_over_default(self) -> None:
        billable, job_type = actions.apply_client_policy(
            self._row(), None, None, current_job_type="Payroll")
        self.assertEqual(job_type, "Payroll")

    def test_none_job_type_preserves_current_blank(self) -> None:
        billable, job_type = actions.apply_client_policy(
            self._row(), None, None, current_job_type="")
        self.assertEqual(job_type, "")

    def test_fresh_capture_takes_roster_default(self) -> None:
        billable, job_type = actions.apply_client_policy(self._row(), None, None)
        self.assertEqual(job_type, "Bookkeeping")

    def test_current_billable_preserved_when_not_requested(self) -> None:
        billable, _ = actions.apply_client_policy(
            self._row(default_billable=1), None, None, current_billable=0)
        self.assertEqual(billable, 0)

    def test_locked_row_ignores_currents(self) -> None:
        row = self._row(display_name="Admin", default_job_type="Administrative",
                        billable_locked=1)
        billable, job_type = actions.apply_client_policy(
            row, None, "Special", current_billable=1, current_job_type="X")
        self.assertEqual((billable, job_type), (0, "Administrative"))


class EditPolicyGuardTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.work = Path(self.tmp.name)
        self.db = self.work / "timeassist.sqlite"
        actions.init_state(self.db, "2026-05-28T09:00:00")

    def test_task_only_edit_preserves_legacy_locked_billable(self) -> None:
        # Legacy row: billable=1 on the locked Admin client (pre-upgrade data).
        entry = actions.add_missing_entry(
            self.db, "Some Client", "t", "2026-05-28T10:00:00", "2026-05-28T10:30:00", "yes")
        with db.connect(self.db) as conn:
            conn.execute(
                "UPDATE time_entries SET client_name='Admin', billable=1, "
                "capture_status='resolved', review_status='draft' WHERE entry_id=?",
                (entry["entry_id"],))
            conn.commit()
        after = actions.edit_entry(self.db, entry["entry_id"], task="notes only")
        self.assertEqual(after["billable"], 1)  # preserved; the approve gate owns legacy rows

    def test_explicit_job_type_edit_on_locked_row_applies_policy(self) -> None:
        entry = actions.add_missing_entry(
            self.db, "Some Client", "t", "2026-05-28T10:00:00", "2026-05-28T10:30:00", "yes")
        with db.connect(self.db) as conn:
            conn.execute(
                "UPDATE time_entries SET client_name='Admin', billable=1, "
                "capture_status='resolved', review_status='draft' WHERE entry_id=?",
                (entry["entry_id"],))
            conn.commit()
        after = actions.edit_entry(self.db, entry["entry_id"], job_type="Whatever")
        self.assertEqual(after["billable"], 0)
        self.assertEqual(after["job_type"], "Administrative")

    def test_explicit_empty_job_type_edit_clears_it(self) -> None:
        entry = actions.add_missing_entry(
            self.db, "Client Z", "t", "2026-05-28T10:00:00", "2026-05-28T10:30:00",
            "yes", job_type="Payroll")
        after = actions.edit_entry(self.db, entry["entry_id"], job_type="")
        self.assertEqual(after["job_type"], "")


class ClarifyJobTypePreservationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.work = Path(self.tmp.name)
        self.db = self.work / "timeassist.sqlite"
        actions.init_state(self.db, "2026-05-28T09:00:00")

    def test_task_only_clarify_preserves_blank_job_type(self) -> None:
        actions.start_session(self.db, "Client A", "w", "yes", "2026-05-28T09:00:00")
        session = actions.clarify_active_session(self.db, task="better notes",
                                                 at="2026-05-28T09:05:00")
        self.assertEqual(session["job_type"], "")
```

NOTE: `Client A`/`Some Client`/`Client Z` are not on any roster; after Task 3 lands these
captures become `needs_info`, which does not affect these assertions (edit of a
needs_info entry with only task/job_type keeps its status; the guard tests hand-set
`capture_status='resolved'`). If any assertion here starts failing after Task 3, fix the
test setup (seed a roster with `import_clients`), not the engine.

- [ ] **Step 2: Run the new tests, verify they fail** (`current_job_type` unexpected
  keyword / wrong job_type values):

Run: `python3 -m unittest tests.test_actions.ApplyClientPolicyCurrentValueTests tests.test_actions.EditPolicyGuardTests tests.test_actions.ClarifyJobTypePreservationTests -v`
Expected: FAIL/ERROR.

- [ ] **Step 3: Implement.** Replace `apply_client_policy` (actions.py:512-535) with:

```python
def apply_client_policy(
    row: sqlite3.Row | None,
    billable_requested: str | bool | None,
    job_type_requested: str | None,
    *,
    current_billable: int | None = None,
    current_job_type: str | None = None,
) -> tuple[int, str]:
    """Engine-enforced client policy (pilot feedback #34). Pinned by tests.

    Locked (administrative) clients can never be billable; their job_type is
    always the roster default. Explicit billable=yes on a locked client is an
    operator error, rejected in plain language. Enforcement keys off the
    `billable_locked` column, never off client names, so an operator roster
    override degrades safely.

    Precedence for each field: explicit request (job_type="" clears), then the
    caller's current stored value (clarify/edit preservation), then the roster
    default. Fresh captures pass no current values, so roster defaults apply.
    """
    if row is not None and int(row["billable_locked"]):
        if billable_requested is not None and bool_to_int(billable_requested) == 1:
            raise ValueError(f"client '{row['display_name']}' is administrative and cannot be billable")
        return 0, row["default_job_type"]
    if billable_requested is not None:
        billable = bool_to_int(billable_requested)
    elif current_billable is not None:
        billable = int(current_billable)
    else:
        billable = int(row["default_billable"]) if row is not None else 1
    if job_type_requested is not None:
        job_type = job_type_requested.strip()
    elif current_job_type is not None:
        job_type = current_job_type
    else:
        job_type = row["default_job_type"] if row is not None else ""
    return billable, job_type
```

Thread `current_job_type` through `resolve_capture_with_metadata` — add the keyword and
pass it to the policy call (actions.py:545-566):

```python
def resolve_capture_with_metadata(
    conn,
    client: str,
    task: str,
    billable: str | bool | None,
    *,
    clarification: bool = False,
    job_type: str | None = None,
    current_job_type: str | None = None,
) -> dict[str, Any]:
    ...
    billable_int, job_type_resolved = apply_client_policy(
        row, billable, job_type, current_job_type=current_job_type)
```

In `clarify_active_session` (actions.py:869-878): delete the `next_job_type` threading
line and pass the raw arg + current value instead:

```python
        next_client = client if client is not None else active["client_name"]
        next_task = task if task is not None else active["task_text"]
        current_job_type = active.get("job_type") or ""
        capture = resolve_capture_with_metadata(
            conn, next_client, next_task,
            billable if billable is not None else None,
            clarification=True, job_type=job_type, current_job_type=current_job_type)
        if client is not None and billable is None and active.get("capture_status") == "needs_info" and capture["capture_status"] == "needs_info":
            # The operator addressed the client; that confirms the open timer.
            # Known roster clients already resolved above with their roster
            # default; unknown names resolve here keeping the session's current
            # billable rather than demanding it be retyped.
            capture = resolve_capture_with_metadata(
                conn, next_client, next_task, bool(active["billable"]),
                clarification=True, job_type=job_type, current_job_type=current_job_type)
```

In `edit_entry`: delete the `effective_job_type` line (actions.py:1171-1174); in the
capture branch pass `job_type=job_type, current_job_type=before.get("job_type") or ""`
to BOTH `resolve_capture_with_metadata` calls; replace the else-branch
(actions.py:1207-1219) with:

```python
        else:
            new_client = before["client_name"]
            if billable is None and job_type is None:
                # Nothing policy-relevant requested: preserve stored values and
                # skip the roster scan entirely.
                new_billable = before["billable"]
                new_job_type = before.get("job_type") or ""
            else:
                # Enforce client policy on any billable/job_type edit so a locked
                # (administrative) client can never be flipped billable via edit.
                row = resolve_client_row(conn, new_client)
                new_billable, new_job_type = apply_client_policy(
                    row, billable, job_type,
                    current_billable=before["billable"],
                    current_job_type=before.get("job_type") or "")
```

- [ ] **Step 4: Run the new tests (PASS) and the full suite** — some existing tests may
  pin the OLD blank-backfill or roster-default-on-fresh-capture behavior. Fix only tests
  whose assertions contradict the locked semantics above (e.g. a test asserting an
  unrelated edit backfills a roster default). `test_edit_unrelated_field_preserves_blank_job_type`
  must still pass unchanged.

Run: `python3 -m unittest discover -s tests`
Expected: OK.

- [ ] **Step 5: Commit**

```bash
git add timeassist/actions.py tests/test_actions.py
git commit -m "fix: one job_type precedence rule — explicit ('' clears) > stored > roster default (#35 review)"
```

---

### Task 2: roster `default_job_type` import column + merge-import takes ownership (I4+M1)

**Files:**
- Modify: `timeassist/actions.py:366-442` (import_clients)
- Test: `tests/test_actions.py`

- [ ] **Step 1: Write the failing tests** (in/near `ClientRosterTests`, reusing its `_write_csv` helper — it writes a CSV from header+rows):

```python
    def test_import_reads_default_job_type_column(self) -> None:
        actions.import_clients(self.db, self._write_csv(
            "clients.csv",
            "display_name,aliases,default_billable,default_job_type",
            "Acme Co,,yes,Bookkeeping",
        ))
        with db.connect(self.db) as conn:
            row = conn.execute("SELECT default_job_type FROM clients WHERE display_name='Acme Co'").fetchone()
        self.assertEqual(row["default_job_type"], "Bookkeeping")

    def test_merge_import_over_seeded_admin_takes_ownership(self) -> None:
        # Operator merge-imports their OWN client named Admin: the seeded lock
        # must not survive — merge and replace modes must agree (operator wins).
        actions.import_clients(self.db, self._write_csv(
            "clients.csv", "display_name,aliases,default_billable", "Admin,,yes",
        ), mode="merge")
        with db.connect(self.db) as conn:
            row = conn.execute("SELECT default_billable, billable_locked, default_job_type FROM clients WHERE display_name='Admin'").fetchone()
        self.assertEqual(int(row["default_billable"]), 1)
        self.assertEqual(int(row["billable_locked"]), 0)
        self.assertEqual(row["default_job_type"], "")
        session = actions.start_session(self.db, "Admin", "their admin client", "yes", "2026-05-28T09:00:00")
        self.assertEqual(session["billable"], 1)

    def test_fresh_capture_autofills_roster_default_job_type(self) -> None:
        actions.import_clients(self.db, self._write_csv(
            "clients.csv",
            "display_name,aliases,default_billable,default_job_type",
            "Acme Co,,yes,Bookkeeping",
        ))
        session = actions.start_session(self.db, "Acme Co", "w", None, "2026-05-28T09:00:00")
        self.assertEqual(session["job_type"], "Bookkeeping")
        entry = actions.add_missing_entry(self.db, "Acme Co", "w", "2026-05-28T10:00:00", "2026-05-28T10:30:00")
        self.assertEqual(entry["job_type"], "Bookkeeping")
```

- [ ] **Step 2: Run them, verify failure.**

Run: `python3 -m unittest tests.test_actions.ClientRosterTests -v`
Expected: the three new tests FAIL.

- [ ] **Step 3: Implement in `import_clients`.** Parsed tuples gain a field
  (update the type annotation at actions.py:374 to `list[tuple[str, str, str, int, str]]`):

```python
            parsed.append((key, display, aliases, parse_billable_flag(raw.get("default_billable")),
                           (raw.get("default_job_type") or "").strip()))
```

Update the merge-mode unpacking at actions.py:413/422 to five-tuples
(`for key, _display, _aliases, _default_billable, _default_job_type in parsed` etc.), and
replace the upsert (actions.py:426-438):

```python
        for key, display, aliases, default_billable, default_job_type in parsed:
            conn.execute(
                """
                INSERT INTO clients(client_key, display_name, aliases, default_billable, default_job_type, billable_locked, updated_at)
                VALUES (?, ?, ?, ?, ?, 0, ?)
                ON CONFLICT(client_key) DO UPDATE SET
                    display_name = excluded.display_name,
                    aliases = excluded.aliases,
                    default_billable = excluded.default_billable,
                    default_job_type = excluded.default_job_type,
                    billable_locked = 0,
                    updated_at = excluded.updated_at
                """,
                (key, display, aliases, default_billable, default_job_type, changed_at),
            )
```

(The `billable_locked = 0` on update is the ownership transfer: an operator CSV row for
a seeded key unlocks it, matching replace-mode behavior.)

- [ ] **Step 4: Run the full suite.**

Run: `python3 -m unittest discover -s tests`
Expected: OK.

- [ ] **Step 5: Commit**

```bash
git add timeassist/actions.py tests/test_actions.py
git commit -m "feat: default_job_type roster column; operator import unlocks seeded admin rows (#35 review I4/M1)"
```

---

### Task 3: mark unknown clients `needs_info` on `start` and `add_missing` (C1 engine)

**Files:**
- Modify: `timeassist/actions.py:716-740` (start_session), `:1098-1112`
  (add_missing_entry); delete `resolve_capture` (`:538-542`)
- Test: `tests/test_actions.py`

- [ ] **Step 1: Write the failing tests:**

```python
class UnknownClientCaptureGateTests(unittest.TestCase):
    # Pilot email (#34): a non-roster name is fine as a temporary placeholder,
    # but at approve/export time the name must match the master list. That gate
    # is needs_info — so EVERY capture path must mark unknown clients, not just
    # switch. Pinned per the intentional-but-surprising convention.
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.work = Path(self.tmp.name)
        self.db = self.work / "timeassist.sqlite"
        actions.init_state(self.db, "2026-05-28T09:00:00")

    def test_start_unknown_client_is_needs_info(self) -> None:
        session = actions.start_session(self.db, "Zeta Nowhere Ltd", "mystery", None, "2026-05-28T09:00:00")
        self.assertEqual(session["capture_status"], "needs_info")
        self.assertEqual(session["capture_note"], "client_not_in_roster")
        entry = actions.end_session(self.db, "2026-05-28T09:30:00")
        self.assertEqual(entry["review_status"], "needs_info")

    def test_add_missing_unknown_client_is_needs_info_and_blocked_from_approval(self) -> None:
        entry = actions.add_missing_entry(self.db, "Ghost Client", "phantom",
                                          "2026-05-28T10:00:00", "2026-05-28T10:30:00")
        self.assertEqual(entry["review_status"], "needs_info")
        with self.assertRaises(ValueError):
            actions.set_approval(self.db, entry["entry_id"], True)

    def test_confirm_as_is_edit_still_resolves(self) -> None:
        entry = actions.add_missing_entry(self.db, "Ghost Client", "phantom",
                                          "2026-05-28T10:00:00", "2026-05-28T10:30:00")
        after = actions.edit_entry(self.db, entry["entry_id"], client="Ghost Client")
        self.assertEqual(after["review_status"], "draft")
        self.assertEqual(after["capture_status"], "resolved")
        self.assertEqual(after["billable"], 1)  # unknown-name confirm keeps billable

    def test_start_known_client_stays_resolved(self) -> None:
        path = self.work / "clients.csv"
        path.write_text("display_name,aliases,default_billable\nClient A,,yes\n")
        actions.import_clients(self.db, path)
        session = actions.start_session(self.db, "Client A", "w", None, "2026-05-28T11:00:00")
        self.assertEqual(session["capture_status"], "resolved")
```

- [ ] **Step 2: Run them, verify the first two FAIL** (capture_status 'resolved').

- [ ] **Step 3: Implement.** In `start_session`, replace the `resolve_capture` call and
  INSERT (actions.py:726-734) with the switch-style capture:

```python
        capture = resolve_capture_with_metadata(conn, client, task, billable, job_type=job_type)
        try:
            cur = conn.execute(
                """
                INSERT INTO active_sessions(
                    client_name, task_text, billable, job_type, started_at, raw_client_name,
                    raw_task_text, capture_status, capture_note, clarified_at,
                    last_checkin_at, status, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?)
                """,
                (
                    capture["client_name"],
                    capture["task_text"],
                    capture["billable"],
                    capture["job_type"],
                    started,
                    capture["raw_client_name"],
                    capture["raw_task_text"],
                    capture["capture_status"],
                    capture["capture_note"],
                    capture["clarified_at"],
                    started,
                    started,
                    started,
                ),
            )
```

(The two f-strings referencing `canonical`/`task` in the surrounding log_event line
become `capture["client_name"]`/`capture["task_text"]`.)

In `add_missing_entry`, replace the resolve + INSERT (actions.py:1104-1110):

```python
        capture = resolve_capture_with_metadata(conn, client, task, billable, job_type=job_type)
        rounded = round_minutes(duration, *get_rounding(conn))
        review_status = "needs_info" if capture["capture_status"] == "needs_info" else "draft"
        cur = conn.execute(
            """
            INSERT INTO time_entries(
                client_name, task_text, billable, job_type, start_at, end_at, duration_minutes,
                rounded_minutes, review_status, raw_client_name, raw_task_text,
                capture_status, capture_note, clarified_at, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                capture["client_name"], capture["task_text"], capture["billable"],
                capture["job_type"], start_iso, end_iso, duration, rounded, review_status,
                capture["raw_client_name"], capture["raw_task_text"],
                capture["capture_status"], capture["capture_note"], capture["clarified_at"],
                end_iso, end_iso,
            ),
        )
```

(Update the following log_event's `canonical`/`task` references the same way.)

Delete `resolve_capture` (actions.py:538-542) — `grep -rn "resolve_capture\b"` and
migrate any remaining test callers to `resolve_capture_with_metadata` or the public
actions they exercise.

- [ ] **Step 4: Run ONLY the new tests (PASS). Do NOT run the full suite yet** — Task 4
  owns the fallout.

- [ ] **Step 5: Commit** (suite intentionally red until Task 4; commit together with
  Task 4 if the project's every-commit-green rule must hold — preferred: implement
  Task 3 + Task 4 in one working tree session and commit once green).

```bash
git add timeassist/actions.py tests/test_actions.py
git commit -m "feat: unknown clients are needs_info on every capture path (#34 approve/export roster gate)"
```

---

### Task 4: C1 fallout — workflow smoke, contract test, suite, demo

**Files:**
- Modify: `.github/workflows/windows-build.yml:108-160` (smoke sequence),
  `tests/test_workflow_smoke_contract.py:88-137` (_shaped_payloads),
  `timeassist/demo.py:50-57` (scripted flow), `tests/test_mcp_server.py`,
  `tests/test_prototype_workflow.py`, `tests/test_plugin_data_paths.py`,
  `tests/test_actions.py` (existing tests only)
- Regenerate: `demo/generated/` via `python3 scripts/run_stakeholder_demo.py`

- [ ] **Step 1: windows-build.yml** — after the `add_missing` Call-Tool (id 3), insert a
  confirm-as-is edit (this also makes the CI smoke exercise the new placeholder flow),
  and renumber the later ids (4→5, 5→6, 6→7, 7→8, 8→9, 9→10):

```powershell
            $null = Call-Tool 4 "edit" @{ entry_id = 1; client = "Client A" }
```

No new `ConvertFrom-Json` payload variables are introduced, so
`VARIABLE_TO_TOOL` in the contract test needs no new entries.

- [ ] **Step 2: tests/test_workflow_smoke_contract.py** — mirror the sequence in
  `_shaped_payloads` (insert after the add_missing `_payload` call, renumber msg ids to
  match the workflow):

```python
        self._payload(4, "edit", {"entry_id": 1, "client": "Client A"})
```

- [ ] **Step 3: timeassist/demo.py** — the scripted flow approves entries for
  `Client A`/`Client B`; give the demo a roster so nothing is needs_info. Before the
  `start` step in the flow list (actions.py-style args at demo.py:50), write a synthetic
  roster CSV into the demo workdir and prepend an import step:

```python
    clients_csv = out / "demo-clients.csv"
    clients_csv.write_text(
        "display_name,aliases,default_billable,default_job_type\n"
        "Client A,,yes,Bookkeeping\n"
        "Client B,,yes,Tax\n"
    )
```

and as the first commands after `init`:

```python
        ["import-clients", "--file", str(clients_csv), "--mode", "replace", "--confirm-replace"],
```

(Adapt to demo.py's actual step-list structure — keep entry ids 1 and 2 unchanged; the
import creates no entries. The demo transcript gains the import step; that is desired.)

- [ ] **Step 4: Run the full suite and fix every C1-fallout failure by these rules:**

Run: `python3 -m unittest discover -s tests 2>&1 | tail -30`

- A test whose PURPOSE is a capture/approve/export flow on a synthetic client
  (`Client A`, `Acme Co`, …): seed a roster first. In `tests/test_mcp_server.py` add a
  helper on the test class and call it in the failing tests right after `init_state`:

```python
    def seed_roster(self, *names: str) -> None:
        path = Path(self.tmp.name) / "clients.csv"
        path.write_text("display_name,aliases,default_billable\n"
                        + "".join(f"{name},,yes\n" for name in names))
        self.payload("import_clients", {"file": str(path), "mode": "merge"})
```

  (Check the actual `import_clients` MCP tool argument names in `mcp_server.call_tool`
  first and match them.) For `tests/test_actions.py` failures use
  `actions.import_clients` with a written CSV; `tests/test_prototype_workflow.py`
  already imports a roster at line 293-301 — extend that CSV with any missing names
  instead of adding steps; `tests/test_plugin_data_paths.py:125` likewise seeds or
  confirm-edits.
- A test that ASSERTS unknown-client capture behavior: update the expectation to
  `needs_info` (that is now the correct behavior).
- Never weaken an assertion to make it pass; if a fix feels wrong, stop and flag it.

Expected after fixes: OK (301+ tests).

- [ ] **Step 5: Regenerate the demo and verify it is synthetic-only:**

Run: `python3 scripts/run_stakeholder_demo.py && git diff --stat demo/generated/`
Expected: regenerated files, only synthetic names.

- [ ] **Step 6: Commit** (combined with Task 3 if not yet committed):

```bash
git add .github/workflows/windows-build.yml tests/ timeassist/demo.py demo/generated/
git commit -m "test+ci: roster gate fallout — smoke confirm step, contract replay, rosters in fixtures, demo roster (#35 review C1)"
```

---

### Task 5: enforce the billable lock at approve/approve_all/export (I2)

**Files:**
- Modify: `timeassist/actions.py:1390-1419` (set_approval), `:1422-1468` (approve_all),
  `:1471-1530` (export_entries), `timeassist/mcp_views.py:97-129` (approve_all/export views)
- Test: `tests/test_actions.py`, `tests/test_mcp_views.py`

- [ ] **Step 1: Write the failing tests:**

```python
class LockedBillableFinalizeGateTests(unittest.TestCase):
    # Pilot email (#34): admin clients must be IMPOSSIBLE to bill. Capture and
    # edit force billable=0, but pre-upgrade (v0.1.19) rows can carry billable=1
    # on a now-locked client — the finalize gates are the safety net.
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.work = Path(self.tmp.name)
        self.db = self.work / "timeassist.sqlite"
        actions.init_state(self.db, "2026-05-28T09:00:00")

    def _legacy_admin_entry(self) -> int:
        entry = actions.add_missing_entry(self.db, "Placeholder", "internal admin work",
                                          "2026-05-28T10:00:00", "2026-05-28T10:30:00")
        with db.connect(self.db) as conn:
            conn.execute(
                "UPDATE time_entries SET client_name='Admin', billable=1, "
                "capture_status='resolved', review_status='draft' WHERE entry_id=?",
                (entry["entry_id"],))
            conn.commit()
        return entry["entry_id"]

    def test_approve_rejects_locked_billable_entry(self) -> None:
        entry_id = self._legacy_admin_entry()
        with self.assertRaises(ValueError) as ctx:
            actions.set_approval(self.db, entry_id, True)
        self.assertIn("administrative and cannot be billable", str(ctx.exception))

    def test_approve_all_skips_locked_billable_and_counts(self) -> None:
        self._legacy_admin_entry()
        result = actions.approve_all(self.db, "2026-05-28")
        self.assertEqual(result["approved_count"], 0)
        self.assertEqual(result["skipped_locked_count"], 1)
        self.assertEqual(result["skipped_locked_minutes"], 30)

    def test_export_skips_locked_billable_and_counts(self) -> None:
        entry_id = self._legacy_admin_entry()
        with db.connect(self.db) as conn:  # simulate a pre-upgrade approval
            conn.execute("UPDATE time_entries SET review_status='approved' WHERE entry_id=?",
                         (entry_id,))
            conn.commit()
        out = self.work / "out.csv"
        with self.assertRaises(ValueError):
            # only entry of the day is skipped -> nothing to export
            actions.export_entries(self.db, "2026-05-28", out)

    def test_non_billable_admin_entry_finalizes_normally(self) -> None:
        session = actions.start_session(self.db, "Admin", "emails", None, "2026-05-28T11:00:00")
        self.assertEqual(session["billable"], 0)
        actions.end_session(self.db, "2026-05-28T11:30:00")
        result = actions.approve_all(self.db, "2026-05-28")
        self.assertEqual(result["approved_count"], 1)
```

Also in `tests/test_mcp_views.py`: `approve_all`/`export` views include
`skipped_locked_count`/`skipped_locked_minutes` when > 0 and omit them when 0
(copy the `missing_notes_count` test pattern).

- [ ] **Step 2: Run, verify failure** (`KeyError: 'skipped_locked_count'`, no raise).

- [ ] **Step 3: Implement.** Add a helper next to `set_approval`:

```python
def _locked_billable_reason(conn, entry: dict[str, Any]) -> str | None:
    """Non-None when a billable entry names a billable_locked client — legacy
    (pre-lock) data the capture/edit paths never see. Finalize gates use this
    so such time can never be approved or exported billable."""
    if not entry.get("billable"):
        return None
    row = resolve_client_row(conn, entry["client_name"])
    if row is not None and int(row["billable_locked"]):
        return (f"entry {entry['entry_id']} bills '{row['display_name']}', which is "
                "administrative and cannot be billable; edit billable to no before approving")
    return None
```

In `set_approval`, after the needs_info check (actions.py:1404-1409), add:

```python
        if approved:
            locked_reason = _locked_billable_reason(conn, before)
            if locked_reason:
                raise ValueError(locked_reason)
```

In `approve_all`, inside the approval loop (actions.py:1452), skip and count:

```python
        skipped_locked_count = 0
        skipped_locked_minutes = 0
        for row in rows:
            before = row_to_dict(row)
            if _locked_billable_reason(conn, before):
                skipped_locked_count += 1
                skipped_locked_minutes += int(before["rounded_minutes"])
                continue
            ...
```

and add `"skipped_locked_count"`/`"skipped_locked_minutes"` to the result dict.

In `export_entries`, filter the fetched entries (after actions.py:1504) and count the
same way, adding both keys to its result dict; the existing "nothing to export" error
fires when the filter empties the list.

In `mcp_views.py`, in `_view_approve_all` and `_view_export`, add:

```python
    if result.get("skipped_locked_count"):
        shaped["skipped_locked_count"] = result["skipped_locked_count"]
        shaped["skipped_locked_minutes"] = result["skipped_locked_minutes"]
```

- [ ] **Step 4: Full suite.** Run: `python3 -m unittest discover -s tests` — Expected: OK.
  (`tests/test_workflow_smoke_contract.py` still passes: the workflow reads no new keys.)

- [ ] **Step 5: Commit**

```bash
git add timeassist/actions.py timeassist/mcp_views.py tests/
git commit -m "feat: approve/export refuse billable time on locked admin clients (legacy-data safety net, #35 review I2)"
```

---

### Task 6: seeding never collides with operator labels (I3)

**Files:**
- Modify: `timeassist/db.py:233-244` (seed loop)
- Test: `tests/test_actions.py` (near the existing seed tests at :168-238)

- [ ] **Step 1: Write the failing test:**

```python
    def test_seed_skipped_when_operator_alias_uses_the_name(self) -> None:
        # Replace-import drops the seeds; the operator's OWN roster row carries
        # alias 'admin'. Re-seeding 'Admin' would shadow that alias (the exact
        # display-name pass beats the alias pass), so the seed must be skipped.
        path = self.work / "clients.csv"
        path.write_text("display_name,aliases,default_billable\nAdministrator,admin,yes\n")
        actions.import_clients(self.db, path, mode="replace")
        session = actions.start_session(self.db, "admin", "internal", None, "2026-05-28T09:00:00")
        self.assertEqual(session["client_name"], "Administrator")
        self.assertEqual(session["billable"], 1)
        with db.connect(self.db) as conn:
            self.assertIsNone(conn.execute(
                "SELECT 1 FROM clients WHERE display_name = 'Admin'").fetchone())
```

(Use this file's actual test-class conventions; `import_clients` mode="replace" via
`actions` does not need confirm_replace — that flag lives at the CLI/MCP layer. Verify
and adapt if the actions-layer signature differs.)

- [ ] **Step 2: Run, verify FAIL** (today the seed re-appears and hijacks 'admin').

- [ ] **Step 3: Implement** — replace the seed loop in `db.initialize`:

```python
        # Seed the built-in non-billable admin clients. ON CONFLICT DO NOTHING so
        # a re-run never clobbers operator roster edits (initialize() runs on
        # every action via ensure_initialized()); additionally skip a seed whose
        # name is already an operator row's display name or alias under a
        # different key — otherwise the seeded display name would shadow that
        # label (exact display match beats alias match in resolve_client_row).
        label_owner: dict[str, str] = {}
        for row in conn.execute("SELECT client_key, display_name, aliases FROM clients"):
            for label in (row["display_name"], *(row["aliases"] or "").split(";")):
                normalized = label.strip().lower()
                if normalized:
                    label_owner.setdefault(normalized, row["client_key"])
        for display_name in ADMIN_CLIENT_SEEDS:
            key = _slugify_client_key(display_name)
            if label_owner.get(display_name.lower(), key) != key:
                continue
            conn.execute(
                """
                INSERT INTO clients(client_key, display_name, aliases, default_billable, default_job_type, billable_locked, updated_at)
                VALUES (?, ?, '', 0, 'Administrative', 1, ?)
                ON CONFLICT(client_key) DO NOTHING
                """,
                (key, display_name, now),
            )
```

- [ ] **Step 4: Full suite.** Run: `python3 -m unittest discover -s tests` — Expected: OK
  (the double-initialize idempotence test at tests/test_actions.py:168 must still pass).

- [ ] **Step 5: Commit**

```bash
git add timeassist/db.py tests/test_actions.py
git commit -m "fix: admin seeds defer to operator display names and aliases (#35 review I3)"
```

---

### Task 7: sanitized packet redacts Job Type (I1)

**Files:**
- Modify: `timeassist/actions.py:1581-1595` (anonymized_entries)
- Test: `tests/test_actions.py` (packet tests area)

- [ ] **Step 1: Write the failing test:**

```python
    def test_sanitized_packet_redacts_job_type(self) -> None:
        actions.add_missing_entry(
            self.db, "Real Client", "notes about a person",
            "2026-05-28T10:00:00", "2026-05-28T10:30:00",
            job_type="Tax prep for Smith Family Trust")
        out = self.work / "packet.md"
        actions.write_sanitized_packet(self.db, "2026-05-28", out)
        packet = out.read_text()
        self.assertNotIn("Smith Family Trust", packet)
        self.assertIn("Job Type 1", packet)
```

(If the packet test class seeds a roster after Task 4, keep consistent; needs_info
entries still appear in review/packet, so no roster is required here.)

- [ ] **Step 2: Run, verify FAIL** (raw job_type in packet).

- [ ] **Step 3: Implement** — in `anonymized_entries`, redact job_type with the same
  mapping pattern as clients (free text routinely embeds client detail):

```python
def anonymized_entries(entries: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, str]]:
    mapping: dict[str, str] = {}
    job_type_mapping: dict[str, str] = {}
    safe_entries: list[dict[str, Any]] = []
    for index, entry in enumerate(entries, start=1):
        client = entry["client_name"]
        if client not in mapping:
            mapping[client] = f"Client {len(mapping) + 1}"
        safe = dict(entry)
        safe["client_name"] = mapping[client]
        # task_text and job_type are free text that routinely embeds real
        # client/contact detail; the packet promises anonymized labels only.
        safe["task_text"] = f"Task {index}"
        job_type = entry.get("job_type") or ""
        if job_type:
            if job_type not in job_type_mapping:
                job_type_mapping[job_type] = f"Job Type {len(job_type_mapping) + 1}"
            safe["job_type"] = job_type_mapping[job_type]
        safe_entries.append(safe)
    return safe_entries, mapping
```

- [ ] **Step 4: Full suite** (a demo/packet fixture may pin the old raw value — update it,
  then re-run `python3 scripts/run_stakeholder_demo.py` if `demo/generated/` embeds a
  packet). Expected: OK.

- [ ] **Step 5: Commit**

```bash
git add timeassist/actions.py tests/test_actions.py demo/generated/
git commit -m "fix: sanitized packet anonymizes Job Type labels (#35 review I1)"
```

---

### Task 8: `import_clients` MCP view — counts only (M4)

**Files:**
- Modify: `timeassist/mcp_views.py:170-199`
- Test: `tests/test_mcp_views.py`

- [ ] **Step 1: Write the failing test:**

```python
    def test_import_clients_view_returns_counts_only(self) -> None:
        shaped = mcp_views.shape("import_clients", {
            "mode": "merge", "imported_count": 2,
            "clients": [{"client_key": "a", "display_name": "A", "aliases": "",
                         "default_billable": 1, "default_job_type": "",
                         "billable_locked": 0, "updated_at": "2026-05-28T09:00:00"}],
        })
        self.assertEqual(shaped, {"mode": "merge", "imported_count": 2})
```

- [ ] **Step 2: Run, verify FAIL** (raw clients echoed).

- [ ] **Step 3: Implement:**

```python
def _view_import_clients(result: dict[str, Any]) -> dict[str, Any]:
    # Counts only: the roster echo would burn tokens and now carries engine-only
    # columns (billable_locked, default_job_type); the model can call list_clients.
    return {"mode": result["mode"], "imported_count": result["imported_count"]}
```

and register `"import_clients": _view_import_clients` in `_VIEWS`.

- [ ] **Step 4: Full suite** — Expected: OK (fix any mcp_server test that asserted the
  echoed roster; the CLI keeps the full result).

- [ ] **Step 5: Commit**

```bash
git add timeassist/mcp_views.py tests/
git commit -m "feat: import_clients MCP result is counts only (#35 review M4)"
```

---

### Task 9: cleanup + missing pins (M6/M7)

**Files:**
- Modify: `timeassist/db.py:112-116`, `timeassist/actions.py:341-343`, `:788-794`,
  `:1369-1374`, `tests/test_actions.py:568-640` (ManagementTiebreakTests fixtures),
  `:1169-1173` (format_hhmm test), `:1206` area (duplicate injection test)

- [ ] **Step 1: Dedupe slugify.** In `db.py` rename `_slugify_client_key` →
  `slugify_client_key` (public), drop its "duplicated here" comment, update the seed
  loop call. In `actions.py` delete `slugify_client_key` (`:341-343`) and add
  `slugify_client_key` to the existing `from .db import ...` line (verify with
  `grep -rn "slugify_client_key"` that all callers — including `import_clients` and any
  tests — still resolve).

- [ ] **Step 2: One notes-missing predicate.** In `actions.py` add above
  `_flag_missing_notes`:

```python
def _notes_missing(task_text: str | None) -> bool:
    return not (task_text or "").strip()
```

Use it in `_flag_missing_notes` and replace the `review_entries` count
(actions.py:1369-1374, dropping the redundant discarded filter — `list_entries_for_date`
already excludes discarded rows):

```python
    # #34: nudge count for entries whose Notes were skipped.
    missing_notes_count = sum(1 for e in entries if _notes_missing(e.get("task_text")))
```

- [ ] **Step 3: ManagementTiebreakTests fixtures through the real import path.** Replace
  `_insert` raw SQL with a CSV import (Highfield Partners / Highfield Partners Management
  pass label-uniqueness validation):

```python
    def _seed(self) -> None:
        path = self.work / "clients.csv"
        path.write_text(
            "display_name,aliases,default_billable\n"
            "Highfield Partners,,yes\n"
            "Highfield Partners Management,,no\n"
        )
        actions.import_clients(self.db, path)
```

Update the five tests to call `self._seed()` instead of the two `_insert` calls.

- [ ] **Step 4: Missing pins.** In `test_format_hhmm` add
  `self.assertEqual(actions.format_hhmm(1500), "25:00")` (spec promised a >24h case).
  Add the end-path leak regression next to the switch one (tests/test_actions.py:1992):

```python
    def test_end_audit_log_never_persists_notes_missing(self) -> None:
        actions.start_session(self.db, "Client A", "", None, "2026-05-28T09:00:00")
        entry = actions.end_session(self.db, "2026-05-28T09:30:00")
        self.assertTrue(entry.get("notes_missing"))
        with db.connect(self.db) as conn:
            leaked = conn.execute(
                "SELECT 1 FROM event_log WHERE COALESCE(after_json,'') LIKE '%notes_missing%' "
                "OR COALESCE(before_json,'') LIKE '%notes_missing%'").fetchone()
        self.assertIsNone(leaked)
```

(Match the surrounding class's setUp; seed a roster if the class does after Task 4.)

- [ ] **Step 5: Remove the duplicate injection test** —
  `ExportFormatTests.test_export_still_neutralizes_formula_injection` (the same invariant
  is pinned by `ExportHardeningTests.test_export_neutralizes_csv_formula_injection`).

- [ ] **Step 6: Full suite.** Run: `python3 -m unittest discover -s tests` — Expected: OK.

- [ ] **Step 7: Commit**

```bash
git add timeassist/ tests/
git commit -m "chore: dedupe slugify + notes predicate, real-import fixtures, >24h and end-leak pins (#35 review M6/M7)"
```

---

### Task 10: docs — CHANGELOG, SKILL.md, decision log, spec header (M2/M3/M8)

**Files:**
- Modify: `CHANGELOG.md` (Unreleased section), 
  `plugin/timeassist/skills/billable-time-assistant/SKILL.md:110-117`,
  `docs/decision-log.md`, `docs/plans/2026-07-01-timmy-pilot-feedback.md:3-4`,
  `CLAUDE.md` (local, gitignored — slim-entry key list), `tests/test_plugin_data_paths.py`

- [ ] **Step 1: CHANGELOG.md Unreleased.** Reword the management bullet (M2) to:

```markdown
- When a client and its near-identical "management" company both appear on the
  roster, name-matching never lands on the management company by accident: it is
  billed only when named exactly; anything ambiguous is flagged for review instead
  of guessed.
```

Replace the now-true-by-import claim and add the new behavior:

```markdown
- Roster CSVs may include a `default_job_type` column; new time for that client
  fills it in automatically.
- A client name that isn't on the roster is flagged for confirmation on every
  capture path (timers, switches, and added blocks) — approval and export always
  see it first.
- Approve and export refuse time billed to an administrative client (protects
  data recorded before this version); the sanitized packet now anonymizes Job
  Type labels too.
```

- [ ] **Step 2: SKILL.md.** In the Administrative-clients paragraph (:113) append the
  M3 qualifier:

```markdown
If the operator's own roster deliberately reuses one of these names (via import),
their client's settings win — follow the engine's response, not this rule.
```

Do not change the phrases asserted by `tests/test_plugin_data_paths.py` (grep each
asserted string after editing). Mention the new skip counts where approve/export are
described: "`approve_all`/`export` may report `skipped_locked_count` — administrative
time recorded as billable by an older version; fix with one `edit` setting billable no."

- [ ] **Step 3: decision log** — append three entries (Decision/Why format, dated
  2026-07-02): (a) unknown-client `needs_info` now applies to every capture path — the
  #34 approve/export roster gate is real for start/add_missing, capture still never
  blocks; (b) billable lock enforced at approve/approve_all/export as a legacy-data
  safety net — the engine never silently rewrites stored billable, it refuses/skips and
  tells the operator; (c) admin seeding defers to operator labels and merge-import takes
  ownership (billable_locked reset) — supersedes the narrower 2026-06 "ON CONFLICT DO
  NOTHING" wording; note the word-multiset argument for the management-pass
  unreachability while editing (fold preserves word multisets, so fold-collisions
  contain "management" together or not at all).

- [ ] **Step 4: spec header** — in `docs/plans/2026-07-01-timmy-pilot-feedback.md`
  replace the header line (:3-4) with:

```markdown
> **Status: IMPLEMENTED on `feat/timmy-pilot-feedback` (PR #35), pending release —
> do not re-execute. Review-fix addendum: `docs/plans/2026-07-02-timmy-review-fixes.md`.**
```

- [ ] **Step 5: CLAUDE.md (local)** — update the slim-entry key list to
  `entry_id/client/notes/job_type/billable/start/end/minutes/status (+ raw_minutes,
  needs_info, notes_missing)`.

- [ ] **Step 6: gate test + suite.** Extend `tests/test_plugin_data_paths.py` required
  phrases with `"skipped_locked_count"`. Run the full suite — Expected: OK.

- [ ] **Step 7: Commit**

```bash
git add CHANGELOG.md plugin/ docs/ tests/test_plugin_data_paths.py
git commit -m "docs: review-fix round — accurate management wording, admin-name override note, decision log (#35)"
```

---

### Task 11: final verification + push

- [ ] **Step 1:** `python3 -m unittest discover -s tests` → OK; note the new test count.
- [ ] **Step 2:** MCP smoke from CLAUDE.md (initialize + tools/list on a throwaway DB)
  → 24 tools, no error.
- [ ] **Step 3:** Live E2E on a throwaway DB (CLI): init → import roster (with
  default_job_type col) → start unknown client → verify needs_info in result → edit
  confirm → start Admin billable=yes rejected → approve_all → export → CSV has the six
  columns, H:MM durations, auto-filled Job Type; sanitize-packet shows `Job Type N`.
- [ ] **Step 4:** `python3 scripts/timeassist.py --version` → 0.1.20 (unchanged).
- [ ] **Step 5:** `git push` to `feat/timmy-pilot-feedback`; comment on PR #35
  summarizing the review-fix round (findings addressed, new behavior, test count).
