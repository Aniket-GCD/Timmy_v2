"""Unit tests for QBO company env parsing (no network)."""

from __future__ import annotations

import json
import pytest

from timeassist.qbo_clients import parse_companies


def test_parse_companies_ok():
    env = {
        "QBO_COMPANIES": json.dumps(
            [{"office": "gcd", "realm_id": "123", "refresh_token": "rt"}]
        )
    }
    rows = parse_companies(env)
    assert rows == [{"office": "GCD", "realm_id": "123", "refresh_token": "rt"}]


def test_parse_companies_missing():
    with pytest.raises(ValueError, match="QBO_COMPANIES"):
        parse_companies({})
