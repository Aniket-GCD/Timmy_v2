# strict_roster + add_client Implementation Plan

> **Status: SHIPPED in v0.1.23-prototype (PR #43) — never execute this plan.**

**Goal:** A firm-level `strict_roster` setting that disables confirm-as-is
resolution of `needs_info` entries, an `add_client` tool so a new client can be
added to the roster in one call, and sign-off documentation for the rounding
floor — per the locked decisions below.

**Architecture:** Enforcement lives at the single point every resolution path
funnels through — `resolve_capture_with_metadata` in `timeassist/actions.py`
(its `clarification and billable_explicit` escape hatch is confirm-as-is).
Under strict mode a deliberate confirm attempt raises a plain-language
ValueError; plain capture is untouched, so capture-now/clarify-later survives.
`add_client` is a one-row, add-only roster insert reusing the import
validators. Stdlib only.

**Tech Stack:** Python stdlib + SQLite, unittest.

## Decisions locked

Sign-off: Josh, 2026-07-02 — `docs/plans/2026-07-02-issue-39-owner-decisions.md`.

- **Decision 1 = C:** `strict_roster` setting, default off. When on,
  `edit`/`clarify_active` refuse to resolve a `needs_info` entry to a name not
  on the roster (engine raises; assistant relays verbatim). Capture never
  blocks under any mode (invariant). Scope is resolution-time only: entries
  confirmed as-is before strict was enabled stay confirmed — approve does not
  re-scan the roster (noted in the decision log as a known limitation).
- **add_client** ships with it (strict mode is unusable without a one-call way
  to put a new client on the roster). Add-only: an existing `client_key` or a
  colliding name/alias is an error, never an overwrite — updates stay with
  `import_clients`.
- **Decision 2 = A:** rounding floor stays; document it (decision log +
  quick start + CHANGELOG). No code change.
- Item 2 `is_management_shell` flag: deferred, not in this plan.

---

### Task 1: `strict_roster` setting (validation + reader)

**Files:**
- Modify: `timeassist/actions.py` (`set_setting` ~line 197; helper near
  `parse_billable_flag` ~line 637)
- Test: `tests/test_actions.py`

- [x] **Step 1: Write failing tests** — `StrictRosterSettingTests`:
  `set_setting("strict_roster", "on")` stores `"yes"`; `"0"` stores `"no"`;
  `"maybe"` raises ValueError mentioning `yes or no`; fresh DB defaults off
  (`strict_roster_enabled(conn)` is False); enabled after storing yes.
- [x] **Step 2: Run** `python3 -m unittest tests.test_actions.StrictRosterSettingTests -v` — FAIL (AttributeError).
- [x] **Step 3: Implement** — in `set_setting`, after the rounding-rule check:

```python
    if key == "strict_roster":
        value = normalize_strict_roster(value)
```

  and next to `parse_billable_flag`:

```python
def normalize_strict_roster(value: str) -> str:
    token = (value or "").strip().lower()
    if token in _BILLABLE_TRUTHY:
        return "yes"
    if token in _BILLABLE_FALSY:
        return "no"
    raise ValueError(f"strict_roster must be yes or no, got: {value}")


def strict_roster_enabled(conn) -> bool:
    return (get_setting(conn, "strict_roster", "no") or "no").strip().lower() in _BILLABLE_TRUTHY
```

- [x] **Step 4: Run** the same tests — PASS.
- [x] **Step 5: Commit** `feat: strict_roster setting with yes/no validation`

### Task 2: strict enforcement in the resolution funnel

**Files:**
- Modify: `timeassist/actions.py` (`resolve_capture_with_metadata` ~line 586)
- Test: `tests/test_actions.py`

- [x] **Step 1: Write failing tests** — `StrictRosterEnforcementTests`
  (roster: Client A; strict on unless stated):
  - confirm-as-is edit (`edit(id, client=<same unknown>)` on needs_info)
    raises ValueError containing `strict roster`; entry stays `needs_info`.
  - explicit-billable confirm (`edit(id, billable="yes")` on needs_info
    unknown) raises; stays `needs_info`.
  - `clarify_active(client=<unknown>)` on a needs_info timer raises.
  - correcting to a roster name still resolves to draft with roster defaults.
  - capture never blocks: `start`/`add_missing` with unknown client succeed
    and mark `needs_info` while strict is on.
  - strict off: confirm-as-is still resolves (existing behavior pinned).
- [x] **Step 2: Run** — FAIL (no ValueError raised).
- [x] **Step 3: Implement** — in `resolve_capture_with_metadata`, before the
  `needs_info` line:

```python
    if not known_client and clarification and billable_explicit and strict_roster_enabled(conn):
        raise ValueError(
            f"strict roster mode is on: '{raw_client}' is not on the roster; "
            "correct the entry to a roster client, or add the client with add_client first"
        )
```

- [x] **Step 4: Run** tests + full suite — PASS (re-round pin and confirm-as-is
  tests must stay green; they run with strict off).
- [x] **Step 5: Commit** `feat: strict_roster disables confirm-as-is at resolution`

### Task 3: `add_client` action

**Files:**
- Modify: `timeassist/actions.py` (new function after `import_clients`)
- Test: `tests/test_actions.py`

- [x] **Step 1: Write failing tests** — `AddClientTests`: adds one client with
  defaults (billable yes, empty job type, slugified key) and count; persists
  aliases/default_billable/default_job_type/client_key when given; duplicate
  `client_key` raises (mentions `import_clients`); name/alias colliding with
  an existing label raises; end-to-end: strict on → needs_info entry →
  `add_client` → `edit(client=name)` resolves to draft with roster defaults.
- [x] **Step 2: Run** — FAIL.
- [x] **Step 3: Implement**:

```python
def add_client(db_path: str | Path, display_name: str, aliases: str = "",
               default_billable: str | None = None, default_job_type: str = "",
               client_key: str | None = None, at: str | None = None) -> dict[str, Any]:
    """Add ONE new client to the roster. Add-only by design: an existing key or
    colliding label is an error, never an overwrite — updates go through
    import_clients, which owns replace/merge semantics."""
    ensure_initialized(db_path)
    changed_at = iso(parse_at(at)) if at else now_iso()
    display = (display_name or "").strip()
    if not display:
        raise ValueError("display_name is required")
    key = (client_key or "").strip() or slugify_client_key(display)
    aliases_value = (aliases or "").strip()
    with connect(db_path) as conn:
        existing = conn.execute("SELECT client_key, display_name, aliases FROM clients ORDER BY client_key").fetchall()
        for row in existing:
            if row["client_key"] == key:
                raise ValueError(
                    f"client_key '{key}' already exists for '{row['display_name']}'; "
                    "add_client only adds new clients — use import_clients to update the roster"
                )
        final_rows = [(row["client_key"], row["display_name"], row["aliases"] or "") for row in existing]
        final_rows.append((key, display, aliases_value))
        validate_client_label_uniqueness(final_rows)
        conn.execute(
            "INSERT INTO clients(client_key, display_name, aliases, default_billable, default_job_type, billable_locked, updated_at) VALUES (?, ?, ?, ?, ?, 0, ?)",
            (key, display, aliases_value, parse_billable_flag(default_billable), (default_job_type or "").strip(), changed_at),
        )
        client = row_to_dict(conn.execute("SELECT * FROM clients WHERE client_key = ?", (key,)).fetchone())
        count = conn.execute("SELECT COUNT(*) AS c FROM clients").fetchone()["c"]
        log_event(conn, "add_client", f"added client {display}", "clients", None, after={"client_key": key}, at=changed_at)
        conn.commit()
    return {"client": client, "client_count": count}
```

- [x] **Step 4: Run** — PASS.
- [x] **Step 5: Commit** `feat: add_client — one-call add-only roster insert`

### Task 4: MCP surface (tool, config key, dispatch, view)

**Files:**
- Modify: `timeassist/mcp_server.py` (TOOLS after `import_clients` ~line 248;
  `config` schema ~line 200 + dispatch ~line 416)
- Modify: `timeassist/mcp_views.py` (`_view_add_client` + `_VIEWS`)
- Test: `tests/test_mcp_server.py` (tool-name set ~line 65 + round trips),
  `tests/test_mcp_views.py`

- [x] **Step 1: Write failing tests** — tool-name set gains `add_client`;
  `add_client` round trip returns slim client + count; missing-name/duplicate
  errors surface as isError; `config {strict_roster: "yes", confirm: true}`
  sets it and it shows in the settings readout; strict confirm-as-is via the
  `edit` tool returns isError with the strict message; add_client view drops
  empty aliases/job type but keeps `default_billable`.
- [x] **Step 2: Run** — FAIL.
- [x] **Step 3: Implement** — TOOLS entry:

```python
    {
        "name": "add_client",
        "description": "Add ONE new client to the roster. Fails if the client already exists (use import_clients to update). Ask the operator before adding; never add on your own initiative.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "display_name": {"type": "string"},
                "aliases": {"type": "string", "description": "Optional ';'-separated alternate names."},
                "default_billable": {"type": "string", "enum": ["yes", "no"], "description": "Defaults to yes."},
                "default_job_type": {"type": "string", "description": "Auto-fills Job Type on new entries for this client."},
                "client_key": {"type": "string", "description": "Optional stable key; derived from display_name when omitted."},
                "at": {"type": "string", "description": "Optional ISO timestamp."},
            },
            "required": ["display_name"],
        },
    },
```

  `config` schema gains:

```python
                "strict_roster": {
                    "type": "string",
                    "enum": ["yes", "no"],
                    "description": "Firm policy: when yes, needs_info entries can only resolve to roster names (confirm-as-is is off). Default no.",
                },
```

  dispatch — `strict_roster` joins the one-at-a-time guard and:

```python
        if strict_roster:
            _require_confirm(arguments, "changing TimeAssist settings")
            return actions.set_setting(db_path, "strict_roster", strict_roster)
```

```python
    if name == "add_client":
        return actions.add_client(db_path, arguments["display_name"], arguments.get("aliases", ""), arguments.get("default_billable"), arguments.get("default_job_type", ""), arguments.get("client_key"), arguments.get("at"))
```

  view (keys mirror `_view_list_clients`, plus job type):

```python
def _view_add_client(result: dict[str, Any]) -> dict[str, Any]:
    client = result.get("client", {})
    slim = {key: client.get(key) for key in ("client_key", "display_name", "default_billable")}
    if client.get("aliases"):
        slim["aliases"] = client["aliases"]
    if client.get("default_job_type"):
        slim["default_job_type"] = client["default_job_type"]
    return {"client": slim, "client_count": result["client_count"]}
```

- [x] **Step 4: Run** — PASS.
- [x] **Step 5: Commit** `feat: add_client MCP tool + strict_roster config key`

### Task 5: CLI parity

**Files:**
- Modify: `timeassist/cli.py` (`config` parser ~line 136 + handler ~line 296;
  new `add-client` parser after `import-clients` ~line 156 + handler ~line 331)
- Test: `tests/test_cli_help.py` (help contract)

- [x] **Step 1: Extend the help-contract test** for `add-client` and
  `config --strict-roster`; run — FAIL.
- [x] **Step 2: Implement** — parser:

```python
    add_client = sub.add_parser("add-client", help="add one new client to the roster")
    add_client.add_argument("--name", required=True, help="client display name")
    add_client.add_argument("--aliases", default="", help="optional ';'-separated alternate names")
    add_client.add_argument("--default-billable", choices=["yes", "no"], help="default billable flag (yes when omitted)")
    add_client.add_argument("--default-job-type", default="", help="job type auto-filled on new entries")
    add_client.add_argument("--client-key", help="optional stable key; derived from the name when omitted")
    add_client.add_argument("--at", help="ISO timestamp for deterministic demos/tests")
    add_client.add_argument("--dry-run", action="store_true")
```

  `config` gains `--strict-roster` (choices yes/no) wired like
  `--rounding-rule` (same confirm + one-at-a-time guard). Handler:

```python
    if command == "add-client":
        details = actions.add_client(db_path, args.name, args.aliases, args.default_billable, args.default_job_type, args.client_key, args.at)
        return CommandResult(True, command, "client-added", f"Added client {details['client']['display_name']}.", details)
```

- [x] **Step 3: Run** — PASS. **Step 4: Commit** `feat: CLI add-client + config --strict-roster`

### Task 6: SKILL.md contract + gate phrases

**Files:**
- Modify: `plugin/timeassist/skills/billable-time-assistant/SKILL.md`
  (tools table ~line 37; Client roster section ~line 96)
- Modify: `tests/test_plugin_data_paths.py` (required phrases ~line 59)

- [x] **Step 1: Add gate phrases** `add_client` and `strict_roster`; run gate
  test — FAIL.
- [x] **Step 2: Update SKILL.md** — table row after Import:
  `| Add one new roster client | `add_client` | `display_name` |`
  Roster section, after the confirm-as-is/clarify sentence:
  "When `config` shows `strict_roster` `yes`, confirm-as-is is off: the engine
  refuses to resolve a name not on the roster — relay its message, then offer
  to correct the entry or, with operator confirmation, `add_client`."
  And extend the never-on-your-own-initiative sentence to cover `add_client`.
- [x] **Step 3: Run** gate test + full suite — PASS.
  **Step 4: Commit** `feat: SKILL.md contract for strict_roster + add_client`

### Task 7: sign-off documentation (Decision 2 = A + this feature)

**Files:**
- Modify: `docs/decision-log.md` (two entries), `CHANGELOG.md`
  (`## v0.1.23-prototype — unreleased`), `docs/accountant-quick-start.md`
  (floor line in First-day setup step 5), `docs/admin-install.md`
  (strict_roster + add-client note in first-run setup)

- [x] **Step 1: Decision log** — rounding-floor entry (adapted from the
  owner-decisions pre-draft, signed off 2026-07-02) and a strict_roster entry
  (Decision/Why, scope: resolution-time only; pre-strict confirmations stand;
  capture never blocks).
- [x] **Step 2: CHANGELOG** unreleased section: strict_roster, add_client,
  rounding-floor documentation note.
- [x] **Step 3: Quick start + admin install** lines; run full suite — PASS.
  **Step 4: Commit** `docs: rounding-floor sign-off + strict_roster operator docs`

### Task 8: ship

- [x] Full suite green; `git push` + PR referencing issue #39 items 1/4 and
  this plan; note in the PR that SKILL.md changed → run `python3 evals/run.py`
  before the next release (billed to the local subscription).
