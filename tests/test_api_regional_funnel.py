"""
API tests for the regional lead funnel snapshot.

Day 30 exposes one row per dealer region for one required month, including
lead volume, test drives, units sold, and three regional ratio-of-sums rates.
"""

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

MONTH = "2026-09"

EXPECTED_FIELDS = [
    "region",
    "leads",
    "test_drives",
    "units_sold",
    "test_drive_rate_pct",
    "drive_to_sale_pct",
    "lead_to_sale_pct",
]


def schema_allows_null(schema):
    if schema.get("type") == "null":
        return True

    return any(schema_allows_null(option) for option in schema.get("anyOf", []))


@pytest.fixture
def rolled_back_connection(monkeypatch):
    engine = db.get_engine()

    with engine.connect() as connection:
        transaction = connection.begin()

        monkeypatch.setattr(
            db,
            "get_engine",
            lambda: connection,
        )

        try:
            yield connection
        finally:
            transaction.rollback()


def target_region_and_dealer(connection):
    row = connection.execute(text("""
            SELECT region, MIN(dealer_id) AS dealer_id
            FROM dealers
            GROUP BY region
            ORDER BY region
            LIMIT 1
            """)).mappings().one()

    return row["region"], row["dealer_id"]


def response_row_by_region(response, region):
    return next(row for row in response.json() if row["region"] == region)


def test_regional_funnel_matches_database_query_and_exact_fields():
    expected = db.to_records(db.get_regional_funnel_snapshot(MONTH))

    response = client.get(
        "/performance/funnel",
        params={"month": MONTH},
    )

    assert response.status_code == 200

    data = response.json()

    assert data == expected
    assert all(list(row) == EXPECTED_FIELDS for row in data)


def test_regional_funnel_returns_five_regions_alphabetically():
    response = client.get(
        "/performance/funnel",
        params={"month": MONTH},
    )

    assert response.status_code == 200

    data = response.json()
    regions = [row["region"] for row in data]

    assert len(data) == 5
    assert regions == sorted(regions)
    assert len(set(regions)) == 5


def test_regional_funnel_json_types_on_committed_data():
    response = client.get(
        "/performance/funnel",
        params={"month": MONTH},
    )

    assert response.status_code == 200

    for row in response.json():
        assert type(row["region"]) is str

        assert type(row["leads"]) is int
        assert type(row["test_drives"]) is int
        assert type(row["units_sold"]) is int

        assert type(row["test_drive_rate_pct"]) is float
        assert type(row["drive_to_sale_pct"]) is float
        assert type(row["lead_to_sale_pct"]) is float


def test_missing_sales_serializes_units_and_sale_rates_as_null(
    rolled_back_connection,
):
    connection = rolled_back_connection
    region, dealer_id = target_region_and_dealer(connection)

    connection.execute(
        text("""
            DELETE FROM sales_monthly
            WHERE dealer_id = :dealer_id
              AND month = :month
            """),
        {
            "dealer_id": dealer_id,
            "month": MONTH,
        },
    )

    response = client.get(
        "/performance/funnel",
        params={"month": MONTH},
    )

    assert response.status_code == 200

    row = response_row_by_region(response, region)

    assert type(row["leads"]) is int
    assert type(row["test_drives"]) is int
    assert type(row["test_drive_rate_pct"]) is float

    assert row["units_sold"] is None
    assert row["drive_to_sale_pct"] is None
    assert row["lead_to_sale_pct"] is None


def test_missing_sales_keeps_other_regions_units_as_json_integers(
    rolled_back_connection,
):
    connection = rolled_back_connection
    region, dealer_id = target_region_and_dealer(connection)

    connection.execute(
        text("""
            DELETE FROM sales_monthly
            WHERE dealer_id = :dealer_id
              AND month = :month
            """),
        {
            "dealer_id": dealer_id,
            "month": MONTH,
        },
    )

    snapshot = db.get_regional_funnel_snapshot(MONTH)

    # One NaN forces pandas to represent the otherwise-integer column
    # as float64. The API response model must still emit unaffected
    # values as JSON integers.
    assert pd.api.types.is_float_dtype(snapshot["units_sold"])

    response = client.get(
        "/performance/funnel",
        params={"month": MONTH},
    )

    assert response.status_code == 200

    other_rows = [row for row in response.json() if row["region"] != region]

    assert other_rows

    for row in other_rows:
        assert type(row["units_sold"]) is int


