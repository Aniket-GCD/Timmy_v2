"""Firm pay-period edit windows (America/Chicago wall clock).

Period A: entry days 9–23 → editable from that month's 9th 00:00 through day 24 23:59:59.
Period B: entry day 24–month-end, then 1–8 → editable from that period's 24th 00:00
through day 9 of the following month 23:59:59.

Eligibility uses the work day (entry_date / start_at date), not submit time.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

# Exact firm names; match against local staff_name (trimmed, casefold).
SUPERUSER_NAMES = frozenset(
    {
        "shanya schweitzer",
        "nathan moorhead",
        "hannah curtis",
        "alex daley",
        "julia moorhead",
    }
)

CHICAGO_TZ_NAME = "America/Chicago"


def _as_date(entry_date: date | str) -> date:
    if isinstance(entry_date, date) and not isinstance(entry_date, datetime):
        return entry_date
    token = str(entry_date).strip()[:10]
    return date.fromisoformat(token)


def chicago_now(now: datetime | str | None = None) -> datetime:
    """Wall-clock 'now' in America/Chicago (naive local Chicago time)."""
    if now is not None:
        if isinstance(now, datetime):
            return now.replace(microsecond=0, tzinfo=None)
        token = str(now).strip()
        if token.endswith("Z"):
            token = token[:-1] + "+00:00"
        parsed = datetime.fromisoformat(token)
        if parsed.tzinfo is not None:
            try:
                from zoneinfo import ZoneInfo

                parsed = parsed.astimezone(ZoneInfo(CHICAGO_TZ_NAME))
            except Exception:
                parsed = parsed.astimezone().replace(tzinfo=None)  # type: ignore[assignment]
                return parsed.replace(microsecond=0)
            return parsed.replace(tzinfo=None, microsecond=0)
        return parsed.replace(microsecond=0)
    try:
        from zoneinfo import ZoneInfo

        return datetime.now(ZoneInfo(CHICAGO_TZ_NAME)).replace(tzinfo=None, microsecond=0)
    except Exception:
        # Operator machines at GCD are Chicago-local; fall back to system clock.
        return datetime.now().replace(microsecond=0)


def edit_window_for(entry_date: date | str) -> tuple[datetime, datetime]:
    """Inclusive start/end datetimes (Chicago wall) for editing this work day."""
    ed = _as_date(entry_date)
    y, m, d = ed.year, ed.month, ed.day
    if 9 <= d <= 23:
        return datetime(y, m, 9, 0, 0, 0), datetime(y, m, 24, 23, 59, 59)
    if d >= 24:
        start = datetime(y, m, 24, 0, 0, 0)
        if m == 12:
            end = datetime(y + 1, 1, 9, 23, 59, 59)
        else:
            end = datetime(y, m + 1, 9, 23, 59, 59)
        return start, end
    # Days 1–8: period began on the previous month's 24th.
    if m == 1:
        start = datetime(y - 1, 12, 24, 0, 0, 0)
    else:
        start = datetime(y, m - 1, 24, 0, 0, 0)
    return start, datetime(y, m, 9, 23, 59, 59)


def editable_now(entry_date: date | str, now: datetime | str | None = None) -> bool:
    current = chicago_now(now)
    start, end = edit_window_for(entry_date)
    return start <= current <= end


def is_superuser(staff_name: str | None) -> bool:
    return (staff_name or "").strip().casefold() in SUPERUSER_NAMES


def can_edit_entry(
    entry_date: date | str,
    staff_name: str | None,
    now: datetime | str | None = None,
) -> bool:
    if is_superuser(staff_name):
        return True
    return editable_now(entry_date, now=now)


def refuse_edit_message(entry_date: date | str, now: datetime | str | None = None) -> str:
    start, end = edit_window_for(entry_date)
    current = chicago_now(now)
    return (
        f"entry date {_as_date(entry_date).isoformat()} is outside the pay-period edit window "
        f"({start.isoformat()} through {end.isoformat()} Chicago); "
        f"now is {current.isoformat()}. Superusers can still edit."
    )


def entry_work_date(entry: dict[str, Any]) -> str:
    start_at = (entry.get("start_at") or "").strip()
    if len(start_at) >= 10:
        return start_at[:10]
    raise ValueError("entry is missing start_at date")
