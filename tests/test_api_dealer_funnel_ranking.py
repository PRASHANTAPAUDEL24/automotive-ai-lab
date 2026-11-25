"""Day 33 HTTP contract for monthly dealer funnel ranking.

Reuse the independent CSV oracle from the database tests, not production SQL.
"""

import pandas as pd
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from test_dealer_funnel_ranking import (
    DEALERS,
    MONTHS,
    base_rows,
    leads_threshold,
    rank_rows,
    tie_boundaries,
)

import api
import db
from api import app

PATH = "/performance/funnel/ranking"
MONTH = "2026-09"
client = TestClient(app, raise_server_exceptions=False)
FIELDS = [
    "dealer_id",
    "dealer_name",
    "region",
    "month",
    "leads",
    "test_drives",
    "units_sold",
    "test_drive_rate_pct",
    "drive_to_sale_pct",
    "lead_to_sale_pct",
    "rank",
]
INT_FIELDS = {"dealer_id", "leads", "test_drives", "units_sold", "rank"}
RATE_FIELDS = {"test_drive_rate_pct", "drive_to_sale_pct", "lead_to_sale_pct"}
STRING_FIELDS = {"dealer_name", "region", "month"}


def valid_row(**overrides):
    row = {
        "dealer_id": 101,
        "dealer_name": "Test Dealer",
        "region": "Central",
        "month": MONTH,
        "leads": 150,
        "test_drives": 120,
        "units_sold": 91,
        "test_drive_rate_pct": 80.0,
        "drive_to_sale_pct": 91 * 100 / 120,
        "lead_to_sale_pct": 91 * 100 / 150,
        "rank": 1,
    }
    row.update(overrides)
    return row


def patch_query(monkeypatch, function):
    monkeypatch.setattr(api, "get_dealer_funnel_ranking", function, raising=False)


def assert_rows(response, expected):
    assert response.status_code == 200, response.text
    actual = response.json()
    assert isinstance(actual, list)
    assert len(actual) == len(expected)
    for row, wanted in zip(actual, expected):
        assert list(row) == FIELDS
        for key in INT_FIELDS:
            assert type(row[key]) is int
            assert row[key] == wanted[key]
        for key in STRING_FIELDS:
            assert type(row[key]) is str
            assert row[key] == wanted[key]
        for key in RATE_FIELDS:
            if wanted[key] is None:
                assert row[key] is None
            else:
                assert type(row[key]) is float
                assert row[key] == pytest.approx(
                    float(wanted[key]), rel=1e-9, abs=1e-12
                )


@pytest.fixture
def transaction_connection(monkeypatch):
    with db.get_engine().connect() as connection:
        transaction = connection.begin()
        monkeypatch.setattr(db, "get_engine", lambda: connection)
        try:
            yield connection
        finally:
            transaction.rollback()


@pytest.mark.parametrize("month", MONTHS)
def test_all_months_match_independent_oracle(month):
    assert_rows(client.get(PATH, params={"month": month}), rank_rows(base_rows(month)))


@pytest.mark.parametrize("limit", [1, 5, 40, 41, 2**31, 99_999_999_999, db.MAX_LIMIT])
def test_limit_matches_oracle(limit):
    assert_rows(
        client.get(PATH, params={"month": MONTH, "limit": limit}),
        rank_rows(base_rows(MONTH), limit=limit),
    )


@pytest.mark.parametrize("label", ["median", "max", "above_max"])
@pytest.mark.parametrize("limit", [None, 5])
def test_threshold_and_limit(label, limit):
    threshold = leads_threshold(MONTH, label)
    params = {"month": MONTH, "min_leads": threshold}
    if limit is not None:
        params["limit"] = limit
    assert_rows(
        client.get(PATH, params=params),
        rank_rows(base_rows(MONTH), min_leads=threshold, limit=limit),
    )


TIE_CASES = [
    (month, k) for month in MONTHS for k in tie_boundaries(rank_rows(base_rows(month)))
]


@pytest.mark.parametrize(("month", "limit"), TIE_CASES)
def test_limit_cuts_exact_tie_deterministically(month, limit):
    assert_rows(
        client.get(PATH, params={"month": month, "limit": limit}),
        rank_rows(base_rows(month), limit=limit),
    )


@pytest.mark.parametrize("threshold", [0, 2**31, 99_999_999_999, db.MAX_LIMIT])
def test_threshold_bigint_boundaries(threshold):
    assert_rows(
        client.get(PATH, params={"month": MONTH, "min_leads": threshold}),
        rank_rows(base_rows(MONTH), min_leads=threshold),
    )


