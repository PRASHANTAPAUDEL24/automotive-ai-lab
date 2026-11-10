# Program: tests/test_api.py
# Day 11: pytest tests for FastAPI endpoints
# Created on: 2026-11-01
# Author: Prashanta Paudel
# Purpose: Validate API responses, filtering, error handling,
# and JSON-safe conversion.

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from api import app
from db import InvalidMonthError, get_engine, to_records

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


def test_dealer_endpoint_returns_111():
    response = client.get("/dealers/111")

    assert response.status_code == 200

    dealer = response.json()

    assert dealer["dealer_id"] == 111
    assert dealer["dealer_name"] == "Buffalo Sunset Vertex Automotive"
    assert dealer["combined_risk"] is True


def test_get_unknown_dealer_returns_404():
    response = client.get("/dealers/999")

    assert response.status_code == 404
    assert response.json() == {"detail": "Dealer 999 not found"}


def test_get_dealer_with_non_integer_id_returns_422():
    response = client.get("/dealers/abc")

    assert response.status_code == 422


def test_dealer_response_has_expected_fields():
    response = client.get("/dealers/111")

    assert response.status_code == 200

    assert set(response.json().keys()) == {
        "dealer_id",
        "dealer_name",
        "region",
        "size_class",
        "units_sold",
        "target_units",
        "achievement_pct",
        "available_units",
        "aged_units",
        "avg_days_available",
        "aged_pct",
        "months_of_supply",
        "high_supply",
        "inventory_risk",
        "sales_risk",
        "combined_risk",
        "early_overstock_watch",
    }


def test_invalid_dealer_response_returns_500(monkeypatch):
    bad_dealer = {
        "dealer_id": "not-a-number",
        "dealer_name": "Buffalo Sunset Vertex Automotive",
        "region": "Northeast",
        "size_class": "Medium",
        "units_sold": 10,
        "target_units": 20,
        "achievement_pct": 50.0,
        "available_units": 25,
        "aged_units": 5,
        "avg_days_available": 40.0,
        "aged_pct": 20.0,
        "months_of_supply": 2.5,
        "high_supply": False,
        "inventory_risk": False,
        "sales_risk": True,
        "combined_risk": False,
        "early_overstock_watch": False,
    }

    monkeypatch.setattr(
        "api.get_dealer",
        lambda dealer_id: bad_dealer,
    )

    test_client = TestClient(
        app,
        raise_server_exceptions=False,
    )

    response = test_client.get("/dealers/111")

    assert response.status_code == 500


def test_dealer_with_null_fields_returns_200(monkeypatch):
    dealer_with_nulls = {
        "dealer_id": 111,
        "dealer_name": "Buffalo Sunset Vertex Automotive",
        "region": "Northeast",
        "size_class": "Medium",
        "units_sold": 0,
        "target_units": None,
        "achievement_pct": None,
        "available_units": 0,
        "aged_units": 0,
        "avg_days_available": None,
        "aged_pct": None,
        "months_of_supply": None,
        "high_supply": False,
        "inventory_risk": False,
        "sales_risk": False,
        "combined_risk": False,
        "early_overstock_watch": False,
    }

    monkeypatch.setattr(
        "api.get_dealer",
        lambda dealer_id: dealer_with_nulls,
    )

    response = client.get("/dealers/111")

    assert response.status_code == 200

    data = response.json()

    assert data["target_units"] is None
    assert data["achievement_pct"] is None
    assert data["avg_days_available"] is None
    assert data["aged_pct"] is None
    assert data["months_of_supply"] is None


def test_region_summary_endpoint_returns_five_regions():
    response = client.get("/regions/summary")

    assert response.status_code == 200
    assert len(response.json()) == 5


def test_region_summary_endpoint_west_values():
    response = client.get("/regions/summary")

    assert response.status_code == 200

    west = next(region for region in response.json() if region["region"] == "West")

    assert west["dealers"] == 8
    assert west["sales_risk_dealers"] == 2
    assert west["inventory_risk_dealers"] == 2
    assert west["combined_risk_dealers"] == 0
    assert west["early_overstock_watch_dealers"] == 2


def test_region_summary_response_has_expected_fields():
    response = client.get("/regions/summary")

    assert response.status_code == 200

    assert set(response.json()[0].keys()) == {
        "region",
        "dealers",
        "sales_risk_dealers",
        "inventory_risk_dealers",
        "combined_risk_dealers",
        "early_overstock_watch_dealers",
    }


def test_at_risk_endpoint_returns_twenty_dealers():
    response = client.get("/dealers/at-risk")

    assert response.status_code == 200

    data = response.json()

    assert len(data) == 20
    assert data[0]["dealer_id"] == 111
    assert data[0]["rank"] == 1
    assert data[0]["risk_tier"] == 1
    assert [dealer["rank"] for dealer in data] == list(range(1, 21))


def test_at_risk_endpoint_limit_five():
    response = client.get(
        "/dealers/at-risk",
        params={"limit": 5},
    )

    assert response.status_code == 200

    data = response.json()

    assert len(data) == 5
    assert [dealer["rank"] for dealer in data] == [1, 2, 3, 4, 5]


def test_at_risk_endpoint_rejects_zero_limit():
    response = client.get(
        "/dealers/at-risk",
        params={"limit": 0},
    )

    assert response.status_code == 422


