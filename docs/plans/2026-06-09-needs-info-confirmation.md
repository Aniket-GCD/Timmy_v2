# Needs-Info Confirmation UX Implementation Plan (start of 0.1.20)

> **Status: SHIPPED** in v0.1.20-prototype (PR #29, merged 2026-06-09). Kept for reference — do not execute.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Make "the operator confirms an unknown client is correct as-is" a one-step path, and make the needs_info rejection error teach that path — fixing the Haiku pilot transcript where the assistant needed four attempts (including an unauthorized roster-import attempt) to resolve confirmed entries.

**Architecture:** No new tool. `edit` (and `clarify_active`) become the confirmation path: an operator-driven edit that addresses the `client` field counts as explicit confirmation and resolves needs_info, keeping the entry's current billable instead of demanding it be retyped. Capture notes stay stored as the stable token `client_not_in_roster`; they are humanized only at presentation (error messages + MCP views) via one helper. SKILL.md documents the recipe and bans self-initiated roster imports.

**Decisions locked:**
- An edit/clarify that does NOT address `client` (e.g. task-only edit) still leaves needs_info — the client question stays open; resolution must be deliberate.
- Correcting to a *different* unknown client also resolves (human-named labels are authoritative; capture-now philosophy).
- Humanize at the boundary, never in storage (`capture_note` DB token unchanged; event log unchanged).
- Version bumps to 0.1.20 in this branch; NO release tag (more 0.1.20 work may follow; ship via the shipping-a-timeassist-release skill when Josh says go).

**Baseline:** branch from main (4cf7c9f); 218 tests green. Worker rules: stdlib only; full suite before every commit; commits end with `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`.

---

### Task 1: Confirm-as-is resolution in `edit_entry` and `clarify_active_session`

**Files:** Modify `timeassist/actions.py`; Test `tests/test_actions.py`, `tests/test_mcp_server.py`.

- [ ] **Step 1: Failing tests.** In `tests/test_actions.py`, new class (reuse neighbours' temp-db style; produce a needs_info entry via start → switch to unknown client → end, as existing tests do):

```python
class NeedsInfoConfirmationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = str(Path(self.tmp.name) / "t.sqlite")
        actions.init_state(self.db, "2026-05-28T08:00:00")
        actions.start_session(self.db, "Client A", "cleanup", at="2026-05-28T09:00:00")
        switched = actions.switch_session(self.db, "acme", "test2", at="2026-05-28T09:10:00")
        self.entry = actions.end_session(self.db, at="2026-05-28T09:20:00")
        self.assertEqual(self.entry["capture_status"], "needs_info")

    def test_edit_reasserting_same_client_confirms_entry(self) -> None:
        resolved = actions.edit_entry(self.db, self.entry["entry_id"], client="acme")
        self.assertEqual(resolved["review_status"], "draft")
        self.assertEqual(resolved["capture_status"], "resolved")
        self.assertIsNone(resolved["capture_note"])
        self.assertEqual(resolved["billable"], self.entry["billable"])  # kept, not re-asked
        self.assertIsNotNone(resolved["clarified_at"])

    def test_edit_correcting_to_other_unknown_client_also_confirms(self) -> None:
        resolved = actions.edit_entry(self.db, self.entry["entry_id"], client="bobco")
        self.assertEqual(resolved["capture_status"], "resolved")
        self.assertEqual(resolved["client_name"], "bobco")

    def test_edit_without_client_keeps_needs_info_open(self) -> None:
        edited = actions.edit_entry(self.db, self.entry["entry_id"], task="better notes")
        self.assertEqual(edited["review_status"], "needs_info")
        self.assertEqual(edited["capture_status"], "needs_info")

    def test_explicit_billable_still_resolves_as_before(self) -> None:
        resolved = actions.edit_entry(self.db, self.entry["entry_id"], client="acme", billable="no")
        self.assertEqual(resolved["capture_status"], "resolved")
        self.assertEqual(resolved["billable"], 0)

    def test_clarify_active_with_client_alone_resolves(self) -> None:
        actions.start_session(self.db, "bob", "taxes", at="2026-05-28T10:00:00")
        session = actions.clarify_active_session(self.db, client="bob", at="2026-05-28T10:05:00")
        self.assertEqual(session["capture_status"], "resolved")
```

Note: `start_session` resolves captures without metadata, so the clarify test's start may NOT mark needs_info — verify how existing tests create a needs_info ACTIVE session (switch to unknown client without ending) and use that instead if so.

In `tests/test_mcp_server.py`, add the transcript regression (slim keys: `status`, `needs_info`):

```python
    def test_operator_confirms_unknown_client_in_one_edit(self) -> None:
        self.payload("init_state", {"at": "2026-05-28T08:55:00"})
        self.payload("start", {"client": "Client A", "task": "test1", "at": "2026-05-28T09:00:00"})
        self.payload("switch", {"client": "acme", "task": "test2", "at": "2026-05-28T09:10:00"})
        entry = self.payload("end", {"at": "2026-05-28T09:20:00"})
        review = self.payload("review", {"date": "2026-05-28"})
        rejected = self.call("approve", {"entry_id": entry["entry_id"], "review_token": review["review_token"]})
        self.assertTrue(rejected.get("isError"))
        confirmed = self.payload("edit", {"entry_id": entry["entry_id"], "client": "acme"})
        self.assertEqual(confirmed["status"], "draft")
        self.assertNotIn("needs_info", confirmed)
        review = self.payload("review", {"date": "2026-05-28"})
        approved = self.payload("approve", {"entry_id": entry["entry_id"], "review_token": review["review_token"]})
        self.assertEqual(approved["status"], "approved")
```

- [ ] **Step 2: Run; confirm the new tests FAIL** (entries stay needs_info on client-only edits).

- [ ] **Step 3: Implement.** In `edit_entry` (actions.py, the `if client is not None or was_needs_info:` branch), pass the entry's current billable as explicit confirmation when the operator addressed the client:

```python
        if client is not None or was_needs_info:
            confirm_billable = billable
            if confirm_billable is None and was_needs_info and client is not None:
                # An operator-driven edit that re-asserts or corrects the client
                # is the confirmation itself; keep the entry's current billable
                # rather than demanding it be retyped (Haiku pilot transcript,
                # 2026-06-09: four attempts to resolve a confirmed entry).
                confirm_billable = bool(before["billable"])
            capture = resolve_capture_with_metadata(
                conn,
                client if client is not None else before["client_name"],
                new_task,
                confirm_billable,
                clarification=was_needs_info,
            )
```
(The existing `if billable is None and client is None: capture["billable"] = before["billable"]` line stays.)

In `clarify_active_session`, mirror it: before the `resolve_capture_with_metadata` call, compute `confirm_billable = billable` and if `confirm_billable is None and client is not None and (active.get("capture_status") == "needs_info")`, set `confirm_billable = bool(active["billable"])`; pass `confirm_billable` instead of `billable`. Keep the existing post-call `if billable is None and client is None:` fallback.

- [ ] **Step 4: Full suite green; commit** `feat: client edit confirms needs_info entries without retyping billable`.

---

### Task 2: Humanized capture notes + teaching rejection error

**Files:** Modify `timeassist/actions.py`, `timeassist/mcp_views.py`; Test `tests/test_actions.py`, `tests/test_mcp_views.py`, `tests/test_mcp_server.py`.

- [ ] **Step 1: Failing tests.**

`tests/test_actions.py` (in NeedsInfoConfirmationTests):

```python
    def test_approval_rejection_teaches_the_recipe(self) -> None:
        with self.assertRaisesRegex(ValueError, r"client 'acme' is not in the roster.*edit"):
            actions.set_approval(self.db, self.entry["entry_id"], True)
```

`tests/test_mcp_views.py`: update the three `needs_info` assertions from the raw token to the humanized text — `slim_entry`/`slim_session` should now yield `"client 'Client B' is not in the roster"` for FULL_SESSION (client_name "Client B") and `"client 'Client A' is not in the roster"` for the entry fixture (client_name "Client A"). Update `tests/test_mcp_server.py` assertions on `needs_info == "client_not_in_roster"` (lines ~79, ~129) to the humanized equivalents for their client names.

- [ ] **Step 2: Implement.** In `actions.py`, next to `needs_review_reason`:

```python
def capture_note_text(note: str | None, client_name: str | None = None) -> str | None:
    """Human wording for stored capture-note tokens (storage keeps the token)."""
    if note == "client_not_in_roster":
        return f"client '{client_name}' is not in the roster" if client_name else "client is not in the roster"
    return note
```

In `set_approval`, replace the needs_info raise with:

```python
        if before["review_status"] == "needs_info" or before.get("capture_status") == "needs_info":
            reason = capture_note_text(before.get("capture_note"), before.get("client_name")) or "missing client/task details"
            raise ValueError(
                f"entry {entry_id} needs clarification before approval ({reason}); "
                "confirm or correct it with edit — pass entry_id and client — to return it to draft"
            )
```

In `mcp_views.py`, import `capture_note_text` from `.actions` (actions does not import mcp_views; no cycle) and use it for both `needs_info` fields:

```python
from .actions import capture_note_text
...
    if entry.get("capture_status") == "needs_info":
        slim["needs_info"] = (
            capture_note_text(entry.get("capture_note"), entry.get("client_name"))
            or entry.get("needs_review_reason")
            or "needs_info"
        )
```
(and the analogous change in `slim_session` using `session.get("client_name")`).

- [ ] **Step 3: Full suite green (the DB token and event log must be unchanged — grep that no storage writes changed); commit** `feat: humanize capture notes at the boundary; rejection error teaches the edit recipe`.

---

### Task 3: SKILL.md recipe + guardrails, version 0.1.20, CHANGELOG

**Files:** Modify `plugin/timeassist/skills/billable-time-assistant/SKILL.md`, `timeassist/__init__.py`, `plugin/timeassist/.claude-plugin/plugin.json`, `CHANGELOG.md`. Gate: `test_plugin_skill_documents_server_side_gates` phrases must survive.

- [ ] **Step 1: SKILL.md.** In the **Client roster** section, replace the final sentence ("Unknown clients are soft: ... before approval/export.") with:

```markdown
Unknown clients are soft: recorded as typed, marked `needs_info`, never blocked.
If the operator confirms the name is correct as-is (or corrects it), resolve
with one `edit` passing `entry_id` and `client` — billable is kept, the entry
returns to draft. `clarify_active` does the same but only while the timer is
still open; closed entries always use `edit`. Never import or change the
roster on your own initiative — offer `import_clients` to the operator as a
one-time option instead.
```

In **Workflow** step 5, after "approved entries must be unapproved first).", insert: "A rejected approval for `needs_info` is resolved the same way: one `edit` with `entry_id` and `client`."

- [ ] **Step 2: Versions + CHANGELOG.** Bump both version files to `0.1.20`. CHANGELOG: read house style (## vX.Y.Z-prototype — date with Added/Changed); since this is unreleased, use the same heading style with today's date and a note it is pending release, or an "Unreleased" heading if precedent exists — match whatever the file's convention supports, content:

```markdown
- Confirming an unknown client now takes one step: `edit` with the client name
  resolves a needs_info entry without retyping billable (same for
  `clarify_active` on the open timer).
- needs_info reasons are now plain language ("client 'acme' is not in the
  roster") in tool results and approval-rejection errors, and the rejection
  error explains the exact resolution recipe.
- Plugin skill: documents the confirm-as-is recipe and forbids self-initiated
  roster imports.
```

- [ ] **Step 3: Verify** full suite + gate test + `python3 scripts/timeassist.py --version` → 0.1.20. **Commit** `chore: bump TimeAssist pilot version to 0.1.20` (skill changes may be a separate `docs:` commit first). Do NOT tag — release happens later via shipping-a-timeassist-release.
