# Decision Log

## 2026-05-28 — Start with a private local-kit repo

**Decision:** Create a private repo for the local Claude Code workstation kit rather than starting with a central hosted bot.

**Why:** The real work context lives on the user's machine. A local kit keeps sensitive data local and gives the workflow a deterministic, inspectable core.

## 2026-05-28 — Human-reviewed time capture, not surveillance

**Decision:** V1 must not include keystroke logging, screen recording, silent inbox monitoring, automatic billing decisions, or direct QuickBooks writeback.

**Why:** The stakeholder value is better capture and review, not employee monitoring.

## 2026-05-28 — Build the action contract before integrations

**Decision:** Define and test local actions first: `init`, `start`, `switch`, `end`, `review`, `approve`, `export`, and `sanitize-packet`.

**Why:** n8n, Teams, and future agent wrappers should reuse the same core workflow instead of creating separate logic paths.

## 2026-06-09 — Shape MCP results at the boundary, not in the engine

**Decision:** Trim model-facing tool results in `timeassist/mcp_views.py` (compact JSON, slim entries, no echoed entry lists) while `actions.py` and the CLI keep full-fidelity dicts.

**Why:** Every byte of an MCP result costs Cowork tokens, but the engine and CLI need complete rows for audit and debugging. One boundary layer keeps both honest.

## 2026-06-09 — Mistaken captures are soft-deleted, never removed

**Decision:** `discard_entry` sets `review_status='discarded'` (hidden from review/approval/export, audit-logged); rows are never hard-deleted, and the review_token gate is unchanged — mutations do not return fresh tokens, so the operator must see a refreshed review before approval/export.

**Why:** "Time entries are kept forever" is a billing-audit invariant, and auto-refreshed tokens would let the assistant approve state the operator never saw.

## 2026-06-10 — Pilot feedback flows through GitHub Issues

