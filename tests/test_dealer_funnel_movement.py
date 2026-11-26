"""Day 35: signed dealer conversion movement, with an independent CSV oracle.

The prior month is the immediately preceding calendar month. Both observations
must have positive leads and aggregated sales, with inclusive thresholds.
Rank exact percentage-point changes ascending, then dealer ID; limit afterward.
The query uses one SQL statement, even for missing months and empty results.
No test imports the not-yet-implemented function during collection.
"""

import re
from contextlib import contextmanager
from datetime import date, timedelta
from fractions import Fraction
from itertools import pairwise

import pandas as pd
import pytest
from sqlalchemy import event, text
from test_dealer_funnel_opportunities import DEALERS, LEADS, MONTHS, SALES, base_rows

import db

EXPECTED_COLUMNS = [
    "dealer_id",
    "dealer_name",
    "region",
    "month",
    "prior_month",
    "leads",
    "prior_leads",
    "units_sold",
    "prior_units_sold",
    "conversion_pct",
    "prior_conversion_pct",
    "conversion_change_pp",
    "rank",
]
FLOAT_COLUMNS = ["conversion_pct", "prior_conversion_pct", "conversion_change_pp"]
INTEGER_COLUMNS = [
    "dealer_id",
    "leads",
    "prior_leads",
    "units_sold",
    "prior_units_sold",
    "rank",
]
COMPARISON_MONTHS = MONTHS[1:]
MONTH = MONTHS[-1]
PRIOR = MONTHS[-2]
IDS = sorted(DEALERS)
MAX_INT = 2**31 - 1


def previous_month(month):
    """Independent calendar oracle for the committed, positive-year dataset."""
    return (date.fromisoformat(month + "-01") - timedelta(days=1)).isoformat()[:7]


def movement_rows(current_rows, prior_rows, min_leads=0, limit=None):
    prior_by_id = {row["dealer_id"]: row for row in prior_rows}
    result = []
    for row in current_rows:
        prior = prior_by_id.get(row["dealer_id"])
        if prior is None:
            continue
        if any(
            r["leads"] is None
            or r["leads"] <= 0
            or r["leads"] < min_leads
            or r["units_sold"] is None
            for r in (row, prior)
        ):
            continue
        current_rate = Fraction(100 * row["units_sold"], row["leads"])
        prior_rate = Fraction(100 * prior["units_sold"], prior["leads"])
        result.append(
            {
                "dealer_id": row["dealer_id"],
                "dealer_name": row["dealer_name"],
                "region": row["region"],
                "month": row["month"],
                "prior_month": prior["month"],
                "leads": row["leads"],
                "prior_leads": prior["leads"],
                "units_sold": row["units_sold"],
                "prior_units_sold": prior["units_sold"],
                "conversion_pct": current_rate,
                "prior_conversion_pct": prior_rate,
                "conversion_change_pp": current_rate - prior_rate,
            }
        )
    result.sort(key=lambda row: (row["conversion_change_pp"], row["dealer_id"]))
    ranked = [dict(row, rank=i) for i, row in enumerate(result, 1)]
    return ranked if limit is None else ranked[:limit]


def expected_for(month, **kwargs):
    return movement_rows(base_rows(month), base_rows(previous_month(month)), **kwargs)


def assert_matches(frame, expected):
    assert isinstance(frame, pd.DataFrame)
    assert list(frame.columns) == EXPECTED_COLUMNS
    assert len(frame) == len(expected)
    assert frame.notna().all().all()
    for actual, wanted in zip(frame.to_dict("records"), expected):
        for field in EXPECTED_COLUMNS:
            if field in FLOAT_COLUMNS:
                # Zero and tiny signed changes must not be masked by absolute tolerance.
                assert actual[field] == pytest.approx(
                    float(wanted[field]), rel=1e-12, abs=0
                )
            else:
                assert actual[field] == wanted[field], field
    if expected:
        for field in INTEGER_COLUMNS:
            assert pd.api.types.is_integer_dtype(frame[field]), field
        for field in FLOAT_COLUMNS:
            assert pd.api.types.is_float_dtype(frame[field]), field


