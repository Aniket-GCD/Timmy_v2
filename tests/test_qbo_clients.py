"""Unit tests for QBO token load/save and clients sync (no network)."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from timeassist import qbo_clients as qc


ENV = {
    "SUPABASE_URL": "https://example.supabase.co",
    "SUPABASE_KEY": "service-test-key",
    "QBO_CLIENT_ID": "cid",
    "QBO_CLIENT_SECRET": "csecret",
}


def test_parse_companies_ok():
    env = {
        "QBO_COMPANIES": json.dumps(
            [{"office": "gcd", "realm_id": "123", "refresh_token": "rt"}]
        )
    }
    rows = qc.parse_companies(env)
    assert rows == [{"office": "GCD", "realm_id": "123", "refresh_token": "rt"}]


def test_parse_companies_missing():
    with pytest.raises(ValueError, match="qbo_tokens|QBO_COMPANIES"):
        qc.parse_companies({})


def test_load_companies_from_qbo_tokens_ok():
    rows = [
        {"office": "gcd", "realm_id": "r1", "refresh_token": "rt1", "updated_at": "2020-01-01T00:00:00Z"},
        {"office": "MH", "realm_id": "r2", "refresh_token": "rt2", "updated_at": None},
    ]
    with patch.object(qc, "_fetch_table_rows", return_value=rows):
        out = qc.load_companies_from_qbo_tokens(ENV)
    assert [c["office"] for c in out] == ["GCD", "MH"]
    assert out[0]["refresh_token"] == "rt1"


def test_load_companies_missing_office():
    rows = [{"office": "GCD", "realm_id": "r1", "refresh_token": "rt1"}]
    with patch.object(qc, "_fetch_table_rows", return_value=rows):
        with pytest.raises(ValueError, match="MH"):
            qc.load_companies_from_qbo_tokens(ENV)


def test_recently_refreshed():
    now = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
    fresh = (now - timedelta(minutes=2)).isoformat()
    stale = (now - timedelta(minutes=10)).isoformat()
    assert qc.recently_refreshed(fresh, now=now) is True
    assert qc.recently_refreshed(stale, now=now) is False
    assert qc.recently_refreshed(None, now=now) is False


def test_refresh_access_token_returns_pair():
    payload = json.dumps(
        {"access_token": "at", "refresh_token": "rt-new"}
    ).encode()

    class Resp:
        def read(self):
            return payload

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    with patch.object(qc, "urlopen", return_value=Resp()):
        access, refresh = qc.refresh_access_token(
            client_id="a", client_secret="b", refresh_token="rt-old"
        )
    assert access == "at"
    assert refresh == "rt-new"


def test_refresh_keeps_old_refresh_when_omitted():
    payload = json.dumps({"access_token": "at"}).encode()

    class Resp:
        def read(self):
            return payload

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    with patch.object(qc, "urlopen", return_value=Resp()):
        access, refresh = qc.refresh_access_token(
            client_id="a", client_secret="b", refresh_token="rt-old"
        )
    assert access == "at"
    assert refresh == "rt-old"


def test_save_refresh_token_patch():
    with patch.object(qc, "request_json") as req:
        qc.save_refresh_token("gcd", "rt-new", environ=ENV)
    assert req.call_count == 1
    args, kwargs = req.call_args
    assert args[0] == "PATCH"
    assert args[1] == "qbo_tokens"
    assert kwargs["body"]["refresh_token"] == "rt-new"
    assert "updated_at" in kwargs["body"]


def test_upsert_insert_new_qbo_id():
    action = qc.upsert_client_row(
        name="Acme",
        office="GCD",
        qbo_id="99",
        active=True,
        existing_by_qbo={},
        existing_by_name_office={},
        dry_run=True,
    )
    assert action == "insert"


def test_upsert_update_same_qbo_changed_name():
    existing = {"id": 7, "qbo_customer_id": "99", "name": "Old", "office": "GCD"}
    with patch.object(qc, "request_json") as req:
        action = qc.upsert_client_row(
            name="New Name",
            office="GCD",
            qbo_id="99",
            active=True,
            existing_by_qbo={("GCD", "99"): existing},
            existing_by_name_office={},
            dry_run=False,
        )
    assert action == "update"
    assert req.call_args.kwargs["body"]["name"] == "New Name"


def test_upsert_unchanged_still_update():
    """Existing hit always counts as update (no field-diff skip)."""
    existing = {
        "id": 1,
        "qbo_customer_id": "1",
        "name": "Same",
        "office": "GCD",
        "active": True,
    }
    action = qc.upsert_client_row(
        name="Same",
        office="GCD",
        qbo_id="1",
        active=True,
        existing_by_qbo={("GCD", "1"): existing},
        existing_by_name_office={},
        dry_run=True,
    )
    assert action == "update"


def test_upsert_inactive_flag():
    existing = {"id": 3, "qbo_customer_id": "5", "name": "X", "office": "MH"}
    with patch.object(qc, "request_json") as req:
        qc.upsert_client_row(
            name="X",
            office="MH",
            qbo_id="5",
            active=False,
            existing_by_qbo={("MH", "5"): existing},
            existing_by_name_office={},
            dry_run=False,
        )
    assert req.call_args.kwargs["body"]["active"] is False


def test_duplicate_names_different_offices():
    by_name = {("acme", "GCD"): {"id": 1, "name": "Acme", "office": "GCD"}}
    # MH Acme is a different row (insert) even if display name matches GCD
    action = qc.upsert_client_row(
        name="Acme",
        office="MH",
        qbo_id="mh-1",
        active=True,
        existing_by_qbo={},
        existing_by_name_office=by_name,
        dry_run=True,
    )
    assert action == "insert"


def test_same_qbo_id_different_offices_inserts():
    existing = {"id": 1, "qbo_customer_id": "5", "name": "MH Co", "office": "MH"}
    action = qc.upsert_client_row(
        name="GCD Co",
        office="GCD",
        qbo_id="5",
        active=True,
        existing_by_qbo={("MH", "5"): existing},
        existing_by_name_office={("mh co", "MH"): existing},
        dry_run=True,
    )
    assert action == "insert"


def test_sync_office_skips_recent_refresh():
    fresh = datetime.now(timezone.utc).isoformat()
    with patch.object(qc, "refresh_access_token") as refresh:
        out = qc.sync_office_customers(
            office="GCD",
            realm_id="r1",
            refresh_token="rt",
            client_id="c",
            client_secret="s",
            updated_at=fresh,
        )
    refresh.assert_not_called()
    assert out["skipped_recent_refresh"] == 1


def test_sync_office_dry_run_saves_token_not_clients():
    clients_calls: list[tuple] = []

    def fake_request(method, table, **kwargs):
        clients_calls.append((method, table, kwargs.get("body")))
        return None

    with (
        patch.object(qc, "refresh_access_token", return_value=("access", "rt-rotated")),
        patch.object(qc, "save_refresh_token") as save,
        patch.object(qc, "fetch_customers", return_value=[
            {"Id": "10", "DisplayName": "NewCo", "Active": True},
            {"Id": "11", "DisplayName": "OldCo", "Active": False},
        ]),
        patch.object(qc, "_fetch_table_rows", return_value=[
            {"id": 2, "qbo_customer_id": "11", "name": "OldCo", "office": "GCD"},
        ]),
        patch.object(qc, "request_json", side_effect=fake_request),
    ):
        counts = qc.sync_office_customers(
            office="GCD",
            realm_id="r1",
            refresh_token="rt-old",
            client_id="c",
            client_secret="s",
            dry_run=True,
            environ=ENV,
            updated_at="2000-01-01T00:00:00Z",
        )

    save.assert_called_once()
    assert save.call_args[0][0] == "GCD"
    assert save.call_args[0][1] == "rt-rotated"
    # dry-run: upsert_client_row must not write the roster table
    assert not any(t in {"clients", qc.CLIENTS_TABLE} for _, t, _ in clients_calls)
    assert counts["insert"] == 1
    assert counts["update"] == 1


def test_sync_all_one_office_refresh_fail_continues():
    companies = [
        {
            "office": "GCD",
            "realm_id": "r1",
            "refresh_token": "bad",
            "updated_at": "2000-01-01T00:00:00Z",
        },
        {
            "office": "MH",
            "realm_id": "r2",
            "refresh_token": "ok",
            "updated_at": "2000-01-01T00:00:00Z",
        },
    ]

    def sync_side(**kwargs):
        if kwargs["office"] == "GCD":
            raise ValueError("QBO token refresh failed HTTP 400: invalid_grant")
        return {
            "office": "MH",
            "realm_id": "r2",
            "insert": 1,
            "update": 0,
            "skip": 0,
        }

    with (
        patch.object(qc, "load_companies_from_qbo_tokens", return_value=companies),
        patch.object(qc, "sync_office_customers", side_effect=lambda **kw: sync_side(**kw)),
        patch("timeassist.clients_seed.ensure_unassigned", return_value={
            "unassigned_inserted": 0,
            "unassigned_skipped": 2,
        }),
    ):
        with pytest.raises(RuntimeError, match="One or more offices failed"):
            qc.sync_all_companies(dry_run=True, environ=ENV)