def test_missing_lead_row_serializes_lead_metrics_as_null_and_preserves_units(
    rolled_back_connection,
):
    connection = rolled_back_connection
    region, dealer_id = target_region_and_dealer(connection)

    expected_units = next(
        row["units_sold"]
        for row in db.to_records(db.get_regional_funnel_snapshot(MONTH))
        if row["region"] == region
    )

    connection.execute(
        text("""
            DELETE FROM leads_monthly
            WHERE dealer_id = :dealer_id
              AND month = :month
            """),
        {
            "dealer_id": dealer_id,
            "month": MONTH,
        },
    )

    response = client.get(
        "/performance/funnel",
        params={"month": MONTH},
    )

    assert response.status_code == 200

    row = response_row_by_region(response, region)

    assert row["leads"] is None
    assert row["test_drives"] is None
    assert row["test_drive_rate_pct"] is None

    assert type(row["units_sold"]) is int
    assert row["units_sold"] == expected_units

    assert row["drive_to_sale_pct"] is None
    assert row["lead_to_sale_pct"] is None


def test_openapi_uses_regional_funnel_response_model():
    schema = app.openapi()

    operation = schema["paths"]["/performance/funnel"]["get"]

    response_schema = operation["responses"]["200"]["content"]["application/json"][
        "schema"
    ]

    model_ref = response_schema["items"]["$ref"]
    model_name = model_ref.rsplit("/", 1)[-1]

    assert model_name == "RegionalFunnel"

    model_schema = schema["components"]["schemas"][model_name]

    assert list(model_schema["properties"]) == EXPECTED_FIELDS
    assert set(model_schema["required"]) == set(EXPECTED_FIELDS)

    assert not schema_allows_null(model_schema["properties"]["region"])

    for name in EXPECTED_FIELDS[1:]:
        assert schema_allows_null(model_schema["properties"][name])


def test_openapi_month_parameter_uses_shared_pattern():
    schema = app.openapi()

    operation = schema["paths"]["/performance/funnel"]["get"]

    month_parameter = next(
        parameter
        for parameter in operation["parameters"]
        if (parameter["in"] == "query" and parameter["name"] == "month")
    )

    assert month_parameter["schema"]["pattern"] == db.MONTH_QUERY_PATTERN


def test_missing_month_returns_422_on_query_month():
    response = client.get("/performance/funnel")

    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == [
        "query",
        "month",
    ]


def test_empty_month_returns_422_on_query_month():
    response = client.get(
        "/performance/funnel",
        params={"month": ""},
    )

    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == [
        "query",
        "month",
    ]


@pytest.mark.parametrize(
    "month",
    [
        "2026-9",
        "2026-00",
        "2026-13",
        "2026-09\n",
        "２０２６-０９",
    ],
)
def test_malformed_month_returns_422_on_query_month(month):
    response = client.get(
        "/performance/funnel",
        params={"month": month},
    )

    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == [
        "query",
        "month",
    ]


def test_unknown_month_returns_exact_404():
    response = client.get(
        "/performance/funnel",
        params={"month": "2099-01"},
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "Month 2099-01 not found"}


def test_invalid_month_error_from_db_returns_422(monkeypatch):
    def raise_invalid_month(month):
        raise db.InvalidMonthError(f"Invalid month: {month!r}. Expected YYYY-MM.")

    monkeypatch.setattr(
        api,
        "get_regional_funnel_snapshot",
        raise_invalid_month,
        raising=False,
    )

    response = client.get(
        "/performance/funnel",
        params={"month": MONTH},
    )

    assert response.status_code == 422
    assert response.json() == {"detail": "Invalid month: '2026-09'. Expected YYYY-MM."}


def test_month_not_found_error_from_db_returns_404(monkeypatch):
    def raise_not_found(month):
        raise db.MonthNotFoundError(f"Month {month} not found")

    monkeypatch.setattr(
        api,
        "get_regional_funnel_snapshot",
        raise_not_found,
        raising=False,
    )

    response = client.get(
        "/performance/funnel",
        params={"month": MONTH},
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "Month 2026-09 not found"}


@pytest.mark.parametrize(
    "path",
    [
        "/performance/regions",
        "/performance/models",
        "/performance",
    ],
)
def test_existing_performance_routes_still_work(path):
    response = client.get(
        path,
        params={"month": MONTH},
    )

    assert response.status_code == 200
