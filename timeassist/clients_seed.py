"""Shared client seed helpers (Unassigned holding rows for GCD / MH)."""

from __future__ import annotations

from typing import Any

from timeassist.supabase_ref import _fetch_table_rows, request_json

CLIENTS_TABLE = "clients_qbo_preview"

UNASSIGNED_ROWS: list[dict[str, Any]] = [
    {"name": "Unassigned", "office": "GCD", "qbo_customer_id": "UNASSIGNED", "active": True},
    {"name": "Unassigned", "office": "MH", "qbo_customer_id": "UNASSIGNED-MH", "active": True},
]


def index_clients_by_name_office(
    environ: dict[str, str] | None = None,
) -> dict[tuple[str, str], dict[str, Any]]:
    rows = _fetch_table_rows(CLIENTS_TABLE, environ=environ)
    idx: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        name = str(row.get("name") or row.get("display_name") or "").strip()
        office = str(row.get("office") or "").strip().upper()
        if name and office:
            idx[(name.casefold(), office)] = row
    return idx


def ensure_unassigned(
    idx: dict[tuple[str, str], dict[str, Any]] | None = None,
    *,
    dry_run: bool = False,
    environ: dict[str, str] | None = None,
) -> dict[str, int]:
    """Ensure GCD + MH Unassigned holding clients exist. Returns insert counts."""
    index = idx if idx is not None else index_clients_by_name_office(environ=environ)
    inserted = 0
    skipped = 0
    for row in UNASSIGNED_ROWS:
        key = (str(row["name"]).casefold(), str(row["office"]))
        if key in index:
            skipped += 1
            continue
        if dry_run:
            inserted += 1
            continue
        request_json("POST", CLIENTS_TABLE, body=row, prefer="return=minimal", environ=environ)
        index[key] = row
        inserted += 1
    return {"unassigned_inserted": inserted, "unassigned_skipped": skipped}
