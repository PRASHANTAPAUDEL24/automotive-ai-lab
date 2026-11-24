"""Query-layer tests for the dealer funnel ranking (Day 33).

Contract under test: ``db.get_dealer_funnel_ranking(month, limit=None,
min_leads=0)`` ranks dealers for one month by the raw, unrounded
``lead_to_sale_pct`` (highest first, ``dealer_id`` ascending as the
deterministic tie-break) using contiguous ``ROW_NUMBER()`` ranks that are
assigned after eligibility filtering and before ``limit``.

A dealer is eligible when its lead-to-sale rate is defined (a lead row with
positive leads and an aggregated sales dealer-month exist) and
``leads >= min_leads``. A missing drive-to-sale rate does not exclude a dealer.

Error contract: a malformed month raises ``InvalidMonthError``; an invalid
``limit`` raises ``InvalidLimitError``; an invalid ``min_leads`` raises
``InvalidMinLeadsError``; all are checked, in that order, before any database
read. A well-formed month with no ``leads_monthly`` rows raises
``MonthNotFoundError``, while an existing month with no eligible dealers
returns an empty DataFrame.

Expected values come from an independent recomputation over the source CSVs
with exact ``Fraction`` arithmetic. The real data has no zero-lead, zero-drive
or missing rows, so every eligibility rule is exercised inside rolled-back
transactions. The module reaches the new function only through ``db.`` so a
missing implementation fails each test individually.
"""

import csv
from collections import defaultdict
from fractions import Fraction
from pathlib import Path

import pandas as pd
import pytest
from sqlalchemy import text

import db

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

