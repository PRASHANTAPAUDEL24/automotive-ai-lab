"""
API tests for network-wide monthly lead-funnel trend.

Day 32 exposes the network funnel trend through an HTTP endpoint with
optional inclusive start/end bounds while preserving database-layer
missing-data and zero-denominator semantics.
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

EXPECTED_KEYS = {
    "month",
    "leads",
    "test_drives",
    "units_sold",
    "test_drive_rate_pct",
    "drive_to_sale_pct",
    "lead_to_sale_pct",
}


def _valid_row(**overrides):
    row = {
        "month": "2026-09",
        "leads": 8558,
        "test_drives": 3125,
        "units_sold": 1252,
        "test_drive_rate_pct": 36.51437251694321,
        "drive_to_sale_pct": 40.064,
        "lead_to_sale_pct": 14.629586352,
    }
    row.update(overrides)
    return row


@pytest.fixture
def transaction_connection(monkeypatch):
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


# ============================================================
# Baseline behavior
# ============================================================


def test_no_range_returns_complete_24_month_trend():
    response = client.get("/performance/funnel/trend")

    assert response.status_code == 200

    body = response.json()

    assert len(body) == 24
    assert body[0]["month"] == "2024-10"
    assert body[-1]["month"] == "2026-09"


def test_trend_is_oldest_first():
    response = client.get("/performance/funnel/trend")

    assert response.status_code == 200

    months = [row["month"] for row in response.json()]

    assert months == sorted(months)


def test_response_has_exact_expected_fields():
    response = client.get(
        "/performance/funnel/trend",
        params={
            "start": "2026-09",
            "end": "2026-09",
        },
    )

    assert response.status_code == 200

    body = response.json()

    assert len(body) == 1
    assert set(body[0]) == EXPECTED_KEYS


def test_response_matches_database_layer():
    response = client.get("/performance/funnel/trend")

    assert response.status_code == 200

    expected = db.to_records(db.get_network_funnel_trend())

    assert response.json() == expected


# ============================================================
# Inclusive range behavior
# ============================================================


def test_start_only_is_inclusive():
    response = client.get(
        "/performance/funnel/trend",
        params={"start": "2026-07"},
    )

    assert response.status_code == 200

    months = [row["month"] for row in response.json()]

    assert months == [
        "2026-07",
        "2026-08",
        "2026-09",
    ]


def test_end_only_is_inclusive():
    response = client.get(
        "/performance/funnel/trend",
        params={"end": "2024-12"},
    )

    assert response.status_code == 200

    months = [row["month"] for row in response.json()]

    assert months == [
        "2024-10",
        "2024-11",
        "2024-12",
    ]


def test_both_bounds_are_inclusive():
    response = client.get(
        "/performance/funnel/trend",
        params={
            "start": "2026-07",
            "end": "2026-09",
        },
    )

    assert response.status_code == 200

    months = [row["month"] for row in response.json()]

    assert months == [
        "2026-07",
        "2026-08",
        "2026-09",
    ]


def test_equal_start_and_end_returns_one_month():
    response = client.get(
        "/performance/funnel/trend",
        params={
            "start": "2026-09",
            "end": "2026-09",
        },
    )

    assert response.status_code == 200

    body = response.json()

    assert len(body) == 1
    assert body[0]["month"] == "2026-09"


@pytest.mark.parametrize(
    ("start", "end"),
    [
        ("2027-01", None),
        (None, "2024-09"),
        ("2027-01", "2027-03"),
    ],
)
def test_valid_empty_window_returns_200_empty(start, end):
    params = {}

    if start is not None:
        params["start"] = start

    if end is not None:
        params["end"] = end

    response = client.get(
        "/performance/funnel/trend",
        params=params,
    )

    assert response.status_code == 200
    assert response.json() == []


# ============================================================
# Validation
# ============================================================


@pytest.mark.parametrize(
    "start",
    [
        "2026-9",
        "2026-00",
        "2026-13",
        "not-a-month",
        "2026-09\n",
    ],
)
def test_malformed_start_is_rejected_by_fastapi(start):
    response = client.get(
        "/performance/funnel/trend",
        params={"start": start},
    )

    assert response.status_code == 422


@pytest.mark.parametrize(
    "end",
    [
        "2026-9",
        "2026-00",
        "2026-13",
        "not-a-month",
        "2026-09\n",
    ],
)
def test_malformed_end_is_rejected_by_fastapi(end):
    response = client.get(
        "/performance/funnel/trend",
        params={"end": end},
    )

    assert response.status_code == 422


def test_reversed_range_returns_422():
    response = client.get(
        "/performance/funnel/trend",
        params={
            "start": "2026-09",
            "end": "2026-08",
        },
    )

    assert response.status_code == 422


def test_database_invalid_month_error_maps_to_422(monkeypatch):
    def fake_get_network_funnel_trend(*, start=None, end=None):
        raise db.InvalidMonthError("bad month")

    monkeypatch.setattr(
        api,
        "get_network_funnel_trend",
        fake_get_network_funnel_trend,
    )

    response = client.get("/performance/funnel/trend")

    assert response.status_code == 422
    assert response.json()["detail"] == "bad month"


def test_database_invalid_range_error_maps_to_422(monkeypatch):
    def fake_get_network_funnel_trend(*, start=None, end=None):
        raise db.InvalidMonthRangeError("bad range")

    monkeypatch.setattr(
        api,
        "get_network_funnel_trend",
        fake_get_network_funnel_trend,
    )

    response = client.get("/performance/funnel/trend")

    assert response.status_code == 422
    assert response.json()["detail"] == "bad range"


# ============================================================
# Null and zero serialization
# ============================================================


def test_nullable_lead_metrics_serialize_as_null(monkeypatch):
    frame = pd.DataFrame(
        [
            _valid_row(
                leads=None,
                test_drives=None,
                test_drive_rate_pct=None,
                drive_to_sale_pct=None,
                lead_to_sale_pct=None,
            )
        ]
    )

    monkeypatch.setattr(
        api,
        "get_network_funnel_trend",
        lambda start=None, end=None: frame,
    )

    response = client.get("/performance/funnel/trend")

    assert response.status_code == 200

    row = response.json()[0]

    assert row["leads"] is None
    assert row["test_drives"] is None
    assert row["test_drive_rate_pct"] is None
    assert row["drive_to_sale_pct"] is None
    assert row["lead_to_sale_pct"] is None


def test_nullable_sales_metrics_serialize_as_null(monkeypatch):
    frame = pd.DataFrame(
        [
            _valid_row(
                units_sold=None,
                drive_to_sale_pct=None,
                lead_to_sale_pct=None,
            )
        ]
    )

    monkeypatch.setattr(
        api,
        "get_network_funnel_trend",
        lambda start=None, end=None: frame,
    )

    response = client.get("/performance/funnel/trend")

    assert response.status_code == 200

    row = response.json()[0]

    assert row["units_sold"] is None
    assert row["drive_to_sale_pct"] is None
    assert row["lead_to_sale_pct"] is None


def test_zero_values_are_not_converted_to_null(monkeypatch):
    frame = pd.DataFrame(
        [
            _valid_row(
                leads=0,
                test_drives=0,
                units_sold=0,
                test_drive_rate_pct=None,
                drive_to_sale_pct=None,
                lead_to_sale_pct=None,
            )
        ]
    )

    monkeypatch.setattr(
        api,
        "get_network_funnel_trend",
        lambda start=None, end=None: frame,
    )

    response = client.get("/performance/funnel/trend")

    assert response.status_code == 200

    row = response.json()[0]

    assert row["leads"] == 0
    assert row["test_drives"] == 0
    assert row["units_sold"] == 0


def test_numeric_nan_in_multi_row_result_serializes_as_null(monkeypatch):
    frame = pd.DataFrame(
        [
            _valid_row(
                month="2026-08",
                units_sold=float("nan"),
                drive_to_sale_pct=float("nan"),
                lead_to_sale_pct=float("nan"),
            ),
            _valid_row(month="2026-09"),
        ]
    )

    monkeypatch.setattr(
        api,
        "get_network_funnel_trend",
        lambda start=None, end=None: frame,
    )

    response = client.get("/performance/funnel/trend")

    assert response.status_code == 200

    first = response.json()[0]

    assert first["units_sold"] is None
    assert first["drive_to_sale_pct"] is None
    assert first["lead_to_sale_pct"] is None


# ============================================================
# Real-database missing-data propagation
# ============================================================


def test_real_missing_lead_row_serializes_network_nulls(
    transaction_connection,
):
    transaction_connection.execute(
        text("""
            DELETE FROM leads_monthly
            WHERE dealer_id = 101
              AND month = :month
            """),
        {"month": "2026-09"},
    )

    response = client.get(
        "/performance/funnel/trend",
        params={
            "start": "2026-09",
            "end": "2026-09",
        },
    )

    assert response.status_code == 200

    body = response.json()

    assert len(body) == 1

    row = body[0]

    assert row["month"] == "2026-09"
    assert row["leads"] is None
    assert row["test_drives"] is None
    assert row["units_sold"] is not None

    assert row["test_drive_rate_pct"] is None
    assert row["drive_to_sale_pct"] is None
    assert row["lead_to_sale_pct"] is None


def test_real_missing_sales_rows_serialize_network_nulls(
    transaction_connection,
):
    transaction_connection.execute(
        text("""
            DELETE FROM sales_monthly
            WHERE dealer_id = 101
              AND month = :month
            """),
        {"month": "2026-09"},
    )

    response = client.get(
        "/performance/funnel/trend",
        params={
            "start": "2026-09",
            "end": "2026-09",
        },
    )

    assert response.status_code == 200

    body = response.json()

    assert len(body) == 1

    row = body[0]

    assert row["month"] == "2026-09"
    assert row["leads"] is not None
    assert row["test_drives"] is not None
    assert row["units_sold"] is None

    assert row["test_drive_rate_pct"] is not None
    assert row["drive_to_sale_pct"] is None
    assert row["lead_to_sale_pct"] is None


# ============================================================
# Response model and OpenAPI
# ============================================================


@pytest.mark.parametrize("field", sorted(EXPECTED_KEYS))
def test_missing_field_in_database_result_returns_500(
    monkeypatch,
    field,
):
    row = _valid_row()
    row.pop(field)

    frame = pd.DataFrame([row])

    monkeypatch.setattr(
        api,
        "get_network_funnel_trend",
        lambda start=None, end=None: frame,
    )

    response = client.get("/performance/funnel/trend")

    assert response.status_code == 500


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("month", 123),
        ("leads", "bad"),
        ("test_drives", "bad"),
        ("units_sold", "bad"),
        ("test_drive_rate_pct", "bad"),
        ("drive_to_sale_pct", "bad"),
        ("lead_to_sale_pct", "bad"),
    ],
)
def test_invalid_field_value_returns_500(
    monkeypatch,
    field,
    value,
):
    frame = pd.DataFrame([_valid_row(**{field: value})])

    monkeypatch.setattr(
        api,
        "get_network_funnel_trend",
        lambda start=None, end=None: frame,
    )

    response = client.get("/performance/funnel/trend")

    assert response.status_code == 500


def test_openapi_marks_all_fields_required_and_metrics_nullable():
    schema = app.openapi()

    model = schema["components"]["schemas"]["NetworkMonthlyFunnel"]

    assert set(model["required"]) == EXPECTED_KEYS

    properties = model["properties"]

    for field in EXPECTED_KEYS - {"month"}:
        field_schema = properties[field]

        assert "anyOf" in field_schema
        assert {"type": "null"} in field_schema["anyOf"]


def test_openapi_field_types():
    schema = app.openapi()

    model = schema["components"]["schemas"]["NetworkMonthlyFunnel"]

    properties = model["properties"]

    assert properties["month"]["type"] == "string"

    for field in (
        "leads",
        "test_drives",
        "units_sold",
    ):
        types = {option["type"] for option in properties[field]["anyOf"]}

        assert types == {"integer", "null"}

    for field in (
        "test_drive_rate_pct",
        "drive_to_sale_pct",
        "lead_to_sale_pct",
    ):
        types = {option["type"] for option in properties[field]["anyOf"]}

        assert types == {"number", "null"}


def test_unexpected_database_error_returns_500(monkeypatch):
    def fake_get_network_funnel_trend(*, start=None, end=None):
        raise RuntimeError("unexpected failure")

    monkeypatch.setattr(
        api,
        "get_network_funnel_trend",
        fake_get_network_funnel_trend,
    )

    response = client.get("/performance/funnel/trend")

    assert response.status_code == 500
