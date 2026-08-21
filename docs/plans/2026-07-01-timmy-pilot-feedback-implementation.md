# Timmy Pilot Feedback (v0.1.21 iteration) Implementation Plan

> **Status: SHIPPED in v0.1.21-prototype (PR #35) — never execute this plan.**

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. **Subagents must run on Opus (operator instruction).**

**Goal:** Implement the pilot-feedback email items (issue #34) per spec `docs/plans/2026-07-01-timmy-pilot-feedback.md`: job_type + notes columns, admin pseudo-clients with billable lock, comma-swap + management-tiebreak name matching, notes nudges, HH:MM export columns, and Timmy user-facing branding.

**Architecture:** Deterministic Python + SQLite engine (`timeassist/`), stdlib only — **never add third-party deps**. All logic lands in `actions.py`/`db.py`; MCP result shaping only in `mcp_views.py`; behavior contracts in BOTH SKILL.md copies. Tests: `python3 -m unittest discover -s tests` (currently 228 tests + 5 subtests, all green) **must pass before every commit**.

**Tech Stack:** Python 3 stdlib, sqlite3, unittest. Branch off `main` (create `feat/timmy-pilot-feedback` from `docs/timmy-pilot-feedback-spec`'s base or after that PR merges — do not commit to main). Every commit message ends with:
`Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`

**Invariants that must survive (from CLAUDE.md):** engine owns all time math; `needs_info` gates approve/export; capture never blocks; rounding floor untouched; timestamps naive local ISO; no hard deletes; synthetic data only.

---

## File map

| File | Change |
|---|---|
| `timeassist/db.py` | `job_type` on `active_sessions`+`time_entries`; `default_job_type`,`billable_locked` on `clients`; seed 4 admin clients |
| `timeassist/actions.py` | `name_fold`, `_management_fold`, rewritten `resolve_client` (4 passes), billable-lock enforcement, `job_type` plumbing in start/switch/add_missing/edit/clarify, `notes_missing` on close, `missing_notes_count` in review, HH:MM export columns |
| `timeassist/mcp_views.py` | slim entry: `task`→`notes`, add `job_type`; slim session same; `missing_notes_count` in review view; `notes_missing` passthrough on end/switch |
| `timeassist/mcp_server.py` | `job_type` param on start/switch/add_missing/edit/clarify_active tool schemas; wording "notes" |
| `timeassist/cli.py` | `--job-type` flags mirroring MCP params |
| `plugin/timeassist/skills/billable-time-assistant/SKILL.md` + `skills/billable-time-assistant/SKILL.md` (BOTH copies) | Timmy persona, notes nudges, proactive needs_info surfacing, placeholder-must-match contract, job_type column |
| `plugin/timeassist/plugin.json`, `.claude-plugin/marketplace.json` (repo root) | Timmy display name/description only — key/id/exe names unchanged |
| `docs/accountant-quick-start.md`, `docs/wiki/`, `CHANGELOG.md`, `docs/decision-log.md` | Branding + operator-facing notes + decisions |
| `tests/test_actions.py`, `tests/test_mcp_views.py`, `tests/test_mcp_server.py`, `tests/test_package_plugin.py`, `tests/test_workflow_smoke_contract.py` | New coverage per task; contract updates |

**Version bump:** deferred to release (do NOT touch `__init__.py`/plugin.json version — a test enforces they match).

---

### Task 1: Schema — job_type, client defaults, billable lock

**Files:** Modify `timeassist/db.py` (SCHEMA + column-definition maps + `initialize()`); Test `tests/test_actions.py`.

- [ ] **Step 1: Write failing tests** — append to `tests/test_actions.py` (follow the file's existing tmp-db fixture pattern; reuse its helper for a fresh db path):

```python
class SchemaMigrationTests(unittest.TestCase):
    def test_new_columns_and_seeds_are_idempotent(self):
        db_path = self.make_db_path()  # use the module's existing tmp-db helper
        actions.ensure_initialized(db_path)
        actions.ensure_initialized(db_path)  # second run must not raise
        with db.connect(db_path) as conn:
            entry_cols = {r["name"] for r in conn.execute("PRAGMA table_info(time_entries)")}
            sess_cols = {r["name"] for r in conn.execute("PRAGMA table_info(active_sessions)")}
            client_cols = {r["name"] for r in conn.execute("PRAGMA table_info(clients)")}
            self.assertIn("job_type", entry_cols)
            self.assertIn("job_type", sess_cols)
            self.assertLessEqual({"default_job_type", "billable_locked"}, client_cols)
            rows = conn.execute(
                "SELECT display_name, default_job_type, default_billable, billable_locked "
                "FROM clients WHERE billable_locked = 1 ORDER BY display_name"
            ).fetchall()
        self.assertEqual(
            [(r["display_name"], r["default_job_type"], r["default_billable"], r["billable_locked"]) for r in rows],
            [("Admin", "Administrative", 0, 1), ("Early Out", "Administrative", 0, 1),
             ("Holiday", "Administrative", 0, 1), ("Staff Meeting", "Administrative", 0, 1)],
        )

    def test_admin_seed_does_not_clobber_operator_roster_edit(self):
        db_path = self.make_db_path()
        actions.ensure_initialized(db_path)
        with db.connect(db_path) as conn:
            conn.execute("UPDATE clients SET aliases = 'ADM' WHERE display_name = 'Admin'")
            conn.commit()
        actions.ensure_initialized(db_path)
        with db.connect(db_path) as conn:
            row = conn.execute("SELECT aliases FROM clients WHERE display_name = 'Admin'").fetchone()
        self.assertEqual(row["aliases"], "ADM")
```

- [ ] **Step 2: Run to verify failure**
Run: `python3 -m unittest tests.test_actions.SchemaMigrationTests -v` — Expected: FAIL (missing columns / no seeded rows).

- [ ] **Step 3: Implement in `db.py`**
  - Add to `SCHEMA` table definitions (new-DB path) AND to migration maps (existing-DB path):

```python
ENTRY_JOB_COLUMN_DEFINITIONS = {"job_type": "TEXT NOT NULL DEFAULT ''"}
CLIENT_COLUMN_DEFINITIONS = {
    "default_job_type": "TEXT NOT NULL DEFAULT ''",
    "billable_locked": "INTEGER NOT NULL DEFAULT 0",
}

ADMIN_CLIENT_SEEDS = ("Admin", "Early Out", "Holiday", "Staff Meeting")
```

  - Generalize the existing `_ensure_capture_columns` pattern (add a `_ensure_columns(conn, table, definitions)` helper; keep `_ensure_capture_columns` calling it) and in `initialize()` call it for the two new maps, then seed (uses the existing `ON CONFLICT ... DO NOTHING` idiom so operator edits are never clobbered — mirror `slugify_client_key` from actions.py for keys; inline the same logic or a local copy to avoid a circular import):

```python
for display in ADMIN_CLIENT_SEEDS:
    conn.execute(
        """
        INSERT INTO clients(client_key, display_name, aliases, default_billable,
                            default_job_type, billable_locked, updated_at)
        VALUES (?, ?, '', 0, 'Administrative', 1, ?)
        ON CONFLICT(client_key) DO NOTHING
        """,
        (_slugify(display), display, now),
    )
```

  Also add `job_type TEXT NOT NULL DEFAULT ''` to both table bodies in `SCHEMA` and the two client columns to the `clients` body, so fresh DBs match migrated ones.

- [ ] **Step 4: Run** `python3 -m unittest tests.test_actions.SchemaMigrationTests -v` — Expected: PASS. Then full suite: `python3 -m unittest discover -s tests` — Expected: all pass (some tests may assert exact roster contents; if any now fail because 4 seeded clients exist, update those assertions deliberately, noting it in the commit).

- [ ] **Step 5: Commit** — `git add timeassist/db.py tests/test_actions.py && git commit` (`feat: add job_type/default_job_type/billable_locked columns and seed admin clients`).

---

### Task 2: `name_fold` comma-swap matching (folded 2026-06-17 spec)

**Files:** Modify `timeassist/actions.py` (near `resolve_client`, line ~452); Test `tests/test_actions.py`.

- [ ] **Step 1: Write failing tests**

```python
class NameFoldTests(unittest.TestCase):
    def test_comma_swap_and_normalization(self):
        self.assertEqual(actions.name_fold("Smith, John"), "john smith")
        self.assertEqual(actions.name_fold("  JOHN   SMITH "), "john smith")
        self.assertEqual(actions.name_fold("Acme Holdings LLC"), "acme holdings llc")
        # Malformed comma forms fall through without swapping
        self.assertEqual(actions.name_fold("Smith, John, Jr"), "smith, john, jr")
        self.assertEqual(actions.name_fold("Smith,"), "smith,")

class ResolveClientFoldTests(unittest.TestCase):
    # setUp: fresh db, import roster with clients "Smith, John" and "Acme Holdings LLC"
    def test_typed_first_last_matches_comma_roster_entry(self):
        with db.connect(self.db_path) as conn:
            name, billable = actions.resolve_client(conn, "John Smith")
        self.assertEqual(name, "Smith, John")
        self.assertEqual(billable, 1)

    def test_duplicate_folds_stay_needs_info(self):
        # Add a second client whose display name folds identically ("John Smith")
        # then resolving "john smith" must return (input, None) — never guesses.
        ...
```

(Write the duplicate-fold setup concretely: insert a second row `display_name='John Smith'` directly via SQL since `import_clients` may reject near-duplicates; assert `resolve_client` returns `("john smith", None)`.)

- [ ] **Step 2: Run** `python3 -m unittest tests.test_actions.NameFoldTests tests.test_actions.ResolveClientFoldTests -v` — Expected: FAIL (`name_fold` missing).

- [ ] **Step 3: Implement** — pure helper + third pass in `resolve_client` (after the alias pass, before the fallthrough):

```python
def name_fold(name: str) -> str:
    """Fold 'Lastname, Firstname' to 'firstname lastname' (lower, collapsed spaces).

    Only names with exactly one comma and text on both sides swap; business
    names and malformed strings fold to plain lowercase so they can never
    cross-match. Display names only — aliases stay exact-match.
    """
    s = " ".join(name.lower().split())
    if "," in s:
        parts = [p.strip() for p in s.split(",")]
        if len(parts) == 2 and all(parts):
            s = f"{parts[1]} {parts[0]}"
    return s
```

In `resolve_client`, after the alias loop:

```python
    folded_target = name_fold(name)
    fold_matches = [row for row in rows if name_fold(row["display_name"]) == folded_target]
    if len(fold_matches) == 1:
        row = fold_matches[0]
        return row["display_name"], int(row["default_billable"])
    # 0 or >1 fold matches: never guess between people — fall through (needs_info).
    return name, None
```

- [ ] **Step 4: Run targeted tests then full suite** — Expected: PASS / all green.
- [ ] **Step 5: Commit** (`feat: comma-swap name folding in resolve_client (spec 2026-06-17)`).

---

### Task 3: Management-company tiebreak

**Files:** Modify `timeassist/actions.py` (`resolve_client`, `capture_note_text`); Test `tests/test_actions.py`.

**Locked semantics (from spec, sharpened):** a fourth pass, only reached when passes 1–3 found nothing. Strip the whole word `management` from folded names; if the stripped target equals the stripped display name of **exactly two** roster entries, **exactly one** of which contains the word `management`, and the **typed name does not** contain the word `management`, resolve to the non-management entry. Every other shape (three candidates, both/neither management, target says management) falls through to `needs_info`. This is deterministic — pinned by test + comment per the rounding-floor convention.

- [ ] **Step 1: Write failing tests**

```python
class ManagementTiebreakTests(unittest.TestCase):
    # setUp: roster has "Highfield Partners" and "Highfield Partners Management"
    def test_ambiguous_pair_resolves_to_non_management(self):
        with db.connect(self.db_path) as conn:
            name, billable = actions.resolve_client(conn, "highfield partners")
        self.assertEqual(name, "Highfield Partners")  # exact pass wins here already
        # The tiebreak case proper: typed name matches NEITHER exactly
        with db.connect(self.db_path) as conn:
            name, billable = actions.resolve_client(conn, "Partners, Highfield")  # folds to 'highfield partners'
        self.assertEqual(name, "Highfield Partners")

    def test_typed_management_never_tiebreaks(self):
        with db.connect(self.db_path) as conn:
            name, billable = actions.resolve_client(conn, "Highfield Management Partners")
        self.assertIsNone(billable)  # needs_info, no guess

    def test_three_candidates_or_two_management_stay_needs_info(self):
        # add "Highfield Partners Management Two" style rows and assert fallthrough
        ...

    def test_management_substring_inside_word_does_not_count(self):
        # 'Mismanagement Co' — 'management' is not a standalone word; no tiebreak
        ...
```

(Fill the `...` tests concretely when writing: insert extra rows via SQL, assert `(input, None)` returns.)

- [ ] **Step 2: Run** — Expected: FAIL.

- [ ] **Step 3: Implement**

```python
def _management_fold(name: str) -> str:
    words = [w for w in name_fold(name).split() if w != "management"]
    return " ".join(words)


def _has_management_word(name: str) -> bool:
    return "management" in name_fold(name).split()
```

In `resolve_client`, replace the final fallthrough with:

```python
    # Management tiebreak (pilot feedback #34): firms register a near-identical
    # "management" shell company; when a typed name is ambiguous between exactly
    # one management and one non-management roster entry, deterministically pick
    # the non-management one so the shell never gets billed by accident. This is
    # a pinned deterministic rule, NOT a guess — every other ambiguity still
    # returns needs_info (see ManagementTiebreakTests).
    if not _has_management_word(name):
        stripped_target = _management_fold(name)
        candidates = [row for row in rows if _management_fold(row["display_name"]) == stripped_target]
        mgmt = [row for row in candidates if _has_management_word(row["display_name"])]
        if len(candidates) == 2 and len(mgmt) == 1:
            row = next(r for r in candidates if not _has_management_word(r["display_name"]))
            return row["display_name"], int(row["default_billable"])
    return name, None
```

**Provenance:** in `resolve_capture_with_metadata`, when the resolved canonical differs from raw AND the tiebreak fired, we still get `client_changed=True` so `raw_client_name` is preserved — sufficient audit trail; no new capture_note token needed (keeps the view layer untouched). Verify with a test that `raw_client_name` is stored on a tiebreak capture.

- [ ] **Step 4: Run targeted + full suite** — Expected: PASS / green.
- [ ] **Step 5: Commit** (`feat: deterministic management-company tiebreak in resolve_client (#34)`).

---

### Task 4: job_type plumbing + billable lock enforcement

**Files:** Modify `timeassist/actions.py` (`resolve_client` → new `resolve_client_row`, `resolve_capture_with_metadata`, `start_session`, `switch_session`, `add_missing_entry`, `edit_entry`, `clarify_active_session`, `close_active_session` insert lists); Test `tests/test_actions.py`.

**Design:** add `resolve_client_row(conn, name) -> sqlite3.Row | None` containing all four matching passes; `resolve_client` becomes a thin wrapper returning the old tuple (keeps every existing caller/test working). Capture resolution reads `default_job_type`/`billable_locked` off the row.

Rules (engine-enforced, pinned):
1. Known client + no job_type given → `job_type = default_job_type` (may be `''`).
2. `billable_locked` client → force `billable = 0` and `job_type = default_job_type`; an **explicit** `billable=yes` raises `ValueError("client 'Admin' is administrative and cannot be billable")` (plain language, assistant relays verbatim).
3. Unknown client → `job_type` = whatever was passed (or `''`).
4. `edit_entry`/`clarify_active_session` accept `job_type` like other fields; editing a locked client's billable to yes raises the same error; editing the client TO a locked one re-forces the lock.

- [ ] **Step 1: Write failing tests**

```python
class BillableLockTests(unittest.TestCase):
    def test_start_on_admin_client_forces_nonbillable_administrative(self):
        result = actions.start_session(self.db_path, "Admin", "weekly filing", at="2026-07-01T09:00:00")
        self.assertEqual(result["billable"], 0)
        self.assertEqual(result["job_type"], "Administrative")

    def test_explicit_billable_yes_on_locked_client_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "cannot be billable"):
            actions.start_session(self.db_path, "Holiday", "day off", billable="yes", at="2026-07-01T09:00:00")

    def test_edit_cannot_make_locked_client_billable(self):
        actions.start_session(self.db_path, "Staff Meeting", "standup", at="2026-07-01T09:00:00")
        entry = actions.end_session(self.db_path, at="2026-07-01T09:30:00")
        with self.assertRaisesRegex(ValueError, "cannot be billable"):
            actions.edit_entry(self.db_path, entry["entry_id"], billable="yes")

    def test_known_client_inherits_default_job_type(self):
        # roster client with default_job_type='Tax' -> start without job_type -> 'Tax'
        ...

    def test_job_type_flows_through_switch_edit_add_missing(self):
        ...
```

- [ ] **Step 2: Run** — Expected: FAIL (no `job_type` key, no lock).
- [ ] **Step 3: Implement** per the design above. Keep the enforcement in ONE helper so all five entry points share it:

```python
def apply_client_policy(row, billable_requested, job_type_requested) -> tuple[int, str]:
    """Engine-enforced client policy (pilot feedback #34). Pinned by tests.

    Locked (administrative) clients can never be billable; their job_type is
    always the roster default. Explicit billable=yes on a locked client is an
    operator error, rejected in plain language.
    """
    if row is not None and int(row["billable_locked"]):
        if billable_requested is not None and bool_to_int(billable_requested) == 1:
            raise ValueError(f"client '{row['display_name']}' is administrative and cannot be billable")
        return 0, row["default_job_type"]
    if billable_requested is not None:
        billable = bool_to_int(billable_requested)
    else:
        billable = int(row["default_billable"]) if row is not None else 1
    if job_type_requested:
        return billable, job_type_requested.strip()
    return billable, (row["default_job_type"] if row is not None else "")
```

Thread `job_type: str | None = None` through `start_session`, `switch_session`, `add_missing_entry`, `edit_entry`, `clarify_active_session`; write `job_type` in every INSERT/UPDATE that writes `task_text` (sessions and entries), and carry it in `close_active_session`'s session→entry copy.

- [ ] **Step 4: Run full suite** — Expected: green (existing tests unaffected: `resolve_client` tuple API preserved).
- [ ] **Step 5: Commit** (`feat: job_type plumbing and billable lock for administrative clients`).

---

### Task 5: Notes flags (day-of + review nudge hooks)

**Files:** Modify `timeassist/actions.py` (`end_session`, `switch_session`, `review_entries`); Test `tests/test_actions.py`.

- [ ] **Step 1: Write failing tests**

```python
class NotesNudgeTests(unittest.TestCase):
    def test_stop_flags_missing_notes(self):
        actions.start_session(self.db_path, "Acme Holdings LLC", "", at="2026-07-01T09:00:00")
        entry = actions.end_session(self.db_path, at="2026-07-01T09:30:00")
        self.assertTrue(entry["notes_missing"])

    def test_stop_with_notes_has_no_flag(self):
        actions.start_session(self.db_path, "Acme Holdings LLC", "quarterly filing", at="2026-07-01T09:00:00")
        entry = actions.end_session(self.db_path, at="2026-07-01T09:30:00")
        self.assertIsNone(entry.get("notes_missing"))

    def test_switch_flags_missing_notes_on_closed_entry(self):
        ...

    def test_review_counts_missing_notes(self):
        # two entries, one with empty task_text -> missing_notes_count == 1
        result = actions.review_entries(self.db_path, "2026-07-01")
        self.assertEqual(result["missing_notes_count"], 1)
```

- [ ] **Step 2: Run** — Expected: FAIL.
- [ ] **Step 3: Implement**
  - In the dict returned by `end_session` (the closed entry) and in `switch_session`'s `closed_entry`: set `entry["notes_missing"] = True` when `not entry["task_text"].strip()`, else leave key absent (None-dropping keeps results compact).
  - In `review_entries`, alongside the totals loop: `missing_notes_count = sum(1 for e in entries if e["review_status"] != "discarded" and not (e["task_text"] or "").strip())`; add to the returned dict.
- [ ] **Step 4: Run full suite** — Expected: green.
- [ ] **Step 5: Commit** (`feat: missing-notes flags on stop/switch/review for nudges (#34)`).

---

### Task 6: MCP views — notes/job_type keys + nudge fields

**Files:** Modify `timeassist/mcp_views.py` (`slim_entry`, `slim_session`, `_view_review`); Test `tests/test_mcp_views.py`.

- [ ] **Step 1: Write failing tests** — in `tests/test_mcp_views.py`, following its existing shape-assertion style:

```python
def test_slim_entry_uses_notes_and_job_type(self):
    entry = self.sample_entry(task_text="filed the return", job_type="Tax")
    slim = mcp_views.slim_entry(entry)
    self.assertEqual(slim["notes"], "filed the return")
    self.assertEqual(slim["job_type"], "Tax")
    self.assertNotIn("task", slim)

def test_slim_entry_omits_empty_job_type_and_carries_notes_missing(self):
    entry = self.sample_entry(task_text="", job_type="")
    entry["notes_missing"] = True
    slim = mcp_views.drop_nones(mcp_views.slim_entry(entry))
    self.assertNotIn("job_type", slim)
    self.assertTrue(slim["notes_missing"])

def test_review_view_carries_missing_notes_count(self):
    result = self.sample_review_result(missing_notes_count=2)
    shaped = mcp_views.shape("review", result)
    self.assertEqual(shaped["missing_notes_count"], 2)
```

- [ ] **Step 2: Run** — Expected: FAIL.
- [ ] **Step 3: Implement** in `slim_entry`:

```python
        "notes": entry.get("task_text"),          # renamed from "task" (pilot #34)
        "job_type": entry.get("job_type") or None, # None -> dropped when empty
```
plus `if entry.get("notes_missing"): slim["notes_missing"] = True`. Mirror `task`→`notes` + `job_type` in `slim_session`. In `_view_review`: `if result.get("missing_notes_count"): shaped["missing_notes_count"] = result["missing_notes_count"]`.

- [ ] **Step 4: Run full suite** — Expected: some `test_mcp_views`/`test_mcp_server` assertions on the `task` key fail; update them to `notes` deliberately. Then green.
- [ ] **Step 5: Commit** (`feat: MCP views expose notes/job_type and nudge fields`).

---

### Task 7: MCP tool schemas + CLI flags

**Files:** Modify `timeassist/mcp_server.py` (TOOLS entries + `call_tool` for start/switch/add_missing/edit/clarify_active: add optional `job_type` string param; change "task" wording to "notes (what was done)" in descriptions — keep descriptions terse, token budget); Modify `timeassist/cli.py` (add `--job-type` to the matching subcommands; relabel help text task→notes). Test `tests/test_mcp_server.py`, `tests/test_cli_help.py`.

- [ ] **Step 1: Write failing tests** — extend the existing tool-schema assertions in `tests/test_mcp_server.py`: each of the five tools' `inputSchema.properties` contains `job_type`; a `tools/call` of `start` with `job_type` round-trips into the shaped result. NO tool added/removed → the tool-name set assertion stays untouched.
- [ ] **Step 2: Run** — Expected: FAIL.
- [ ] **Step 3: Implement.** Pass `job_type=arguments.get("job_type")` through to the actions.
- [ ] **Step 4: Run full suite.** — Expected: green. Also run the MCP smoke test from CLAUDE.md (throwaway DB) and eyeball `tools/list`.
- [ ] **Step 5: Commit** (`feat: job_type parameter on capture/edit tools and CLI`).

---

### Task 8: Export — new columns + HH:MM duration

**Files:** Modify `timeassist/actions.py` (`export_entries` writer + a new `format_hhmm` helper); Test `tests/test_actions.py` AND `tests/test_workflow_smoke_contract.py` + `.github/workflows/windows-build.yml` if its PowerShell asserts CSV headers/payload keys (**check this — the exact gap that failed the first v0.1.19 build**).

- [ ] **Step 1: Write failing tests**

```python
class ExportFormatTests(unittest.TestCase):
    def test_format_hhmm(self):
        self.assertEqual(actions.format_hhmm(0), "0:00")
        self.assertEqual(actions.format_hhmm(5), "0:05")
        self.assertEqual(actions.format_hhmm(90), "1:30")
        self.assertEqual(actions.format_hhmm(600), "10:00")

    def test_export_columns_and_hhmm(self):
        # approve one entry (client 'Acme Holdings LLC', job_type 'Tax', 90 min) then export
        ...
        with open(result["output"], newline="") as f:
            rows = list(csv.DictReader(f))
        self.assertEqual(list(rows[0].keys()), ["Date", "Client", "Job Type", "Notes", "Duration", "Billable"])
        self.assertEqual(rows[0]["Duration"], "1:30")
        self.assertEqual(rows[0]["Job Type"], "Tax")
```

- [ ] **Step 2: Run** — Expected: FAIL.
- [ ] **Step 3: Implement**

```python
def format_hhmm(minutes: int) -> str:
    return f"{minutes // 60}:{minutes % 60:02d}"
```

In `export_entries`, replace the writer block:

```python
            writer = csv.DictWriter(f, fieldnames=["Date", "Client", "Job Type", "Notes", "Duration", "Billable"])
            writer.writeheader()
            for entry in entries:
                writer.writerow(
                    {
                        "Date": entry["start_at"][:10],
                        "Client": csv_safe(entry["client_name"]),
                        "Job Type": csv_safe(entry.get("job_type") or ""),
                        "Notes": csv_safe(entry["task_text"]),
                        "Duration": format_hhmm(entry["rounded_minutes"]),
                        "Billable": billable_text(entry["billable"]),
                    }
                )
```

Engine still stores integer minutes — HH:MM is display-only; rounding floor untouched.

- [ ] **Step 4: Run full suite** — fix any test asserting the old `Customer/Description/DurationMinutes` headers deliberately. **Grep `windows-build.yml` for header/payload assertions and sync `tests/test_workflow_smoke_contract.py` in the same commit.** Expected: green.
- [ ] **Step 5: Commit** (`feat: export columns Date/Client/Job Type/Notes/Duration(HH:MM)/Billable (#34)`).

---

### Task 9: SKILL.md (both copies) — Timmy persona + behavior contracts

**Files:** Modify `plugin/timeassist/skills/billable-time-assistant/SKILL.md` AND the repo-root copy `skills/billable-time-assistant/SKILL.md` (verify actual path — CLAUDE.md says the plugin copy is the gate-tested contract; memory notes a duplicated copy that must stay in sync); Test `tests/test_package_plugin.py` (the gate test asserting key phrases).

- [ ] **Step 1: Update the gate test first** — add key-phrase assertions (adapt to the test's existing phrase-check style): `"Timmy"`, `"notes"`, a nudge phrase (e.g. `"nudge"`), a surfacing phrase (e.g. `"before approval"`), and the placeholder contract phrase (e.g. `"must match the roster"`). Run: Expected FAIL.
- [ ] **Step 2: Edit both SKILL.md copies (identically):**
  - Persona: the assistant is called **Timmy** (tool/server names unchanged — do not rename tools in examples).
  - Column language: entries have Client, Job Type, **Notes** (what was done), Duration, Billable.
  - Notes nudge: when a `stop`/`switch` result carries `notes_missing`, ask once, briefly, for a note; when `review` shows `missing_notes_count > 0`, nudge once more before approval. Never block approval over notes.
  - Proactive surfacing (spec 2026-06-17 Section B): when `review` returns `needs_info` entries or `skipped_needs_info_count > 0`, name those clients and offer to resolve **before approval** — do not wait to be asked; resolve via the existing one-`edit` confirm-as-is recipe.
  - Placeholder contract: unknown client names are fine during capture, but before approve/export they **must match the roster** (that's what needs_info enforces).
  - Administrative clients: Admin/Early Out/Holiday/Staff Meeting are always non-billable Administrative; if the operator asks to bill one, relay the engine's error verbatim.
  - Keep the existing "never self-initiate roster imports" rule. Keep it terse — SKILL.md size is token-budgeted (~45% trim was a feature in 0.1.19).
- [ ] **Step 3: Run full suite** — Expected: green.
- [ ] **Step 4: Commit** (`feat: Timmy skill contract — nudges, surfacing, placeholder + admin rules`).

---

### Task 10: Branding + docs + changelog + decision log

**Files:** Modify `plugin/timeassist/plugin.json` (display `name`/`description` fields ONLY — not the version, not any key the packaging test derives paths from; check `tests/test_package_plugin.py` first), `.claude-plugin/marketplace.json` (repo root), `docs/accountant-quick-start.md` (non-technical language), `docs/wiki/` intro page, `CHANGELOG.md`, `docs/decision-log.md`.

- [ ] **Step 1: plugin.json + marketplace.json** — user-facing name "Timmy", description mentioning "(formerly TimeAssist)". Run full suite after (version-match + packaging tests must stay green).
- [ ] **Step 2: CHANGELOG.md** — new `## Unreleased` section at top (heading gets finalized at release per convention):

```markdown
## Unreleased

Pilot feedback round 2 (issue #34). Operators upgrading from v0.1.19 also get
v0.1.20's one-step needs_info confirmation, which they have not seen yet.

### Added
- Job Type on every entry; roster clients can carry a default job type.
- Administrative clients (Admin, Early Out, Holiday, Staff Meeting) are built in,
  always non-billable, and always Administrative — the engine enforces this.
- Names typed as `John Smith` now match roster entries stored as `Smith, John`.
- When two roster names differ only by the word "management", ambiguous captures
  deterministically bill the non-management company (never the management shell).
- Gentle nudges when an entry has no notes: once when the timer stops, once at review.

### Changed
- TimeAssist is now called **Timmy** (user-facing name only).
- Entry "task" is now "Notes"; exports use columns Date, Client, Job Type, Notes,
  Duration (HH:MM), Billable.
- Review proactively lists unresolved clients before approval.
```

- [ ] **Step 3: decision-log.md** — append Decision/Why entries: management tiebreak is deterministic engine logic (why: client-requested default, mis-billing risk, provenance in raw_client_name); notes nudge never blocks approval (why: email asked for nudge, not gate); Timmy rename is branding-only (why: zero CI/build risk); job_type is a free string (why: no confirmed vocabulary).
- [ ] **Step 4: accountant-quick-start.md + wiki** — rename to Timmy, mention Notes column and the admin clients, non-technical wording.
- [ ] **Step 5: Run full suite, commit** (`docs: Timmy branding, changelog, decision log (#34)`).

---

### Task 11: Final verification sweep

- [ ] **Step 1:** `python3 -m unittest discover -s tests` — Expected: all pass (count will now exceed 228; record the new count).
- [ ] **Step 2:** `python3 scripts/timeassist.py --version` — Expected: `0.1.20` and still matches plugin.json (bump happens at release, not here).
- [ ] **Step 3:** MCP smoke test from CLAUDE.md (throwaway DB) — Expected: initialize + tools/list respond; spot-check a `start`→`stop`→`review`→`approve_all`→`export` round trip on `/tmp/smoke.sqlite` and open the CSV to see the new columns.
- [ ] **Step 4:** `python3 scripts/run_stakeholder_demo.py` — regenerate `demo/generated/` (synthetic only); commit if changed.
- [ ] **Step 5:** Cross-check the CLAUDE.md sync list: both SKILL.md copies identical where shared; no `TOOLS` add/remove; `test_workflow_smoke_contract.py` in step with `windows-build.yml`; marketplace.json untouched except display fields.
- [ ] **Step 6:** Final commit if anything shook out, then open a PR to `main` (no direct pushes) referencing issue #34, body ending with the standard generated-with footer. **Do not tag/release** — that's a separate `shipping-a-timeassist-release` run later (note: first release after 2026-06-15 needs a `workflow_dispatch` validation run before tagging, runner-image redirect).
