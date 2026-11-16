"""
API tests for network-wide monthly performance history.

Day 24 exposes network-level monthly sales and target performance with
optional inclusive start and end month bounds.
"""

import os

import pandas as pd
import pytest
from fastapi.testclient import TestClient

import api
from api import app
from db import (
    InvalidMonthError,
    get_engine,
    get_network_performance_history,
    to_records,
)

client = TestClient(
    app,
    raise_server_exceptions=False,
)

EXPECTED_FIELDS = [
    "month",
    "dealer_count",
    "units_sold",
    "target_units",
    "achievement_pct",
]


def test_network_performance_returns_complete_history():
    response = client.get("/performance/trend")

    assert response.status_code == 200

    data = response.json()

    assert len(data) == 24
    assert list(data[0]) == EXPECTED_FIELDS
    assert data[0]["month"] == "2024-10"
    assert data[-1]["month"] == "2026-09"
    assert [row["month"] for row in data] == sorted(row["month"] for row in data)
    assert all(row["dealer_count"] == 40 for row in data)


def test_network_performance_matches_db_layer():
    response = client.get("/performance/trend")

    assert response.status_code == 200
    assert response.json() == to_records(get_network_performance_history())


@pytest.mark.parametrize(
    ("params", "expected_months"),
    [
        ({"start": "2026-08"}, ["2026-08", "2026-09"]),
        ({"end": "2024-11"}, ["2024-10", "2024-11"]),
        (
            {"start": "2025-03", "end": "2025-05"},
            ["2025-03", "2025-04", "2025-05"],
        ),
        (
            {"start": "2025-03", "end": "2025-03"},
            ["2025-03"],
        ),
    ],
)
def test_network_range_filters_are_inclusive(params, expected_months):
    response = client.get(
        "/performance/trend",
        params=params,
    )

    assert response.status_code == 200
    assert [row["month"] for row in response.json()] == expected_months


@pytest.mark.parametrize(
    "params",
    [
        {"start": "2030-01"},
        {"end": "2020-12"},
        {"start": "2020-01", "end": "2020-12"},
    ],
)
def test_valid_empty_window_returns_empty(params):
    response = client.get(
        "/performance/trend",
        params=params,
    )

    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.parametrize(
    "start",
    [
        "2026-00",
        "2026-13",
        "2026-1",
        "26-01",
        "abcd-ef",
        "٢٠٢٦-٠١",
        "2026-03\n",
    ],
)
def test_invalid_start_returns_422_from_query_validation(start):
    response = client.get(
        "/performance/trend",
        params={"start": start},
    )

    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == ["query", "start"]


@pytest.mark.parametrize(
    "end",
    [
        "2026-00",
        "2026-13",
        "2026-1",
        "26-01",
        "abcd-ef",
        "٢٠٢٦-٠١",
        "2026-03\n",
    ],
)
def test_invalid_end_returns_422_from_query_validation(end):
    response = client.get(
        "/performance/trend",
        params={"end": end},
    )

    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == ["query", "end"]


@pytest.mark.parametrize(
    "params",
    [
        {"start": "2026-09", "end": "2026-08"},
        {"start": "2025-12", "end": "2025-01"},
    ],
)
def test_reversed_range_returns_422(params):
    response = client.get(
        "/performance/trend",
        params=params,
    )

    assert response.status_code == 422
    assert response.json() == {"detail": "start month must not be after end month"}


def test_invalid_month_error_from_database_layer_returns_422(monkeypatch):
    def raise_invalid_month(start=None, end=None):
        raise InvalidMonthError("start month must use YYYY-MM format")

    monkeypatch.setattr(
        api,
        "get_network_performance_history",
        raise_invalid_month,
    )

    response = client.get(
        "/performance/trend",
        params={"start": "2026-01"},
    )

    assert response.status_code == 422
    assert response.json() == {"detail": "start month must use YYYY-MM format"}


def test_missing_database_url_returns_500(monkeypatch):
    database_url = os.environ["DATABASE_URL"]

    get_engine.cache_clear()
    monkeypatch.delenv("DATABASE_URL")

    try:
        response = client.get("/performance/trend")
    finally:
        get_engine.cache_clear()

    assert response.status_code == 500
    assert database_url not in response.text


def test_invalid_response_from_data_layer_returns_500(monkeypatch):
    invalid = pd.DataFrame(
        [
            {
                "month": "2026-01",
                "dealer_count": "forty",
                "units_sold": 100,
                "target_units": 120,
                "achievement_pct": 83.33,
            }
        ]
    )

    monkeypatch.setattr(
        api,
        "get_network_performance_history",
        lambda start=None, end=None: invalid,
    )

    response = client.get("/performance/trend")

    assert response.status_code == 500


def test_existing_monthly_performance_route_still_works():
    response = client.get(
        "/performance",
        params={"month": "2026-09"},
    )

    assert response.status_code == 200
    assert len(response.json()) == 40


def test_missing_target_serializes_as_null(monkeypatch):
    nullable = pd.DataFrame(
        [
            {
                "month": "2026-01",
                "dealer_count": 40,
                "units_sold": 1000,
                "target_units": float("nan"),
                "achievement_pct": float("nan"),
            }
        ]
    )

    monkeypatch.setattr(
        api,
        "get_network_performance_history",
        lambda start=None, end=None: nullable,
    )

    response = client.get("/performance/trend")

    assert response.status_code == 200

    assert response.json() == [
        {
            "month": "2026-01",
            "dealer_count": 40,
            "units_sold": 1000,
            "target_units": None,
            "achievement_pct": None,
        }
    ]


def test_counts_are_json_integers_and_percentage_is_float():
    response = client.get(
        "/performance/trend",
        params={
            "start": "2026-01",
            "end": "2026-01",
        },
    )

    assert response.status_code == 200

    row = response.json()[0]

    assert type(row["dealer_count"]) is int
    assert type(row["units_sold"]) is int
    assert type(row["target_units"]) is int
    assert type(row["achievement_pct"]) is float