**Decision:** Each piece of pilot feedback becomes one GitHub Issue labeled `pilot-feedback`, containing the verbatim transcript, an evaluation (what happened, root cause, ranked fixes), and a disposition linking the fixing PR/release. Implementation plans in `docs/plans/` get a `Status: SHIPPED in vX.Y.Z (PR #N)` header once released. (Template: issue #31.)

**Why:** Chat-pasted transcripts are lossy and unsearchable, and the v0.1.20 fix showed diagnosis depends on verbatim detail (which tools the model tried, in what order). Issues link feedback → plan → PR → release so future sessions can reconstruct intent without conversation history, and status headers stop stale plans from being mistaken for current intent.

## 2026-07-01 — Management-shell protection is inherent in matching, not a separate tiebreak

**Decision:** Near-identical "management" shell companies are protected from accidental billing by the deterministic matching passes themselves, not by a dedicated tiebreak pass. The plan's explicit exactly-two/exactly-one-management tiebreak was implemented, then proven unreachable and removed: any non-management input that would strip-match the management/non-management pair already uniquely fold-matches the non-management row in an earlier pass, so control never reaches the tiebreak. A management name is therefore only billed when the operator types it exactly. Do not reintroduce the explicit pass.

**Why:** Dead code that looks load-bearing invites future edits that "fix" it and reintroduce the very ambiguity it pretended to guard. The protection is stronger stated as an emergent property of the passes (pinned by tests) than as an unreachable branch. The unreachability argument is word-multiset preservation: name_fold only lowercases and reorders words, so two names that fold equal contain the word 'management' together or not at all — the exactly-one-management tiebreak condition is impossible.

## 2026-07-01 — Notes nudge informs, never blocks approval

**Decision:** A missing-notes nudge surfaces once when the timer stops and once at review (`notes_missing` flag, `missing_notes_count`), but approval and export are never blocked on notes.

**Why:** The pilot email asked for a reminder, not a gate. Blocking approval on notes would break the capture-now/clarify-later invariant and frustrate operators who legitimately have nothing to add.

## 2026-07-01 — "Timmy" is branding only

**Decision:** The user-facing product name becomes Timmy; every internal identifier — package, CLI, exe, repo, MCP server, tool names, plugin/marketplace `name` keys — stays `timeassist`.

**Why:** The PyInstaller/Windows build and the plugin/marketplace wiring are name-sensitive; renaming identifiers risks the build with zero user benefit. A display-name change carries no CI/build risk.

## 2026-07-01 — Job Type is a free string, forced only for locked admin clients

**Decision:** `job_type` is a free-text field per entry; the engine forces `'Administrative'` only for the locked built-in admin clients. No fixed job-type vocabulary is enforced.

**Why:** The firm has not confirmed a job-type vocabulary yet, so hard-coding one now would guess wrong and require a migration later. Free text captures reality today; only the admin clients have a billing-critical value worth enforcing.

## 2026-07-01 — Built-in admin clients seed with ON CONFLICT DO NOTHING

**Decision:** The four admin clients (Admin, Early Out, Holiday, Staff Meeting) are seeded with `ON CONFLICT DO NOTHING`, so operator roster edits to a same-named row win. A replace-mode roster import drops them; they are re-seeded on the next engine action.

**Why:** Operators must stay the authority over their roster, so seeding must never clobber their edits. The transient gap after a replace-import is acceptable because the very next action re-seeds the built-ins, and the engine still enforces non-billable Administrative behaviour whenever they exist.

## 2026-07-02 — Unknown-client needs_info applies to every capture path

**Decision:** `start` and `add_missing` route unknown roster labels through `resolve_capture_with_metadata` and mark them `needs_info`, exactly like `switch` — closing the #34 approve/export roster gate. Capture still never blocks, and confirm-as-is stays one operator `edit` (or `clarify_active` on the open timer) that addresses `client`.

**Why:** The pilot email requires every entry's client to match the master list at approve/export time. That gate is only real if every capture path marks placeholders; a gate that `start`/`add_missing` slipped through was no gate at all. Marking (not blocking) preserves capture-now/clarify-later, and confirm-as-is stays a single edit.

## 2026-07-02 — Billable lock is enforced at approve/approve_all/export as a legacy-data safety net

**Decision:** Beyond capture/edit, the billable lock is re-checked when finalizing: `approve` refuses a billable entry whose client row is `billable_locked`; `approve_all`/`export` skip such entries and report `skipped_locked_count`/`skipped_locked_minutes` (surfaced in MCP views only when > 0). The engine never silently rewrites stored `billable`.

**Why:** Rows recorded before this version (v0.1.19) can carry `billable=1` on a now-locked administrative client. Surfacing them — refuse, or skip and count — beats silently flipping stored billing data, which a billing audit trail must never do. The operator clears each with one `edit` setting billable no.

## 2026-07-02 — Admin seeding defers to operator labels; operator import takes ownership of a seeded key

**Decision:** `initialize()` skips seeding an admin client whose display name (case-insensitive) already matches an operator row's display name OR alias under a different `client_key`, and an operator roster import that upserts a seeded key resets `billable_locked = 0`, so merge takes ownership exactly as replace does. Supersedes the narrower 2026-07-01 "ON CONFLICT DO NOTHING" framing: that alone let a re-seed's exact display name shadow an operator alias, and left merge- and replace-import disagreeing over a seeded key.

**Why:** Seeding must never create a label collision the roster import itself rejects, and the operator is the authority over their roster — merge and replace must agree that an operator's own row for a seeded name wins, lock included.

## 2026-07-02 — Rounding floor: positive work never rounds to zero

**Decision:** `round_minutes` bills at least one full increment for any positive entry: under `nearest_<N>_minutes`, an entry that would round down to 0 becomes N instead (7 raw minutes under nearest-15 → 15). Signed off as billing policy by Josh on 2026-07-02 (issue #39 item 4, Decision 2 = A in `docs/plans/2026-07-02-issue-39-owner-decisions.md`).

**Why:** Work done must never silently vanish from the export. The floor is the rounding-time mirror of the >=1 raw-minute rule in `minutes_between`, and matches minimum-billing-increment practice. Operators who don't want a floor keep raw time (`exact`).

## 2026-07-02 — strict_roster is a firm-level toggle that closes confirm-as-is; add_client makes it workable

**Decision:** A `strict_roster` setting (default off, canonical yes/no, unrecognized values rejected). When on, the confirm-as-is escape hatch in `resolve_capture_with_metadata` raises instead of resolving: a `needs_info` entry can only return to draft under a roster name. Capture still never blocks under any mode. `add_client` ships alongside — a one-call, add-only roster insert (existing key or colliding label is an error; updates stay with `import_clients`). Scope is resolution-time only: entries confirmed as-is before strict was enabled stay confirmed — approve does not re-scan the roster (known limitation; harden later only if the firm asks). Chosen as Decision 1 = C over removing confirm-as-is outright (issue #39 item 1), preserving the 2026-07-02 marking-not-blocking design for pilots that need leniency.

**Why:** The change request read "needs to match what is on the master list" as absolute; the counter-case is one-off clients not yet in QuickBooks. A firm-level toggle gives this firm the absolute guarantee without reversing capture-now/clarify-later for everyone — and without an add-one-client path, strict mode would strand the person who logged the time (the only roster fix was a merge-mode CSV re-import).

## 2026-07-08 — Date-range review/export shares one range token; approval stays per-day

**Decision:** `review` and `export` take an optional `end_date`. A ranged `review` returns per-day `days` summaries (not entry lists — the model token budget) plus one `review_token` scoped to the whole span; `export` accepts the same `date`+`end_date` and that token and writes one CSV. `approve`/`approve_all` never take `end_date` — approval stays strictly per-day, so a range export only ever writes entries already approved through per-day review. An `end_date` equal to (or absent against) `date` collapses to a byte-identical single-day call, so every previously issued single-day token stays valid. Ranged HTML review is refused — render one day at a time.

**Why:** The pilot firm asked to "look back in time and even grab dates that may overlap the old and the new methods" (issue #34); a one-day-at-a-time export cannot serve that without 20+ round-trips. Widening review/export while leaving the approval gate per-day gives the lookback without weakening the operator's authority over what gets billed. Sharing the span normalization (`_normalize_date_span`) and returning summaries instead of entries keeps the range path honest about the token budget.

## 2026-07-08 — operator_code identifies the operator in export filenames only, not the CSV columns

**Decision:** A `config` setting `operator_code` (2–4 letters, stored uppercased) names which operator an install belongs to, using the firm's employee-initials codes. When set, the default export filename becomes `quickbooks-time-<CODE>-<date>.csv` (or `...-<from>_to_<to>.csv` for a range) and the code is echoed in the export result; the CSV columns the firm specified — Date, Client, Job Type, Notes, Duration, Billable — are unchanged. An Employee column is parked as a firm question.

**Why:** The firm's billing workbook is a client-rows × employee-initials-columns matrix, so per-operator exports must carry an identity — but the firm gave those six columns verbatim as the contract. Encoding identity in the filename and result metadata keeps 41 operators' daily files distinct in a shared folder without changing a column contract we don't yet have sign-off to change. The roster stays rate/retainer-free for the same reason: those live in the workbook's formulas, not the tracker (billing-sheet gap analysis, issue #34).
