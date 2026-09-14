#!/usr/bin/env python3
"""Pull QBO Customers (read-only) into Supabase clients.

Requires QBO_CLIENT_ID, QBO_CLIENT_SECRET, QBO_COMPANIES JSON, and Supabase service role.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _supabase_env import load_supabase_script_env  # noqa: E402
from timeassist.qbo_clients import sync_all_companies  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    load_supabase_script_env(ROOT)
    results = sync_all_companies(dry_run=args.dry_run)
    print(json.dumps(results, indent=2))
    print("Done." + (" (dry-run — no Supabase writes)" if args.dry_run else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
