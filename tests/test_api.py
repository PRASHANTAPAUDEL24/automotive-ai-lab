# Program: tests/test_api.py
# Day 11: pytest tests for FastAPI endpoints
# Created on: 2026-11-01
# Author: Prashanta Paudel
# Purpose: Validate API responses, filtering, error handling,
# and JSON-safe conversion.

import pandas as pd
from fastapi.testclient import TestClient

from api import app, to_records
from db import get_engine

client = TestClient(app)


def test_health():
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_dealers_returns_all_40():
    response = client.get("/dealers")

    assert response.status_code == 200
    assert len(response.json()) == 40


def test_dealers_region_filter():
    response = client.get(
        "/dealers",
        params={"region": "West"},
    )

    assert response.status_code == 200
    assert len(response.json()) == 8


def test_dealers_combined_risk():
    response = client.get(
        "/dealers",
        params={"risk": "combined_risk"},
    )

    data = response.json()

    assert response.status_code == 200
    assert len(data) == 1

    dealer = data[0]

    assert dealer["dealer_id"] == 111
    assert isinstance(dealer["dealer_id"], int)
    assert isinstance(dealer["achievement_pct"], (int, float))
    assert dealer["combined_risk"] is True


def test_dealers_west_early_overstock_watch():
    response = client.get(
        "/dealers",
        params={
            "region": "West",
            "risk": "early_overstock_watch",
        },
    )

    assert response.status_code == 200

    dealer_ids = {dealer["dealer_id"] for dealer in response.json()}

    assert dealer_ids == {105, 130}


def test_invalid_risk_returns_400():
    response = client.get(
        "/dealers",
        params={"risk": "dealer_name"},
    )

    assert response.status_code == 400
    assert response.json() == {"detail": "Invalid risk filter: dealer_name"}


def test_unknown_region_returns_empty_list():
    response = client.get(
        "/dealers",
        params={"region": "Atlantis"},
    )

    assert response.status_code == 200
    assert response.json() == []


def test_injection_string_returns_empty_list():
    response = client.get(
        "/dealers",
        params={"region": "West' OR '1'='1"},
    )

    assert response.status_code == 200
    assert response.json() == []


def test_to_records_converts_nan_to_none():
    result = to_records(
        pd.DataFrame(
            {
                "x": [1.5, float("nan")],
            }
        )
    )

    assert result == [
        {"x": 1.5},
        {"x": None},
    ]


def test_missing_database_url_returns_500(monkeypatch):
    get_engine.cache_clear()
    monkeypatch.delenv("DATABASE_URL", raising=False)

    test_client = TestClient(
        app,
        raise_server_exceptions=False,
    )

    response = test_client.get("/dealers")

    assert response.status_code == 500
    assert "DATABASE_URL" not in response.text

    get_engine.cache_clear()
