import pandas as pd
import pytest
from fastapi.testclient import TestClient

import db
from api import app

client = TestClient(app, raise_server_exceptions=False)

FULL_RESULT_ROWS = 20
LARGE_LIMITS = [2**31, 99_999_999_999, 2**63 - 1]


@pytest.mark.parametrize("limit", LARGE_LIMITS)
def test_db_large_limit_returns_the_full_global_ranking(limit):
    unbounded = db.get_at_risk_dealers()
    limited = db.get_at_risk_dealers(limit=limit)

    assert len(unbounded) == FULL_RESULT_ROWS
    pd.testing.assert_frame_equal(limited, unbounded)


@pytest.mark.parametrize("limit", LARGE_LIMITS)
def test_api_large_limit_matches_the_unbounded_response(limit):
    unbounded = client.get("/dealers/at-risk")
    limited = client.get("/dealers/at-risk", params={"limit": limit})

    assert unbounded.status_code == 200
    assert limited.status_code == 200
    assert len(limited.json()) == FULL_RESULT_ROWS
    assert limited.json() == unbounded.json()


def test_api_limit_above_bigint_maximum_returns_422_on_limit():
    response = client.get("/dealers/at-risk", params={"limit": 2**63})

    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == ["query", "limit"]


def test_at_risk_query_casts_limit_to_bigint(monkeypatch):
    captured = {}

    def fake_read_sql(query, engine, params=None):
        captured["sql"] = " ".join(str(query).split())
        captured["params"] = params
        return pd.DataFrame()

    monkeypatch.setattr(db.pd, "read_sql", fake_read_sql)

    db.get_at_risk_dealers(limit=2**31)

    assert "LIMIT CAST(:limit AS bigint)" in captured["sql"]
    assert "AS integer" not in captured["sql"]
    assert captured["params"] == {"limit": 2**31}
