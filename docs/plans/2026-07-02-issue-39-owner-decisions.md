# Requirements-owner decisions for issue #39 (items 1 and 4, optional 2)

Status: DECIDED 2026-07-02 — Josh signed off on the recommended option for
each: **Decision 1 = C** (firm-level `strict_roster` toggle, default off, plus
an add-one-client path), **Decision 2 = A** (keep the rounding floor and
document it), **item 2 flag = deferred** (no urgency, revisit on demand).
Implementation: `docs/plans/2026-07-02-strict-roster-add-client.md`,
SHIPPED in v0.1.23-prototype (PR #43).
This document is the decision record; do not implement from it directly.

Source: issue #39 (pilot functional-test change request, 2026-07-02).
Items 3 and 5 are closed (regression pin merged in #40; docs shipped in #41).
Item 6 stays parked with the same "down the line" item on #34.

---

## Decision 1 (issue #39 item 1) — Should "confirm as-is" survive the approve gate?

**Today (v0.1.22):** Capture never blocks. An off-roster client name is
recorded as typed and marked `needs_info` on every capture path; `needs_info`
entries cannot be approved or exported. The operator resolves with one `edit`
that addresses `client` — either correcting to a roster name **or confirming
the typed name as-is**, which returns the entry to draft and makes it
approvable under a name that is not on the master list.

**The change request:** Remove the confirm-as-is override. At approve, every
entry must resolve to a roster name; the fix paths are "correct to an existing
roster client" or "add the client to the master list first, then approve."
Rationale: the requirement says the name "needs to match what is on the master
list", and the override quietly defeats the list.

**Why this is escalated instead of implemented:** the current behavior is a
locked design decision (decision log, 2026-07-02: "Marking (not blocking)
preserves capture-now/clarify-later, and confirm-as-is stays a single edit").
Reversing it flips the engine, the SKILL.md assistant contract, the pinned
tests, and the `needs_info_confirmed_as_is` model eval together.

**A cost acceptance would surface:** there is currently no way to add a single
client to the roster from a conversation — the only path is a merge-mode CSV
re-import. A strict rule almost certainly needs a dedicated add-one-client
tool, or the person who logged the time cannot fix it in-chat and the burden
lands on whoever manages the roster CSV.

**Options:**

- **A — Keep confirm-as-is (status quo).** The master list stays advisory at
  the edge: unknown names still require an explicit operator confirmation, but
  a deliberate confirmation is final. No work.
- **B — Enforce strictly, always.** Confirm-as-is is removed for everyone.
  Requires: engine change, add-one-client path, SKILL.md, tests, eval flip,
  operator docs. One-off/not-yet-in-QuickBooks clients cannot be billed until
  the roster is updated.
- **C — Firm-level setting (recommended).** A config flag (e.g.
  `strict_roster`, default off = today's behavior) that, when on, makes
  `edit`/`clarify_active` refuse to resolve `needs_info` to a non-roster name.
  Your firm turns it on and gets exactly the requested guarantee; the
  capture-now/clarify-later default survives for pilots that need leniency.
  Still requires the add-one-client path to be usable in practice.

**Needed from the requirements owner:** pick A, B, or C. If B or C, also
confirm the expected resolution flow for a genuinely new client (who adds it
to the master list, and is a chat-side "add client" tool acceptable, or must
the roster only ever change via CSV import?).

---

## Decision 2 (issue #39 item 4) — Minimum-increment rounding floor

**Today:** rounding never turns positive work into zero. Under any rounding
rule, an entry that would round down to 0 bills one full increment instead
(a 7-minute call under nearest-15 becomes 15 minutes, not 0). This is
intentional (code comment: "work done must never silently vanish from the
export"), pinned by test — but it has never been signed off as billing policy
or documented anywhere an operator can see.

**The consequence to sign off:** with rounding enabled, a 2-minute call is
billed at the full increment (e.g. 15 minutes under nearest-15). This matches
common minimum-billing-increment practice, but it is a billing-policy choice,
not an engineering one.

**Options:**

- **A — Keep the floor and document it (recommended).** No behavior change.
  Add a decision-log entry (pre-drafted below) plus one operator-facing line
  in the accountant quick start and CHANGELOG.
- **B — True nearest rounding.** Small entries can round to 0 and drop out of
  the export — the work silently vanishes unless the operator keeps raw time.
  Contradicts the existing "never vanish" invariant.
- **C — Make the floor configurable.** Engineering cost for a policy question
  the firm should answer once.

**Needed from the requirements owner:** pick A, B, or C (A expected).

**Pre-drafted decision-log entry for A** (to be added verbatim on sign-off):

> ## YYYY-MM-DD — Rounding floor: positive work never rounds to zero
>
> **Decision:** `round_minutes` bills at least one full increment for any
> positive entry: under `nearest_<N>_minutes`, an entry that would round down
> to 0 becomes N instead (7 raw minutes under nearest-15 → 15). Signed off as
> billing policy by the requirements owner on YYYY-MM-DD (issue #39 item 4).
>
> **Why:** Work done must never silently vanish from the export. The floor is
> the rounding-time mirror of the >=1 raw-minute rule in `minutes_between`,
> and matches minimum-billing-increment practice. Operators who don't want a
> floor keep raw time (`exact`).

---

## Optional (issue #39 item 2) — `is_management_shell` as metadata only

The requested engine auto-resolve was pushed back on with evidence (the engine
already never guesses: any ambiguous match → `needs_info`; pinned by
`ManagementTiebreakTests`). The open question is narrower: is a roster flag
marking management-shell clients wanted **purely as metadata** — surfaced in
`list_clients`/reports for visibility — with zero matching-behavior change?
Nice-to-have; no urgency. A yes/no is enough.

---

## How to respond

Reply on issue #39 (or to Josh directly) with: Decision 1 = A/B/C,
Decision 2 = A/B/C, item 2 flag = yes/no. Accepted decisions get dated
entries in `docs/decision-log.md`; any engine work gets its own plan doc with
a "Decisions locked" section before implementation.
