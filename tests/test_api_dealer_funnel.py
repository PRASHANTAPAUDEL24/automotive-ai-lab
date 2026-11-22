"""
API tests for dealer-level monthly lead-funnel history.

Day 31 exposes the dealer funnel history through an HTTP endpoint with
optional inclusive start/end bounds while preserving the database-layer
missing-data semantics.
"""

import pandas as pd
import pytest
from fastapi.testclient import TestClient

import api
import db
from api import app

client = TestClient(
    app,
    raise_server_exceptions=False,
)

EXPECTED_KEYS = {
    "dealer_id",
    "dealer_name",
    "month",
    "leads",
    "test_drives",
    "units_sold",
    "test_drive_rate_pct",
    "drive_to_sale_pct",
    "lead_to_sale_pct",
}


# ============================================================
# Baseline history behavior
# ============================================================


def test_no_range_returns_complete_24_month_history():
    response = client.get("/dealers/101/funnel")

    assert response.status_code == 200

    body = response.json()

    assert len(body) == 24
    assert body[0]["month"] == "2024-10"
    assert body[-1]["month"] == "2026-09"


def test_history_is_oldest_first():
    response = client.get("/dealers/101/funnel")

    assert response.status_code == 200

    months = [row["month"] for row in response.json()]

    assert months == sorted(months)


