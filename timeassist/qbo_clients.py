"""Read-only QuickBooks Online Customer sync into Supabase ``clients``.

Never writes to QBO. Upserts by ``qbo_customer_id`` when present, else
``(name, office)``.

Env:
  QBO_CLIENT_ID
  QBO_CLIENT_SECRET
  QBO_COMPANIES='[{"office":"GCD","realm_id":"...","refresh_token":"..."}]'
  SUPABASE_URL + SUPABASE_SERVICE_ROLE_KEY (or SUPABASE_KEY)
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
from typing import Any
from urllib.request import Request, urlopen

from timeassist.supabase_ref import _fetch_table_rows, request_json

TOKEN_URL = "https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer"
QBO_BASE = "https://quickbooks.api.intuit.com/v3/company"
CLIENTS_TABLE = "clients"
USER_AGENT = "curl/8.5.0"


def parse_companies(environ: dict[str, str] | None = None) -> list[dict[str, str]]:
    env = os.environ if environ is None else environ
    raw = (env.get("QBO_COMPANIES") or "").strip()
    if not raw:
        raise ValueError(
            "Set QBO_COMPANIES JSON array, e.g. "
            '[{"office":"GCD","realm_id":"...","refresh_token":"..."}]'
        )
    data = json.loads(raw)
    if not isinstance(data, list) or not data:
        raise ValueError("QBO_COMPANIES must be a non-empty JSON array")
    out: list[dict[str, str]] = []
    for item in data:
        office = str(item.get("office") or "").strip().upper()
        realm = str(item.get("realm_id") or "").strip()
        refresh = str(item.get("refresh_token") or "").strip()
        if office not in {"GCD", "MH"} or not realm or not refresh:
            raise ValueError("Each QBO company needs office (GCD|MH), realm_id, refresh_token")
        out.append({"office": office, "realm_id": realm, "refresh_token": refresh})
    return out


def refresh_access_token(
    *,
    client_id: str,
    client_secret: str,
    refresh_token: str,
) -> str:
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
    return token


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
) -> dict[str, int]:
    token = refresh_access_token(
        client_id=client_id,
        client_secret=client_secret,
        refresh_token=refresh_token,
    )
    customers = fetch_customers(realm_id, token)
    existing = _fetch_table_rows(CLIENTS_TABLE)
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
    return counts


def sync_all_companies(*, dry_run: bool = False, environ: dict[str, str] | None = None) -> list[dict[str, Any]]:
    env = os.environ if environ is None else environ
    client_id = (env.get("QBO_CLIENT_ID") or "").strip()
    client_secret = (env.get("QBO_CLIENT_SECRET") or "").strip()
    if not client_id or not client_secret:
        raise ValueError("Set QBO_CLIENT_ID and QBO_CLIENT_SECRET")
    results: list[dict[str, Any]] = []
    for company in parse_companies(env):
        counts = sync_office_customers(
            office=company["office"],
            realm_id=company["realm_id"],
            refresh_token=company["refresh_token"],
            client_id=client_id,
            client_secret=client_secret,
            dry_run=dry_run,
        )
        results.append({"office": company["office"], "realm_id": company["realm_id"], **counts})
    return results