def test_at_risk_endpoint_rejects_non_integer_limit():
    response = client.get(
        "/dealers/at-risk",
        params={"limit": "Not a number"},
    )

    assert response.status_code == 422


def test_at_risk_response_has_expected_fields():
    response = client.get(
        "/dealers/at-risk",
        params={"limit": 1},
    )

    assert response.status_code == 200

    assert set(response.json()[0].keys()) == {
        "dealer_id",
        "dealer_name",
        "region",
        "size_class",
        "units_sold",
        "target_units",
        "achievement_pct",
        "available_units",
        "aged_units",
        "avg_days_available",
        "aged_pct",
        "months_of_supply",
        "high_supply",
        "inventory_risk",
        "sales_risk",
        "combined_risk",
        "early_overstock_watch",
        "rank",
        "risk_tier",
    }


def test_performance_endpoint_returns_40_dealers():
    response = client.get(
        "/performance",
        params={"month": "2026-03"},
    )

    assert response.status_code == 200

    data = response.json()

    assert len(data) == 40
    assert all(row["month"] == "2026-03" for row in data)


def test_performance_response_has_expected_fields():
    response = client.get(
        "/performance",
        params={"month": "2026-03"},
    )

    assert response.status_code == 200

    assert set(response.json()[0].keys()) == {
        "dealer_id",
        "dealer_name",
        "month",
        "units_sold",
        "target_units",
        "achievement_pct",
    }


def test_performance_dealers_are_sorted_by_id():
    response = client.get(
        "/performance",
        params={"month": "2026-03"},
    )

    assert response.status_code == 200

    dealer_ids = [row["dealer_id"] for row in response.json()]

    assert dealer_ids == sorted(dealer_ids)


def test_performance_missing_month_returns_422():
    response = client.get("/performance")

    assert response.status_code == 422


@pytest.mark.parametrize(
    "month",
    [
        "2026-3",
        "2026-13",
        "2026-00",
        "202603",
        " 2026-03",
        "2026-03-01",
        "abc",
        "",
        "2026-03\n",
        "\u0662\u0660\u0662\u0666-03",
    ],
)
def test_performance_invalid_month_format_returns_422(month):
    response = client.get(
        "/performance",
        params={"month": month},
    )

    assert response.status_code == 422

    detail = response.json()["detail"]

    assert isinstance(detail, list)
    assert detail[0]["loc"] == ["query", "month"]


@pytest.mark.parametrize(
    "month",
    [
        "2024-09",
        "2026-10",
        "2030-01",
    ],
)
def test_performance_unknown_month_returns_404(month):
    response = client.get(
        "/performance",
        params={"month": month},
    )

    assert response.status_code == 404
    assert month in response.json()["detail"]


def test_performance_null_fields_are_allowed(monkeypatch):
    fake = pd.DataFrame(
        [
            {
                "dealer_id": 999,
                "dealer_name": "Test Dealer",
                "month": "2026-03",
                "units_sold": 0,
                "target_units": None,
                "achievement_pct": None,
            }
        ]
    )

    monkeypatch.setattr(
        "api.get_monthly_performance",
        lambda month: fake,
    )

    response = client.get(
        "/performance",
        params={"month": "2026-03"},
    )

    assert response.status_code == 200

    data = response.json()[0]

    assert data["target_units"] is None
    assert data["achievement_pct"] is None


def test_performance_invalid_response_returns_500(monkeypatch):
    fake = pd.DataFrame(
        [
            {
                "dealer_id": "not-a-number",
                "dealer_name": "Test Dealer",
                "month": "2026-03",
                "units_sold": 10,
                "target_units": 20,
                "achievement_pct": 50.0,
            }
        ]
    )

    monkeypatch.setattr(
        "api.get_monthly_performance",
        lambda month: fake,
    )

    test_client = TestClient(
        app,
        raise_server_exceptions=False,
    )

    response = test_client.get(
        "/performance",
        params={"month": "2026-03"},
    )

    assert response.status_code == 500


def test_performance_missing_database_url_returns_500(monkeypatch):
    get_engine.cache_clear()
    monkeypatch.delenv("DATABASE_URL", raising=False)

    test_client = TestClient(
        app,
        raise_server_exceptions=False,
    )

    response = test_client.get(
        "/performance",
        params={"month": "2026-09"},
    )

    assert response.status_code == 500
    assert "DATABASE_URL" not in response.text

    get_engine.cache_clear()


def test_performance_invalid_month_error_safety_net_returns_422(monkeypatch):
    def raise_invalid_month(month):
        raise InvalidMonthError(f"Invalid month: {month!r}. Expected YYYY-MM.")

    monkeypatch.setattr(
        "api.get_monthly_performance",
        raise_invalid_month,
    )

    response = client.get(
        "/performance",
        params={"month": "2026-03"},
    )

    assert response.status_code == 422
    assert response.json() == {"detail": "Invalid month: '2026-03'. Expected YYYY-MM."}


def test_performance_unknown_month_has_expected_detail():
    response = client.get(
        "/performance",
        params={"month": "2030-01"},
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "Month 2030-01 not found"}


@pytest.mark.parametrize(
    "month",
    [
        "2024-10",
        "2026-09",
    ],
)
def test_performance_boundary_months_return_40_dealers(month):
    response = client.get(
        "/performance",
        params={"month": month},
    )

    assert response.status_code == 200
    assert len(response.json()) == 40
    assert all(row["month"] == month for row in response.json())