def test_response_has_exact_expected_fields():
    response = client.get(
        "/dealers/101/funnel",
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
    response = client.get("/dealers/101/funnel")

    assert response.status_code == 200

    expected = db.to_records(db.get_dealer_funnel_history(101))

    assert response.json() == expected


# ============================================================
# Inclusive range filtering
# ============================================================


def test_start_only_is_inclusive():
    response = client.get(
        "/dealers/101/funnel",
        params={"start": "2026-01"},
    )

    assert response.status_code == 200

    assert [row["month"] for row in response.json()] == [
        "2026-01",
        "2026-02",
        "2026-03",
        "2026-04",
        "2026-05",
        "2026-06",
        "2026-07",
        "2026-08",
        "2026-09",
    ]


def test_end_only_is_inclusive():
    response = client.get(
        "/dealers/101/funnel",
        params={"end": "2024-12"},
    )

    assert response.status_code == 200

    assert [row["month"] for row in response.json()] == [
        "2024-10",
        "2024-11",
        "2024-12",
    ]


def test_both_bounds_are_inclusive():
    response = client.get(
        "/dealers/101/funnel",
        params={
            "start": "2025-03",
            "end": "2025-05",
        },
    )

    assert response.status_code == 200

    assert [row["month"] for row in response.json()] == [
        "2025-03",
        "2025-04",
        "2025-05",
    ]


def test_equal_start_and_end_returns_one_month():
    response = client.get(
        "/dealers/101/funnel",
        params={
            "start": "2025-03",
            "end": "2025-03",
        },
    )

    assert response.status_code == 200

    assert [row["month"] for row in response.json()] == ["2025-03"]


@pytest.mark.parametrize(
    ("start", "end"),
    [
        ("2030-01", "2030-12"),
        ("2020-01", "2020-12"),
        ("2030-01", None),
        (None, "2020-12"),
    ],
)
def test_real_dealer_with_empty_window_returns_200_empty(
    start,
    end,
):
    params = {}

    if start is not None:
        params["start"] = start

    if end is not None:
        params["end"] = end

    response = client.get(
        "/dealers/101/funnel",
        params=params,
    )

    assert response.status_code == 200
    assert response.json() == []


# ============================================================
# Dealer existence
# ============================================================


@pytest.mark.parametrize(
    "dealer_id",
    [
        999,
        100,
        141,
    ],
)
def test_unknown_dealer_returns_404(dealer_id):
    response = client.get(f"/dealers/{dealer_id}/funnel")

    assert response.status_code == 404
    assert response.json() == {"detail": f"Dealer {dealer_id} not found"}


def test_unknown_dealer_with_empty_window_still_returns_404():
    response = client.get(
        "/dealers/999/funnel",
        params={
            "start": "2030-01",
            "end": "2030-12",
        },
    )

    assert response.status_code == 404

    assert response.json() == {"detail": "Dealer 999 not found"}


# ============================================================
# FastAPI month-format validation
# ============================================================


@pytest.mark.parametrize(
    "start",
    [
        "2026-9",
        "26-09",
        "2026/09",
        "2026-13",
        "2026-00",
        " 2026-01",
        "2026-01\n",
        "",
    ],
)
def test_malformed_start_is_rejected_by_fastapi(start):
    response = client.get(
        "/dealers/101/funnel",
        params={"start": start},
    )

    assert response.status_code == 422


@pytest.mark.parametrize(
    "end",
    [
        "2026-9",
        "26-09",
        "2026/09",
        "2026-13",
        "2026-00",
        " 2026-01",
        "2026-01\n",
        "",
    ],
)
def test_malformed_end_is_rejected_by_fastapi(end):
    response = client.get(
        "/dealers/101/funnel",
        params={"end": end},
    )

    assert response.status_code == 422


def test_reversed_range_returns_422():
    response = client.get(
        "/dealers/101/funnel",
        params={
            "start": "2026-09",
            "end": "2026-08",
        },
    )

    assert response.status_code == 422

    assert response.json() == {"detail": "start month must not be after end month"}


# ============================================================
# Explicit DB exception mapping
# ============================================================


def test_database_invalid_month_error_maps_to_422(
    monkeypatch,
):
    def fake_history(*args, **kwargs):
        raise db.InvalidMonthError("start month must use YYYY-MM format")

    monkeypatch.setattr(
        api,
        "get_dealer_funnel_history",
        fake_history,
    )

    response = client.get("/dealers/101/funnel")

    assert response.status_code == 422

    assert response.json() == {"detail": "start month must use YYYY-MM format"}


def test_database_invalid_range_error_maps_to_422(
    monkeypatch,
):
    def fake_history(*args, **kwargs):
        raise db.InvalidMonthRangeError("start month must not be after end month")

    monkeypatch.setattr(
        api,
        "get_dealer_funnel_history",
        fake_history,
    )

    response = client.get("/dealers/101/funnel")

    assert response.status_code == 422

    assert response.json() == {"detail": "start month must not be after end month"}


def test_database_dealer_not_found_maps_to_404(
    monkeypatch,
):
    def fake_history(*args, **kwargs):
        raise db.DealerNotFoundError("Dealer 101 not found")

    monkeypatch.setattr(
        api,
        "get_dealer_funnel_history",
        fake_history,
    )

    response = client.get("/dealers/101/funnel")

    assert response.status_code == 404

    assert response.json() == {"detail": "Dealer 101 not found"}


# ============================================================
# Nullable funnel response contract
# ============================================================


def test_nullable_lead_metrics_serialize_as_null(
    monkeypatch,
):
    frame = pd.DataFrame(
        [
            {
                "dealer_id": 101,
                "dealer_name": "Test Dealer",
                "month": "2026-09",
                "leads": None,
                "test_drives": None,
                "units_sold": 25,
                "test_drive_rate_pct": None,
                "drive_to_sale_pct": None,
                "lead_to_sale_pct": None,
            }
        ]
    )

    monkeypatch.setattr(
        api,
        "get_dealer_funnel_history",
        lambda *args, **kwargs: frame,
    )

    response = client.get("/dealers/101/funnel")

    assert response.status_code == 200

    row = response.json()[0]

    assert row["leads"] is None
    assert row["test_drives"] is None
    assert row["units_sold"] == 25
    assert row["test_drive_rate_pct"] is None
    assert row["drive_to_sale_pct"] is None
    assert row["lead_to_sale_pct"] is None


def test_nullable_sales_metrics_serialize_as_null(
    monkeypatch,
):
    frame = pd.DataFrame(
        [
            {
                "dealer_id": 101,
                "dealer_name": "Test Dealer",
                "month": "2026-09",
                "leads": 100,
                "test_drives": 40,
                "units_sold": None,
                "test_drive_rate_pct": 40.0,
                "drive_to_sale_pct": None,
                "lead_to_sale_pct": None,
            }
        ]
    )

    monkeypatch.setattr(
        api,
        "get_dealer_funnel_history",
        lambda *args, **kwargs: frame,
    )

    response = client.get("/dealers/101/funnel")

    assert response.status_code == 200

    row = response.json()[0]

    assert row["leads"] == 100
    assert row["test_drives"] == 40
    assert row["units_sold"] is None
    assert row["test_drive_rate_pct"] == pytest.approx(40.0)
    assert row["drive_to_sale_pct"] is None
    assert row["lead_to_sale_pct"] is None


def test_zero_values_are_not_converted_to_null(
    monkeypatch,
):
    frame = pd.DataFrame(
        [
            {
                "dealer_id": 101,
                "dealer_name": "Test Dealer",
                "month": "2026-09",
                "leads": 10,
                "test_drives": 0,
                "units_sold": 0,
                "test_drive_rate_pct": 0.0,
                "drive_to_sale_pct": None,
                "lead_to_sale_pct": 0.0,
            }
        ]
    )

    monkeypatch.setattr(
        api,
        "get_dealer_funnel_history",
        lambda *args, **kwargs: frame,
    )

    response = client.get("/dealers/101/funnel")

    assert response.status_code == 200

    row = response.json()[0]

    assert row["test_drives"] == 0
    assert row["units_sold"] == 0
    assert row["test_drive_rate_pct"] == pytest.approx(0.0)
    assert row["drive_to_sale_pct"] is None
    assert row["lead_to_sale_pct"] == pytest.approx(0.0)


# ============================================================
# Response-model protection
# ============================================================


def _valid_row(**overrides):
    row = {
        "dealer_id": 101,
        "dealer_name": "Test Dealer",
        "month": "2026-09",
        "leads": 100,
        "test_drives": 40,
        "units_sold": 20,
        "test_drive_rate_pct": 40.0,
        "drive_to_sale_pct": 50.0,
        "lead_to_sale_pct": 20.0,
    }
    row.update(overrides)

    return row


@pytest.mark.parametrize("field", sorted(EXPECTED_KEYS))
def test_missing_field_in_database_result_returns_500(
    monkeypatch,
    field,
):
    """Required-but-nullable: an absent key must fail, not become null."""
    frame = pd.DataFrame([_valid_row()]).drop(columns=[field])

    monkeypatch.setattr(
        api,
        "get_dealer_funnel_history",
        lambda *args, **kwargs: frame,
    )

    response = client.get("/dealers/101/funnel")

    assert response.status_code == 500


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("dealer_id", None),
        ("dealer_name", None),
        ("month", None),
        ("month", 202609),
        ("leads", "many"),
        ("lead_to_sale_pct", "high"),
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
        "get_dealer_funnel_history",
        lambda *args, **kwargs: frame,
    )

    response = client.get("/dealers/101/funnel")

    assert response.status_code == 500


