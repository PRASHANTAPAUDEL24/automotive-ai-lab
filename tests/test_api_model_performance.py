"""
API tests for monthly vehicle-model performance.

Day 29 exposes one network-level row per sold vehicle model for one required
month, including catalog attributes, network sales share, and unit-weighted
average sale price.
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
    "model",
    "segment",
    "msrp",
    "units_sold",
    "share_pct",
    "avg_sale_price",
]


def schema_allows_null(schema):
    if schema.get("type") == "null":
        return True

    return any(schema_allows_null(option) for option in schema.get("anyOf", []))


def test_model_performance_returns_eight_models_in_database_order():
    expected = db.to_records(db.get_model_performance(MONTH))

    response = client.get(
        "/performance/models",
        params={"month": MONTH},
    )

    assert response.status_code == 200

    data = response.json()

    assert len(data) == 8
    assert data == expected
    assert all(list(row) == EXPECTED_FIELDS for row in data)


def test_model_performance_matches_database_query():
    expected = db.to_records(db.get_model_performance(MONTH))

    response = client.get(
        "/performance/models",
        params={"month": MONTH},
    )

    assert response.status_code == 200
    assert response.json() == expected


def test_model_performance_json_types():
    response = client.get(
        "/performance/models",
        params={"month": MONTH},
    )

    assert response.status_code == 200

    for row in response.json():
        assert type(row["model"]) is str
        assert type(row["segment"]) is str
        assert type(row["msrp"]) is int
        assert type(row["units_sold"]) is int
        assert type(row["share_pct"]) is float
        assert type(row["avg_sale_price"]) is float


def test_missing_month_returns_422_on_query_month():
    response = client.get("/performance/models")

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
def test_malformed_month_returns_422_on_query_month(month):
    response = client.get(
        "/performance/models",
        params={"month": month},
    )

    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == [
        "query",
        "month",
    ]


def test_unknown_month_returns_exact_404():
    response = client.get(
        "/performance/models",
        params={"month": "2030-01"},
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "Month 2030-01 not found"}


def test_openapi_uses_model_monthly_performance_response_model():
    schema = app.openapi()

    operation = schema["paths"]["/performance/models"]["get"]

    response_schema = operation["responses"]["200"]["content"]["application/json"][
        "schema"
    ]

    model_ref = response_schema["items"]["$ref"]
    model_name = model_ref.rsplit("/", 1)[-1]

    assert model_name == "ModelMonthlyPerformance"

    model_schema = schema["components"]["schemas"][model_name]

    assert list(model_schema["properties"]) == EXPECTED_FIELDS
    assert set(model_schema["required"]) == set(EXPECTED_FIELDS)

    for name in (
        "model",
        "segment",
        "msrp",
        "units_sold",
    ):
        assert not schema_allows_null(model_schema["properties"][name])

    assert schema_allows_null(model_schema["properties"]["share_pct"])
    assert schema_allows_null(model_schema["properties"]["avg_sale_price"])


def test_openapi_month_parameter_uses_shared_pattern():
    schema = app.openapi()
    operation = schema["paths"]["/performance/models"]["get"]

    month_parameter = next(
        parameter
        for parameter in operation["parameters"]
        if parameter["in"] == "query" and parameter["name"] == "month"
    )

    assert month_parameter["schema"]["pattern"] == db.MONTH_QUERY_PATTERN


def test_invalid_month_error_from_db_returns_422(monkeypatch):
    def raise_invalid_month(month):
        raise db.InvalidMonthError(f"Invalid month: {month!r}. Expected YYYY-MM.")

    monkeypatch.setattr(
        api,
        "get_model_performance",
        raise_invalid_month,
        raising=False,
    )

    response = client.get(
        "/performance/models",
        params={"month": MONTH},
    )

    assert response.status_code == 422
    assert response.json() == {"detail": "Invalid month: '2026-09'. Expected YYYY-MM."}


def test_month_not_found_error_from_db_returns_404(monkeypatch):
    def raise_not_found(month):
        raise db.MonthNotFoundError(f"Month {month} not found")

    monkeypatch.setattr(
        api,
        "get_model_performance",
        raise_not_found,
        raising=False,
    )

    response = client.get(
        "/performance/models",
        params={"month": MONTH},
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "Month 2026-09 not found"}


def test_nullable_share_and_average_price_are_serialized(
    monkeypatch,
):
    nullable = pd.DataFrame(
        [
            {
                "model": "Vertex Alpha",
                "segment": "Sedan",
                "msrp": 30000,
                "units_sold": 0,
                "share_pct": None,
                "avg_sale_price": None,
            }
        ]
    )

    monkeypatch.setattr(
        api,
        "get_model_performance",
        lambda month: nullable,
        raising=False,
    )

    response = client.get(
        "/performance/models",
        params={"month": MONTH},
    )

    assert response.status_code == 200
    assert response.json() == [
        {
            "model": "Vertex Alpha",
            "segment": "Sedan",
            "msrp": 30000,
            "units_sold": 0,
            "share_pct": None,
            "avg_sale_price": None,
        }
    ]


def test_invalid_response_data_returns_500(monkeypatch):
    invalid = pd.DataFrame(
        [
            {
                "model": "Vertex Alpha",
                "segment": "Sedan",
                "msrp": "not-an-integer",
                "units_sold": 10,
                "share_pct": 12.5,
                "avg_sale_price": 29000.0,
            }
        ]
    )

    monkeypatch.setattr(
        api,
        "get_model_performance",
        lambda month: invalid,
        raising=False,
    )

    response = client.get(
        "/performance/models",
        params={"month": MONTH},
    )

    assert response.status_code == 500


@pytest.fixture
def rolled_back_connection(monkeypatch):
    engine = db.get_engine()

    with engine.connect() as connection:
        transaction = connection.begin()
        monkeypatch.setattr(db, "get_engine", lambda: connection)

        try:
            yield connection
        finally:
            transaction.rollback()


def test_zero_unit_model_serializes_zero_share_and_null_price(
    rolled_back_connection,
):
    connection = rolled_back_connection

    model = connection.execute(
        text("SELECT min(model) FROM vehicle_models")
    ).scalar_one()

    connection.execute(
        text(
            "UPDATE sales_monthly SET units_sold = 0, avg_sale_price = NULL "
            "WHERE month = :month AND model = :model"
        ),
        {"month": MONTH, "model": model},
    )

    response = client.get("/performance/models", params={"month": MONTH})

    assert response.status_code == 200
    data = response.json()

    row = next(item for item in data if item["model"] == model)
    others = [item for item in data if item["model"] != model]

    assert row["units_sold"] == 0
    assert row["share_pct"] == 0.0
    assert row["avg_sale_price"] is None

    assert len(others) == 7
    assert all(type(item["avg_sale_price"]) is float for item in others)


def test_nan_numeric_value_is_serialized_as_json_null(monkeypatch):
    """
    Pin the HTTP serialization contract for pandas NaN.

    Regardless of the internal record-conversion path, a NaN numeric value
    must be exposed to API clients as JSON null.
    """
    performance = pd.DataFrame(
        [
            {
                "model": "Vertex Alpha",
                "segment": "Sedan",
                "msrp": 30000,
                "units_sold": 0,
                "share_pct": 0.0,
                "avg_sale_price": float("nan"),
            },
            {
                "model": "Vertex Beta",
                "segment": "SUV",
                "msrp": 40000,
                "units_sold": 10,
                "share_pct": 100.0,
                "avg_sale_price": 39000.0,
            },
        ]
    )

    assert pd.isna(performance.loc[0, "avg_sale_price"])
    assert performance.loc[1, "avg_sale_price"] == 39000.0

    monkeypatch.setattr(
        api,
        "get_model_performance",
        lambda month: performance,
    )

    response = client.get(
        "/performance/models",
        params={"month": MONTH},
    )

    assert response.status_code == 200

    data = response.json()

    assert data[0]["avg_sale_price"] is None
    assert data[1]["avg_sale_price"] == 39000.0
