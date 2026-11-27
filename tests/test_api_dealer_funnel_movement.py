"""Day 35 HTTP contract for dealer funnel movement, with an independent oracle."""

import pandas as pd
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from test_dealer_funnel_movement import (
    COMPARISON_MONTHS,
    EXPECTED_COLUMNS,
    IDS,
    MONTH,
    PRIOR,
    expected_for,
    movement_rows,
    previous_month,
    shaped_pair,
)
from test_dealer_funnel_opportunities import DEALERS, LEADS, MONTHS, base_rows

import api
import db
from api import app

PATH = "/performance/funnel/movement"
FIELDS = EXPECTED_COLUMNS
INT_FIELDS = {
    "dealer_id",
    "leads",
    "prior_leads",
    "units_sold",
    "prior_units_sold",
    "rank",
}
STRING_FIELDS = {"dealer_name", "region", "month", "prior_month"}
FLOAT_FIELDS = set(FIELDS) - INT_FIELDS - STRING_FIELDS
DESCRIPTIONS = {
    "dealer_id": "Unique dealer identifier",
    "dealer_name": "Dealer business name",
    "region": "Dealer sales region",
    "month": "Reporting month in YYYY-MM format",
    "prior_month": "Immediately preceding calendar month in YYYY-MM format",
    "leads": "Recorded leads in the reporting month",
    "prior_leads": "Recorded leads in the prior month",
    "units_sold": "Aggregated vehicle sales in the reporting month",
    "prior_units_sold": "Aggregated vehicle sales in the prior month",
    "conversion_pct": "Reporting-month sales per 100 leads",
    "prior_conversion_pct": "Prior-month sales per 100 leads",
    "conversion_change_pp": (
        "Reporting-month minus prior-month conversion rate, in percentage points; "
        "negative values are deterioration"
    ),
    "rank": "Global movement rank; 1 represents the largest deterioration",
}
client = TestClient(app, raise_server_exceptions=False)


def valid_row(**overrides):
    row = {
        "dealer_id": 101,
        "dealer_name": "Test Dealer",
        "region": "Central",
        "month": MONTH,
        "prior_month": PRIOR,
        "leads": 150,
        "prior_leads": 140,
        "units_sold": 20,
        "prior_units_sold": 28,
        "conversion_pct": 20 * 100 / 150,
        "prior_conversion_pct": 28 * 100 / 140,
        "conversion_change_pp": 20 * 100 / 150 - 28 * 100 / 140,
        "rank": 1,
    }
    row.update(overrides)
    return row


def patch_query(monkeypatch, function):
    monkeypatch.setattr(api, "get_dealer_funnel_movement", function, raising=False)


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
            # Zero and tiny signed changes must not be masked by absolute tolerance.
            assert row[key] == pytest.approx(float(wanted[key]), rel=1e-12, abs=0)
    return actual