def test_openapi_marks_all_fields_required_and_metrics_nullable():
    schema = app.openapi()["components"]["schemas"]["DealerMonthlyFunnel"]

    assert sorted(schema["required"]) == sorted(EXPECTED_KEYS)

    for field in (
        "leads",
        "test_drives",
        "units_sold",
        "test_drive_rate_pct",
        "drive_to_sale_pct",
        "lead_to_sale_pct",
    ):
        options = schema["properties"][field]["anyOf"]

        assert "null" in [option.get("type") for option in options]

    for field in (
        "dealer_id",
        "dealer_name",
        "month",
    ):
        assert "anyOf" not in schema["properties"][field]


def test_unexpected_database_error_returns_500(
    monkeypatch,
):
    def fake_history(*args, **kwargs):
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(
        api,
        "get_dealer_funnel_history",
        fake_history,
    )

    response = client.get("/dealers/101/funnel")

    assert response.status_code == 500


def test_numeric_nan_in_multi_row_result_serializes_as_null(
    monkeypatch,
):
    """
    A missing month among real rows turns numeric columns into float64
    with NaN. The route must still return JSON null for it.
    """
    frame = pd.DataFrame(
        [
            _valid_row(month="2026-08"),
            _valid_row(
                month="2026-09",
                leads=None,
                test_drives=None,
                test_drive_rate_pct=None,
                drive_to_sale_pct=None,
                lead_to_sale_pct=None,
            ),
        ]
    )

    assert frame["leads"].dtype == "float64"
    assert frame["test_drives"].dtype == "float64"

    monkeypatch.setattr(
        api,
        "get_dealer_funnel_history",
        lambda *args, **kwargs: frame,
    )

    response = client.get("/dealers/101/funnel")

    assert response.status_code == 200

    august, september = response.json()

    assert august["leads"] == 100
    assert august["test_drives"] == 40
    assert august["lead_to_sale_pct"] == pytest.approx(20.0)

    assert september["leads"] is None
    assert september["test_drives"] is None
    assert september["units_sold"] == 20
    assert september["test_drive_rate_pct"] is None
    assert september["drive_to_sale_pct"] is None
    assert september["lead_to_sale_pct"] is None


def test_openapi_field_types():
    properties = app.openapi()["components"]["schemas"]["DealerMonthlyFunnel"][
        "properties"
    ]

    assert properties["dealer_id"]["type"] == "integer"
    assert properties["dealer_name"]["type"] == "string"
    assert properties["month"]["type"] == "string"

    for field in (
        "leads",
        "test_drives",
        "units_sold",
    ):
        assert {"type": "integer"} in properties[field]["anyOf"]

    for field in (
        "test_drive_rate_pct",
        "drive_to_sale_pct",
        "lead_to_sale_pct",
    ):
        assert {"type": "number"} in properties[field]["anyOf"]
