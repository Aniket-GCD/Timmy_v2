"""Stdlib GET client for the firm's Supabase lookups (clients, job_codes).

Secrets stay in the environment. Keys are never logged. New-style
``sb_secret_`` keys go in the ``apikey`` header only — they must not be sent
as ``Authorization: Bearer`` (that path is treated as a browser and blocked).
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
from typing import Any
from urllib.request import Request, urlopen

# curl-like UA so secret keys are not blocked as a browser client.
USER_AGENT = "curl/8.5.0"


class DuplicateTimeEntryError(ValueError):
    """Raised when Supabase unique(staff_name, office, entry_date, start_time, end_time) fires."""


def credentials_from_env(environ: dict[str, str] | None = None) -> tuple[str, str]:
    env = os.environ if environ is None else environ
    url = (env.get("SUPABASE_URL") or "").strip().rstrip("/")
    key = (
        (env.get("SUPABASE_KEY") or "").strip()
        or (env.get("SUPABASE_ANON_KEY") or "").strip()
        or (env.get("SUPABASE_SECRET") or "").strip()
    )
    if not url or not key:
        raise ValueError(
            "Set SUPABASE_URL and SUPABASE_KEY (or SUPABASE_ANON_KEY / SUPABASE_SECRET). "
            "Do not type the key into chat."
        )
    return url, key


def is_secret_key(key: str) -> bool:
    return key.startswith("sb_secret_")


def rest_headers(
    key: str,
    *,
    json_body: bool = False,
    prefer: str | None = None,
) -> dict[str, str]:
    headers = {
        "apikey": key,
        "Accept": "application/json",
        "User-Agent": USER_AGENT,
    }
    if not is_secret_key(key):
        headers["Authorization"] = f"Bearer {key}"
    if json_body:
        headers["Content-Type"] = "application/json"
        headers["Prefer"] = prefer or "return=minimal"
    elif prefer:
        headers["Prefer"] = prefer
    return headers


def _table_url(base_url: str, table: str, query: dict[str, str] | None = None) -> str:
    path = f"{base_url}/rest/v1/{table}"
    if query:
        return path + "?" + urllib.parse.urlencode(query)
    return path


def request_json(
    method: str,
    table: str,
    *,
    body: dict[str, Any] | None = None,
    query: dict[str, str] | None = None,
    environ: dict[str, str] | None = None,
    timeout: float = 30,
    prefer: str | None = None,
) -> Any:
    """HTTP JSON against PostgREST. Never includes the API key in raised errors."""
    url, key = credentials_from_env(environ)
    payload = None if body is None else json.dumps(body).encode("utf-8")
    headers = rest_headers(key, json_body=payload is not None, prefer=prefer)
    request = Request(
        _table_url(url, table, query),
        data=payload,
        headers=headers,
        method=method.upper(),
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            raw = response.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")
        raise _http_error(exc.code, detail) from None
    except urllib.error.URLError as exc:
        raise ValueError("Supabase request failed (network).") from exc
    if not raw:
        return None
    try:
        return json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError:
        raise ValueError("Supabase returned non-JSON.") from None


def _http_error(status: int, detail: str) -> Exception:
    lowered = detail.lower()
    unique_hit = (
        status == 409
        or "23505" in detail
        or "duplicate key" in lowered
        or "unique constraint" in lowered
    )
    if unique_hit:
        return DuplicateTimeEntryError(
            "This time block is already recorded (same staff, office, date, start, and end). "
            "Overlapping neighbors like 9-10 and 10-11 for the same client are allowed."
        )
    # Strip anything that might echo a key from a misconfigured proxy; keep short.
    snippet = detail.replace("\n", " ").strip()[:240]
    return ValueError(f"Supabase HTTP {status}" + (f": {snippet}" if snippet else ""))


def get_clients(environ: dict[str, str] | None = None) -> list[dict[str, Any]]:
    rows = request_json("GET", "clients", query={"select": "*"}, environ=environ)
    return rows if isinstance(rows, list) else []


def get_job_codes(environ: dict[str, str] | None = None) -> list[dict[str, Any]]:
    rows = request_json("GET", "job_codes", query={"select": "*"}, environ=environ)
    return rows if isinstance(rows, list) else []


def slim_job_code(row: dict[str, Any]) -> dict[str, Any]:
    code = str(row.get("job_code") or row.get("code") or "").strip()
    return {
        "job_code": code,
        "description": (row.get("description") or "").strip() or None,
        "account": (row.get("account") or "").strip() or None,
    }


def list_job_codes(environ: dict[str, str] | None = None) -> dict[str, Any]:
    codes = [slim_job_code(row) for row in get_job_codes(environ=environ)]
    codes = [row for row in codes if row["job_code"]]
    return {"job_codes": codes}


def account_for_job_code(job_code: str, rows: list[dict[str, Any]]) -> str:
    wanted = job_code.strip().casefold()
    for row in rows:
        slim = slim_job_code(row)
        if slim["job_code"].casefold() == wanted:
            account = slim.get("account") or ""
            if not account:
                raise ValueError(
                    f"Job Code '{slim['job_code']}' has no account on the job_codes row; account is never typed."
                )
            return account
    raise ValueError(
        f"Job Code '{job_code}' is not in job_codes; copy account from that table, never type it."
    )


def client_display_name(row: dict[str, Any]) -> str:
    for key in ("client", "display_name", "name"):
        value = (row.get(key) or "").strip()
        if value:
            return value
    return ""
