# Program: test_api_dealer_performance.py
# Day 19: API tests for dealer-level monthly performance history.
# Created on: 2026-11-03
# Author: Prashanta Paudel
# Purpose: Validate the HTTP contract for GET /dealers/{dealer_id}/performance
# without changing the existing Day 18 API test file.

from pathlib import Path

import pandas as pd
import pytest
from fastapi.testclient import TestClient

import api
from api import app
from db import get_dealer_performance_history, get_engine, to_records

# Use the committed dealer source file rather than hardcoding the valid IDs.
DATA_DIR = Path(__file__).resolve().parents[1] / "data"

DEALER_IDS = pd.read_csv(DATA_DIR / "dealers.csv")["dealer_id"].tolist()


# The endpoint reuses the existing MonthlyPerformance response model.
EXPECTED_FIELDS = [
    "dealer_id",
    "dealer_name",
    "month",
    "units_sold",
    "target_units",
    "achievement_pct",
]


# Keep server exceptions inside the HTTP response so tests can verify
# that unexpected application errors correctly become HTTP 500 responses.
client = TestClient(
    app,
    raise_server_exceptions=False,
)


def test_dealer_performance_history_returns_complete_history():
    """
    A known dealer should return its complete 24-month history.

    The endpoint contract requires:
    - HTTP 200
    - exactly 24 rows
    - exactly the six MonthlyPerformance fields
    - oldest month first
    - only the requested dealer
    """

    response = client.get("/dealers/101/performance")

    assert response.status_code == 200

    data = response.json()

    assert len(data) == 24

    # Check the response-model fields exactly.
    assert list(data[0]) == EXPECTED_FIELDS

    # History must be chronological from oldest to newest.
    assert data[0]["month"] == "2024-10"
    assert data[-1]["month"] == "2026-09"

    months = [row["month"] for row in data]
    assert months == sorted(months)

    # The route must never leak another dealer's rows.
    assert all(row["dealer_id"] == 101 for row in data)


@pytest.mark.parametrize(
    "dealer_id",
    DEALER_IDS,
)
def test_every_dealer_returns_24_months(dealer_id):
    """
    Every dealer in the committed dealer list should be reachable
    through the API and should return all 24 available months.
    """

    response = client.get(f"/dealers/{dealer_id}/performance")

    assert response.status_code == 200
    assert len(response.json()) == 24


def test_dealer_performance_history_matches_db_layer():
    """
    The API should expose the DB-layer result without reshaping it.

    This protects the boundary between get_dealer_performance_history()
    and the HTTP response.
    """

    response = client.get("/dealers/101/performance")

    expected = to_records(get_dealer_performance_history(101))

    assert response.status_code == 200
    assert response.json() == expected


@pytest.mark.parametrize(
    "dealer_id",
    [
        999,
        0,
        -1,
        100,
        141,
        10**20,
    ],
)
def test_unknown_dealer_returns_404(dealer_id):
    """
    A syntactically valid integer that does not identify a real dealer
    should return the dedicated dealer-not-found response.

    The exact body matters: before this route exists, FastAPI itself
    returns {"detail": "Not Found"}, which must not make this test pass.
    """

    response = client.get(f"/dealers/{dealer_id}/performance")

    assert response.status_code == 404
    assert response.json() == {"detail": f"Dealer {dealer_id} not found"}


@pytest.mark.parametrize(
    "dealer_id",
    [
        "abc",
        "1.5",
        "1e3",
    ],
)
def test_non_integer_dealer_id_returns_422(dealer_id):
    """
    FastAPI should reject non-integer path parameters before the DB
    function is called.
    """

    response = client.get(f"/dealers/{dealer_id}/performance")

    assert response.status_code == 422

    detail = response.json()["detail"]

    # FastAPI validation errors are structured as a list.
    assert isinstance(detail, list)

    # Prove the failure came from path validation for dealer_id.
    assert detail[0]["loc"] == [
        "path",
        "dealer_id",
    ]


def test_dealer_performance_history_allows_null_fields(
    monkeypatch,
):
    """
    target_units and achievement_pct are nullable in MonthlyPerformance.

    A missing target should therefore serialize as JSON null instead
    of causing response-model validation to fail.
    """

    history = pd.DataFrame(
        [
            {
                "dealer_id": 101,
                "dealer_name": "Test Dealer",
                "month": "2026-09",
                "units_sold": 10,
                "target_units": None,
                "achievement_pct": None,
            }
        ]
    )

    monkeypatch.setattr(
        api,
        "get_dealer_performance_history",
        lambda dealer_id, start=None, end=None: history,
    )

    response = client.get("/dealers/101/performance")

    assert response.status_code == 200

    data = response.json()

    assert len(data) == 1
    assert data[0]["target_units"] is None
    assert data[0]["achievement_pct"] is None


def test_dealer_performance_history_invalid_response_returns_500(
    monkeypatch,
):
    """
    The MonthlyPerformance response model should reject invalid DB output.

    Using a clearly invalid units_sold value proves FastAPI/Pydantic
    still validates the response contract.
    """

    history = pd.DataFrame(
        [
            {
                "dealer_id": 101,
                "dealer_name": "Test Dealer",
                "month": "2026-09",
                "units_sold": "x",
                "target_units": 20,
                "achievement_pct": 50.0,
            }
        ]
    )

    monkeypatch.setattr(
        api,
        "get_dealer_performance_history",
        lambda dealer_id, start=None, end=None: history,
    )

    response = client.get("/dealers/101/performance")

    assert response.status_code == 500


def test_dealer_performance_history_missing_database_url_returns_500(
    monkeypatch,
):
    """
    An unrelated configuration ValueError must remain a server error.

    This protects against accidentally catching broad ValueError in the
    endpoint and incorrectly converting configuration failures into 404s.
    """

    monkeypatch.delenv(
        "DATABASE_URL",
        raising=False,
    )

    # Force get_engine() to read the environment again instead of
    # returning the engine cached by earlier tests.
    get_engine.cache_clear()

    response = client.get("/dealers/101/performance")

    assert response.status_code == 500
    assert "DATABASE_URL" not in response.text

    get_engine.cache_clear()


def test_existing_dealer_routes_still_work():
    """
    Adding the history route must not break existing /dealers routes.

    These checks protect the current at-risk endpoint and single-dealer
    endpoint from accidental routing regressions.
    """

    at_risk_response = client.get("/dealers/at-risk")
    dealer_response = client.get("/dealers/101")

    assert at_risk_response.status_code == 200
    assert dealer_response.status_code == 200
