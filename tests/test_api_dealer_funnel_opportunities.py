"""Day 34 HTTP contract, with independent CSV oracle and integration checks."""

import pandas as pd
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from test_dealer_funnel_opportunities import (
    DEALERS,
    MONTHS,
    base_rows,
    leads_threshold,
    opportunity_rows,
)

import api
import db
from api import app

PATH = "/performance/funnel/opportunities"
MONTH = "2026-09"
client = TestClient(app, raise_server_exceptions=False)
FIELDS = [
    "dealer_id",
    "dealer_name",
    "region",
    "month",
    "leads",
    "units_sold",
    "dealer_lead_to_sale_pct",
    "regional_lead_to_sale_pct",
    "conversion_gap_pp",
    "estimated_opportunity_units",
    "rank",
]
INT_FIELDS = {"dealer_id", "leads", "units_sold", "rank"}
STRING_FIELDS = {"dealer_name", "region", "month"}
FLOAT_FIELDS = set(FIELDS) - INT_FIELDS - STRING_FIELDS
DESCRIPTIONS = {
    "dealer_id": "Unique dealer identifier",
    "dealer_name": "Dealer business name",
    "region": "Dealer sales region",
    "month": "Reporting month in YYYY-MM format",
    "leads": "Recorded monthly leads",
    "units_sold": "Actual monthly vehicle sales",
    "dealer_lead_to_sale_pct": "Dealer sales per 100 leads",
    "regional_lead_to_sale_pct": (
        "Regional ratio-of-sums conversion rate, including the dealer"
    ),
    "conversion_gap_pp": "Regional minus dealer conversion rate, in percentage points",
    "estimated_opportunity_units": (
        "Estimated additional units at the regional benchmark; not a sales forecast"
    ),
    "rank": "Global opportunity rank; 1 represents the largest estimated opportunity",
}


def valid_row(**overrides):
    row = {
        "dealer_id": 101,
        "dealer_name": "Test Dealer",
        "region": "Central",
        "month": MONTH,
        "leads": 150,
        "units_sold": 20,
        "dealer_lead_to_sale_pct": 20 * 100 / 150,
        "regional_lead_to_sale_pct": 20.123456789123,
        "conversion_gap_pp": 20.123456789123 - 20 * 100 / 150,
        "estimated_opportunity_units": 150 * 20.123456789123 / 100 - 20,
        "rank": 1,
    }
    row.update(overrides)
    return row


def patch_query(monkeypatch, function):
    monkeypatch.setattr(api, "get_dealer_funnel_opportunities", function, raising=False)


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
        for key in FLOAT_FIELDS:
            assert type(row[key]) is float
            assert row[key] == pytest.approx(float(wanted[key]), rel=1e-9, abs=1e-9)
    return actual


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
    assert_rows(
        client.get(PATH, params={"month": month}),
        opportunity_rows(base_rows(month)),
    )


@pytest.mark.parametrize("month", MONTHS)
def test_all_months_reconcile_with_database(month):
    expected = db.to_records(db.get_dealer_funnel_opportunities(month))
    assert assert_rows(client.get(PATH, params={"month": month}), expected) == expected


@pytest.mark.parametrize("limit", [1, 5, 40, 41, 2**31, 99_999_999_999, db.MAX_LIMIT])
def test_limit_matches_oracle(limit):
    assert_rows(
        client.get(PATH, params={"month": MONTH, "limit": limit}),
        opportunity_rows(base_rows(MONTH), limit=limit),
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
        opportunity_rows(base_rows(MONTH), min_leads=threshold, limit=limit),
    )


@pytest.mark.parametrize("threshold", [0, 2**31, 99_999_999_999, db.MAX_LIMIT])
def test_threshold_bigint_boundaries(threshold):
    assert_rows(
        client.get(PATH, params={"month": MONTH, "min_leads": threshold}),
        opportunity_rows(base_rows(MONTH), min_leads=threshold),
    )


