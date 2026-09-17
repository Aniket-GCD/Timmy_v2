#!/usr/bin/env python3
"""Import MH (or any office) clients CSV into Supabase clients table.

CSV columns: name, office
Also ensures Unassigned exists for GCD and MH.

Usage (from kit root):
  python scripts/import_mh_clients_csv.py
  python scripts/import_mh_clients_csv.py --dry-run
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.append(str(SCRIPTS))

from _supabase_env import load_supabase_script_env  # noqa: E402
from timeassist.clients_seed import (  # noqa: E402
    CLIENTS_TABLE,
    ensure_unassigned,
    index_clients_by_name_office,
)
from timeassist.supabase_ref import request_json  # noqa: E402

DEFAULT_CSV = ROOT / "McKinley & Hutchings GCD CPAS_Customer Contact List (2).csv"


def load_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        out: list[dict[str, str]] = []
        for row in reader:
            name = (row.get("name") or row.get("display_name") or "").strip()
            if not name:
                continue
            office = (row.get("office") or "MH").strip().upper() or "MH"
            out.append({"name": name, "office": office})
        return out


def index_existing() -> dict[tuple[str, str], dict]:
    return index_clients_by_name_office()


def upsert_clients(
    rows: list[dict[str, str]],
    idx: dict[tuple[str, str], dict],
    *,
    dry_run: bool,
) -> tuple[int, int]:
    inserted = 0
    updated = 0
    for row in rows:
        key = (row["name"].casefold(), row["office"])
        existing = idx.get(key)
        body = {"name": row["name"], "office": row["office"], "active": True}
        if existing:
            if dry_run:
                updated += 1
                continue
            rid = existing.get("id")
            if rid is None:
                continue
            request_json(
                "PATCH",
                CLIENTS_TABLE,
                body={"active": True, "name": row["name"], "office": row["office"]},
                query={"id": f"eq.{rid}"},
                prefer="return=minimal",
            )
            updated += 1
        else:
            if dry_run:
                inserted += 1
                continue
            request_json("POST", CLIENTS_TABLE, body=body, prefer="return=minimal")
            idx[key] = body
            inserted += 1
    return inserted, updated


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", type=Path, default=DEFAULT_CSV)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if not args.csv.is_file():
        raise SystemExit(f"CSV not found: {args.csv}")

    load_supabase_script_env(ROOT)
    rows = load_rows(args.csv)
    print(f"Loaded {len(rows)} clients from {args.csv.name}")
    idx = index_existing()
    print(f"Existing clients in Supabase: {len(idx)}")
    ensure_unassigned(idx, dry_run=args.dry_run)
    print("Unassigned seed checked (GCD + MH)")
    inserted, updated = upsert_clients(rows, idx, dry_run=args.dry_run)
    print(f"Inserted {inserted}, updated/reactivated {updated}" + (" (dry-run)" if args.dry_run else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