@pytest.mark.parametrize(
    ("extra", "limit", "min_leads"),
    [
        ({}, None, 0),
        ({"limit": 1}, 1, 0),
        ({"min_leads": 10}, None, 10),
        ({"limit": 5, "min_leads": 50}, 5, 50),
        (
            {"limit": db.MAX_LIMIT, "min_leads": db.MAX_LIMIT},
            db.MAX_LIMIT,
            db.MAX_LIMIT,
        ),
    ],
)
def test_exact_parameter_forwarding(monkeypatch, extra, limit, min_leads):
    calls = []

    def fake(month, limit=None, min_leads=0):
        calls.append((month, limit, min_leads, type(limit), type(min_leads)))
        return pd.DataFrame(columns=FIELDS)

    patch_query(monkeypatch, fake)
    response = client.get(PATH, params={"month": MONTH, **extra})
    assert response.status_code == 200
    assert response.json() == []
    assert calls == [(MONTH, limit, min_leads, type(limit), int)]


INVALID_CASES = [({}, "month")]
INVALID_CASES += [
    ({"month": value}, "month")
    for value in [
        "",
        "2026-9",
        "2026-00",
        "2026-13",
        "2026-09\n",
        " 2026-09",
        "2026-09 ",
        "2026/09",
        "abcd",
        "２０２６-０９",
        "2026-０９",
        "202609",
    ]
]
INVALID_CASES += [
    ({"month": MONTH, "limit": value}, "limit")
    for value in [
        "0",
        "-1",
        "1.5",
        "abc",
        "true",
        "",
        str(2**63),
    ]
]
INVALID_CASES += [
    ({"month": MONTH, "min_leads": value}, "min_leads")
    for value in [
        "-1",
        "1.5",
        "abc",
        "true",
        "",
        str(2**63),
    ]
]


@pytest.mark.parametrize(("params", "field"), INVALID_CASES)
def test_invalid_query_rejected_before_database(monkeypatch, params, field):
    calls = []

    def fake(*args, **kwargs):
        calls.append((args, kwargs))
        return pd.DataFrame(columns=FIELDS)

    patch_query(monkeypatch, fake)
    response = client.get(PATH, params=params)
    assert response.status_code == 422
    assert any(item["loc"] == ["query", field] for item in response.json()["detail"])
    assert calls == []


def test_unknown_month_exact_404():
    response = client.get(PATH, params={"month": "2030-01"})
    assert response.status_code == 404
    assert response.json() == {"detail": "Month 2030-01 not found"}


@pytest.mark.parametrize(
    ("error_type", "message", "status"),
    [
        (db.InvalidMonthError, "Invalid month: '2026-09'. Expected YYYY-MM.", 422),
        (
            db.InvalidLimitError,
            f"Invalid limit: 5. Expected an integer between 1 and {db.MAX_LIMIT}.",
            422,
        ),
        (
            db.InvalidMinLeadsError,
            f"Invalid min_leads: 10. Expected an integer between 0 and {db.MAX_LIMIT}.",
            422,
        ),
        (db.MonthNotFoundError, "Month 2026-09 not found", 404),
    ],
)
def test_database_exception_mapping(monkeypatch, error_type, message, status):
    calls = []

    def fake(*args, **kwargs):
        calls.append(True)
        raise error_type(message)

    patch_query(monkeypatch, fake)
    response = client.get(PATH, params={"month": MONTH, "limit": 5, "min_leads": 10})
    assert response.status_code == status
    assert calls == [True]
    assert response.json() == {"detail": message}


@pytest.mark.parametrize(
    "error_type", [RuntimeError, ValueError, db.DealerNotFoundError]
)
def test_unexpected_exception_is_500(monkeypatch, error_type):
    def fake(*args, **kwargs):
        raise error_type("private internal diagnostic")

    patch_query(monkeypatch, fake)
    response = client.get(PATH, params={"month": MONTH})
    assert response.status_code == 500
    assert "private internal diagnostic" not in response.text


def test_mocked_rows_preserve_order_and_raw_rates(monkeypatch):
    rows = [
        valid_row(
            dealer_id=102,
            leads=178,
            test_drives=140,
            units_sold=108,
            test_drive_rate_pct=14000 / 178,
            drive_to_sale_pct=10800 / 140,
            lead_to_sale_pct=10800 / 178,
        ),
        valid_row(rank=2),
    ]
    # The deliberately supplied order is authoritative at the HTTP boundary.
    patch_query(monkeypatch, lambda *a, **kw: pd.DataFrame(rows))
    assert_rows(client.get(PATH, params={"month": MONTH}), rows)


def test_nan_serializes_as_null_without_losing_zero(monkeypatch):
    rows = [
        valid_row(),
        valid_row(
            dealer_id=102,
            rank=2,
            leads=10,
            test_drives=0,
            units_sold=0,
            test_drive_rate_pct=0.0,
            drive_to_sale_pct=None,
            lead_to_sale_pct=0.0,
        ),
    ]
    frame = pd.DataFrame(rows)
    assert pd.isna(frame.loc[1, "drive_to_sale_pct"])
    patch_query(monkeypatch, lambda *a, **kw: frame)
    assert_rows(client.get(PATH, params={"month": MONTH}), rows)