EXPECTED_COLUMNS = [
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
EXACT_KEYS = [
    "dealer_id",
    "dealer_name",
    "region",
    "month",
    "leads",
    "test_drives",
    "units_sold",
    "rank",
]
RATE_KEYS = ["test_drive_rate_pct", "drive_to_sale_pct", "lead_to_sale_pct"]
INTEGER_COLUMNS = ["rank", "dealer_id", "leads", "test_drives", "units_sold"]


def _read_rows(filename):
    with (DATA_DIR / filename).open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


DEALERS = {int(row["dealer_id"]): row for row in _read_rows("dealers.csv")}
LEADS = {
    (int(row["dealer_id"]), row["month"]): (
        int(row["leads"]),
        int(row["test_drives"]),
    )
    for row in _read_rows("leads_monthly.csv")
}
_sales_totals = defaultdict(int)
for _row in _read_rows("sales_monthly.csv"):
    _sales_totals[(int(_row["dealer_id"]), _row["month"])] += int(_row["units_sold"])
SALES = dict(_sales_totals)
MONTHS = sorted({month for _, month in LEADS})
FIXTURE_MONTH = MONTHS[-1]


def _pct(numerator, denominator):
    if numerator is None or denominator in (None, 0):
        return None
    return Fraction(numerator * 100, denominator)


def make_row(dealer_id, month, leads, test_drives, units_sold):
    dealer = DEALERS[dealer_id]
    return {
        "dealer_id": dealer_id,
        "dealer_name": dealer["dealer_name"],
        "region": dealer["region"],
        "month": month,
        "leads": leads,
        "test_drives": test_drives,
        "units_sold": units_sold,
        "test_drive_rate_pct": _pct(test_drives, leads),
        "drive_to_sale_pct": _pct(units_sold, test_drives),
        "lead_to_sale_pct": _pct(units_sold, leads),
    }


def base_rows(month):
    """One oracle row per dealer for a month, with None where data is missing."""
    rows = []
    for dealer_id in sorted(DEALERS):
        leads, test_drives = LEADS.get((dealer_id, month), (None, None))
        rows.append(
            make_row(
                dealer_id, month, leads, test_drives, SALES.get((dealer_id, month))
            )
        )
    return rows


def rank_rows(rows, min_leads=0, limit=None):
    eligible = [
        row
        for row in rows
        if row["lead_to_sale_pct"] is not None and row["leads"] >= min_leads
    ]
    eligible.sort(key=lambda row: (-row["lead_to_sale_pct"], row["dealer_id"]))
    ranked = [dict(row, rank=position) for position, row in enumerate(eligible, 1)]
    return ranked if limit is None else ranked[:limit]


def replace_row(rows, new_row):
    return [
        new_row if row["dealer_id"] == new_row["dealer_id"] else row for row in rows
    ]


def _same_rate(actual, wanted):
    if wanted is None:
        return actual is None or bool(pd.isna(actual))
    if actual is None or bool(pd.isna(actual)):
        return False
    return float(actual) == pytest.approx(float(wanted), rel=1e-9, abs=1e-12)


def assert_matches(result, expected):
    assert isinstance(result, pd.DataFrame)
    assert list(result.columns) == EXPECTED_COLUMNS
    records = result.to_dict("records")
    assert len(records) == len(expected)
    for actual, wanted in zip(records, expected):
        label = f"rank {wanted['rank']} dealer {wanted['dealer_id']}"
        for key in EXACT_KEYS:
            assert actual[key] == wanted[key], f"{label}: {key}"
        for key in RATE_KEYS:
            assert _same_rate(actual[key], wanted[key]), f"{label}: {key}"


def tie_boundaries(ranked):
    """Limits that cut between two dealers with exactly equal rates."""
    return [
        k
        for k in range(1, len(ranked))
        if ranked[k - 1]["lead_to_sale_pct"] == ranked[k]["lead_to_sale_pct"]
    ]


def leads_threshold(month, label):
    values = sorted(
        row["leads"] for row in base_rows(month) if row["leads"] is not None
    )
    return {
        "median": values[len(values) // 2],
        "max": values[-1],
        "above_max": values[-1] + 1,
    }[label]


@pytest.fixture
def forbid_database_access(monkeypatch):
    """Invalid input must be rejected before acquiring the database."""

    def unexpected_database_access():
        pytest.fail("Database accessed before input validation")

    monkeypatch.setattr(db, "get_engine", unexpected_database_access)


@pytest.fixture
def transaction_connection(monkeypatch):
    engine = db.get_engine()
    connection = engine.connect()
    transaction = connection.begin()
    monkeypatch.setattr(db, "get_engine", lambda: connection)
    try:
        yield connection
    finally:
        transaction.rollback()
        connection.close()


# ---------------------------------------------------------------------------
# Oracle sanity: these guard the tests themselves and do not need the new query.
# ---------------------------------------------------------------------------


def test_oracle_covers_the_24_month_span_and_all_dealers():
    assert len(MONTHS) == 24
    assert len(DEALERS) == 40
    assert all(len(rank_rows(base_rows(month))) == 40 for month in MONTHS)


def test_real_data_contains_exact_ties_that_exercise_the_tie_break():
    tied = sum(len(tie_boundaries(rank_rows(base_rows(month)))) for month in MONTHS)
    assert tied > 0


# ---------------------------------------------------------------------------
# Real-data parity across every month
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("month", MONTHS)
def test_ranking_matches_independent_oracle_for_every_month(month):
    result = db.get_dealer_funnel_ranking(month)

    assert_matches(result, rank_rows(base_rows(month)))
    assert result["rank"].tolist() == list(range(1, 41))


@pytest.mark.parametrize("month", MONTHS)
def test_tied_rates_are_ordered_by_dealer_id_and_get_distinct_ranks(month):
    result = db.get_dealer_funnel_ranking(month)
    records = result.to_dict("records")
    exact = [_pct(row["units_sold"], row["leads"]) for row in records]

    for position in range(1, len(records)):
        assert exact[position - 1] >= exact[position]
        if exact[position - 1] == exact[position]:
            assert records[position - 1]["dealer_id"] < records[position]["dealer_id"]
    assert result["rank"].is_unique


def test_count_columns_keep_integer_dtypes():
    result = db.get_dealer_funnel_ranking(MONTHS[0])

    for column in INTEGER_COLUMNS:
        assert pd.api.types.is_integer_dtype(result[column]), column
    assert result["test_drive_rate_pct"].notna().all()
    assert result["lead_to_sale_pct"].notna().all()


def test_limit_is_accepted_positionally():
    month = MONTHS[3]

    assert_matches(
        db.get_dealer_funnel_ranking(month, 7),
        rank_rows(base_rows(month), limit=7),
    )


# ---------------------------------------------------------------------------
# limit
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("month", MONTHS)
def test_limit_returns_exact_prefix_including_cuts_through_tie_groups(month):
    full = rank_rows(base_rows(month))
    limits = sorted({1, 2, 5, len(full) - 1, len(full), *tie_boundaries(full)})

    for limit in limits:
        assert_matches(
            db.get_dealer_funnel_ranking(month, limit=limit),
            full[:limit],
        )


@pytest.mark.parametrize("limit", [41, 1000, 2**31, 99_999_999_999, db.MAX_LIMIT])
def test_limit_above_row_count_returns_every_ranked_dealer(limit):
    month = MONTHS[5]

    assert_matches(
        db.get_dealer_funnel_ranking(month, limit=limit),
        rank_rows(base_rows(month)),
    )


@pytest.mark.parametrize("limit", [0, -1, 2**63, True, False, 1.5, "5"])
def test_invalid_limit_raises_with_exact_message(limit, forbid_database_access):
    with pytest.raises(db.InvalidLimitError) as error:
        db.get_dealer_funnel_ranking(MONTHS[0], limit=limit)

    assert str(error.value) == (
        f"Invalid limit: {limit!r}. Expected an integer between 1 and {db.MAX_LIMIT}."
    )


# ---------------------------------------------------------------------------
# min_leads
# ---------------------------------------------------------------------------


def test_min_leads_zero_is_the_default():
    month = MONTHS[7]

    pd.testing.assert_frame_equal(
        db.get_dealer_funnel_ranking(month),
        db.get_dealer_funnel_ranking(month, min_leads=0),
    )


@pytest.mark.parametrize("label", ["median", "max", "above_max"])
@pytest.mark.parametrize("month", MONTHS)
def test_min_leads_filters_inclusively_and_reranks_contiguously(month, label):
    threshold = leads_threshold(month, label)
    expected = rank_rows(base_rows(month), min_leads=threshold)

    result = db.get_dealer_funnel_ranking(month, min_leads=threshold)

    assert_matches(result, expected)
    if label == "above_max":
        assert result.empty
    else:
        assert any(row["leads"] == threshold for row in expected)
        assert result["rank"].tolist() == list(range(1, len(expected) + 1))


@pytest.mark.parametrize("month", MONTHS)
def test_limit_is_applied_after_min_leads_filtering_and_ranking(month):
    threshold = leads_threshold(month, "median")
    expected = rank_rows(base_rows(month), min_leads=threshold, limit=5)

    assert_matches(
        db.get_dealer_funnel_ranking(month, limit=5, min_leads=threshold),
        expected,
    )


def test_min_leads_at_bigint_maximum_is_valid_and_returns_empty_frame():
    result = db.get_dealer_funnel_ranking(MONTHS[0], min_leads=db.MAX_LIMIT)

    assert_matches(result, [])


@pytest.mark.parametrize("min_leads", [-1, 2**63, True, False, None, 1.5, "10", 10.0])
def test_invalid_min_leads_raises_with_exact_message(min_leads, forbid_database_access):
    with pytest.raises(db.InvalidMinLeadsError) as error:
        db.get_dealer_funnel_ranking(MONTHS[0], min_leads=min_leads)

    assert str(error.value) == (
        f"Invalid min_leads: {min_leads!r}. "
        f"Expected an integer between 0 and {db.MAX_LIMIT}."
    )


def test_min_leads_error_is_a_value_error():
    assert issubclass(db.InvalidMinLeadsError, ValueError)


# ---------------------------------------------------------------------------
# Month validation and validation order
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "month",
    [
        "2026-9",
        "abcd",
        "2026-09\n",
        "",
        "2026/09",
        "２０２６-０９",
        "2026-00",
        "2026-13",
        " 2026-09",
        "2026-09 ",
        None,
        202609,
        True,
    ],
)
def test_malformed_month_raises_invalid_month_error(month, forbid_database_access):
    with pytest.raises(db.InvalidMonthError):
        db.get_dealer_funnel_ranking(month)


@pytest.mark.parametrize("month", ["2026-10", "2024-09", "2099-01"])
def test_well_formed_month_without_lead_rows_raises_month_not_found(month):
    with pytest.raises(db.MonthNotFoundError):
        db.get_dealer_funnel_ranking(month)


def test_validation_runs_before_the_database_in_documented_order(
    forbid_database_access,
):
    missing = "2099-01"

    with pytest.raises(db.InvalidLimitError):
        db.get_dealer_funnel_ranking(missing, limit=0)
    with pytest.raises(db.InvalidMinLeadsError):
        db.get_dealer_funnel_ranking(missing, min_leads=-1)
    with pytest.raises(db.InvalidMonthError):
        db.get_dealer_funnel_ranking("bad", limit=0, min_leads=-1)
    with pytest.raises(db.InvalidLimitError):
        db.get_dealer_funnel_ranking(MONTHS[0], limit=0, min_leads=-1)


# ---------------------------------------------------------------------------
# Eligibility rules, exercised in rolled-back transactions
# ---------------------------------------------------------------------------


def _middle_dealer():
    return rank_rows(base_rows(FIXTURE_MONTH))[19]["dealer_id"]


def _run(rows, **kwargs):
    return db.get_dealer_funnel_ranking(FIXTURE_MONTH, **kwargs), rank_rows(
        rows, **kwargs
    )


def test_dealer_without_a_lead_row_is_excluded(transaction_connection):
    dealer_id = _middle_dealer()
    transaction_connection.execute(
        text("DELETE FROM leads_monthly WHERE dealer_id = :d AND month = :m"),
        {"d": dealer_id, "m": FIXTURE_MONTH},
    )
    units = SALES[(dealer_id, FIXTURE_MONTH)]
    rows = replace_row(
        base_rows(FIXTURE_MONTH),
        make_row(dealer_id, FIXTURE_MONTH, None, None, units),
    )

    result, expected = _run(rows)

    assert dealer_id not in result["dealer_id"].tolist()
    assert len(expected) == 39
    assert_matches(result, expected)


def test_dealer_without_a_sales_row_is_excluded(transaction_connection):
    dealer_id = _middle_dealer()
    transaction_connection.execute(
        text("DELETE FROM sales_monthly WHERE dealer_id = :d AND month = :m"),
        {"d": dealer_id, "m": FIXTURE_MONTH},
    )
    leads, drives = LEADS[(dealer_id, FIXTURE_MONTH)]
    rows = replace_row(
        base_rows(FIXTURE_MONTH),
        make_row(dealer_id, FIXTURE_MONTH, leads, drives, None),
    )

    result, expected = _run(rows)

    assert dealer_id not in result["dealer_id"].tolist()
    assert len(expected) == 39
    assert_matches(result, expected)


@pytest.mark.parametrize("min_leads", [0, 1])
def test_dealer_with_zero_leads_is_excluded(transaction_connection, min_leads):
    dealer_id = _middle_dealer()
    transaction_connection.execute(
        text("UPDATE leads_monthly SET leads = 0 WHERE dealer_id = :d AND month = :m"),
        {"d": dealer_id, "m": FIXTURE_MONTH},
    )
    drives = LEADS[(dealer_id, FIXTURE_MONTH)][1]
    units = SALES[(dealer_id, FIXTURE_MONTH)]
    rows = replace_row(
        base_rows(FIXTURE_MONTH),
        make_row(dealer_id, FIXTURE_MONTH, 0, drives, units),
    )

    result, expected = _run(rows, min_leads=min_leads)

    assert dealer_id not in result["dealer_id"].tolist()
    assert len(expected) == 39
    assert_matches(result, expected)


def test_zero_units_with_positive_leads_stays_rankable_in_last_place(
    transaction_connection,
):
    dealer_id = _middle_dealer()
    transaction_connection.execute(
        text(
            "UPDATE sales_monthly SET units_sold = 0 WHERE dealer_id = :d AND month = :m"
        ),
        {"d": dealer_id, "m": FIXTURE_MONTH},
    )
    leads, drives = LEADS[(dealer_id, FIXTURE_MONTH)]
    rows = replace_row(
        base_rows(FIXTURE_MONTH),
        make_row(dealer_id, FIXTURE_MONTH, leads, drives, 0),
    )

    result, expected = _run(rows)

    assert len(expected) == 40
    assert expected[-1]["dealer_id"] == dealer_id
    assert float(result.iloc[-1]["lead_to_sale_pct"]) == 0.0
    assert_matches(result, expected)


def test_zero_test_drives_with_sales_stays_rankable_with_null_drive_to_sale(
    transaction_connection,
):
    dealer_id = _middle_dealer()
    transaction_connection.execute(
        text(
            "UPDATE leads_monthly SET test_drives = 0 "
            "WHERE dealer_id = :d AND month = :m"
        ),
        {"d": dealer_id, "m": FIXTURE_MONTH},
    )
    leads = LEADS[(dealer_id, FIXTURE_MONTH)][0]
    units = SALES[(dealer_id, FIXTURE_MONTH)]
    rows = replace_row(
        base_rows(FIXTURE_MONTH),
        make_row(dealer_id, FIXTURE_MONTH, leads, 0, units),
    )

    result, expected = _run(rows)

    assert len(expected) == 40
    row = result[result["dealer_id"] == dealer_id].iloc[0]
    assert float(row["test_drive_rate_pct"]) == 0.0
    assert pd.isna(row["drive_to_sale_pct"])
    assert not pd.isna(row["lead_to_sale_pct"])
    assert_matches(result, expected)


def test_missing_one_model_row_keeps_dealer_eligible_with_remaining_units(
    transaction_connection,
):
    dealer_id = _middle_dealer()
    model_rows = transaction_connection.execute(
        text(
            "SELECT model, units_sold FROM sales_monthly "
            "WHERE dealer_id = :d AND month = :m "
            "ORDER BY units_sold DESC, model"
        ),
        {"d": dealer_id, "m": FIXTURE_MONTH},
    ).all()
    assert len(model_rows) > 1
    model, removed = model_rows[0]
    assert removed > 0
    transaction_connection.execute(
        text(
            "DELETE FROM sales_monthly "
            "WHERE dealer_id = :d AND month = :m AND model = :model"
        ),
        {"d": dealer_id, "m": FIXTURE_MONTH, "model": model},
    )
    leads, drives = LEADS[(dealer_id, FIXTURE_MONTH)]
    units = SALES[(dealer_id, FIXTURE_MONTH)] - removed
    rows = replace_row(
        base_rows(FIXTURE_MONTH),
        make_row(dealer_id, FIXTURE_MONTH, leads, drives, units),
    )

    result, expected = _run(rows)

    assert len(expected) == 40
    row = result[result["dealer_id"] == dealer_id].iloc[0]
    assert row["units_sold"] == units
    assert_matches(result, expected)


def test_month_with_leads_but_no_sales_returns_empty_frame_not_an_error(
    transaction_connection,
):
    transaction_connection.execute(
        text("DELETE FROM sales_monthly WHERE month = :m"),
        {"m": FIXTURE_MONTH},
    )

    result = db.get_dealer_funnel_ranking(FIXTURE_MONTH)

    assert_matches(result, [])


def test_month_with_all_zero_leads_returns_empty_frame(transaction_connection):
    transaction_connection.execute(
        text("UPDATE leads_monthly SET leads = 0 WHERE month = :m"),
        {"m": FIXTURE_MONTH},
    )

    result = db.get_dealer_funnel_ranking(FIXTURE_MONTH)

    assert_matches(result, [])


def test_month_with_sales_but_no_lead_rows_raises_month_not_found(
    transaction_connection,
):
    transaction_connection.execute(
        text("DELETE FROM leads_monthly WHERE month = :m"),
        {"m": FIXTURE_MONTH},
    )
    sales_left = transaction_connection.execute(
        text("SELECT count(*) FROM sales_monthly WHERE month = :m"),
        {"m": FIXTURE_MONTH},
    ).scalar_one()
    assert sales_left > 0

    with pytest.raises(db.MonthNotFoundError):
        db.get_dealer_funnel_ranking(FIXTURE_MONTH)


@pytest.mark.parametrize("smaller_id_gets_smaller_counts", [True, False])
def test_equal_rates_with_different_counts_tie_break_on_dealer_id(
    transaction_connection, smaller_id_gets_smaller_counts
):
    first_id, second_id = sorted(DEALERS)[:2]
    small, large = (10, 4, 3), (20, 8, 6)
    counts = {
        first_id: small if smaller_id_gets_smaller_counts else large,
        second_id: large if smaller_id_gets_smaller_counts else small,
    }
    model = transaction_connection.execute(
        text("SELECT model FROM vehicle_models ORDER BY model LIMIT 1")
    ).scalar_one()
    rows = base_rows(FIXTURE_MONTH)
    for dealer_id, (leads, drives, units) in counts.items():
        transaction_connection.execute(
            text(
                "UPDATE leads_monthly SET leads = :l, test_drives = :t "
                "WHERE dealer_id = :d AND month = :m"
            ),
            {"l": leads, "t": drives, "d": dealer_id, "m": FIXTURE_MONTH},
        )
        transaction_connection.execute(
            text("DELETE FROM sales_monthly WHERE dealer_id = :d AND month = :m"),
            {"d": dealer_id, "m": FIXTURE_MONTH},
        )
        transaction_connection.execute(
            text(
                "INSERT INTO sales_monthly "
                "(dealer_id, month, model, units_sold, avg_sale_price) "
                "VALUES (:d, :m, :model, :u, NULL)"
            ),
            {"d": dealer_id, "m": FIXTURE_MONTH, "model": model, "u": units},
        )
        rows = replace_row(
            rows, make_row(dealer_id, FIXTURE_MONTH, leads, drives, units)
        )

    result, expected = _run(rows)

    assert [row["dealer_id"] for row in expected[:2]] == [first_id, second_id]
    assert result["dealer_id"].tolist()[:2] == [first_id, second_id]
    assert result["rank"].tolist()[:2] == [1, 2]
    assert_matches(result, expected)


@pytest.mark.parametrize("smaller_id_gets_lower_exact_rate", [True, False])
def test_rates_equal_after_rounding_are_ranked_by_the_unrounded_value(
    transaction_connection, smaller_id_gets_lower_exact_rate
):
    # 91/150 = 60.6667 and 108/178 = 60.6742 both display as 60.67, so only the
    # raw numeric value separates them; both sit above every real rate.
    first_id, second_id = sorted(DEALERS)[:2]
    lower, higher = (150, 50, 91), (178, 59, 108)
    counts = {
        first_id: lower if smaller_id_gets_lower_exact_rate else higher,
        second_id: higher if smaller_id_gets_lower_exact_rate else lower,
    }
    model = transaction_connection.execute(
        text("SELECT model FROM vehicle_models ORDER BY model LIMIT 1")
    ).scalar_one()
    rows = base_rows(FIXTURE_MONTH)
    for dealer_id, (leads, drives, units) in counts.items():
        transaction_connection.execute(
            text(
                "UPDATE leads_monthly SET leads = :l, test_drives = :t "
                "WHERE dealer_id = :d AND month = :m"
            ),
            {"l": leads, "t": drives, "d": dealer_id, "m": FIXTURE_MONTH},
        )
        transaction_connection.execute(
            text("DELETE FROM sales_monthly WHERE dealer_id = :d AND month = :m"),
            {"d": dealer_id, "m": FIXTURE_MONTH},
        )
        transaction_connection.execute(
            text(
                "INSERT INTO sales_monthly "
                "(dealer_id, month, model, units_sold, avg_sale_price) "
                "VALUES (:d, :m, :model, :u, NULL)"
            ),
            {"d": dealer_id, "m": FIXTURE_MONTH, "model": model, "u": units},
        )
        rows = replace_row(
            rows, make_row(dealer_id, FIXTURE_MONTH, leads, drives, units)
        )

    result, expected = _run(rows)

    higher_id = first_id if counts[first_id] == higher else second_id
    lower_id = second_id if higher_id == first_id else first_id
    assert [row["dealer_id"] for row in expected[:2]] == [higher_id, lower_id]
    assert result["dealer_id"].tolist()[:2] == [higher_id, lower_id]
    assert_matches(result, expected)


@pytest.fixture
def captured_ranking_sql(monkeypatch):
    """Capture generated SQL without connecting to PostgreSQL."""
    import pandas as pd

    statements = []
    fake_source = object()

    def capture_read_sql(statement, source, *args, **kwargs):
        assert source is fake_source

        statements.append(
            {
                "sql": " ".join(str(statement).split()).lower(),
                "params": dict(kwargs.get("params", {})),
            }
        )

        if len(statements) == 1:
            return pd.DataFrame({"exists": [1]})

        if len(statements) == 2:
            return pd.DataFrame()

        pytest.fail("Unexpected additional SQL statement")

    monkeypatch.setattr(db, "get_engine", lambda: fake_source)
    monkeypatch.setattr(db.pd, "read_sql", capture_read_sql)

    def capture():
        db.get_dealer_funnel_ranking(
            "2026-09",
            limit=5,
            min_leads=10,
        )

        assert len(statements) == 2

        return statements[1]

    return capture


def test_ranking_query_has_explicit_final_order_by_rank(
    captured_ranking_sql,
):
    """The final result must explicitly order rows by rank."""
    captured = captured_ranking_sql()
    sql = captured["sql"]

    assert "from ranked order by rank" in sql


def test_ranking_query_casts_limit_to_bigint(
    captured_ranking_sql,
):
    """The optional limit must retain its explicit bigint cast."""
    captured = captured_ranking_sql()
    sql = captured["sql"]
    params = captured["params"]

    assert sql.endswith("limit cast(:limit as bigint)")
    assert params["limit"] == 5


def test_ranking_query_casts_min_leads_to_bigint(
    captured_ranking_sql,
):
    """The inclusive threshold must use an explicit bigint cast."""
    captured = captured_ranking_sql()
    sql = captured["sql"]
    params = captured["params"]

    assert "f.leads >= cast(:min_leads as bigint)" in sql
    assert params["min_leads"] == 10
