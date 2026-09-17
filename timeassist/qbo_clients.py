"""Read-only QuickBooks Online Customer sync into Supabase ``clients``.

Never writes to QBO. Upserts by ``qbo_customer_id`` when present, else
``(name, office)``.

Company credentials come from Supabase ``qbo_tokens`` (filled by
``qbo_oauth_setup.py``). Rotated refresh tokens are written back immediately
after every Intuit refresh — including ``--dry-run`` (only ``clients`` writes
are skipped on dry-run).

Env:
  QBO_CLIENT_ID
  QBO_CLIENT_SECRET
  SUPABASE_URL + SUPABASE_SERVICE_ROLE_KEY (or SUPABASE_KEY)
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.parse
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.request import Request, urlopen

from timeassist.supabase_ref import _fetch_table_rows, request_json

TOKEN_URL = "https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer"
QBO_BASE = "https://quickbooks.api.intuit.com/v3/company"
CLIENTS_TABLE = "clients_qbo_preview"
TOKENS_TABLE = "qbo_tokens"
USER_AGENT = "curl/8.5.0"
REQUIRED_OFFICES = frozenset({"GCD", "MH"})
RECENT_REFRESH_SECONDS = 5 * 60

REFRESH_FAIL_HINT = (
    "Re-run: python qbo_oauth_setup.py for this office "
    "(revoke, password/security change, or 100-day connection expiry)."
)


def parse_companies(environ: dict[str, str] | None = None) -> list[dict[str, str]]:
    """Deprecated: prefer ``load_companies_from_qbo_tokens``. Kept for legacy tests."""
    env = os.environ if environ is None else environ
    raw = (env.get("QBO_COMPANIES") or "").strip()
    if not raw:
        raise ValueError(
            "QBO_COMPANIES is deprecated. Store tokens in Supabase qbo_tokens "
            "(see docs/qbo-clients-sync.md) or set a legacy JSON array."
        )
    data = json.loads(raw)
    if not isinstance(data, list) or not data:
        raise ValueError("QBO_COMPANIES must be a non-empty JSON array")
    out: list[dict[str, str]] = []
    for item in data:
        office = str(item.get("office") or "").strip().upper()
        realm = str(item.get("realm_id") or "").strip()
        refresh = str(item.get("refresh_token") or "").strip()
        if office not in REQUIRED_OFFICES or not realm or not refresh:
            raise ValueError("Each QBO company needs office (GCD|MH), realm_id, refresh_token")
        out.append({"office": office, "realm_id": realm, "refresh_token": refresh})
    return out


def _parse_updated_at(raw: Any) -> datetime | None:
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def recently_refreshed(updated_at: Any, *, now: datetime | None = None) -> bool:
    """True if token row was updated within the concurrency guard window."""
    dt = _parse_updated_at(updated_at)
    if dt is None:
        return False
    clock = now or datetime.now(timezone.utc)
    return clock - dt < timedelta(seconds=RECENT_REFRESH_SECONDS)


def load_companies_from_qbo_tokens(
    environ: dict[str, str] | None = None,
    *,
    require_offices: frozenset[str] | None = REQUIRED_OFFICES,
) -> list[dict[str, Any]]:
    """Load GCD/MH rows from ``qbo_tokens``. Raises if required offices missing."""
    rows = _fetch_table_rows(TOKENS_TABLE, environ=environ)
    by_office: dict[str, dict[str, Any]] = {}
    for row in rows:
        office = str(row.get("office") or "").strip().upper()
        realm = str(row.get("realm_id") or "").strip()
        refresh = str(row.get("refresh_token") or "").strip()
        if office not in REQUIRED_OFFICES or not realm or not refresh:
            continue
        by_office[office] = {
            "office": office,
            "realm_id": realm,
            "refresh_token": refresh,
            "updated_at": row.get("updated_at"),
        }
    needed = require_offices if require_offices is not None else REQUIRED_OFFICES
    missing = sorted(needed - set(by_office))
    if missing:
        raise ValueError(
            f"qbo_tokens missing office(s): {', '.join(missing)}. "
            "Run python qbo_oauth_setup.py for each (see docs/qbo-clients-sync.md)."
        )
    return [by_office[o] for o in sorted(by_office) if o in needed]


def save_refresh_token(
    office: str,
    refresh_token: str,
    *,
    environ: dict[str, str] | None = None,
    realm_id: str | None = None,
) -> None:
    """Persist rotated refresh token + ``updated_at`` (always, including dry-run)."""
    office_u = office.strip().upper()
    body: dict[str, Any] = {
        "office": office_u,
        "refresh_token": refresh_token.strip(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    if realm_id:
        body["realm_id"] = realm_id
        request_json(
            "POST",
            TOKENS_TABLE,
            body=body,
            environ=environ,
            prefer="resolution=merge-duplicates,return=minimal",
        )
        return
    request_json(
        "PATCH",
        TOKENS_TABLE,
        body={"refresh_token": body["refresh_token"], "updated_at": body["updated_at"]},
        query={"office": f"eq.{office_u}"},
        environ=environ,
        prefer="return=minimal",
    )


def refresh_access_token(
    *,
    client_id: str,
    client_secret: str,
    refresh_token: str,
) -> tuple[str, str]:
    """Return ``(access_token, refresh_token)``. Keep old refresh if Intuit omits a new one."""
    import base64

    basic = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
    body = urllib.parse.urlencode(
        {"grant_type": "refresh_token", "refresh_token": refresh_token}
    ).encode()
    req = Request(
        TOKEN_URL,
        data=body,
        headers={
            "Authorization": f"Basic {basic}",
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
            "User-Agent": USER_AGENT,
        },
        method="POST",
    )
    try:
        with urlopen(req, timeout=60) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:240]
        raise ValueError(f"QBO token refresh failed HTTP {exc.code}: {detail}") from None
    token = (payload.get("access_token") or "").strip()
    if not token:
        raise ValueError("QBO token refresh returned no access_token")
    new_refresh = (payload.get("refresh_token") or "").strip() or refresh_token
    return token, new_refresh


def fetch_customers(realm_id: str, access_token: str) -> list[dict[str, Any]]:
    """Query active + inactive customers (paged via startPosition)."""
    all_rows: list[dict[str, Any]] = []
    start = 1
    page_size = 100
    while True:
        query = f"select * from Customer startposition {start} maxresults {page_size}"
        url = (
            f"{QBO_BASE}/{urllib.parse.quote(realm_id)}/query?"
            + urllib.parse.urlencode({"query": query, "minorversion": "65"})
        )
        req = Request(
            url,
            headers={
                "Authorization": f"Bearer {access_token}",
                "Accept": "application/json",
                "User-Agent": USER_AGENT,
            },
            method="GET",
        )
        try:
            with urlopen(req, timeout=60) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:240]
            raise ValueError(f"QBO query failed HTTP {exc.code}: {detail}") from None
        qr = payload.get("QueryResponse") or {}
        customers = qr.get("Customer") or []
        if not isinstance(customers, list):
            customers = [customers] if customers else []
        all_rows.extend(customers)
        if len(customers) < page_size:
            break
        start += page_size
    return all_rows


def _customer_display_name(row: dict[str, Any]) -> str:
    return str(
        row.get("DisplayName")
        or row.get("CompanyName")
        or row.get("FullyQualifiedName")
        or ""
    ).strip()


def upsert_client_row(
    *,
    name: str,
    office: str,
    qbo_id: str,
    active: bool,
    existing_by_qbo: dict[str, dict],
    existing_by_name_office: dict[tuple[str, str], dict],
    dry_run: bool,
) -> str:
    """Upsert one client. Existing hit → always ``update`` (even if fields match)."""
    body = {
        "name": name,
        "office": office,
        "qbo_customer_id": qbo_id,
        "active": active,
    }
    hit = existing_by_qbo.get(qbo_id) or existing_by_name_office.get((name.casefold(), office))
    if hit and hit.get("id") is not None:
        if dry_run:
            return "update"
        request_json(
            "PATCH",
            CLIENTS_TABLE,
            body=body,
            query={"id": f"eq.{hit['id']}"},
            prefer="return=minimal",
        )
        return "update"
    if dry_run:
        return "insert"
    request_json("POST", CLIENTS_TABLE, body=body, prefer="return=minimal")
    return "insert"


def sync_office_customers(
    *,
    office: str,
    realm_id: str,
    refresh_token: str,
    client_id: str,
    client_secret: str,
    dry_run: bool = False,
    environ: dict[str, str] | None = None,
    updated_at: Any = None,
    skip_recent: bool = True,
) -> dict[str, Any]:
    if skip_recent and recently_refreshed(updated_at):
        print(
            f"[qbo] {office}: skipped_recent_refresh "
            f"(updated_at within {RECENT_REFRESH_SECONDS // 60} min)",
            file=sys.stderr,
        )
        return {
            "office": office,
            "realm_id": realm_id,
            "skipped_recent_refresh": 1,
            "insert": 0,
            "update": 0,
            "skip": 0,
        }

    access_token, new_refresh = refresh_access_token(
        client_id=client_id,
        client_secret=client_secret,
        refresh_token=refresh_token,
    )
    # Always persist rotated refresh before any clients work (incl. dry-run).
    save_refresh_token(office, new_refresh, environ=environ, realm_id=realm_id)

    customers = fetch_customers(realm_id, access_token)
    existing = _fetch_table_rows(CLIENTS_TABLE, environ=environ)
    by_qbo: dict[str, dict] = {}
    by_name: dict[tuple[str, str], dict] = {}
    for row in existing:
        qid = str(row.get("qbo_customer_id") or "").strip()
        if qid:
            by_qbo[qid] = row
        name = str(row.get("name") or "").strip()
        off = str(row.get("office") or "").strip().upper()
        if name and off:
            by_name[(name.casefold(), off)] = row

    counts = {"insert": 0, "update": 0, "skip": 0}
    for cust in customers:
        name = _customer_display_name(cust)
        qbo_id = str(cust.get("Id") or "").strip()
        if not name or not qbo_id:
            counts["skip"] += 1
            continue
        active = cust.get("Active", True) is not False
        action = upsert_client_row(
            name=name,
            office=office,
            qbo_id=qbo_id,
            active=active,
            existing_by_qbo=by_qbo,
            existing_by_name_office=by_name,
            dry_run=dry_run,
        )
        counts[action] = counts.get(action, 0) + 1
        if action == "insert":
            by_qbo[qbo_id] = {"qbo_customer_id": qbo_id, "name": name, "office": office}
            by_name[(name.casefold(), office)] = by_qbo[qbo_id]
    return {"office": office, "realm_id": realm_id, **counts}


def sync_all_companies(
    *,
    dry_run: bool = False,
    environ: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    env = os.environ if environ is None else environ
    client_id = (env.get("QBO_CLIENT_ID") or env.get("Client_ID") or "").strip()
    client_secret = (env.get("QBO_CLIENT_SECRET") or env.get("Client_secret") or "").strip()
    if not client_id or not client_secret:
        raise ValueError("Set QBO_CLIENT_ID and QBO_CLIENT_SECRET")

    companies = load_companies_from_qbo_tokens(env)
    results: list[dict[str, Any]] = []
    any_failed = False

    for company in companies:
        office = company["office"]
        try:
            counts = sync_office_customers(
                office=office,
                realm_id=company["realm_id"],
                refresh_token=company["refresh_token"],
                client_id=client_id,
                client_secret=client_secret,
                dry_run=dry_run,
                environ=env,
                updated_at=company.get("updated_at"),
            )
            results.append(counts)
        except Exception as exc:  # noqa: BLE001 — per-office isolation
            any_failed = True
            msg = (
                f"[qbo] REFRESH/SYNC FAILED for office={office}: {exc}\n"
                f"[qbo] {REFRESH_FAIL_HINT}"
            )
            print(msg, file=sys.stderr)
            results.append(
                {
                    "office": office,
                    "realm_id": company.get("realm_id"),
                    "error": str(exc),
                    "reauth_required": True,
                }
            )

    from timeassist.clients_seed import ensure_unassigned

    seed = ensure_unassigned(dry_run=dry_run, environ=env)
    results.append({"seed": "unassigned", **seed})

    if any_failed:
        raise RuntimeError(
            "One or more offices failed QBO sync. "
            "See stderr; re-run qbo_oauth_setup.py for offices with reauth_required."
        )
    return results
