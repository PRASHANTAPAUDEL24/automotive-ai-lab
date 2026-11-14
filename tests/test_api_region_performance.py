"""
API tests for regional monthly performance history.

Day 22 exposes region-level monthly sales and target performance with
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
    get_region_performance_history,
    to_records,
)

client = TestClient(
    app,
    raise_server_exceptions=False,
)

REGIONS = [
    "Midwest",
    "Northeast",
    "Southeast",
    "Southwest",
    "West",
]

EXPECTED_FIELDS = [
    "region",
    "month",
    "dealer_count",
    "units_sold",
    "target_units",
    "achievement_pct",
]


def test_region_performance_returns_complete_history():
    response = client.get("/regions/Midwest/performance")

    assert response.status_code == 200

    data = response.json()

    assert len(data) == 24
    assert list(data[0]) == EXPECTED_FIELDS
    assert data[0]["month"] == "2024-10"
    assert data[-1]["month"] == "2026-09"
    assert [row["month"] for row in data] == sorted(row["month"] for row in data)
    assert all(row["region"] == "Midwest" for row in data)
    assert all(row["dealer_count"] == 8 for row in data)


@pytest.mark.parametrize("region", REGIONS)
def test_every_region_returns_24_months(region):
    response = client.get(f"/regions/{region}/performance")

    assert response.status_code == 200
    assert len(response.json()) == 24


def test_region_performance_matches_db_layer():
    response = client.get("/regions/Midwest/performance")

    expected = to_records(get_region_performance_history("Midwest"))

    assert response.status_code == 200
    assert response.json() == expected


@pytest.mark.parametrize(
    ("params", "expected_months"),
    [
        (
            {"start": "2026-01"},
            [
                "2026-01",
                "2026-02",
                "2026-03",
                "2026-04",
                "2026-05",
                "2026-06",
                "2026-07",
                "2026-08",
                "2026-09",
            ],
        ),
        (
            {"end": "2024-12"},
            [
                "2024-10",
                "2024-11",
                "2024-12",
            ],
        ),
        (
            {
                "start": "2025-03",
                "end": "2025-05",
            },
            [
                "2025-03",
                "2025-04",
                "2025-05",
            ],
        ),
        (
            {
                "start": "2025-03",
                "end": "2025-03",
            },
            [
                "2025-03",
            ],
        ),
    ],
)
def test_region_range_filters_are_inclusive(params, expected_months):
    response = client.get(
        "/regions/Midwest/performance",
        params=params,
    )

    assert response.status_code == 200
    assert [row["month"] for row in response.json()] == expected_months


@pytest.mark.parametrize(
    "params",
    [
        {
            "start": "2030-01",
            "end": "2030-12",
        },
        {
            "start": "2020-01",
            "end": "2020-12",
        },
    ],
)
def test_valid_region_with_empty_window_returns_empty(params):
    response = client.get(
        "/regions/Midwest/performance",
        params=params,
    )

    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.parametrize(
    "region",
    [
        "Atlantis",
        "midwest",
        "Northeast ",
        "MIDWEST",
    ],
)
def test_unknown_region_returns_404(region):
    response = client.get(f"/regions/{region}/performance")

    assert response.status_code == 404
    assert response.json() == {"detail": f"Region {region} not found"}


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
        "/regions/Midwest/performance",
        params={"start": start},
    )

    assert response.status_code == 422

    detail = response.json()["detail"]

    assert detail[0]["loc"] == [
        "query",
        "start",
    ]


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
        "/regions/Midwest/performance",
        params={"end": end},
    )

    assert response.status_code == 422

    detail = response.json()["detail"]

    assert detail[0]["loc"] == [
        "query",
        "end",
    ]


@pytest.mark.parametrize(
    "params",
    [
        {
            "start": "2026-09",
            "end": "2026-08",
        },
        {
            "start": "2025-12",
            "end": "2025-01",
        },
    ],
)
def test_reversed_range_returns_422(params):
    response = client.get(
        "/regions/Midwest/performance",
        params=params,
    )

    assert response.status_code == 422
    assert response.json() == {"detail": "start month must not be after end month"}


def test_invalid_month_error_from_database_layer_returns_422(monkeypatch):
    def raise_invalid_month(region, start=None, end=None):
        raise InvalidMonthError("start month must use YYYY-MM format")

    monkeypatch.setattr(
        api,
        "get_region_performance_history",
        raise_invalid_month,
    )

    response = client.get("/regions/Midwest/performance")

    assert response.status_code == 422
    assert response.json() == {"detail": "start month must use YYYY-MM format"}


def test_missing_database_url_returns_500(monkeypatch):
    database_url = os.environ["DATABASE_URL"]

    monkeypatch.delenv("DATABASE_URL", raising=False)
    get_engine.cache_clear()

    try:
        response = client.get("/regions/Midwest/performance")

        assert response.status_code == 500
        assert database_url not in response.text
    finally:
        get_engine.cache_clear()


def test_invalid_response_from_data_layer_returns_500(monkeypatch):
    invalid = pd.DataFrame(
        [
            {
                "region": "Midwest",
                "month": "2026-09",
                "dealer_count": "not-an-int",
                "units_sold": 200,
                "target_units": 220,
                "achievement_pct": 90.9,
            }
        ]
    )

    monkeypatch.setattr(
        api,
        "get_region_performance_history",
        lambda region, start=None, end=None: invalid,
    )

    response = client.get("/regions/Midwest/performance")

    assert response.status_code == 500


def test_regions_summary_route_still_works():
    response = client.get("/regions/summary")

    assert response.status_code == 200


def test_missing_target_serializes_as_null(monkeypatch):
    """Real data has no missing targets, so stub the NaN that read_sql returns."""
    nullable = pd.DataFrame(
        [
            {
                "region": "Midwest",
                "month": "2026-09",
                "dealer_count": 8,
                "units_sold": 200,
                "target_units": float("nan"),
                "achievement_pct": float("nan"),
            }
        ]
    )

    monkeypatch.setattr(
        api,
        "get_region_performance_history",
        lambda region, start=None, end=None: nullable,
    )

    response = client.get("/regions/Midwest/performance")

    assert response.status_code == 200
    assert response.json()[0]["target_units"] is None
    assert response.json()[0]["achievement_pct"] is None


def test_counts_are_json_integers_and_percentage_is_float():
    """
    Counts must reach clients as integers, not 211.0.

    Equality alone cannot tell them apart, since 211 == 211.0 in Python,
    so check the type of each parsed JSON value.
    """
    rows = client.get("/regions/Midwest/performance").json()

    assert len(rows) == 24

    for row in rows:
        assert type(row["dealer_count"]) is int
        assert type(row["units_sold"]) is int
        assert type(row["target_units"]) is int
        assert type(row["achievement_pct"]) is float