@pytest.fixture
def transaction_connection(monkeypatch):
    with db.get_engine().connect() as connection:
        transaction = connection.begin()
        monkeypatch.setattr(db, "get_engine", lambda: connection)
        try:
            yield connection
        finally:
            transaction.rollback()


@pytest.fixture
def forbid_database_access(monkeypatch):
    def forbidden():
        pytest.fail("Database accessed before validation")

    monkeypatch.setattr(db, "get_engine", forbidden)


def set_counts(connection, dealer_id, month, leads, units, drives=0):
    """Set one observation; units can be a list of per-model integer counts."""
    params = {"d": dealer_id, "m": month, "l": leads, "t": drives}
    connection.execute(
        text(
            "INSERT INTO leads_monthly (dealer_id, month, leads, test_drives) "
            "VALUES (:d, :m, :l, :t) ON CONFLICT (dealer_id, month) "
            "DO UPDATE SET leads=EXCLUDED.leads, test_drives=EXCLUDED.test_drives"
        ),
        params,
    )
    connection.execute(
        text("DELETE FROM sales_monthly WHERE dealer_id=:d AND month=:m"), params
    )
    counts = units if isinstance(units, list) else [units]
    models = (
        connection.execute(text("SELECT model FROM vehicle_models ORDER BY model"))
        .scalars()
        .all()
    )
    assert len(models) >= len(counts)
    for model, count in zip(models, counts):
        connection.execute(
            text(
                "INSERT INTO sales_monthly (dealer_id, month, model, units_sold, avg_sale_price) "
                "VALUES (:d, :m, :model, :u, NULL)"
            ),
            dict(params, model=model, u=count),
        )


def shaped_pair(connection, pairs, month=MONTH, prior=PRIOR):
    """Make an isolated two-month population; all other dealers lack observations.

    pairs maps dealer IDs to ((current leads, units), (prior leads, units)).
    """
    for table in ("leads_monthly", "sales_monthly"):
        connection.execute(
            text(f"DELETE FROM {table} WHERE month IN (:m, :p)"),
            {"m": month, "p": prior},
        )
    current_rows, prior_rows = [], []
    for dealer_id, (current, before) in pairs.items():
        for period, counts, rows in (
            (month, current, current_rows),
            (prior, before, prior_rows),
        ):
            leads, units = counts
            set_counts(connection, dealer_id, period, leads, units)
            rows.append(
                {
                    "dealer_id": dealer_id,
                    "dealer_name": DEALERS[dealer_id]["dealer_name"],
                    "region": DEALERS[dealer_id]["region"],
                    "month": period,
                    "leads": leads,
                    "units_sold": sum(units) if isinstance(units, list) else units,
                }
            )
    return current_rows, prior_rows


def test_oracle_population():
    assert len(MONTHS) == 24 and len(IDS) == 40
    assert all(previous_month(m) == p for p, m in pairwise(MONTHS))
    assert all(len(expected_for(m)) == 40 for m in COMPARISON_MONTHS)


@pytest.mark.parametrize("month", COMPARISON_MONTHS)
def test_all_comparisons_match_oracle(month):
    assert_matches(db.get_dealer_funnel_movement(month), expected_for(month))


@pytest.mark.parametrize("month", COMPARISON_MONTHS)
def test_limit_prefix(month):
    full = expected_for(month)
    for limit in (1, 5, 39, 40, 41):
        assert_matches(db.get_dealer_funnel_movement(month, limit=limit), full[:limit])


