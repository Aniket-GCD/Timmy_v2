#!/usr/bin/env python3
"""Upsert employees from GCD Employees CSV into Supabase (service role).

Usage (from kit root):
  python scripts/sync_employees_from_csv.py
  python scripts/sync_employees_from_csv.py --csv "GCD Employees 9.1.2026.csv"
  python scripts/sync_employees_from_csv.py --dry-run
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _supabase_env import load_supabase_script_env  # noqa: E402
from timeassist.supabase_ref import request_json  # noqa: E402

DEFAULT_CSV = ROOT / "GCD Employees 9.1.2026.csv"
EMPLOYEES_TABLE = "employees"


def _truthy(raw: str) -> bool:
    return raw.strip().upper() in {"1", "TRUE", "YES", "Y", "T"}


def load_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        rows: list[dict[str, str]] = []
        for row in reader:
            staff = (row.get("staff_name") or "").strip()
            if not staff:
                continue
            rows.append(
                {
                    "first_name": (row.get("first_name") or "").strip(),
                    "last_name": (row.get("last_name") or "").strip(),
                    "staff_name": staff,
                    "email": (row.get("emails") or row.get("email") or "").strip().lower(),
                    "is_admin": "true" if _truthy(row.get("is_admin") or "") else "false",
                    "office": (row.get("office") or "GCD").strip().upper() or "GCD",
                    "active": "true",
                }
            )
        return rows


def fetch_by_staff_name(staff_name: str) -> dict | None:
    page = request_json(
        "GET",
        EMPLOYEES_TABLE,
        query={"select": "id,staff_name,email", "staff_name": f"eq.{staff_name}", "limit": "1"},
    )
    if isinstance(page, list) and page:
        return page[0]
    return None


def upsert_row(row: dict[str, str], *, dry_run: bool) -> str:
    body = {
        "first_name": row["first_name"],
        "last_name": row["last_name"],
        "staff_name": row["staff_name"],
        "email": row["email"] or None,
        "is_admin": row["is_admin"] == "true",
        "office": row["office"],
        "active": True,
    }
    existing = fetch_by_staff_name(row["staff_name"])
    if dry_run:
        return f"{'update' if existing else 'insert'} {row['staff_name']} ({row['office']})"
    if existing and existing.get("id"):
        request_json(
            "PATCH",
            EMPLOYEES_TABLE,
            body=body,
            query={"id": f"eq.{existing['id']}"},
            prefer="return=minimal",
        )
        return f"updated {row['staff_name']}"
    request_json("POST", EMPLOYEES_TABLE, body=body, prefer="return=minimal")
    return f"inserted {row['staff_name']}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", type=Path, default=DEFAULT_CSV)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if not args.csv.is_file():
        raise SystemExit(f"CSV not found: {args.csv}")

    load_supabase_script_env(ROOT)
    rows = load_rows(args.csv)
    print(f"Loaded {len(rows)} employees from {args.csv.name}")
    for row in rows:
        print(upsert_row(row, dry_run=args.dry_run))
    print("Done." + (" (dry-run)" if args.dry_run else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
