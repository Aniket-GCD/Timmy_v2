"""Stdlib GET client for the firm's Supabase lookups (clients, job_codes).

Secrets stay in the environment. Keys are never logged. New-style
``sb_secret_`` keys go in the ``apikey`` header only — they must not be sent
as ``Authorization: Bearer`` (that path is treated as a browser and blocked).
"""

from __future__ import annotations

import difflib
import json
import os
import urllib.error
import urllib.parse
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen

# curl-like UA so secret keys are not blocked as a browser client.
USER_AGENT = "curl/8.5.0"

# PostgREST returns at most this many rows per request unless paginated.
POSTGREST_PAGE_SIZE = 1000


class DuplicateTimeEntryError(ValueError):
    """Raised when Supabase unique(staff_name, office, entry_date, start_time, end_time) fires."""

    def __init__(self, message: str, *, detail: str = "") -> None:
        super().__init__(message)
        self.detail = detail


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
            "Overlapping neighbors like 9-10 and 10-11 for the same client are allowed.",
            detail=detail,
        )
    # Strip anything that might echo a key from a misconfigured proxy; keep short.
    snippet = detail.replace("\n", " ").strip()[:240]
    return ValueError(f"Supabase HTTP {status}" + (f": {snippet}" if snippet else ""))


def _fetch_table_rows(
    table: str,
    *,
    environ: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Fetch every row from a PostgREST table, paging past the 1k default cap."""
    all_rows: list[dict[str, Any]] = []
    offset = 0
    while True:
        page = request_json(
            "GET",
            table,
            query={
                "select": "*",
                "limit": str(POSTGREST_PAGE_SIZE),
                "offset": str(offset),
            },
            environ=environ,
        )
        if not isinstance(page, list) or not page:
            break
        all_rows.extend(page)
        if len(page) < POSTGREST_PAGE_SIZE:
            break
        offset += POSTGREST_PAGE_SIZE
    return all_rows


def get_clients(
    environ: dict[str, str] | None = None,
    db_path: str | Path | None = None,
) -> list[dict[str, Any]]:
    from .supabase_config import clients_table

    table = clients_table(db_path=db_path, environ=environ)
    return _fetch_table_rows(table, environ=environ)


def get_job_codes(
    environ: dict[str, str] | None = None,
    db_path: str | Path | None = None,
) -> list[dict[str, Any]]:
    from .supabase_config import job_codes_table

    table = job_codes_table(db_path=db_path, environ=environ)
    return _fetch_table_rows(table, environ=environ)


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
    *,
    client: str | None = None,
    office: str | None = None,
    suggest_limit: int = 3,
) -> dict[str, Any]:
    codes = [slim_job_code(row) for row in get_job_codes(environ=environ, db_path=db_path)]
    codes = [row for row in codes if row["job_code"]]
    result: dict[str, Any] = {"job_codes": codes}
    if client and client.strip():
        result["suggested_job_codes"] = suggest_job_codes_for_client(
            client.strip(),
            office,
            limit=suggest_limit,
            environ=environ,
            db_path=db_path,
            catalog=codes,
        )
        result["other_label"] = "Other"
    return result


def suggest_job_codes_for_client(
    client: str,
    office: str | None = None,
    *,
    limit: int = 3,
    environ: dict[str, str] | None = None,
    db_path: str | Path | None = None,
    catalog: list[dict[str, Any]] | None = None,
) -> list[str]:
    """Top job codes used for this client (office-scoped), else first catalog codes."""
    from .supabase_config import time_entries_table

    wanted = (client or "").strip()
    if not wanted or limit <= 0:
        return []
    counts: dict[str, int] = {}
    try:
        table = time_entries_table(db_path=db_path, environ=environ)
        query: dict[str, str] = {
            "select": "job_code",
            "client": f"eq.{wanted}",
            "limit": "500",
        }
        office_norm = (office or "").strip().upper()
        if office_norm in {"GCD", "MH"}:
            query["office"] = f"eq.{office_norm}"
        rows = request_json("GET", table, query=query, environ=environ)
        if isinstance(rows, list):
            for row in rows:
                code = str(row.get("job_code") or "").strip()
                if not code:
                    continue
                counts[code] = counts.get(code, 0) + 1
    except (ValueError, urllib.error.URLError, OSError, json.JSONDecodeError):
        counts = {}

    ranked = sorted(counts.keys(), key=lambda c: (-counts[c], c.casefold()))
    out = ranked[:limit]
    if len(out) >= limit:
        return out

    if catalog is None:
        catalog = [
            slim_job_code(row)
            for row in get_job_codes(environ=environ, db_path=db_path)
        ]
    seen = {c.casefold() for c in out}
    for row in sorted(catalog, key=lambda r: str(r.get("job_code") or "").casefold()):
        code = str(row.get("job_code") or "").strip()
        if not code or code.casefold() in seen:
            continue
        out.append(code)
        seen.add(code.casefold())
        if len(out) >= limit:
            break
    return out


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
    """Fold names for equality: lower, strip punctuation, optional Last/First swap.

    Person-style ``Last, First`` (both sides a single token) becomes
    ``first last``. Entity commas like ``TSG2 NC, LP`` are not swapped — they
    normalize to the same key as ``TSG2 NC LP``.
    """
    s = " ".join(name.lower().split())
    if "," in s:
        parts = [p.strip() for p in s.split(",")]
        if len(parts) == 2 and all(parts):
            left_toks = parts[0].split()
            right_toks = parts[1].split()
            if len(left_toks) == 1 and len(right_toks) == 1:
                s = f"{parts[1]} {parts[0]}"
    cleaned = "".join(ch if ch.isalnum() or ch.isspace() else " " for ch in s)
    return " ".join(cleaned.split())


def _match_tokens(name: str) -> list[str]:
    """Significant tokens for soft match (strip punctuation noise)."""
    folded = name_fold(name)
    cleaned = "".join(ch if ch.isalnum() or ch.isspace() else " " for ch in folded)
    return [tok for tok in cleaned.split() if len(tok) >= 3]


def _client_choice_score(spoken: str, display: str) -> float:
    """Higher is closer. Used for MCQ top-N client choices."""
    folded_spoken = name_fold(spoken)
    folded = name_fold(display)
    if not folded_spoken or not folded:
        return 0.0
    if folded_spoken == folded:
        return 100.0
    score = difflib.SequenceMatcher(None, folded_spoken, folded).ratio() * 50.0
    if folded_spoken in folded or folded in folded_spoken:
        score += 20.0
    spoken_toks = set(_match_tokens(spoken))
    display_toks = set(_match_tokens(display))
    if spoken_toks and display_toks:
        overlap = len(spoken_toks & display_toks) / len(spoken_toks)
        score += overlap * 30.0
    return score


def top_client_choices(
    spoken: str,
    display_names: list[str],
    *,
    limit: int = 3,
    prefer: str | None = None,
) -> list[str]:
    """Up to ``limit`` closest roster names for multiple-choice confirm."""
    if limit <= 0:
        return []
    out: list[str] = []
    seen: set[str] = set()
    if prefer:
        for display in display_names:
            if display.casefold() == prefer.casefold() or display == prefer:
                out.append(display)
                seen.add(display.casefold())
                break
    scored: list[tuple[float, str]] = []
    for display in display_names:
        key = display.casefold()
        if key in seen or not display.strip():
            continue
        scored.append((_client_choice_score(spoken, display), display))
    scored.sort(key=lambda item: (-item[0], item[1].casefold()))
    for score, display in scored:
        if score <= 0 and not out:
            continue
        if display.casefold() in seen:
            continue
        out.append(display)
        seen.add(display.casefold())
        if len(out) >= limit:
            break
    return out[:limit]


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


def _levenshtein(a: str, b: str) -> int:
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        cur = [i]
        for j, cb in enumerate(b, start=1):
            ins = cur[j - 1] + 1
            delete = prev[j] + 1
            sub = prev[j - 1] + (0 if ca == cb else 1)
            cur.append(min(ins, delete, sub))
        prev = cur
    return prev[-1]


def _person_name_parts(folded: str) -> tuple[str, str] | None:
    """Return (first, last) for a two-token folded person name, else None."""
    parts = folded.split()
    if len(parts) != 2:
        return None
    return parts[0], parts[1]


def _first_name_typo_ok(spoken_first: str, roster_first: str) -> bool:
    dist = _levenshtein(spoken_first, roster_first)
    if dist <= 1:
        return True
    if dist <= 2 and min(len(spoken_first), len(roster_first)) >= 5:
        return True
    return False


NEAR_MATCH_RATIO = 0.88


def near_unique_match(spoken: str, display_names: list[str]) -> str | None:
    """Unique typo / near-miss against the roster (confirm before write).

    Prefer same last name + close first name (Terry/Terri). Else whole-string
    similarity when exactly one candidate clears the bar.
    """
    folded_spoken = name_fold(spoken)
    if not folded_spoken:
        return None
    spoken_person = _person_name_parts(folded_spoken)

    person_hits: list[str] = []
    seen: set[str] = set()
    if spoken_person is not None:
        spoken_first, spoken_last = spoken_person
        for display in display_names:
            roster_person = _person_name_parts(name_fold(display))
            if roster_person is None:
                continue
            roster_first, roster_last = roster_person
            if roster_last != spoken_last:
                continue
            if not _first_name_typo_ok(spoken_first, roster_first):
                continue
            key = display.casefold()
            if key in seen:
                continue
            seen.add(key)
            person_hits.append(display)
        if len(person_hits) == 1:
            return person_hits[0]
        if len(person_hits) > 1:
            return None

    scored: list[tuple[float, str]] = []
    for display in display_names:
        folded = name_fold(display)
        if not folded:
            continue
        ratio = difflib.SequenceMatcher(None, folded_spoken, folded).ratio()
        if ratio >= NEAR_MATCH_RATIO:
            scored.append((ratio, display))
    if not scored:
        return None
    scored.sort(key=lambda item: (-item[0], item[1].casefold()))
    best_ratio, best_name = scored[0]
    # Unique best: no other candidate within a tiny epsilon of the top score.
    rivals = [name for ratio, name in scored[1:] if abs(ratio - best_ratio) < 0.02]
    if rivals:
        return None
    return best_name


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


def classify_client_name(name: str, names: list[str]) -> dict[str, Any]:
    """Classify a spoken name against an already-loaded display-name list.

    kind:
      - exact / fold — safe to resolve without asking
      - soft — unique nickname/token hit; ask before writing
      - none — no hit
    """
    target = name.strip()
    if not target:
        return {"kind": "none", "display_name": None, "spoken": ""}
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
    near = near_unique_match(target, names)
    if near:
        return {"kind": "soft", "display_name": near, "spoken": target}
    return {"kind": "none", "display_name": None, "spoken": target}


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
    clients = list_clients_remote(environ=environ, office=office, db_path=db_path)
    names = [row["display_name"] for row in clients]
    return classify_client_name(name, names)


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


def get_employees(
    environ: dict[str, str] | None = None,
    db_path: str | Path | None = None,
) -> list[dict[str, Any]]:
    """Read-only GET of the firm employees table (never written by Timmy)."""
    from .supabase_config import employees_table

    table = employees_table(db_path=db_path, environ=environ)
    return _fetch_table_rows(table, environ=environ)


def _employee_active(row: dict[str, Any]) -> bool:
    active = row.get("active")
    if active is None:
        return True
    if isinstance(active, bool):
        return active
    return str(active).strip().lower() in {"1", "true", "yes", "t"}


def slim_employee(row: dict[str, Any]) -> dict[str, Any] | None:
    staff = (row.get("staff_name") or "").strip()
    if not staff:
        return None
    office = (row.get("office") or "").strip().upper() or None
    return {
        "staff_name": staff,
        "office": office,
        "first_name": (row.get("first_name") or "").strip() or None,
        "last_name": (row.get("last_name") or "").strip() or None,
        "active": _employee_active(row),
    }


def list_employees_remote(
    environ: dict[str, str] | None = None,
    db_path: str | Path | None = None,
    query: str | None = None,
    *,
    active_only: bool = True,
) -> list[dict[str, Any]]:
    """Live read-only employee list. Optional query filters like list_clients."""
    try:
        rows = get_employees(environ=environ, db_path=db_path)
    except ValueError as exc:
        msg = str(exc).strip() or exc.__class__.__name__
        raise ValueError(f"employee list unavailable: {msg}") from None
    out: list[dict[str, Any]] = []
    for row in rows:
        slim = slim_employee(row)
        if not slim:
            continue
        if active_only and not slim["active"]:
            continue
        out.append(slim)
    needle = (query or "").strip()
    if needle:
        tokens = _match_tokens(needle)
        filtered: list[dict[str, Any]] = []
        for slim in out:
            name = slim["staff_name"]
            if needle.casefold() in name.casefold() or name_fold(needle) == name_fold(name):
                filtered.append(slim)
                continue
            if tokens:
                name_toks = set(_match_tokens(name))
                if name_toks and all(tok in name_toks for tok in tokens):
                    filtered.append(slim)
        out = filtered
    out.sort(key=lambda row: row["staff_name"].casefold())
    return out


def classify_employee_remote(
    name: str,
    *,
    environ: dict[str, str] | None = None,
    db_path: str | Path | None = None,
    office_hint: str | None = None,
) -> dict[str, Any]:
    """Classify a spoken staff name against Supabase employees (read-only).

    kind: exact | fold | soft | ambiguous | none
    """
    target = (name or "").strip()
    if not target:
        return {
            "kind": "none",
            "staff_name": None,
            "office": None,
            "spoken": "",
            "choices": [],
        }
    employees = list_employees_remote(environ=environ, db_path=db_path)
    hint = (office_hint or "").strip().upper()

    def _hit(row: dict[str, Any], kind: str) -> dict[str, Any]:
        return {
            "kind": kind,
            "staff_name": row["staff_name"],
            "office": row.get("office"),
            "spoken": target,
            "choices": [],
        }

    def _ambiguous(rows: list[dict[str, Any]]) -> dict[str, Any]:
        choices = []
        for row in rows:
            office = (row.get("office") or "").strip().upper() or "?"
            choices.append(
                {
                    "staff_name": row["staff_name"],
                    "office": office if office in {"GCD", "MH"} else None,
                    "label": f'{row["staff_name"]} ({office})',
                }
            )
        return {
            "kind": "ambiguous",
            "staff_name": None,
            "office": None,
            "spoken": target,
            "choices": choices,
        }

    lowered = target.casefold()
    exact_hits = [row for row in employees if row["staff_name"].casefold() == lowered]
    if hint in {"GCD", "MH"} and exact_hits:
        narrowed = [row for row in exact_hits if (row.get("office") or "").upper() == hint]
        if len(narrowed) == 1:
            return _hit(narrowed[0], "exact")
    if len(exact_hits) > 1:
        return _ambiguous(exact_hits)
    if len(exact_hits) == 1:
        return _hit(exact_hits[0], "exact")

    folded_target = name_fold(target)
    fold_hits = [
        row for row in employees if name_fold(row["staff_name"]) == folded_target
    ]
    if hint in {"GCD", "MH"} and fold_hits:
        narrowed = [row for row in fold_hits if (row.get("office") or "").upper() == hint]
        if len(narrowed) == 1:
            return _hit(narrowed[0], "fold")
    if len(fold_hits) > 1:
        return _ambiguous(fold_hits)
    if len(fold_hits) == 1:
        return _hit(fold_hits[0], "fold")

    names = [row["staff_name"] for row in employees]
    by_name: dict[str, list[dict[str, Any]]] = {}
    for row in employees:
        by_name.setdefault(row["staff_name"].casefold(), []).append(row)

    soft = soft_unique_match(target, names)
    if soft:
        hits = by_name.get(soft.casefold(), [])
        if hint in {"GCD", "MH"} and hits:
            narrowed = [row for row in hits if (row.get("office") or "").upper() == hint]
            if len(narrowed) == 1:
                return _hit(narrowed[0], "soft")
        if len(hits) > 1:
            return _ambiguous(hits)
        if len(hits) == 1:
            return _hit(hits[0], "soft")

    return {
        "kind": "none",
        "staff_name": None,
        "office": None,
        "spoken": target,
        "choices": [],
    }
