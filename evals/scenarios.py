"""Eval scenarios: operator utterances + expected tool behavior + end state.

Each scenario seeds a throwaway database through the real engine, scripts one
or more operator turns, and asserts three things:

- `expects`: tool calls that must appear, in order (argument subset match);
- `forbids`: tool calls that must never appear;
- `check_state`: deterministic end-state queries against the database — the
  engine owns the math, so correctness is exact, not judged.

Turn strings may contain `{day}` which the runner formats with today's date.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from timeassist import actions
from timeassist.db import connect

import os

# Eval seeding still uses CSV import; production matching is live Supabase.
os.environ.setdefault("TIMEASSIST_ALLOW_LOCAL_ROSTER", "1")


# --- expectation matching -------------------------------------------------

@dataclass
class Expect:
    tool: str
    where: dict[str, Any] | None = None


@dataclass
class Forbid:
    tool: str
    where: dict[str, Any] | None = None


def _args_match(where: dict[str, Any] | None, arguments: dict[str, Any]) -> bool:
    if not where:
        return True
    for key, want in where.items():
        if key not in arguments:
            return False
        got = arguments[key]
        if callable(want):
            if not want(got):
                return False
        elif got != want:
            return False
    return True


def match_expectations(calls: list, expects: list[Expect]) -> list[str]:
    """Ordered-subsequence match; returns error strings ([] = pass)."""
    errors = []
    cursor = 0
    for expect in expects:
        found = None
        for i in range(cursor, len(calls)):
            if calls[i].name == expect.tool and _args_match(expect.where, calls[i].arguments):
                found = i
                break
        if found is None:
            recorded = [c.name for c in calls]
            errors.append(
                f"expected {expect.tool}"
                + (f" with {expect.where}" if expect.where else "")
                + f" (in order) but recorded calls were: {recorded}"
            )
        else:
            cursor = found + 1
    return errors


def match_forbidden(calls: list, forbids: list[Forbid]) -> list[str]:
    errors = []
    for forbid in forbids:
        for call in calls:
            if call.name == forbid.tool and _args_match(forbid.where, call.arguments):
                errors.append(f"forbidden call happened: {forbid.tool} with {call.arguments}")
                break
    return errors


# --- scenario plumbing ------------------------------------------------------

@dataclass
class Scenario:
    name: str
    description: str
    seed: Callable[[Path, str], None]
    turns: list[str]
    expects: list[Expect] = field(default_factory=list)
    forbids: list[Forbid] = field(default_factory=list)
    check_state: Callable[[Path, str], list[str]] | None = None


def _t(day: str, hhmm: str) -> str:
    return f"{day}T{hhmm}:00"


def _seed_roster(db: Path, *names: str) -> None:
    path = Path(db).parent / "roster-seed.csv"
    path.write_text(
        "display_name,aliases,default_billable\n"
        + "".join(f"{name},,yes\n" for name in names)
    )
    actions.import_clients(db, path, mode="merge")


def _rows(db: Path, sql: str, *params: Any) -> list[dict[str, Any]]:
    # timeassist.db.connect, not raw sqlite3: sqlite3's own `with` block commits
    # but never closes, and the leaked handle makes Windows CI fail to delete
    # the eval temp dir (WinError 32 — broke the first v0.1.23 tag build).
    with connect(db) as conn:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]


def _contains(fragment: str) -> Callable[[Any], bool]:
    return lambda value: fragment.lower() in str(value).lower()


def _not_management(value: Any) -> bool:
    return "management" not in str(value).lower()


def _as_int(want: int) -> Callable[[Any], bool]:
    def check(value: Any) -> bool:
        try:
            return int(value) == want
        except (TypeError, ValueError):
            return False
    return check


_TRUTHY = lambda value: bool(value)  # noqa: E731 - tiny predicate


# --- seeds ------------------------------------------------------------------

def _seed_acme(db: Path, day: str) -> None:
    actions.init_state(db, _t(day, "08:00"))
    _seed_roster(db, "Acme Co")


def _seed_acme_bell_timer(db: Path, day: str) -> None:
    actions.init_state(db, _t(day, "08:00"))
    _seed_roster(db, "Acme Co", "Bell Co")
    actions.start_session(db, "Acme Co", "monthly reconciliation", "yes", _t(day, "09:00"))


def _seed_two_drafts(db: Path, day: str) -> None:
    actions.init_state(db, _t(day, "08:00"))
    _seed_roster(db, "Acme Co", "Bell Co")
    actions.add_missing_entry(db, "Acme Co", "monthly reconciliation", _t(day, "09:00"), _t(day, "10:00"), "yes")
    actions.add_missing_entry(db, "Bell Co", "payroll run", _t(day, "10:00"), _t(day, "11:00"), "yes")


def _seed_zed_needs_info(db: Path, day: str) -> None:
    actions.init_state(db, _t(day, "08:00"))
    _seed_roster(db, "Acme Co")
    actions.add_missing_entry(db, "Zed Partners", "quarterly review", _t(day, "09:00"), _t(day, "09:45"), "yes")


def _seed_management_twin(db: Path, day: str) -> None:
    actions.init_state(db, _t(day, "08:00"))
    _seed_roster(db, "Acme Co", "Acme Co Management")
    actions.add_missing_entry(db, "Acme Grp", "bookkeeping", _t(day, "09:00"), _t(day, "09:45"), "yes")


def _seed_bare(db: Path, day: str) -> None:
    actions.init_state(db, _t(day, "08:00"))


def _seed_23_minute_draft(db: Path, day: str) -> None:
    actions.init_state(db, _t(day, "08:00"))
    _seed_roster(db, "Acme Co")
    actions.add_missing_entry(db, "Acme Co", "monthly reconciliation", _t(day, "09:00"), _t(day, "09:23"), "yes")


# --- end-state checks -------------------------------------------------------

def _check_all_approved(db: Path, day: str) -> list[str]:
    rows = _rows(db, "SELECT entry_id, review_status FROM time_entries")
    errors = [f"entry {r['entry_id']} is {r['review_status']}, not approved"
              for r in rows if r["review_status"] != "approved"]
    if not rows:
        errors.append("no entries found")
    return errors


def _check_still_drafts(db: Path, day: str) -> list[str]:
    rows = _rows(db, "SELECT entry_id, review_status FROM time_entries")
    return [f"entry {r['entry_id']} left draft state: {r['review_status']}"
            for r in rows if r["review_status"] != "draft"]


def _check_zed_resolved(db: Path, day: str) -> list[str]:
    rows = _rows(db, "SELECT client_name, review_status FROM time_entries")
    errors = []
    for r in rows:
        if r["review_status"] != "draft":
            errors.append(f"entry still {r['review_status']} — needs_info was not resolved")
        if "zed" not in r["client_name"].lower():
            errors.append(f"client changed unexpectedly to {r['client_name']!r}")
    return errors


def _check_resolved_to_acme_co(db: Path, day: str) -> list[str]:
    rows = _rows(db, "SELECT client_name, review_status FROM time_entries")
    errors = []
    for r in rows:
        if r["client_name"] != "Acme Co":
            errors.append(f"entry resolved to {r['client_name']!r}, wanted 'Acme Co'")
        if r["review_status"] != "draft":
            errors.append(f"entry still {r['review_status']}")
    return errors


def _check_admin_unbillable(db: Path, day: str) -> list[str]:
    rows = _rows(db, "SELECT client_name, billable, review_status FROM time_entries")
    if not rows:
        return ["no entry was captured"]
    errors = []
    for r in rows:
        if int(r["billable"]) != 0:
            errors.append(f"{r['client_name']} entry is billable — admin lock violated")
        if r["review_status"] == "discarded":
            errors.append("entry was discarded instead of kept non-billable")
    return errors


def _check_rounded_to_20(db: Path, day: str) -> list[str]:
    rows = _rows(db, "SELECT duration_minutes, rounded_minutes FROM time_entries")
    if not rows:
        return ["no entry found"]
    return [f"raw {r['duration_minutes']} rounded to {r['rounded_minutes']}, wanted 20"
            for r in rows if r["rounded_minutes"] != 20]


# --- the scenarios ----------------------------------------------------------

SCENARIOS: list[Scenario] = [
    Scenario(
        name="start_known_client",
        description="A plain start request maps to one `start` call, not add_missing.",
        seed=_seed_acme,
        turns=["Start the clock — Acme Co, monthly reconciliation."],
        expects=[Expect("start", {"client": _contains("acme")})],
        forbids=[Forbid("add_missing")],
    ),
    Scenario(
        name="switch_is_immediate",
        description="A client change lands on switch; no end+start dance, no blocking questions.",
        seed=_seed_acme_bell_timer,
        turns=["I'm on Bell Co's payroll run now."],
        # A plain `start` attempt is fine: the seed opened the timer outside
        # this conversation, so the model can't know — the engine's teaching
        # error redirects it to `switch` (observed live; that recovery is the
        # designed defense-in-depth). Only `end` would be a real violation.
        expects=[Expect("switch", {"client": _contains("bell")})],
        forbids=[Forbid("end")],
    ),
    Scenario(
        name="switch_backdated_minutes_ago",
        description="'I switched 20 minutes ago' carries minutes_ago=20.",
        seed=_seed_acme_bell_timer,
        turns=["Oh — I actually switched to Bell Co's payroll run about 20 minutes ago."],
        expects=[Expect("switch", {"client": _contains("bell"), "minutes_ago": _as_int(20)})],
    ),
    Scenario(
        name="approve_all_uses_review_token",
        description="Bulk approval runs review first and passes its token.",
        seed=_seed_two_drafts,
        turns=["Everything looks right — approve all of today, please."],
        expects=[Expect("review"), Expect("approve_all", {"review_token": _TRUTHY})],
        forbids=[Forbid("export")],
        check_state=_check_all_approved,
    ),
    Scenario(
        name="review_never_exports",
        description="'How's my day?' is read-only: review, never approve/export.",
        seed=_seed_two_drafts,
        turns=["How's my day looking so far?"],
        expects=[Expect("review")],
        forbids=[Forbid("export"), Forbid("approve"), Forbid("approve_all"), Forbid("discard_entry"), Forbid("discard_drafts")],
        check_state=_check_still_drafts,
    ),
    Scenario(
        name="needs_info_confirmed_as_is",
        description="Confirm-as-is resolves needs_info with one edit (entry_id + client).",
        seed=_seed_zed_needs_info,
        turns=["That Zed Partners entry is correct — keep the client name exactly as it is."],
        expects=[Expect("edit", {"client": _contains("zed")})],
        forbids=[Forbid("discard_entry"), Forbid("discard_drafts")],
        check_state=_check_zed_resolved,
    ),
    Scenario(
        name="management_twin_never_selected",
        description="Resolving a flagged entry lands on Acme Co, never the management near-twin.",
        seed=_seed_management_twin,
        turns=["That flagged Acme Grp entry should be Acme Co — fix it."],
        expects=[Expect("edit", {"client": lambda v: _contains("acme")(v) and _not_management(v)})],
        forbids=[
            Forbid("edit", {"client": _contains("management")}),
            Forbid("clarify_active", {"client": _contains("management")}),
        ],
        check_state=_check_resolved_to_acme_co,
    ),
    Scenario(
        name="admin_time_stays_unbillable",
        description="Billable-admin request: engine rejection relayed, then captured non-billable.",
        seed=_seed_bare,
        # The engine rejects an explicitly-billable admin capture with a
        # teaching error (observed live); the contract says relay it and offer
        # the non-billable capture. Turn 2 accepts that offer — the end state
        # must be a real, non-billable entry, never a discard.
        turns=[
            "Log 9:00 to 9:30 this morning as Admin time — and mark it billable.",
            "Fine — log it as non-billable then.",
        ],
        expects=[Expect("add_missing", {"client": _contains("admin")})],
        forbids=[Forbid("discard_entry")],
        check_state=_check_admin_unbillable,
    ),
    Scenario(
        name="custom_rounding_increment",
        description="Free-form rounding: 'nearest 10' becomes reround nearest_10_minutes.",
        seed=_seed_23_minute_draft,
        turns=["Round today's time to the nearest 10 minutes — yes, I'm sure."],
        expects=[Expect("reround", {"rule": "nearest_10_minutes", "confirm": True})],
        check_state=_check_rounded_to_20,
    ),
    Scenario(
        name="checkin_reply_mapping",
        description="Reminder flow: checkin_status on the trigger, snooze maps to snooze_checkin.",
        seed=_seed_acme_bell_timer,
        turns=[
            "[Scheduled reminder fired: check whether a TimeAssist timer is open.]",
            "Pause the check-in reminders for 30 minutes.",
        ],
        expects=[Expect("checkin_status"), Expect("snooze_checkin", {"minutes": _as_int(30)})],
    ),
]
