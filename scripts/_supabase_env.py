"""Load Supabase URL/key for kit scripts (service role preferred)."""

from __future__ import annotations

import os
from pathlib import Path


def _parse_env_file(path: Path) -> None:
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        raw = line.strip()
        if not raw or raw.startswith("#") or "=" not in raw:
            continue
        key, _, val = raw.partition("=")
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = val


def load_supabase_script_env(kit_root: Path | None = None) -> tuple[str, str]:
    root = kit_root or Path(__file__).resolve().parents[1]
    for rel in ("dashboard/.env.local", "dashboard/.env", ".env"):
        _parse_env_file(root / rel)

    url = (os.environ.get("SUPABASE_URL") or "").strip().rstrip("/")
    key = (
        (os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or "").strip()
        or (os.environ.get("SUPABASE_KEY") or "").strip()
        or (os.environ.get("SUPABASE_SECRET") or "").strip()
    )
    if not url or not key:
        raise SystemExit(
            "Set SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY "
            "(or SUPABASE_KEY) in the environment or dashboard/.env.local"
        )
    # Prefer service role for writes in child modules that read SUPABASE_KEY.
    os.environ["SUPABASE_URL"] = url
    os.environ["SUPABASE_KEY"] = key
    return url, key
