"""Supabase table-name config (stdlib JSON). Secrets stay in the environment.

Load order for file content (first found wins):
1. TIMEASSIST_SUPABASE_CONFIG (path to JSON)
2. <dir of --db>/supabase.json
3. Plugin-shipped config next to the exe: ../config/supabase.json
   (plugin zip layout: timeassist/engine/timeassist.exe + timeassist/config/supabase.json)
4. Built-in defaults (same as shipped config/supabase.json)

Env overrides (win over file) for individual tables:
  TIMEASSIST_SUPABASE_TABLE_TIME_ENTRIES
  TIMEASSIST_SUPABASE_TABLE_CLIENTS
  TIMEASSIST_SUPABASE_TABLE_JOB_CODES
  TIMEASSIST_SUPABASE_TABLE_CURRENTLY_WORKING
  TIMEASSIST_SUPABASE_TABLE_EMPLOYEES
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import Any

_TABLE_NAME_RE = re.compile(r"^[A-Za-z0-9_]+$")

# Keep in sync with config/supabase.json (pilot: write sandbox table).
DEFAULT_SUPABASE_CONFIG: dict[str, Any] = {
    "tables": {
        "time_entries": "time_entries_timmy_v2",
        "clients": "clients",
        "job_codes": "job_codes",
        "currently_working": "currently_working",
        "employees": "employees",
    },
    "unassigned_client_name": "Unassigned",
}

_TABLE_KEYS = ("time_entries", "clients", "job_codes", "currently_working", "employees")

_ENV_TABLE_KEYS = {
    "time_entries": "TIMEASSIST_SUPABASE_TABLE_TIME_ENTRIES",
    "clients": "TIMEASSIST_SUPABASE_TABLE_CLIENTS",
    "job_codes": "TIMEASSIST_SUPABASE_TABLE_JOB_CODES",
    "currently_working": "TIMEASSIST_SUPABASE_TABLE_CURRENTLY_WORKING",
    "employees": "TIMEASSIST_SUPABASE_TABLE_EMPLOYEES",
}


def validate_table_name(name: str, *, label: str) -> str:
    value = (name or "").strip()
    if not value:
        raise ValueError(f"Supabase table name for {label} is empty")
    if not _TABLE_NAME_RE.fullmatch(value):
        raise ValueError(
            f"Supabase table name for {label} must be letters, digits, or underscore only: {value!r}"
        )
    return value


def _deep_copy_defaults() -> dict[str, Any]:
    return {
        "tables": dict(DEFAULT_SUPABASE_CONFIG["tables"]),
        "unassigned_client_name": DEFAULT_SUPABASE_CONFIG["unassigned_client_name"],
    }


def _merge_file_payload(base: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    out = {
        "tables": dict(base["tables"]),
        "unassigned_client_name": base["unassigned_client_name"],
    }
    tables = payload.get("tables")
    if isinstance(tables, dict):
        for key in _TABLE_KEYS:
            if key in tables and tables[key] is not None:
                out["tables"][key] = tables[key]
    if "unassigned_client_name" in payload and payload["unassigned_client_name"] is not None:
        out["unassigned_client_name"] = payload["unassigned_client_name"]
    return out


def _read_json_file(path: Path) -> dict[str, Any]:
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError(f"cannot read Supabase config {path}: {exc}") from None
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON in Supabase config {path}: {exc}") from None
    if not isinstance(payload, dict):
        raise ValueError(f"Supabase config {path} must be a JSON object")
    return payload


def _config_path_from_env(environ: dict[str, str]) -> Path | None:
    raw = (environ.get("TIMEASSIST_SUPABASE_CONFIG") or "").strip()
    if not raw:
        return None
    return Path(raw).expanduser()


def _config_path_beside_db(db_path: str | Path | None) -> Path | None:
    if db_path is None:
        return None
    return Path(db_path).expanduser().resolve().parent / "supabase.json"


def _config_path_plugin_shipped() -> Path | None:
    """config/supabase.json shipped in the plugin zip next to engine/."""
    if getattr(sys, "frozen", False):
        # .../timeassist/engine/timeassist.exe -> .../timeassist/config/supabase.json
        candidate = Path(sys.executable).resolve().parent.parent / "config" / "supabase.json"
        if candidate.is_file():
            return candidate
    # Dev checkout / tests: repo config/
    repo = Path(__file__).resolve().parents[1] / "config" / "supabase.json"
    if repo.is_file():
        return repo
    return None


def _resolve_config_file(
    db_path: str | Path | None,
    environ: dict[str, str],
) -> Path | None:
    env_path = _config_path_from_env(environ)
    if env_path is not None:
        return env_path
    beside = _config_path_beside_db(db_path)
    if beside is not None and beside.is_file():
        return beside
    return _config_path_plugin_shipped()


def load_supabase_config(
    db_path: str | Path | None = None,
    environ: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Return validated config dict with tables + unassigned_client_name."""
    env = os.environ if environ is None else environ
    cfg = _deep_copy_defaults()

    path = _resolve_config_file(db_path, env)
    if path is not None:
        if _config_path_from_env(env) is not None and not path.is_file():
            raise ValueError(f"TIMEASSIST_SUPABASE_CONFIG is not a file: {path}")
        if path.is_file():
            cfg = _merge_file_payload(cfg, _read_json_file(path))

    tables = cfg["tables"]
    for key, env_key in _ENV_TABLE_KEYS.items():
        override = (env.get(env_key) or "").strip()
        if override:
            tables[key] = override

    cfg["tables"] = {
        key: validate_table_name(tables[key], label=key)
        for key in _TABLE_KEYS
    }
    unassigned = (cfg.get("unassigned_client_name") or "").strip() or "Unassigned"
    if not unassigned:
        raise ValueError("unassigned_client_name is empty")
    cfg["unassigned_client_name"] = unassigned
    return cfg


def time_entries_table(
    db_path: str | Path | None = None,
    environ: dict[str, str] | None = None,
) -> str:
    return load_supabase_config(db_path=db_path, environ=environ)["tables"]["time_entries"]


def clients_table(
    db_path: str | Path | None = None,
    environ: dict[str, str] | None = None,
) -> str:
    return load_supabase_config(db_path=db_path, environ=environ)["tables"]["clients"]


def job_codes_table(
    db_path: str | Path | None = None,
    environ: dict[str, str] | None = None,
) -> str:
    return load_supabase_config(db_path=db_path, environ=environ)["tables"]["job_codes"]


def currently_working_table(
    db_path: str | Path | None = None,
    environ: dict[str, str] | None = None,
) -> str:
    return load_supabase_config(db_path=db_path, environ=environ)["tables"]["currently_working"]


def employees_table(
    db_path: str | Path | None = None,
    environ: dict[str, str] | None = None,
) -> str:
    return load_supabase_config(db_path=db_path, environ=environ)["tables"]["employees"]


def unassigned_client_name(
    db_path: str | Path | None = None,
    environ: dict[str, str] | None = None,
) -> str:
    return load_supabase_config(db_path=db_path, environ=environ)["unassigned_client_name"]
