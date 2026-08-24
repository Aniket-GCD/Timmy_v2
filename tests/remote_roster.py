"""Shared test helper: mock live Supabase get_clients for capture/resolve."""

from __future__ import annotations

from typing import Any
from unittest import mock


def install_live_clients(test_case: Any, *names: str, office: str = "GCD") -> Any:
    """Patch supabase_ref.get_clients for the lifetime of test_case.

    Returns an `add(*names)` callable to append more clients mid-test.
    Always includes Unassigned for the given office.
    """
    rows: list[dict[str, Any]] = [
        {"name": "Unassigned", "office": office, "active": True},
    ]
    for name in names:
        rows.append({"name": name, "office": office, "active": True})

    def getter(
        environ: dict[str, str] | None = None,
        db_path: Any = None,
        **_kwargs: Any,
    ) -> list[dict[str, Any]]:
        return list(rows)

    patcher = mock.patch("timeassist.supabase_ref.get_clients", side_effect=getter)
    patcher.start()
    test_case.addCleanup(patcher.stop)

    def add(*more: str) -> None:
        for name in more:
            rows.append({"name": name, "office": office, "active": True})

    return add
