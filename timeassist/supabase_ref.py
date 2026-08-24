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
from pathlib import Path
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


def get_clients(
    environ: dict[str, str] | None = None,
    db_path: str | Path | None = None,
) -> list[dict[str, Any]]:
    from .supabase_config import clients_table

    table = clients_table(db_path=db_path, environ=environ)
    rows = request_json("GET", table, query={"select": "*"}, environ=environ)
    return rows if isinstance(rows, list) else []


def get_job_codes(
    environ: dict[str, str] | None = None,
    db_path: str | Path | None = None,
) -> list[dict[str, Any]]:
    from .supabase_config import job_codes_table

    table = job_codes_table(db_path=db_path, environ=environ)
    rows = request_json("GET", table, query={"select": "*"}, environ=environ)
    return rows if isinstance(rows, list) else []


def slim_job_code(row: dict[str, Any]) -> dict[str, Any]:
    code = str(row.get("job_code") or row.get("code") or "").strip()
    return {
        "job_code": code,
        "description": (row.get("description") or "").strip() or None,
        "account": (row.get("account") or "").strip() or None,
    }


def list_job_codes(
    environ: dict[str, str] | None = None,
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    codes = [slim_job_code(row) for row in get_job_codes(environ=environ, db_path=db_path)]
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


def name_fold(name: str) -> str:
    """Fold 'Lastname, Firstname' to 'firstname lastname' (lower, collapsed spaces)."""
    s = " ".join(name.lower().split())
    if "," in s:
        parts = [p.strip() for p in s.split(",")]
        if len(parts) == 2 and all(parts):
            s = f"{parts[1]} {parts[0]}"
    return s


def _match_tokens(name: str) -> list[str]:
    """Significant tokens for soft match (strip punctuation noise)."""
    folded = name_fold(name)
    cleaned = "".join(ch if ch.isalnum() or ch.isspace() else " " for ch in folded)
    return [tok for tok in cleaned.split() if len(tok) >= 3]


def soft_unique_match(spoken: str, display_names: list[str]) -> str | None:
    """If spoken uniquely identifies one roster name, return that display name.

    Used for nicknames like "Bill's Shop" -> "Bill's Windsurf Shop" when only
    one active client contains all significant spoken tokens. Ambiguous or
    empty -> None (caller asks / uses Unassigned flow).
    """
    tokens = _match_tokens(spoken)
    if not tokens:
        return None
    hits: list[str] = []
    seen: set[str] = set()
    for display in display_names:
        display_toks = set(_match_tokens(display))
        if not display_toks:
            continue
        if all(tok in display_toks for tok in tokens):
            key = display.casefold()
            if key in seen:
                continue
            seen.add(key)
            hits.append(display)
    if len(hits) == 1:
        return hits[0]
    return None


def slim_client(row: dict[str, Any]) -> dict[str, Any]:
    display = client_display_name(row)
    office = (row.get("office") or "").strip() or None
    active = row.get("active")
    if active is None:
        active_flag = True
    elif isinstance(active, bool):
        active_flag = active
    else:
        active_flag = str(active).strip().lower() in {"1", "true", "yes", "t"}
    return {
        "display_name": display,
        "office": office,
        "active": active_flag,
        "client_key": (row.get("qbo_customer_id") or row.get("client_key") or "").strip() or None,
        "default_billable": 1,
        "billable_locked": 0,
        "default_job_type": "",
        "aliases": "",
    }


def _wrap_client_fetch(exc: BaseException) -> ValueError:
    msg = str(exc).strip() or exc.__class__.__name__
    if msg.lower().startswith("set supabase_url") or "supabase" in msg.lower():
        return ValueError(f"client list unavailable: {msg}")
    return ValueError(f"client list unavailable: cannot reach Supabase ({msg})")


def list_clients_remote(
    environ: dict[str, str] | None = None,
    office: str | None = None,
    db_path: str | Path | None = None,
    query: str | None = None,
) -> list[dict[str, Any]]:
    """Live read-only GET of Supabase clients. Fail closed on network/auth errors.

    Optional ``query`` keeps only display names whose tokens match (same soft
    rules as resolve) so the model need not dump the full roster.
    """
    from .supabase_config import unassigned_client_name

    try:
        rows = get_clients(environ=environ, db_path=db_path)
    except ValueError as exc:
        raise _wrap_client_fetch(exc) from None
    unassigned_label = unassigned_client_name(db_path=db_path, environ=environ)
    office_norm = (office or "").strip().upper() or None
    out: list[dict[str, Any]] = []
    for row in rows:
        slim = slim_client(row)
        if not slim["display_name"]:
            continue
        if not slim["active"]:
            continue
        row_office = (slim["office"] or "").strip().upper() or None
        if office_norm:
            # Keep office match; always keep Unassigned for that office (or any Unassigned).
            is_unassigned = slim["display_name"].casefold() == unassigned_label.casefold()
            if row_office and row_office != office_norm and not is_unassigned:
                continue
            if is_unassigned and row_office and row_office != office_norm:
                continue
        out.append(slim)
    out.sort(key=lambda item: item["display_name"].casefold())
    q = (query or "").strip()
    if q:
        tokens = _match_tokens(q)
        needle = name_fold(q)
        filtered: list[dict[str, Any]] = []
        for slim in out:
            display = slim["display_name"]
            folded = name_fold(display)
            if needle and needle in folded:
                filtered.append(slim)
                continue
            if tokens:
                display_toks = set(_match_tokens(display))
                if all(tok in display_toks for tok in tokens):
                    filtered.append(slim)
        out = filtered
    return out


def classify_client_remote(
    name: str,
    *,
    environ: dict[str, str] | None = None,
    office: str | None = None,
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    """Classify spoken name against live Supabase clients.

    kind:
      - exact / fold — safe to resolve without asking
      - soft — unique nickname/token hit; ask "Did you mean …?" before writing
      - none — no hit; ask if new client (Unassigned + reception draft)
    """
    target = name.strip()
    if not target:
        return {"kind": "none", "display_name": None, "spoken": ""}
    clients = list_clients_remote(environ=environ, office=office, db_path=db_path)
    names = [row["display_name"] for row in clients]
    lowered = target.casefold()
    for display in names:
        if display.casefold() == lowered:
            return {"kind": "exact", "display_name": display, "spoken": target}
    folded_target = name_fold(target)
    fold_matches = [display for display in names if name_fold(display) == folded_target]
    if len(fold_matches) == 1:
        return {"kind": "fold", "display_name": fold_matches[0], "spoken": target}
    soft = soft_unique_match(target, names)
    if soft:
        return {"kind": "soft", "display_name": soft, "spoken": target}
    return {"kind": "none", "display_name": None, "spoken": target}


def resolve_client_remote(
    name: str,
    *,
    environ: dict[str, str] | None = None,
    office: str | None = None,
    db_path: str | Path | None = None,
) -> str | None:
    """Return canonical display_name from live Supabase list, or None if unmatched.

    Includes soft unique matches (callers that must ask first use classify_client_remote).
    """
    classified = classify_client_remote(
        name, environ=environ, office=office, db_path=db_path,
    )
    return classified["display_name"]


def roster_row_from_display(display_name: str) -> dict[str, Any]:
    """Stand-in for the old SQLite client row (billable defaults for live roster)."""
    return {
        "display_name": display_name,
        "default_billable": 1,
        "billable_locked": 0,
        "default_job_type": "",
        "aliases": "",
        "client_key": None,
    }
