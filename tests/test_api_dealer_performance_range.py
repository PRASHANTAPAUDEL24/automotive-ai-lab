"""
API tests for dealer performance history range filtering.

Day 20 adds optional inclusive start and end query parameters while
preserving the existing full-history endpoint behavior.
"""

import pytest
from fastapi.testclient import TestClient

import api
from api import app, to_records
from db import InvalidMonthError, get_dealer_performance_history

client = TestClient(
    app,
    raise_server_exceptions=False,
)


def test_no_range_preserves_full_history():
    """
    Return the complete 24-month history when no bounds are supplied.
    """
    response = client.get("/dealers/101/performance")

    assert response.status_code == 200

    body = response.json()

    assert len(body) == 24
    assert body[0]["month"] == "2024-10"
    assert body[-1]["month"] == "2026-09"


def test_start_only_is_inclusive():
    """
    Include the requested start month through the latest available month.
    """
    response = client.get(
        "/dealers/101/performance",
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
    """
    Include the requested end month from the earliest available month.
    """
    response = client.get(
        "/dealers/101/performance",
        params={"end": "2024-12"},
    )

    assert response.status_code == 200

    assert [row["month"] for row in response.json()] == [
        "2024-10",
        "2024-11",
        "2024-12",
    ]


def test_both_bounds_are_inclusive():
    """
    Include both the start and end months in a bounded history request.
    """
    response = client.get(
        "/dealers/101/performance",
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
    """
    Accept a one-month inclusive range.
    """
    response = client.get(
        "/dealers/101/performance",
        params={
            "start": "2025-03",
            "end": "2025-03",
        },
    )

    assert response.status_code == 200

    assert [row["month"] for row in response.json()] == [
        "2025-03",
    ]


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
        {
            "start": "2030-01",
        },
        {
            "end": "2020-12",
        },
    ],
)
def test_real_dealer_with_empty_window_returns_empty(params):
    """
    Return 200 and an empty list when a real dealer has no rows in the range.
    """
    response = client.get(
        "/dealers/101/performance",
        params=params,
    )

    assert response.status_code == 200
    assert response.json() == []


def test_unknown_dealer_with_range_returns_404():
    """
    Preserve 404 for an unknown dealer even when range parameters are supplied.
    """
    response = client.get(
        "/dealers/999/performance",
        params={
            "start": "2030-01",
            "end": "2030-12",
        },
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "Dealer 999 not found"}


@pytest.mark.parametrize(
    ("start", "end"),
    [
        ("2026-09", "2026-08"),
        ("2025-12", "2025-01"),
    ],
)
def test_start_after_end_returns_422(start, end):
    """
    Return 422 with the range-specific error when start is after end.
    """
    response = client.get(
        "/dealers/101/performance",
        params={
            "start": start,
            "end": end,
        },
    )

    assert response.status_code == 422
    assert response.json() == {"detail": "start month must not be after end month"}


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
    """
    Reject malformed start values at the FastAPI query-validation layer.
    """
    response = client.get(
        "/dealers/101/performance",
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
    """
    Reject malformed end values at the FastAPI query-validation layer.
    """
    response = client.get(
        "/dealers/101/performance",
        params={"end": end},
    )

    assert response.status_code == 422

    detail = response.json()["detail"]

    assert detail[0]["loc"] == [
        "query",
        "end",
    ]


@pytest.mark.parametrize(
    ("dealer_id", "start", "end"),
    [
        (101, "2024-10", "2024-12"),
        (111, "2025-03", "2025-08"),
        (125, "2026-01", "2026-09"),
        (140, "2024-10", "2026-09"),
    ],
)
def test_api_matches_database_range_result(
    dealer_id,
    start,
    end,
):
    """
    Return the same range records as the database query layer.
    """
    response = client.get(
        f"/dealers/{dealer_id}/performance",
        params={
            "start": start,
            "end": end,
        },
    )

    expected = to_records(
        get_dealer_performance_history(
            dealer_id,
            start=start,
            end=end,
        )
    )

    assert response.status_code == 200
    assert response.json() == expected


def test_existing_non_integer_dealer_id_still_returns_422():
    """
    Preserve FastAPI path validation for non-integer dealer ids.
    """
    response = client.get(
        "/dealers/abc/performance",
        params={"start": "2025-01"},
    )

    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == [
        "path",
        "dealer_id",
    ]


def test_invalid_month_error_from_database_layer_returns_422(monkeypatch):
    """
    Translate database-layer month validation errors to HTTP 422.
    """

    def raise_invalid_month(dealer_id, start=None, end=None):
        raise InvalidMonthError("start month must use YYYY-MM format")

    monkeypatch.setattr(
        api,
        "get_dealer_performance_history",
        raise_invalid_month,
    )

    response = client.get("/dealers/101/performance")

    assert response.status_code == 422
    assert response.json() == {"detail": "start month must use YYYY-MM format"}