def both_months_threshold(month, label):
    prior = previous_month(month)
    counts = sorted(min(LEADS[(i, month)][0], LEADS[(i, prior)][0]) for i in IDS)
    return {
        "median": counts[len(counts) // 2],
        "max": counts[-1],
        "above_max": counts[-1] + 1,
    }[label]


@pytest.fixture
def transaction_connection(monkeypatch):
    with db.get_engine().connect() as connection:
        transaction = connection.begin()
        monkeypatch.setattr(db, "get_engine", lambda: connection)
        try:
            yield connection
        finally:
            transaction.rollback()


@pytest.mark.parametrize("month", COMPARISON_MONTHS)
def test_all_comparison_months_match_independent_oracle(month):
    assert_rows(client.get(PATH, params={"month": month}), expected_for(month))


@pytest.mark.parametrize("month", COMPARISON_MONTHS)
def test_all_comparison_months_reconcile_with_database(month):
    expected = db.to_records(db.get_dealer_funnel_movement(month))
    assert assert_rows(client.get(PATH, params={"month": month}), expected) == expected


@pytest.mark.parametrize("limit", [1, 5, 40, 41, 2**31, 99_999_999_999, db.MAX_LIMIT])
def test_limit_matches_oracle(limit):
    assert_rows(
        client.get(PATH, params={"month": MONTH, "limit": limit}),
        expected_for(MONTH, limit=limit),
    )


@pytest.mark.parametrize("label", ["median", "max", "above_max"])
@pytest.mark.parametrize("limit", [None, 5])
def test_threshold_and_limit(label, limit):
    threshold = both_months_threshold(MONTH, label)
    params = {"month": MONTH, "min_leads": threshold}
    if limit is not None:
        params["limit"] = limit
    assert_rows(
        client.get(PATH, params=params),
        expected_for(MONTH, min_leads=threshold, limit=limit),
    )


@pytest.mark.parametrize("threshold", [0, 2**31, 99_999_999_999, db.MAX_LIMIT])
def test_threshold_bigint_boundaries(threshold):
    assert_rows(
        client.get(PATH, params={"month": MONTH, "min_leads": threshold}),
        expected_for(MONTH, min_leads=threshold),
    )


def test_threshold_reranks_and_limit_preserves_filtered_prefix():
    cases = []
    for month in COMPARISON_MONTHS:
        full = expected_for(month)
        original_ranks = {row["dealer_id"]: row["rank"] for row in full}
        prior = previous_month(month)
        thresholds = sorted(
            {min(LEADS[(i, month)][0], LEADS[(i, prior)][0]) for i in IDS}
        )
        for threshold in thresholds:
            filtered = expected_for(month, min_leads=threshold)
            if len(filtered) >= 3 and any(
                row["rank"] != original_ranks[row["dealer_id"]] for row in filtered[:2]
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


@pytest.mark.parametrize("month", ["2026-10", "2030-01"])
def test_absent_month_exact_404(month):
    response = client.get(PATH, params={"month": month})
    assert response.status_code == 404
    assert response.json() == {"detail": f"Month {month} not found"}


def test_first_data_month_has_no_prior_and_is_404():
    first = MONTHS[0]
    response = client.get(PATH, params={"month": first})
    assert response.status_code == 404
    assert response.json() == {"detail": f"Month {previous_month(first)} not found"}
    assert response.json() == {"detail": "Month 2024-09 not found"}


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
        (db.MonthNotFoundError, "Month 2026-08 not found", 404),
        (db.MonthNotFoundError, "Month preceding 0000-01 not found", 404),
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
def test_identical_float_movements_keep_authoritative_order(monkeypatch, ids):
    # Distinct exact movements can collide as floats; the database order is final.
    rows = [
        valid_row(dealer_id=dealer, rank=rank, conversion_change_pp=-1.5)
        for rank, dealer in enumerate(ids, 1)
    ]
    patch_query(monkeypatch, lambda *a, **kw: pd.DataFrame(rows))
    assert assert_rows(client.get(PATH, params={"month": MONTH}), rows) == rows


@pytest.mark.parametrize("change", [-12.345678912345, 0.0, 4.7e-36, -4.7e-36, 7.25])
def test_signed_and_tiny_values_are_not_rounded_or_recomputed(monkeypatch, change):
    row = valid_row(conversion_change_pp=change)
    patch_query(monkeypatch, lambda *a, **kw: pd.DataFrame([row]))
    assert assert_rows(client.get(PATH, params={"month": MONTH}), [row]) == [row]


def test_serialization_preserves_genuine_zero_values(monkeypatch):
    row = valid_row(
        units_sold=0,
        prior_units_sold=0,
        conversion_pct=0.0,
        prior_conversion_pct=0.0,
        conversion_change_pp=0.0,
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
    ("statement", "target"),
    [
        ("DELETE FROM sales_monthly WHERE month = :month", MONTH),
        ("DELETE FROM sales_monthly WHERE month = :month", PRIOR),
        ("UPDATE leads_monthly SET leads = 0 WHERE month = :month", MONTH),
        ("UPDATE leads_monthly SET leads = 0 WHERE month = :month", PRIOR),
    ],
)
def test_existing_months_without_comparable_dealers_are_empty_200(
    transaction_connection, statement, target
):
    transaction_connection.execute(text(statement), {"month": target})
    assert_rows(client.get(PATH, params={"month": MONTH}), [])


@pytest.mark.parametrize("missing", [MONTH, PRIOR])
def test_sales_only_month_is_404(transaction_connection, missing):
    transaction_connection.execute(
        text("DELETE FROM leads_monthly WHERE month = :month"), {"month": missing}
    )
    response = client.get(PATH, params={"month": MONTH})
    assert response.status_code == 404
    assert response.json() == {"detail": f"Month {missing} not found"}


@pytest.mark.parametrize("which", ["current", "prior"])
def test_incomplete_dealer_only_is_excluded(transaction_connection, which):
    dealer_id = min(DEALERS)
    month = MONTH if which == "current" else PRIOR
    transaction_connection.execute(
        text("DELETE FROM sales_monthly WHERE month = :month AND dealer_id = :dealer"),
        {"month": month, "dealer": dealer_id},
    )
    current, prior = base_rows(MONTH), base_rows(PRIOR)
    for row in current if which == "current" else prior:
        if row["dealer_id"] == dealer_id:
            row["units_sold"] = None
    expected = movement_rows(current, prior)
    assert len(expected) == len(IDS) - 1
    result = assert_rows(client.get(PATH, params={"month": MONTH}), expected)
    assert dealer_id not in {row["dealer_id"] for row in result}


def test_zero_sales_zero_movement_and_signed_order_through_http(transaction_connection):
    ids = IDS[:4]
    current, prior = shaped_pair(
        transaction_connection,
        {
            ids[0]: ((100, 0), (100, 0)),
            ids[1]: ((100, 10), (100, 20)),
            ids[2]: ((100, 30), (100, 10)),
            ids[3]: ((100, 5), (100, 15)),
        },
    )
    expected = movement_rows(current, prior)
    assert [row["conversion_change_pp"] for row in expected][2] == 0
    result = assert_rows(client.get(PATH, params={"month": MONTH}), expected)
    assert [row["dealer_id"] for row in result] == [ids[1], ids[3], ids[0], ids[2]]
    assert result[2]["conversion_change_pp"] == 0.0
    assert [row["rank"] for row in result] == [1, 2, 3, 4]


def test_omitted_min_leads_is_zero_and_threshold_applies_to_both_months(
    transaction_connection,
):
    low_current, low_prior, exact, high = IDS[:4]
    current, prior = shaped_pair(
        transaction_connection,
        {
            low_current: ((5, 1), (40, 4)),
            low_prior: ((40, 4), (5, 1)),
            exact: ((10, 1), (10, 2)),
            high: ((50, 5), (60, 12)),
        },
    )

    def ids(rows):
        return {row["dealer_id"] for row in rows}

    omitted = assert_rows(
        client.get(PATH, params={"month": MONTH}), movement_rows(current, prior)
    )
    explicit_zero = assert_rows(
        client.get(PATH, params={"month": MONTH, "min_leads": 0}),
        movement_rows(current, prior, min_leads=0),
    )
    assert omitted == explicit_zero
    assert ids(omitted) == {low_current, low_prior, exact, high}

    ten = assert_rows(
        client.get(PATH, params={"month": MONTH, "min_leads": 10}),
        movement_rows(current, prior, min_leads=10),
    )
    assert ids(ten) == {exact, high}
    assert [row["rank"] for row in ten] == [1, 2]

    eleven = assert_rows(
        client.get(PATH, params={"month": MONTH, "min_leads": 11}),
        movement_rows(current, prior, min_leads=11),
    )
    assert ids(eleven) == {high}
    assert [row["rank"] for row in eleven] == [1]


def test_movement_delegates_to_shared_serializer(monkeypatch):
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
    assert response["items"]["$ref"] == "#/components/schemas/RankedDealerMovement"
    model = schema["components"]["schemas"]["RankedDealerMovement"]
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
        ("/performance/funnel/opportunities", {"month": MONTH}),
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
