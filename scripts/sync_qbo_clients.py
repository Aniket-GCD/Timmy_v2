#!/usr/bin/env python3
"""Pull QBO Customers (read-only) into Supabase (see CLIENTS_TABLE).

Requires:
  - Rows in Supabase ``qbo_tokens`` (GCD + MH) from ``qbo_oauth_setup.py``
  - QBO_CLIENT_ID, QBO_CLIENT_SECRET
  - SUPABASE_URL + SUPABASE_SERVICE_ROLE_KEY

``--dry-run`` skips ``clients`` writes but still persists rotated refresh tokens
in ``qbo_tokens`` (Intuit invalidates the old refresh on use).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.append(str(SCRIPTS))

from _supabase_env import load_supabase_script_env  # noqa: E402
from timeassist.qbo_clients import sync_all_companies  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Skip clients upserts; still write rotated refresh tokens to qbo_tokens",
    )
    args = parser.parse_args()
    load_supabase_script_env(ROOT)
    print("[qbo] script start — progress logs go to stderr", file=sys.stderr, flush=True)
    try:
        results = sync_all_companies(dry_run=args.dry_run)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(json.dumps(results, indent=2))
    print(
        "Done."
        + (
            " (dry-run — no clients writes; qbo_tokens may still update)"
            if args.dry_run
            else ""
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
