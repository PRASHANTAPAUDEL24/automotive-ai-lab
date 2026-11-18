"""
API tests for the cross-region monthly performance snapshot.

Day 26 exposes one weighted performance row per region for one required
month while reusing the existing RegionMonthlyPerformance response model.
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
    "region",
    "month",
    "dealer_count",
    "units_sold",
    "target_units",
    "achievement_pct",
]

EXPECTED_REGIONS = [
    "Midwest",
    "Northeast",
    "Southeast",
    "Southwest",
    "West",
]


def schema_allows_null(schema):
    if schema.get("type") == "null":
        return True

    return any(schema_allows_null(option) for option in schema.get("anyOf", []))


def test_regional_snapshot_returns_five_regions_in_order():
    response = client.get(
        "/performance/regions",
        params={"month": "2026-09"},
    )

    assert response.status_code == 200

    data = response.json()

    assert len(data) == 5
    assert [row["region"] for row in data] == EXPECTED_REGIONS
    assert all(row["month"] == "2026-09" for row in data)
    assert all(list(row) == EXPECTED_FIELDS for row in data)


def test_regional_snapshot_matches_database_query():
    expected = db.to_records(db.get_regional_performance_snapshot("2026-09"))

    response = client.get(
        "/performance/regions",
        params={"month": "2026-09"},
    )

    assert response.status_code == 200
    assert response.json() == expected


def test_regional_snapshot_integer_and_float_json_types():
    response = client.get(
        "/performance/regions",
        params={"month": "2026-09"},
    )

    assert response.status_code == 200

    for row in response.json():
        assert type(row["dealer_count"]) is int
        assert type(row["units_sold"]) is int
        assert type(row["target_units"]) is int
        assert type(row["achievement_pct"]) is float


def test_missing_month_returns_422():
    response = client.get("/performance/regions")

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
        "٢٠٢٦-٠٩",
    ],
)
def test_malformed_month_returns_422(month):
    response = client.get(
        "/performance/regions",
        params={"month": month},
    )

    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == [
        "query",
        "month",
    ]


def test_unknown_month_returns_exact_404():
    response = client.get(
        "/performance/regions",
        params={"month": "2030-01"},
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "Month 2030-01 not found"}


def test_response_reuses_region_monthly_performance_model():
    schema = app.openapi()

    operation = schema["paths"]["/performance/regions"]["get"]

    response_schema = operation["responses"]["200"]["content"]["application/json"][
        "schema"
    ]

    model_ref = response_schema["items"]["$ref"]
    model_name = model_ref.rsplit("/", 1)[-1]

    assert model_name == "RegionMonthlyPerformance"

    model_schema = schema["components"]["schemas"][model_name]

    assert list(model_schema["properties"]) == EXPECTED_FIELDS
    assert set(model_schema["required"]) == set(EXPECTED_FIELDS)

    assert schema_allows_null(model_schema["properties"]["target_units"])
    assert schema_allows_null(model_schema["properties"]["achievement_pct"])

    for name in (
        "region",
        "month",
        "dealer_count",
        "units_sold",
    ):
        assert not schema_allows_null(model_schema["properties"][name])


def test_invalid_month_error_from_db_returns_422(monkeypatch):
    def raise_invalid_month(month):
        raise db.InvalidMonthError(f"Invalid month: {month!r}. Expected YYYY-MM.")

    monkeypatch.setattr(
        api,
        "get_regional_performance_snapshot",
        raise_invalid_month,
    )

    response = client.get(
        "/performance/regions",
        params={"month": "2026-09"},
    )

    assert response.status_code == 422

    assert response.json() == {"detail": "Invalid month: '2026-09'. Expected YYYY-MM."}


def test_month_not_found_error_from_db_returns_404(monkeypatch):
    def raise_not_found(month):
        raise db.MonthNotFoundError(f"Month {month} not found")

    monkeypatch.setattr(
        api,
        "get_regional_performance_snapshot",
        raise_not_found,
    )

    response = client.get(
        "/performance/regions",
        params={"month": "2030-01"},
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "Month 2030-01 not found"}


def test_nullable_target_and_achievement_are_serialized(monkeypatch):
    nullable = pd.DataFrame(
        [
            {
                "region": "Midwest",
                "month": "2026-09",
                "dealer_count": 8,
                "units_sold": 100,
                "target_units": None,
                "achievement_pct": None,
            },
            {
                "region": "Northeast",
                "month": "2026-09",
                "dealer_count": 8,
                "units_sold": 100,
                "target_units": 120,
                "achievement_pct": 83.3,
            },
        ]
    )

    monkeypatch.setattr(
        api,
        "get_regional_performance_snapshot",
        lambda month: nullable,
    )

    response = client.get(
        "/performance/regions",
        params={"month": "2026-09"},
    )

    assert response.status_code == 200

    data = response.json()

    assert data == [
        {
            "region": "Midwest",
            "month": "2026-09",
            "dealer_count": 8,
            "units_sold": 100,
            "target_units": None,
            "achievement_pct": None,
        },
        {
            "region": "Northeast",
            "month": "2026-09",
            "dealer_count": 8,
            "units_sold": 100,
            "target_units": 120,
            "achievement_pct": 83.3,
        },
    ]

    assert type(data[1]["target_units"]) is int


def test_missing_target_region_is_null_and_others_stay_integers(
    monkeypatch,
):
    engine = db.get_engine()

    with engine.connect() as connection:
        transaction = connection.begin()

        try:
            monkeypatch.setattr(
                db,
                "get_engine",
                lambda: connection,
            )

            baseline_response = client.get(
                "/performance/regions",
                params={"month": "2026-09"},
            )

            assert baseline_response.status_code == 200
            baseline = baseline_response.json()

            deleted = connection.execute(text("""
                    DELETE FROM dealer_targets
                    WHERE month = '2026-09'
                      AND dealer_id = (
                          SELECT dealer_id
                          FROM dealers
                          WHERE region = 'Midwest'
                          ORDER BY dealer_id
                          LIMIT 1
                      )
                    """))

            assert deleted.rowcount == 1

            response = client.get(
                "/performance/regions",
                params={"month": "2026-09"},
            )

            assert response.status_code == 200
            data = response.json()

            assert [row["region"] for row in data] == EXPECTED_REGIONS

            midwest = data[0]

            assert midwest["target_units"] is None
            assert midwest["achievement_pct"] is None
            assert midwest["dealer_count"] == baseline[0]["dealer_count"]
            assert midwest["units_sold"] == baseline[0]["units_sold"]

            assert data[1:] == baseline[1:]

            for row in data:
                assert type(row["dealer_count"]) is int
                assert type(row["units_sold"]) is int

            for row in data[1:]:
                assert type(row["target_units"]) is int
                assert type(row["achievement_pct"]) is float

        finally:
            transaction.rollback()


def test_invalid_response_data_returns_500(monkeypatch):
    invalid = pd.DataFrame(
        [
            {
                "region": "Midwest",
                "month": "2026-09",
                "dealer_count": "not-an-integer",
                "units_sold": 100,
                "target_units": 120,
                "achievement_pct": 83.3,
            }
        ]
    )

    monkeypatch.setattr(
        api,
        "get_regional_performance_snapshot",
        lambda month: invalid,
    )

    response = client.get(
        "/performance/regions",
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
            "/performance/regions",
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

    ranking = client.get(
        "/performance/ranking",
        params={"month": "2026-09"},
    )

    region_summary = client.get("/regions/summary")

    region_history = client.get(
        "/regions/Midwest/performance",
        params={
            "start": "2026-09",
            "end": "2026-09",
        },
    )

    assert monthly.status_code == 200
    assert len(monthly.json()) == 40

    assert trend.status_code == 200
    assert len(trend.json()) == 24

    assert ranking.status_code == 200
    assert len(ranking.json()) == 40

    assert region_summary.status_code == 200
    assert len(region_summary.json()) == 5

    assert region_history.status_code == 200
    assert len(region_history.json()) == 1