@pytest.mark.parametrize("month", COMPARISON_MONTHS)
@pytest.mark.parametrize("label", ["median", "max", "above_max"])
def test_both_months_threshold(month, label):
    prior = previous_month(month)
    counts = sorted(min(LEADS[(i, month)][0], LEADS[(i, prior)][0]) for i in IDS)
    threshold = {
        "median": counts[len(counts) // 2],
        "max": counts[-1],
        "above_max": counts[-1] + 1,
    }[label]
    assert_matches(
        db.get_dealer_funnel_movement(month, min_leads=threshold),
        expected_for(month, min_leads=threshold),
    )
    assert_matches(
        db.get_dealer_funnel_movement(month, limit=3, min_leads=threshold),
        expected_for(month, limit=3, min_leads=threshold),
    )


@pytest.mark.parametrize("limit", [2**31, 99_999_999_999, db.MAX_LIMIT])
def test_large_limits(limit):
    assert_matches(db.get_dealer_funnel_movement(MONTH, limit), expected_for(MONTH))


@pytest.mark.parametrize("threshold", [2**31, 99_999_999_999, db.MAX_LIMIT])
def test_large_thresholds(threshold):
    assert_matches(db.get_dealer_funnel_movement(MONTH, min_leads=threshold), [])


@pytest.mark.parametrize(
    "month",
    [
        None,
        202609,
        True,
        "",
        "2026-9",
        "2026-00",
        "2026-13",
        "2026/09",
        "２０２６-09",
        "2026-０９",
        "2026-09\n",
        " 2026-09",
        "2026-09 ",
    ],
)
def test_invalid_month(month, forbid_database_access):
    with pytest.raises(db.InvalidMonthError) as error:
        db.get_dealer_funnel_movement(month)
    assert str(error.value) == f"Invalid month: {month!r}. Expected YYYY-MM."


@pytest.mark.parametrize("limit", [0, -1, 2**63, True, False, 1.5, "5"])
def test_invalid_limit(limit, forbid_database_access):
    with pytest.raises(db.InvalidLimitError) as error:
        db.get_dealer_funnel_movement(MONTH, limit=limit)
    assert (
        str(error.value)
        == f"Invalid limit: {limit!r}. Expected an integer between 1 and {db.MAX_LIMIT}."
    )


@pytest.mark.parametrize("min_leads", [-1, 2**63, True, False, 1.5, "5", None])
def test_invalid_min_leads(min_leads, forbid_database_access):
    with pytest.raises(db.InvalidMinLeadsError) as error:
        db.get_dealer_funnel_movement(MONTH, min_leads=min_leads)
    assert (
        str(error.value)
        == f"Invalid min_leads: {min_leads!r}. Expected an integer between 0 and {db.MAX_LIMIT}."
    )


def test_validation_precedence(forbid_database_access):
    with pytest.raises(db.InvalidMonthError):
        db.get_dealer_funnel_movement("bad", 0, -1)
    with pytest.raises(db.InvalidLimitError):
        db.get_dealer_funnel_movement("2030-01", 0, -1)
    with pytest.raises(db.InvalidMinLeadsError):
        db.get_dealer_funnel_movement("2030-01", 1, -1)


@pytest.mark.parametrize("month", ["2030-01", "0000-01", "9999-12", "1999-12"])
def test_absent_current_month_takes_precedence(month):
    with pytest.raises(db.MonthNotFoundError) as error:
        db.get_dealer_funnel_movement(month)
    assert str(error.value) == f"Month {month} not found"


def test_first_month_lacks_prior():
    with pytest.raises(db.MonthNotFoundError) as error:
        db.get_dealer_funnel_movement(MONTHS[0])
    assert str(error.value) == f"Month {previous_month(MONTHS[0])} not found"


@pytest.mark.parametrize("missing", [MONTH, PRIOR])
def test_sales_only_month_is_absent(transaction_connection, missing):
    transaction_connection.execute(
        text("DELETE FROM leads_monthly WHERE month=:m"), {"m": missing}
    )
    with pytest.raises(db.MonthNotFoundError) as error:
        db.get_dealer_funnel_movement(MONTH)
    assert str(error.value) == f"Month {missing} not found"


@pytest.mark.parametrize("month", [MONTH, PRIOR])
@pytest.mark.parametrize("kind", ["lead", "sales", "zero_leads", "negative_leads"])
def test_incomplete_dealer_only_is_excluded(transaction_connection, month, kind):
    dealer_id = IDS[0]
    current, prior = base_rows(MONTH), base_rows(PRIOR)
    row = next(
        r for r in (current if month == MONTH else prior) if r["dealer_id"] == dealer_id
    )
    params = {"d": dealer_id, "m": month}
    if kind == "lead":
        statement = "DELETE FROM leads_monthly WHERE dealer_id=:d AND month=:m"
        row["leads"] = None
    elif kind == "sales":
        statement = "DELETE FROM sales_monthly WHERE dealer_id=:d AND month=:m"
        row["units_sold"] = None
    else:
        value = 0 if kind == "zero_leads" else -1
        statement = "UPDATE leads_monthly SET leads=:l WHERE dealer_id=:d AND month=:m"
        params["l"] = value
        row["leads"] = value
    transaction_connection.execute(text(statement), params)
    expected = movement_rows(current, prior)
    assert len(expected) == 39
    assert_matches(db.get_dealer_funnel_movement(MONTH), expected)


@pytest.mark.parametrize("month", [MONTH, PRIOR])
@pytest.mark.parametrize(
    "statement",
    [
        "DELETE FROM sales_monthly WHERE month=:m",
        "UPDATE leads_monthly SET leads=0 WHERE month=:m",
    ],
)
def test_existing_months_without_comparable_dealers(
    transaction_connection, month, statement
):
    transaction_connection.execute(text(statement), {"m": month})
    assert_matches(db.get_dealer_funnel_movement(MONTH), [])


def test_disjoint_populations(transaction_connection):
    shaped_pair(
        transaction_connection,
        {IDS[0]: ((100, 20), (100, 20)), IDS[1]: ((100, 20), (100, 20))},
    )
    for dealer_id, month in ((IDS[0], MONTH), (IDS[1], PRIOR)):
        transaction_connection.execute(
            text("DELETE FROM leads_monthly WHERE dealer_id=:d AND month=:m"),
            {"d": dealer_id, "m": month},
        )
    assert_matches(db.get_dealer_funnel_movement(MONTH), [])


def test_signed_order_and_numerator_is_not_sort_key(transaction_connection):
    a, b, c, d, e = IDS[:5]
    rows = shaped_pair(
        transaction_connection,
        {
            a: ((1000, 350), (1000, 400)),
            b: ((100, 30), (100, 40)),
            c: ((200, 80), (100, 40)),
            d: ((100, 50), (100, 40)),
            e: ((1000, 450), (1000, 400)),
        },
    )
    expected = movement_rows(*rows)
    assert [r["dealer_id"] for r in expected] == [b, a, c, e, d]
    assert [r["conversion_change_pp"] for r in expected] == [-10, -5, 0, 5, 10]
    assert_matches(db.get_dealer_funnel_movement(MONTH), expected)


@pytest.mark.parametrize("reverse", [False, True])
@pytest.mark.parametrize("sign", [-1, 1])
def test_equal_repeating_movements_tie_by_id(transaction_connection, reverse, sign):
    a, b = IDS[:2]
    pairs = [((3, 1), (3, 2)), ((300000000, 100000000), (600000000, 400000000))]
    if sign == 1:
        pairs = [(p, c) for c, p in pairs]
    if reverse:
        pairs.reverse()
    rows = shaped_pair(transaction_connection, dict(zip((a, b), pairs)))
    expected = movement_rows(*rows)
    assert [r["conversion_change_pp"] for r in expected] == [
        Fraction(sign * 100, 3)
    ] * 2
    assert_matches(db.get_dealer_funnel_movement(MONTH), expected)
    assert_matches(db.get_dealer_funnel_movement(MONTH, limit=1), expected[:1])


@pytest.mark.parametrize("sign", [-1, 1])
def test_near_ties_survive_float_collision(transaction_connection, sign):
    a, b = IDS[:2]
    n = 2_000_000_000
    pairs = [((n + 2, (n + 2) // 2 + 1), (n, 1)), ((n, n // 2 + 1), (n - 2, 1))]
    if sign < 0:
        pairs = [(p, c) for c, p in pairs]
        pairs.reverse()

    # Ensure the exact smaller change belongs to the larger ID.
    def change(pair):
        (l1, u1), (l0, u0) = pair
        return Fraction(100 * u1, l1) - Fraction(100 * u0, l0)

    pairs.sort(key=change, reverse=True)
    rows = shaped_pair(transaction_connection, dict(zip((a, b), pairs)))
    expected = movement_rows(*rows)
    assert expected[0]["dealer_id"] == b
    assert expected[0]["conversion_change_pp"] < expected[1]["conversion_change_pp"]
    assert float(expected[0]["conversion_change_pp"]) == float(
        expected[1]["conversion_change_pp"]
    )
    result = db.get_dealer_funnel_movement(MONTH)
    assert_matches(result, expected)
    assert result["conversion_change_pp"].nunique() == 1
    assert_matches(db.get_dealer_funnel_movement(MONTH, limit=1), expected[:1])


@pytest.mark.parametrize("sign", [-1, 1])
def test_tiny_nonzero_change_does_not_become_zero(transaction_connection, sign):
    n = MAX_INT
    pair = ((n, n - 1), (n - 1, n - 2))
    if sign < 0:
        pair = pair[::-1]
    rows = shaped_pair(transaction_connection, {IDS[0]: pair})
    expected = movement_rows(*rows)
    assert expected[0]["conversion_change_pp"] == Fraction(sign * 100, n * (n - 1))
    assert_matches(db.get_dealer_funnel_movement(MONTH), expected)


def test_bigint_sales_products_do_not_overflow(transaction_connection):
    rows = shaped_pair(
        transaction_connection,
        {
            IDS[0]: ((MAX_INT, [MAX_INT] * 3), (MAX_INT - 1, [MAX_INT] * 2)),
            IDS[1]: ((MAX_INT - 1, [MAX_INT] * 2), (MAX_INT, [MAX_INT] * 3)),
        },
    )
    expected = movement_rows(*rows)
    assert 3 * MAX_INT * (MAX_INT - 1) > db.MAX_LIMIT
    assert_matches(db.get_dealer_funnel_movement(MONTH), expected)


def test_threshold_each_month_inclusive_and_default_low_volume(transaction_connection):
    a, b, c, d, e = IDS[:5]
    rows = shaped_pair(
        transaction_connection,
        {
            a: ((5, 0), (100, 100)),
            b: ((100, 0), (5, 4)),
            c: ((100, 10), (100, 60)),
            d: ((100, 20), (100, 50)),
            e: ((100, 40), (100, 50)),
        },
    )
    full = movement_rows(*rows)
    assert [r["dealer_id"] for r in full] == [a, b, c, d, e]
    assert_matches(db.get_dealer_funnel_movement(MONTH), full)
    filtered = movement_rows(*rows, min_leads=100)
    assert [r["dealer_id"] for r in filtered] == [c, d, e]
    assert_matches(db.get_dealer_funnel_movement(MONTH, min_leads=100), filtered)
    assert_matches(db.get_dealer_funnel_movement(MONTH, 2, 100), filtered[:2])


@pytest.mark.parametrize("month", [MONTH, PRIOR])
def test_missing_model_row_is_not_missing_observation(transaction_connection, month):
    dealer_id = IDS[0]
    params = {"d": dealer_id, "m": month}
    model, units = transaction_connection.execute(
        text(
            "SELECT model, units_sold FROM sales_monthly WHERE dealer_id=:d AND month=:m ORDER BY model LIMIT 1"
        ),
        params,
    ).one()
    transaction_connection.execute(
        text(
            "DELETE FROM sales_monthly WHERE dealer_id=:d AND month=:m AND model=:model"
        ),
        dict(params, model=model),
    )
    current, prior = base_rows(MONTH), base_rows(PRIOR)
    row = next(
        r for r in (current if month == MONTH else prior) if r["dealer_id"] == dealer_id
    )
    row["units_sold"] = SALES[(dealer_id, month)] - units
    assert_matches(db.get_dealer_funnel_movement(MONTH), movement_rows(current, prior))


def test_year_zero_february_compares_with_january(transaction_connection):
    rows = shaped_pair(
        transaction_connection, {IDS[0]: ((10, 2), (10, 4))}, "0000-02", "0000-01"
    )
    assert_matches(db.get_dealer_funnel_movement("0000-02"), movement_rows(*rows))


def test_existing_year_zero_january_has_no_representable_prior(transaction_connection):
    set_counts(transaction_connection, IDS[0], "0000-01", 10, 2)
    with pytest.raises(db.MonthNotFoundError) as error:
        db.get_dealer_funnel_movement("0000-01")
    assert str(error.value) == "Month preceding 0000-01 not found"


@contextmanager
def recorded_statements(connection):
    """Record the data statements a call sends to PostgreSQL.

    pandas probes the catalog with its own table-name lookup before it runs a
    query; that probe is not part of the query under test, so it is excluded.
    """
    statements = []

    def capture(conn, cursor, statement, parameters, context, executemany):
        if "pg_catalog" not in statement.lower():
            statements.append((statement, parameters))

    event.listen(connection, "before_cursor_execute", capture)
    try:
        yield statements
    finally:
        event.remove(connection, "before_cursor_execute", capture)


@pytest.mark.parametrize(
    "scenario", ["ranked", "empty", "missing_current", "missing_prior"]
)
def test_one_statement_and_bound_parameters(transaction_connection, scenario):
    month = (
        "2030-01"
        if scenario == "missing_current"
        else MONTHS[0] if scenario == "missing_prior" else MONTH
    )
    threshold = db.MAX_LIMIT if scenario == "empty" else 0
    with recorded_statements(transaction_connection) as statements:
        if scenario.startswith("missing"):
            with pytest.raises(db.MonthNotFoundError):
                db.get_dealer_funnel_movement(month, limit=5, min_leads=threshold)
        else:
            result = db.get_dealer_funnel_movement(month, limit=5, min_leads=threshold)
            assert_matches(result, expected_for(month, limit=5, min_leads=threshold))
    assert len(statements) == 1
    sql, params = statements[0]
    assert month not in sql
    assert month in params.values()
    assert 5 in params.values()
    assert threshold in params.values()
    assert "dealer_monthly_funnel" in sql.lower()


def test_final_result_is_explicitly_ordered_by_rank(transaction_connection):
    with recorded_statements(transaction_connection) as statements:
        db.get_dealer_funnel_movement(MONTH)
    assert len(statements) == 1
    sql = " ".join(statements[0][0].split()).lower()
    assert re.search(r"order by (\w+\.)?rank$", sql)


@pytest.mark.parametrize("sign", [-1, 1])
def test_day34_scale_is_insufficient_for_movement(transaction_connection, sign):
    # Third finite difference of reciprocal counts: the separation is O(n^-4).
    n = 2_000_000_001
    pairs = [((n, 1), (n + 1, 3)), ((n + 3, 1), (n + 2, 3))]
    if sign == 1:
        pairs = [pair[::-1] for pair in pairs]

    def change(pair):
        (l1, u1), (l0, u0) = pair
        return Fraction(100 * u1, l1) - Fraction(100 * u0, l0)

    pairs.sort(key=change, reverse=True)
    high, low = map(change, pairs)
    assert 0 < high - low < Fraction(1, 10**34)
    assert int(high * 10**30) == int(low * 10**30)
    assert int(high * 10**40) != int(low * 10**40)
    rows = shaped_pair(transaction_connection, dict(zip(IDS[:2], pairs)))
    expected = movement_rows(*rows)
    assert expected[0]["dealer_id"] == IDS[1]
    assert_matches(db.get_dealer_funnel_movement(MONTH), expected)


def test_limit_is_applied_to_rows_explicitly_ordered_by_rank(transaction_connection):
    with recorded_statements(transaction_connection) as statements:
        db.get_dealer_funnel_movement(MONTH, limit=5)
    assert len(statements) == 1
    sql = " ".join(statements[0][0].split()).lower()
    assert re.search(r"from ranked order by rank limit cast\(\S+ as bigint\)", sql)


@pytest.mark.parametrize(
    "pattern",
    [
        r"order by conversion_change_pp asc, dealer_id asc",
        r"c\.leads >= cast\(\S+ as bigint\)",
        r"p\.leads >= cast\(\S+ as bigint\)",
    ],
)
def test_sql_keeps_tie_break_and_threshold_structure(transaction_connection, pattern):
    # Behavior cannot tell these apart: without the dealer_id tie-break rows
    # still arrive in dealer order, and a bare parameter compares equal to a
    # bigint cast. The generated SQL therefore pins them.
    with recorded_statements(transaction_connection) as statements:
        db.get_dealer_funnel_movement(MONTH, limit=5, min_leads=10)
    assert len(statements) == 1
    sql = " ".join(statements[0][0].split()).lower()
    assert re.search(pattern, sql)
