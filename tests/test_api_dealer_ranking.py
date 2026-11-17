"""
API tests for month-aware dealer performance ranking.

Day 25 exposes dealer ranking for one required month, with an optional
bounded limit and a non-null ranked response contract.
"""

import os

import pandas as pd
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

import api
import db
from api import app

client = TestClient(
    app,
    raise_server_exceptions=False,
)

EXPECTED_FIELDS = [
    "dealer_id",
    "dealer_name",
    "month",
    "units_sold",
    "target_units",
    "achievement_pct",
    "rank",
]


def schema_allows_null(schema):
    if schema.get("type") == "null":
        return True

    return any(schema_allows_null(option) for option in schema.get("anyOf", []))


def test_ranking_returns_40_dealers_with_contiguous_integer_ranks():
    response = client.get(
        "/performance/ranking",
        params={"month": "2026-09"},
    )

    assert response.status_code == 200

    data = response.json()

    assert len(data) == 40
    assert list(data[0]) == EXPECTED_FIELDS
    assert all(row["month"] == "2026-09" for row in data)
    assert [row["rank"] for row in data] == list(range(1, 41))
    assert all(type(row["rank"]) is int for row in data)


@pytest.mark.parametrize(
    ("limit", "expected_count"),
    [
        (5, 5),
        (db.MAX_LIMIT, 40),
    ],
)
def test_ranking_limit(limit, expected_count):
    full = client.get(
        "/performance/ranking",
        params={"month": "2026-09"},
    )

    limited = client.get(
        "/performance/ranking",
        params={
            "month": "2026-09",
            "limit": limit,
        },
    )

    assert full.status_code == 200
    assert limited.status_code == 200

    assert len(limited.json()) == expected_count
    assert limited.json() == full.json()[:expected_count]


def test_missing_month_returns_422():
    response = client.get("/performance/ranking")

    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == [
        "query",
        "month",
    ]


@pytest.mark.parametrize(
    "month",
    [
        "2026-13",
        "2026-9",
        "2026-09\n",
    ],
)
def test_malformed_month_returns_422(month):
    response = client.get(
        "/performance/ranking",
        params={"month": month},
    )

    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == [
        "query",
        "month",
    ]


@pytest.mark.parametrize(
    "limit",
    [
        "0",
        "-1",
        "abc",
        str(2**63),
    ],
)
def test_invalid_limit_returns_422(limit):
    response = client.get(
        "/performance/ranking",
        params={
            "month": "2026-09",
            "limit": limit,
        },
    )

    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == [
        "query",
        "limit",
    ]


def test_unknown_month_returns_exact_404():
    response = client.get(
        "/performance/ranking",
        params={"month": "2030-01"},
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "Month 2030-01 not found"}


def test_existing_month_with_no_rankable_dealers_returns_empty(
    monkeypatch,
):
    engine = db.get_engine()

    with engine.connect() as connection:
        transaction = connection.begin()

        try:
            connection.execute(text("""
                    UPDATE dealer_targets
                    SET target_units = 0
                    WHERE month = '2026-09'
                    """))

            monkeypatch.setattr(
                db,
                "get_engine",
                lambda: connection,
            )

            response = client.get(
                "/performance/ranking",
                params={"month": "2026-09"},
            )

            assert response.status_code == 200
            assert response.json() == []

        finally:
            transaction.rollback()


def test_ranked_model_target_and_achievement_are_non_nullable():
    schema = app.openapi()

    operation = schema["paths"]["/performance/ranking"]["get"]

    response_schema = operation["responses"]["200"]["content"]["application/json"][
        "schema"
    ]

    model_ref = response_schema["items"]["$ref"]
    model_name = model_ref.rsplit("/", 1)[-1]

    assert model_name == "RankedMonthlyPerformance"

    model_schema = schema["components"]["schemas"][model_name]

    assert set(model_schema["required"]) == set(EXPECTED_FIELDS)

    assert not schema_allows_null(model_schema["properties"]["target_units"])

    assert not schema_allows_null(model_schema["properties"]["achievement_pct"])


def test_invalid_month_error_from_db_returns_422(monkeypatch):
    def raise_invalid_month(month, limit=None):
        raise db.InvalidMonthError(f"Invalid month: {month!r}. Expected YYYY-MM.")

    monkeypatch.setattr(
        api,
        "get_monthly_dealer_ranking",
        raise_invalid_month,
    )

    response = client.get(
        "/performance/ranking",
        params={"month": "2026-09"},
    )

    assert response.status_code == 422

    assert response.json() == {"detail": "Invalid month: '2026-09'. Expected YYYY-MM."}


def test_invalid_limit_error_from_db_returns_422(monkeypatch):
    def raise_invalid_limit(month, limit=None):
        raise db.InvalidLimitError(
            f"Invalid limit: {limit!r}. "
            f"Expected an integer between 1 and {db.MAX_LIMIT}."
        )

    monkeypatch.setattr(
        api,
        "get_monthly_dealer_ranking",
        raise_invalid_limit,
    )

    response = client.get(
        "/performance/ranking",
        params={
            "month": "2026-09",
            "limit": 5,
        },
    )

    assert response.status_code == 422

    assert response.json() == {
        "detail": (
            "Invalid limit: 5. " f"Expected an integer between 1 and {db.MAX_LIMIT}."
        )
    }


def test_month_not_found_error_from_db_returns_404(monkeypatch):
    def raise_not_found(month, limit=None):
        raise db.MonthNotFoundError(f"Month {month} not found")

    monkeypatch.setattr(
        api,
        "get_monthly_dealer_ranking",
        raise_not_found,
    )

    response = client.get(
        "/performance/ranking",
        params={"month": "2030-01"},
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "Month 2030-01 not found"}


def test_invalid_response_data_returns_500(monkeypatch):
    invalid = pd.DataFrame(
        [
            {
                "dealer_id": 101,
                "dealer_name": "Test Dealer",
                "month": "2026-09",
                "units_sold": 100,
                "target_units": 120,
                "achievement_pct": None,
                "rank": 1,
            }
        ]
    )

    monkeypatch.setattr(
        api,
        "get_monthly_dealer_ranking",
        lambda month, limit=None: invalid,
    )

    response = client.get(
        "/performance/ranking",
        params={"month": "2026-09"},
    )

    assert response.status_code == 500


def test_missing_database_url_returns_500(monkeypatch):
    database_url = os.environ["DATABASE_URL"]

    db.get_engine.cache_clear()
    monkeypatch.delenv(
        "DATABASE_URL",
        raising=False,
    )

    try:
        response = client.get(
            "/performance/ranking",
            params={"month": "2026-09"},
        )
    finally:
        db.get_engine.cache_clear()

    assert response.status_code == 500
    assert database_url not in response.text


def test_existing_performance_routes_still_work():
    monthly = client.get(
        "/performance",
        params={"month": "2026-09"},
    )

    trend = client.get("/performance/trend")

    at_risk = client.get("/dealers/at-risk")

    assert monthly.status_code == 200
    assert len(monthly.json()) == 40

    assert trend.status_code == 200
    assert len(trend.json()) == 24

    assert at_risk.status_code == 200
    assert len(at_risk.json()) == 20
