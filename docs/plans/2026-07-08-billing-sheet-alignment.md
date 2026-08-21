# Billing-sheet alignment: date-range export + operator_code Implementation Plan

**Goal:** A date-range mode for `review`/`export` (the firm's verbatim #34 lookback
ask: "grab dates that may overlap the old and the new methods") and an
`operator_code` identity setting so each operator's exports are attributable to an
employee-initials column in the firm's billing workbook — per the locked decisions
below. Target release: v0.1.24-prototype.

**Architecture:** Range support is an optional `end_date` threaded through the
existing per-date funnel — `review_entries` → `review_token` →
`validate_review_token` → `export_entries` in `timeassist/actions.py` — never new
tools or new tables. Single-day calls stay byte-identical (tokens included, pinned
by test). `operator_code` is a settings-table row validated in `set_setting`
(same pattern as `strict_roster`), surfacing only in the default export filename
and tool-result metadata; the CSV columns the firm specified verbatim in #34
(`Date, Client, Job Type, Notes, Duration, Billable`) are untouched. Stdlib only;
no schema change.

**Tech Stack:** Python stdlib + SQLite, unittest.

## Decisions locked

Sign-off: Josh, 2026-07-08 (in-session, after the Template Billing Sheet gap
analysis — see the 2026-07-08 comment on issue #34).

- **operator_code = filename + metadata only.** When set, the *default* export
  filename becomes `quickbooks-time-<CODE>-<date>.csv` and the code is echoed in
  the export result; the CSV columns do not change. An `Employee` column is a
  firm-contract change → parked as a firm question (see Out of scope). Explicit
  `--output` paths are never rewritten.
- **Range = review + export only; one range token.** `review` and `export` accept
  an optional end date; a range review returns per-day totals plus ONE range
  token (no entry lists in the MCP view — token budget), and range export
  validates that token and writes one CSV
  (`quickbooks-time[-<CODE>]-<from>_to_<to>.csv`). The export-requires-current-
  review_token invariant is preserved verbatim.
- **Approval stays strictly per-day.** `approve`/`approve_all` do NOT accept
  ranges — approving a month sight-unseen would gut the human gate. Range export
  only ever writes entries already `approved`/`exported` through per-day review.
- **Backward compatibility is pinned:** with `end_date` omitted (or equal to
  `date`), review results, tokens, export files, and filenames are identical to
  today.
- `operator_code` format: 2–4 letters, stored trimmed + uppercased (firm codes
  are 2–3 letters — AD, AVD, SGL; one legacy BB). Format-validated free entry for
  now; validating against a firm-distributed employee-code list is future work.

## Context (why now)

The firm's real billing workbook (`exports/Template Billing Sheet.xlsx`,
gitignored — real client data, privacy invariant applies) arrived 2026-07-08 and
resolved the parked #34 billing-sheet item. Its ACCT tabs are client rows ×
employee-initials columns of hours; TimeAssist exports are currently
single-day-only and carry no operator identity, which blocks both the lookback
ask and any future rollup. Rates/retainers/adjustments are workbook formulas —
confirmed not the tracker's job.

---

### Task 1: `operator_code` setting (validation + reader)

**Files:**
- Modify: `timeassist/actions.py` (`set_setting` ~line 197; helpers next to
  `normalize_strict_roster`)
- Test: `tests/test_actions.py`

- [ ] **Step 1: Write failing tests** — `OperatorCodeSettingTests`:
  `set_setting("operator_code", " avd ")` stores `"AVD"`; `"bb"` stores `"BB"`;
  `"A"`, `"ABCDE"`, `"A1"`, `""` raise ValueError mentioning `2-4 letters`;
  fresh DB → `get_operator_code(conn)` is None; set then clear via
  `clear_setting` → None again.
- [ ] **Step 2: Run** `python3 -m unittest tests.test_actions.OperatorCodeSettingTests -v` — FAIL (AttributeError).
- [ ] **Step 3: Implement** — in `set_setting`, after the `user_export_dir` check:

```python
    if key == "operator_code":
        value = normalize_operator_code(value)
```

  and next to `normalize_strict_roster`:

```python
_OPERATOR_CODE_RE = re.compile(r"^[A-Z]{2,4}$")


def normalize_operator_code(value: str) -> str:
    token = (value or "").strip().upper()
    if not _OPERATOR_CODE_RE.match(token):
        raise ValueError(
            f"operator_code must be 2-4 letters (your initials code on the firm's employee list), got: {value}"
        )
    return token


def get_operator_code(conn) -> str | None:
    value = (get_setting(conn, "operator_code") or "").strip()
    return value or None
```