@pytest.mark.parametrize("field", FIELDS)
def test_missing_response_field_is_500(monkeypatch, field):
    row = valid_row()
    del row[field]
    patch_query(monkeypatch, lambda *a, **kw: pd.DataFrame([row]))
    assert client.get(PATH, params={"month": MONTH}).status_code == 500


@pytest.mark.parametrize("field", [key for key in FIELDS if key != "drive_to_sale_pct"])
def test_nonnullable_response_field_rejects_null(monkeypatch, field):
    patch_query(
        monkeypatch, lambda *a, **kw: pd.DataFrame([valid_row(**{field: None})])
    )
    assert client.get(PATH, params={"month": MONTH}).status_code == 500


@pytest.mark.parametrize("field", sorted(INT_FIELDS | RATE_FIELDS))
def test_invalid_numeric_response_is_500(monkeypatch, field):
    patch_query(
        monkeypatch, lambda *a, **kw: pd.DataFrame([valid_row(**{field: "invalid"})])
    )
    assert client.get(PATH, params={"month": MONTH}).status_code == 500


@pytest.mark.parametrize(
    "statement",
    [
        "DELETE FROM sales_monthly WHERE month = :month",
        "UPDATE leads_monthly SET leads = 0 WHERE month = :month",
    ],
)
def test_existing_month_without_eligible_dealers(transaction_connection, statement):
    transaction_connection.execute(text(statement), {"month": MONTH})
    assert_rows(client.get(PATH, params={"month": MONTH}), [])


def test_sales_only_month_is_404(transaction_connection):
    transaction_connection.execute(
        text("DELETE FROM leads_monthly WHERE month = :month"), {"month": MONTH}
    )
    response = client.get(PATH, params={"month": MONTH})
    assert response.status_code == 404
    assert response.json() == {"detail": f"Month {MONTH} not found"}


def test_real_zero_drives_keeps_dealer_and_null_rate(transaction_connection):
    dealer_id = min(DEALERS)
    transaction_connection.execute(
        text(
            "UPDATE leads_monthly SET test_drives = 0 WHERE month = :month AND dealer_id = :dealer_id"
        ),
        {"month": MONTH, "dealer_id": dealer_id},
    )
    rows = base_rows(MONTH)
    for row in rows:
        if row["dealer_id"] == dealer_id:
            row.update(test_drives=0, test_drive_rate_pct=0, drive_to_sale_pct=None)
    assert_rows(client.get(PATH, params={"month": MONTH}), rank_rows(rows))


def types_in(schema):
    if "anyOf" in schema:
        return {kind for option in schema["anyOf"] for kind in types_in(option)}
    return {schema.get("type")}


def test_openapi_response_contract():
    schema = app.openapi()
    response = schema["paths"][PATH]["get"]["responses"]["200"]["content"][
        "application/json"
    ]["schema"]
    assert response["type"] == "array"
    assert response["items"]["$ref"] == "#/components/schemas/RankedDealerFunnel"
    model = schema["components"]["schemas"]["RankedDealerFunnel"]
    assert set(model["required"]) == set(FIELDS)
    assert list(model["properties"]) == FIELDS
    for field, prop in model["properties"].items():
        expected = (
            {"integer"}
            if field in INT_FIELDS
            else {"number"} if field in RATE_FIELDS else {"string"}
        )
        if field == "drive_to_sale_pct":
            expected.add("null")
        assert types_in(prop) == expected


def test_openapi_query_contract():
    params = {p["name"]: p for p in app.openapi()["paths"][PATH]["get"]["parameters"]}
    assert set(params) == {"month", "limit", "min_leads"}
    assert all(p["in"] == "query" for p in params.values())
    assert params["month"]["required"] is True
    assert params["month"]["schema"]["type"] == "string"
    assert params["month"]["schema"]["pattern"] == db.MONTH_QUERY_PATTERN
    for name, minimum in [("limit", 1), ("min_leads", 0)]:
        assert params[name]["required"] is False
        schema = params[name]["schema"]
        assert types_in(schema) == (
            {"integer", "null"} if name == "limit" else {"integer"}
        )
        integer = next(
            s for s in schema.get("anyOf", [schema]) if s.get("type") == "integer"
        )
        assert integer["minimum"] == minimum
        assert integer["maximum"] == db.MAX_LIMIT
        assert schema.get("default") == (None if name == "limit" else 0)


def test_ranking_delegates_to_shared_serializer(monkeypatch):
    """Preserve the shared null-safe serialization contract."""
    row = valid_row()
    frame = pd.DataFrame([row])
    calls = []

    patch_query(monkeypatch, lambda *args, **kwargs: frame)

    original_serializer = api.to_records

    def capture_serializer(result):
        calls.append(result)
        return original_serializer(result)

    monkeypatch.setattr(api, "to_records", capture_serializer)

    response = client.get(PATH, params={"month": MONTH})

    assert_rows(response, [row])
    assert len(calls) == 1
    assert calls[0] is frame