def test_threshold_reranks_and_limit_preserves_filtered_prefix():
    # Choose a real month and threshold that removes an earlier-ranked dealer.
    cases = []
    for month in MONTHS:
        rows = base_rows(month)
        full = opportunity_rows(rows)
        original_ranks = {r["dealer_id"]: r["rank"] for r in full}
        for threshold in sorted({r["leads"] for r in full}):
            filtered = opportunity_rows(rows, min_leads=threshold)
            if len(filtered) >= 3 and any(
                r["rank"] != original_ranks[r["dealer_id"]] for r in filtered[:2]
            ):
                cases.append((month, threshold, filtered))
    assert cases, "CSV fixture must include a rank-changing threshold"
    month, threshold, filtered = cases[0]
    params = {"month": month, "min_leads": threshold}
    full = assert_rows(client.get(PATH, params=params), filtered)
    prefix = assert_rows(client.get(PATH, params={**params, "limit": 2}), filtered[:2])
    assert prefix == full[:2]
    assert [row["rank"] for row in prefix] == [1, 2]


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

    def fake(*args, **kwargs):
        calls.append((args, kwargs))
        return pd.DataFrame(columns=FIELDS)

    patch_query(monkeypatch, fake)
    assert_rows(client.get(PATH, params={"month": MONTH, **extra}), [])
    assert calls == [((MONTH,), {"limit": limit, "min_leads": min_leads})]
    assert type(calls[0][0][0]) is str
    assert type(calls[0][1]["limit"]) is type(limit)
    assert type(calls[0][1]["min_leads"]) is int


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
    for value in ["0", "-1", "1.5", "abc", "true", "", str(2**63)]
]
INVALID_CASES += [
    ({"month": MONTH, "min_leads": value}, "min_leads")
    for value in ["-1", "1.5", "abc", "true", "", str(2**63)]
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
    detail = response.json()["detail"]
    assert isinstance(detail, list)
    assert any(item["loc"] == ["query", field] for item in detail)
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
        calls.append((args, kwargs))
        raise error_type(message)

    patch_query(monkeypatch, fake)
    response = client.get(PATH, params={"month": MONTH, "limit": 5, "min_leads": 10})
    assert response.status_code == status
    assert calls == [((MONTH,), {"limit": 5, "min_leads": 10})]
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


@pytest.mark.parametrize("ids", [(102, 101), (101, 102)])
def test_identical_float_opportunities_keep_authoritative_order(monkeypatch, ids):
    rows = [
        valid_row(
            dealer_id=dealer, rank=rank, estimated_opportunity_units=4906.144638401031
        )
        for rank, dealer in enumerate(ids, 1)
    ]
    patch_query(monkeypatch, lambda *a, **kw: pd.DataFrame(rows))
    assert assert_rows(client.get(PATH, params={"month": MONTH}), rows) == rows


def test_fractional_values_are_not_rounded_or_recomputed(monkeypatch):
    row = valid_row()
    patch_query(monkeypatch, lambda *a, **kw: pd.DataFrame([row]))
    assert assert_rows(client.get(PATH, params={"month": MONTH}), [row]) == [row]


def test_serialization_preserves_genuine_zero_values(monkeypatch):
    row = valid_row(
        units_sold=0,
        dealer_lead_to_sale_pct=0.0,
        regional_lead_to_sale_pct=15.0,
        conversion_gap_pp=15.0,
        estimated_opportunity_units=22.5,
    )
    patch_query(monkeypatch, lambda *a, **kw: pd.DataFrame([row]))
    assert_rows(client.get(PATH, params={"month": MONTH}), [row])


@pytest.mark.parametrize("field", FIELDS)
def test_missing_response_field_is_500(monkeypatch, field):
    row = valid_row()
    del row[field]
    patch_query(monkeypatch, lambda *a, **kw: pd.DataFrame([row]))
    assert client.get(PATH, params={"month": MONTH}).status_code == 500


@pytest.mark.parametrize("field", FIELDS)
def test_nonnullable_response_field_rejects_null(monkeypatch, field):
    patch_query(
        monkeypatch, lambda *a, **kw: pd.DataFrame([valid_row(**{field: None})])
    )
    assert client.get(PATH, params={"month": MONTH}).status_code == 500


@pytest.mark.parametrize("field", FIELDS)
def test_incompatible_response_type_is_500(monkeypatch, field):
    value = 123 if field in STRING_FIELDS else "invalid"
    patch_query(
        monkeypatch, lambda *a, **kw: pd.DataFrame([valid_row(**{field: value})])
    )
    assert client.get(PATH, params={"month": MONTH}).status_code == 500


@pytest.mark.parametrize("field", sorted(FLOAT_FIELDS))
def test_nan_in_required_metric_is_500(monkeypatch, field):
    patch_query(
        monkeypatch, lambda *a, **kw: pd.DataFrame([valid_row(**{field: float("nan")})])
    )
    assert client.get(PATH, params={"month": MONTH}).status_code == 500


@pytest.mark.parametrize(
    "statement",
    [
        "DELETE FROM sales_monthly WHERE month = :month",
        "UPDATE leads_monthly SET leads = 0 WHERE month = :month",
        "UPDATE sales_monthly SET units_sold = 0 WHERE month = :month",
    ],
)
def test_existing_month_without_exceptions(transaction_connection, statement):
    transaction_connection.execute(text(statement), {"month": MONTH})
    assert_rows(client.get(PATH, params={"month": MONTH}), [])


def test_sales_only_month_is_404(transaction_connection):
    transaction_connection.execute(
        text("DELETE FROM leads_monthly WHERE month = :month"), {"month": MONTH}
    )
    response = client.get(PATH, params={"month": MONTH})
    assert response.status_code == 404
    assert response.json() == {"detail": f"Month {MONTH} not found"}


@pytest.mark.parametrize("table", ["leads_monthly", "sales_monthly"])
def test_incomplete_region_is_excluded(transaction_connection, table):
    dealer_id = min(DEALERS)
    transaction_connection.execute(
        text(f"DELETE FROM {table} WHERE month = :month AND dealer_id = :dealer"),
        {"month": MONTH, "dealer": dealer_id},
    )
    rows = base_rows(MONTH)
    for row in rows:
        if row["dealer_id"] == dealer_id:
            if table == "leads_monthly":
                row.update(leads=None, test_drives=None)
            else:
                row.update(units_sold=None)
    expected = opportunity_rows(rows)
    assert expected
    result = assert_rows(client.get(PATH, params={"month": MONTH}), expected)
    assert DEALERS[dealer_id]["region"] not in {row["region"] for row in result}


def test_opportunities_delegates_to_shared_serializer(monkeypatch):
    row = valid_row()
    frame = pd.DataFrame([row])
    calls = []
    patch_query(monkeypatch, lambda *args, **kwargs: frame)
    original = api.to_records

    def capture(result):
        calls.append(result)
        return original(result)

    monkeypatch.setattr(api, "to_records", capture)
    assert_rows(client.get(PATH, params={"month": MONTH}), [row])
    assert len(calls) == 1
    assert calls[0] is frame


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
    assert response["items"]["$ref"] == "#/components/schemas/RankedDealerOpportunity"
    model = schema["components"]["schemas"]["RankedDealerOpportunity"]
    assert set(model["required"]) == set(FIELDS)
    assert list(model["properties"]) == FIELDS
    for field, prop in model["properties"].items():
        expected = (
            {"integer"}
            if field in INT_FIELDS
            else {"number"} if field in FLOAT_FIELDS else {"string"}
        )
        assert types_in(prop) == expected
        assert "default" not in prop
        assert prop["description"].rstrip(".") == DESCRIPTIONS[field]


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


@pytest.mark.parametrize(
    ("path", "params"),
    [
        ("/performance/funnel/ranking", {"month": MONTH}),
        ("/performance/funnel/trend", {}),
        ("/performance/funnel", {"month": MONTH}),
        ("/dealers/101/funnel", {}),
    ],
)
def test_existing_funnel_routes_still_work(path, params):
    response = client.get(path, params=params)
    assert response.status_code == 200
    assert isinstance(response.json(), list)
    assert response.json()