- [ ] **Step 4: Run** the same tests — PASS.
- [ ] **Step 5: Commit** `feat: operator_code setting (2-4 letters, uppercased)`

### Task 2: default export filename (code + range aware)

**Files:**
- Modify: `timeassist/paths.py` (`default_export_path`, line 19-20)
- Modify: `timeassist/actions.py` (new `default_export_filename`)
- Modify: `timeassist/cli.py:216` and `timeassist/mcp_server.py:341-342`
  (`default_export_path` wrappers)
- Test: `tests/test_actions.py`

- [ ] **Step 1: Write failing tests** — `default_export_filename(db_path, "2026-06-30")`
  → `quickbooks-time-2026-06-30.csv` on a fresh DB (unchanged);
  after `set_setting("operator_code", "AVD")` →
  `quickbooks-time-AVD-2026-06-30.csv`; with
  `end_date="2026-06-30"` equal to date → single-day name; with
  `date="2026-06-01", end_date="2026-06-30"` →
  `quickbooks-time-AVD-2026-06-01_to_2026-06-30.csv`.
- [ ] **Step 2: Run — FAIL.**
- [ ] **Step 3: Implement** — `paths.default_export_path` gains optional params:

```python
def default_export_path(date_value: str, end_date: str | None = None, operator_code: str | None = None) -> str:
    code = f"{operator_code}-" if operator_code else ""
    span = date_value if not end_date or end_date == date_value else f"{date_value}_to_{end_date}"
    return f"quickbooks-time-{code}{span}.csv"
```

  and in `actions.py` (so CLI/MCP don't each open the DB):

```python
def default_export_filename(db_path: str | Path, date_value: str, end_date: str | None = None) -> str:
    ensure_initialized(db_path)
    with connect(db_path) as conn:
        code = get_operator_code(conn)
    return paths.default_export_path(date_value, end_date, code)
```

  Point `cli.py:216` `default_export_path` and `mcp_server.py:341`
  `_default_export_path` wrappers at `actions.default_export_filename` (they gain
  the db_path they already have in scope at the call sites, cli.py:294 /
  mcp_server.py:431).
- [ ] **Step 4: Run — PASS.**
- [ ] **Step 5: Commit** `feat: operator/range-aware default export filename`

### Task 3: range review + range token

**Files:**
- Modify: `timeassist/actions.py` (`list_entries_for_date` ~1390,
  `review_token` ~1402, `validate_review_token` ~1429, `review_entries` ~1449)
- Test: `tests/test_actions.py`

- [ ] **Step 1: Write failing tests** — `RangeReviewTests` (seed entries across
  2026-06-01/02/03, one needs_info on the 02nd):
  - `review_entries(db, "2026-06-01", end_date="2026-06-03")` returns all three
    days' entries, span totals, `end_date` in the result, and a `days` list of
    per-day summaries `{date, entry_count, draft_minutes, approved_minutes,
    exported_minutes, needs_info_count}`.
  - **Token compat pin:** for a single day, `review_entries(db, d)["review_token"]
    == review_entries(db, d, end_date=d)["review_token"] ==` the pre-change token
    (assert `end_date=None` produces a snapshot without an `end_date` key — same
    hash as before this change).
  - Range token changes when ANY day in the span changes (edit the 03rd, token
    differs) and `validate_review_token(db, "2026-06-01", old, end_date="2026-06-03")`
    raises the stale message.
  - `end_date < date` raises ValueError; malformed dates raise.
- [ ] **Step 2: Run — FAIL.**
- [ ] **Step 3: Implement**:
  - `list_entries_for_range(conn, date_value, end_date)` — same SELECT as
    `list_entries_for_date` with
    `WHERE substr(start_at, 1, 10) BETWEEN ? AND ?`; `list_entries_for_date`
    becomes a one-line call with `end_date=date_value`.
  - `review_token(date_value, entries, end_date=None)` — add to the snapshot dict
    ONLY when ranged: `if end_date and end_date != date_value:
    snapshot["end_date"] = end_date` (keeps every existing single-day token
    valid).
  - `validate_review_token(db_path, date_value, token, end_date=None)` —
    recompute via `review_entries(db_path, date_value, end_date=end_date)`.
  - `review_entries(..., end_date=None)` — validate span (`end_date >= date`),
    reuse the existing totals loop over the range's entries, and when ranged add
    `"end_date"` and build `days` by grouping on `entry["start_at"][:10]`.
- [ ] **Step 4: Run — PASS** (plus the whole `tests.test_actions` module).
- [ ] **Step 5: Commit** `feat: date-range review with single range token`

### Task 4: range export

**Files:**
- Modify: `timeassist/actions.py` (`export_entries` ~1596: both
  `substr(start_at,1,10) = ?` queries at 1611/1626/1676 become `BETWEEN ? AND ?`)
- Test: `tests/test_actions.py`

- [ ] **Step 1: Write failing tests** — `RangeExportTests`:
  - Approve entries on three days (per-day tokens), export
    `("2026-06-01", end_date="2026-06-03")` → one CSV, rows for all three days in
    `start_at, entry_id` order, Date column varies per row; result carries
    `end_date`, `exported_count`, and `operator_code` when set.
  - needs_info on day 2 and a locked-billable legacy row on day 3 are skipped and
    counted across the span (same semantics as today).
  - Re-export of the same span regenerates the complete file (approved+exported).
  - Empty span raises `no approved or previously exported entries for
    2026-06-01..2026-06-03; nothing to export`.
  - Single-day call with `end_date=None` → filename, rows, and result keys
    identical to a pre-change export (compat pin; no `end_date`/`operator_code`
    keys when unset).
- [ ] **Step 2: Run — FAIL.**
- [ ] **Step 3: Implement** — `export_entries(..., end_date=None)`: normalize
  `end = end_date or date_value`, validate order, swap the three date predicates
  to `BETWEEN ? AND ?` with `(date_value, end)`, include span in the
  nothing-to-export error, read `get_operator_code(conn)` inside the existing
  connection, and extend the result dict with `"end_date": end_date` and
  `"operator_code": code` only when set (drop-nones keeps views clean).
- [ ] **Step 4: Run — PASS.**
- [ ] **Step 5: Commit** `feat: date-range export behind the range review token`

### Task 5: CLI surfaces

**Files:**
- Modify: `timeassist/cli.py` (review parser ~96, export parser ~117, config
  parser ~136, handlers at ~268 review / ~291 export / ~305 config)
- Test: `tests/test_prototype_workflow.py` (CLI flows), `tests/test_cli_help.py`

- [ ] **Step 1: Write failing tests** — `review --date 2026-06-01 --to 2026-06-30`
  returns range details + token; `export --date ... --to ... --review-token <range
  token>` writes the range CSV (and a single-day token for the same start date is
  rejected as stale); `config --operator-code avd` stores AVD and shows in
  `config` readout; `config --clear-operator-code` clears; `--operator-code` with
  another config flag in one call is rejected (matches existing exclusivity).
- [ ] **Step 2: Run — FAIL.**
- [ ] **Step 3: Implement** — add `--to` (dest `end_date`) to review/export
  parsers, pass through to `actions.review_entries`/`validate_review_token`/
  `export_entries`; default output uses `default_export_filename(db_path,
  date_value, end_date)`. Add `--operator-code` / `--clear-operator-code` to the
  config parser and handler (mirror `--user-export-dir` / `--clear-user-export-dir`
  wiring at cli.py:139-140 and ~305-310). HTML review output stays single-day:
  `--to` + `--format html` raises a plain-language ValueError (render is
  day-oriented; range HTML is not in scope).
- [ ] **Step 4: Run — PASS.**
- [ ] **Step 5: Commit** `feat: CLI --to range flags and operator-code config`

### Task 6: MCP surfaces + views

**Files:**
- Modify: `timeassist/mcp_server.py` (review/export/config `TOOLS` schemas
  ~122-145/173-186/199-228; handlers ~408 review / ~428 export / ~436 config
  incl. the one-setting-per-call check at ~443)
- Modify: `timeassist/mcp_views.py` (`_view_review` ~74, `_view_export` ~119)
- Test: `tests/test_mcp_server.py`, `tests/test_mcp_views.py`

- [ ] **Step 1: Write failing tests** —
  - review tool accepts `end_date`; shaped range payload has `date`, `end_date`,
    `days`, `totals`, `skipped_needs_info_count`, `review_token` and **no
    `entries` key** (token budget); single-day shape unchanged.
  - export tool accepts `end_date`; shaped payload gains `end_date`/
    `operator_code` when present, otherwise byte-identical keys to today.
  - config tool accepts `operator_code` and `clear_operator_code`; two config
    args in one call still error; tool-name set in `tests/test_mcp_server.py` is
    UNCHANGED (no new tools — assert explicitly).
- [ ] **Step 2: Run — FAIL.**
- [ ] **Step 3: Implement** — add `end_date` (`"YYYY-MM-DD; with date, reviews/
  exports the whole span with ONE range token"`) to review/export schemas;
  `operator_code` + `clear_operator_code` to config schema and handler (extend
  the exclusivity sum at mcp_server.py:443); update the config tool description
  ("…rounding rule/export copy folder/strict roster policy/operator initials
  code"). In `_view_review`: when `result.get("end_date")`, emit `days` instead
  of `entries`. In `_view_export`: pass through `end_date`/`operator_code` when
  present.
- [ ] **Step 4: Run — PASS** (`tests.test_mcp_server` + `tests.test_mcp_views`).
- [ ] **Step 5: Commit** `feat: MCP range review/export and operator_code config`

### Task 7: SKILL.md contract + gate test

**Files:**
- Modify: `plugin/timeassist/skills/billable-time-assistant/SKILL.md`
- Test: `tests/test_plugin_data_paths.py` (the gate test reading SKILL.md, ~line 57)

- [ ] **Step 1: Extend the gate test** with the new key phrases (range export
  needs a range review token; month-end lookback flow; operator_code is set once
  via config) — FAIL.
- [ ] **Step 2: Update SKILL.md** — export/review sections: "for a month or any
  span ('give me June', 'dates overlapping the old method'), call review with
  date + end_date and pass back its range review_token to export — never loop
  per-day exports"; approval remains per-day; config section gains operator_code
  ("the operator's initials code from the firm's employee list, set once during
  setup; it appears in export filenames"). Keep wording compact — the whole file
  is model-read every session.
- [ ] **Step 3: Run** the gate test — PASS.
- [ ] **Step 4: Commit** `docs: SKILL.md range-export and operator_code contract`

### Task 8: workflow smoke contract check

**Files:**
- Check: `tests/test_workflow_smoke_contract.py`, `.github/workflows/windows-build.yml`

- [ ] **Step 1: Run** `python3 -m unittest tests.test_workflow_smoke_contract -v`.
  All changes are additive result keys on existing tools, so the PowerShell
  payload-key assertions must still pass untouched. If anything fails, update the
  workflow AND the contract test together (the v0.1.19 lesson) — do not silently
  edit `windows-build.yml`.
- [ ] **Step 2: Commit** only if changes were required.

### Task 9: docs

**Files:**
- Modify: `docs/decision-log.md`, `CHANGELOG.md`, `docs/accountant-quick-start.md`,
  `docs/admin-install.md`, `docs/wiki/Architecture.md`

- [ ] **Step 1: decision-log** — two Decision/Why entries: (1) operator_code is
  filename+metadata only; the firm-specified CSV columns are a contract, an
  Employee column waits on the firm; (2) range spans get one range token,
  approval stays per-day so the human gate is never widened.
- [ ] **Step 2: CHANGELOG** — operator-facing: "Ask for a whole date range in one
  file (review + export now take an end date — covers looking back across the
  old and new methods)"; "Set your initials once (`operator_code`) and every
  export file carries them."
- [ ] **Step 3: accountant-quick-start** (non-technical): "You can ask Timmy for
  a whole month's file"; "Tell Timmy your initials once during setup."
  **admin-install**: set `operator_code` at install, next to `strict_roster`.
  **wiki Architecture**: export section gains the range/identity paragraph.
- [ ] **Step 4: Commit** `docs: range export + operator_code documentation`

### Task 10: full verification + release

- [ ] **Step 1:** `python3 -m unittest discover -s tests` — full suite green
  (394 + new).
- [ ] **Step 2:** `python3 scripts/timeassist.py --version` matches plugin.json
  (bump lands with the release branch, not this plan).
- [ ] **Step 3:** SKILL.md and tool descriptions changed → run
  `python3 evals/run.py` before tagging (repo policy; billed to the local
  subscription).
- [ ] **Step 4:** Ship as v0.1.24-prototype via the
  `shipping-a-timeassist-release` skill.

## Out of scope / parked (workbook follow-ups, all firm decisions)

- **Employee column in the CSV** — changes the firm-specified column contract;
  ask the firm (option "column behind a setting" revisitable then).
- **Decimal-hours Duration** — the firm specified HH:MM display, the workbook
  consumes minutes/60 decimals; the conversion can live in the future merge step.
  Ask which they want in the daily CSV before touching `format_hhmm` output.
- **Cross-operator aggregation + the #33 QB Desktop handoff fork** — either time
  gets into QB (IIF route unverified) or TimeAssist + a merge step feeds the
  program/workbook directly; the workbook provides the target schema for the
  second option. Firm's call; blocks any merge-step build.
- **job_type → ACCT vs PR routing** — needs a confirmed vocabulary (at minimum a
  payroll value); currently free text + roster defaults.
- **Firm dimension (Hollon/Mckinley INTERCO)** — possibly two roster
  pseudo-clients, zero schema change; do not build speculatively.
- **Validating operator_code against a firm employee list** — future; the firm's
  own per-tab initials headers drift today, so a distributed canonical code list
  (Employee Matrix export) is the likely shape.
