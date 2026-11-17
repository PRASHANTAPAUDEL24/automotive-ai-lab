"""
Tests for month-aware dealer performance ranking.

Day 25 ranks dealers for one month by unrounded achievement percentage.
Only dealers with a defined achievement percentage are rankable.
"""

import re
from fractions import Fraction
from pathlib import Path

import pandas as pd
import pytest
from sqlalchemy import event, text

import db

DATA_DIR = Path(__file__).resolve().parents[1] / "data"

EXPECTED_COLUMNS = [
    "dealer_id",
    "dealer_name",
    "month",
    "units_sold",
    "target_units",
    "achievement_pct",
    "rank",
]

MAX_LIMIT = 2**63 - 1


def ranking_function():
    """
    Resolve the Day 25 function at runtime so the red suite still collects
    before get_monthly_dealer_ranking() exists.
    """
    return db.get_monthly_dealer_ranking


def available_months_from_csv():
    sales = pd.read_csv(DATA_DIR / "sales_monthly.csv")
    targets = pd.read_csv(DATA_DIR / "dealer_targets.csv")

    return sorted(set(sales["month"]) | set(targets["month"]))


def expected_ranking_from_csv(month):
    """Build one month's ranking independently from the source CSV files."""
    dealers = pd.read_csv(DATA_DIR / "dealers.csv")
    sales = pd.read_csv(DATA_DIR / "sales_monthly.csv")
    targets = pd.read_csv(DATA_DIR / "dealer_targets.csv")

    month_sales = (
        sales[sales["month"].eq(month)]
        .groupby("dealer_id", as_index=False)["units_sold"]
        .sum()
    )

    month_targets = targets[targets["month"].eq(month)][["dealer_id", "target_units"]]

    frame = (
        dealers[["dealer_id", "dealer_name"]]
        .merge(month_sales, on="dealer_id", how="left")
        .merge(month_targets, on="dealer_id", how="left")
    )

    frame["units_sold"] = frame["units_sold"].fillna(0).astype(int)

    rows = []

    for row in frame.itertuples(index=False):
        if pd.isna(row.target_units):
            continue

        target_units = int(row.target_units)

        if target_units == 0:
            continue

        units_sold = int(row.units_sold)

        exact_achievement = Fraction(
            units_sold * 100,
            target_units,
        )

        rows.append(
            {
                "dealer_id": int(row.dealer_id),
                "dealer_name": row.dealer_name,
                "month": month,
                "units_sold": units_sold,
                "target_units": target_units,
                "achievement_pct": float(exact_achievement),
                "_exact_achievement": exact_achievement,
            }
        )

    rows.sort(
        key=lambda row: (
            -row["_exact_achievement"],
            row["dealer_id"],
        )
    )

    for rank, row in enumerate(rows, start=1):
        row["rank"] = rank
        del row["_exact_achievement"]

    return pd.DataFrame(rows, columns=EXPECTED_COLUMNS)


@pytest.mark.parametrize(
    "month",
    available_months_from_csv(),
)
def test_every_month_matches_independent_csv_ranking(month):
    ranking = ranking_function()

    actual = ranking(month).reset_index(drop=True)
    expected = expected_ranking_from_csv(month)

    assert list(actual.columns) == EXPECTED_COLUMNS
    assert len(actual) == len(expected)

    assert actual["dealer_id"].tolist() == expected["dealer_id"].tolist()
    assert actual["dealer_name"].tolist() == expected["dealer_name"].tolist()
    assert actual["month"].tolist() == expected["month"].tolist()
    assert actual["units_sold"].tolist() == expected["units_sold"].tolist()
    assert actual["target_units"].tolist() == expected["target_units"].tolist()
    assert actual["rank"].tolist() == expected["rank"].tolist()

    assert actual["achievement_pct"].tolist() == pytest.approx(
        expected["achievement_pct"].tolist()
    )


def test_committed_month_has_contiguous_ranks():
    ranking = ranking_function()

    result = ranking("2026-09")

    assert len(result) == 40
    assert result["rank"].tolist() == list(range(1, 41))


def test_none_limit_returns_complete_ranking():
    ranking = ranking_function()

    default_result = ranking("2026-09")
    explicit_none = ranking("2026-09", limit=None)

    pd.testing.assert_frame_equal(
        default_result.reset_index(drop=True),
        explicit_none.reset_index(drop=True),
        check_dtype=False,
    )


@pytest.mark.parametrize("limit", [1, 5, 40])
def test_limit_returns_requested_prefix_and_keeps_global_ranks(limit):
    ranking = ranking_function()

    full = ranking("2026-09")
    limited = ranking("2026-09", limit=limit)

    assert len(limited) == limit
    assert limited["rank"].tolist() == list(range(1, limit + 1))

    pd.testing.assert_frame_equal(
        limited.reset_index(drop=True),
        full.head(limit).reset_index(drop=True),
        check_dtype=False,
    )


@pytest.mark.parametrize(
    "limit",
    [
        41,
        1_000_000,
        2**31,
        MAX_LIMIT,
    ],
)
def test_oversized_valid_limit_returns_complete_pool(limit):
    ranking = ranking_function()

    result = ranking("2026-09", limit=limit)

    assert len(result) == 40
    assert result["rank"].tolist() == list(range(1, 41))


@pytest.mark.parametrize(
    "limit",
    [
        0,
        -1,
        True,
        False,
        1.5,
        "5",
        MAX_LIMIT + 1,
    ],
)
def test_invalid_limit_raises_invalid_limit_error(limit):
    ranking = ranking_function()

    expected_value = re.escape(repr(limit))

    with pytest.raises(
        db.InvalidLimitError,
        match=(
            rf"^Invalid limit: {expected_value}\. "
            rf"Expected an integer between 1 and {MAX_LIMIT}\.$"
        ),
    ):
        ranking("2026-09", limit=limit)


@pytest.mark.parametrize(
    "month",
    [
        None,
        202609,
        "2026-00",
        "2026-13",
        "2026-9",
        "26-09",
        "abcd-ef",
        "٢٠٢٦-٠٩",
        "2026-09\n",
    ],
)
def test_invalid_month_raises_invalid_month_error(month):
    ranking = ranking_function()

    expected_value = re.escape(repr(month))

    with pytest.raises(
        db.InvalidMonthError,
        match=(rf"^Invalid month: {expected_value}\. " r"Expected YYYY-MM\.$"),
    ):
        ranking(month)


def test_unknown_month_raises_month_not_found():
    ranking = ranking_function()

    with pytest.raises(
        db.MonthNotFoundError,
        match=r"^Month 2030-01 not found$",
    ):
        ranking("2030-01")


def test_tied_achievement_uses_dealer_id_tiebreak(monkeypatch):
    ranking = ranking_function()
    engine = db.get_engine()

    with engine.connect() as connection:
        transaction = connection.begin()

        try:
            monkeypatch.setattr(db, "get_engine", lambda: connection)

            # sales_monthly contains multiple model rows per dealer/month.
            # Zero all rows first, then put the desired dealer-month total
            # on exactly one existing row.
            connection.execute(text("""
                    UPDATE sales_monthly
                    SET units_sold = 0
                    WHERE dealer_id IN (101, 102)
                      AND month = '2026-09'
                    """))

            # Update dealer 102 first and dealer 101 second so physical row
            # order cannot substitute for the explicit dealer_id tie-break.
            connection.execute(text("""
                    UPDATE sales_monthly
                    SET units_sold = 100
                    WHERE ctid = (
                        SELECT ctid
                        FROM sales_monthly
                        WHERE dealer_id = 102
                          AND month = '2026-09'
                        LIMIT 1
                    )
                    """))

            connection.execute(text("""
                    UPDATE sales_monthly
                    SET units_sold = 100
                    WHERE ctid = (
                        SELECT ctid
                        FROM sales_monthly
                        WHERE dealer_id = 101
                          AND month = '2026-09'
                        LIMIT 1
                    )
                    """))

            connection.execute(text("""
                    UPDATE dealer_targets
                    SET target_units = 100
                    WHERE dealer_id IN (101, 102)
                      AND month = '2026-09'
                    """))

            result = ranking("2026-09")

            tied = result[result["dealer_id"].isin([101, 102])].reset_index(drop=True)

            assert len(tied) == 2
            assert tied["achievement_pct"].tolist() == pytest.approx([100.0, 100.0])
            assert tied["dealer_id"].tolist() == [101, 102]
            assert tied.iloc[0]["rank"] < tied.iloc[1]["rank"]

        finally:
            transaction.rollback()


def test_ranking_uses_unrounded_achievement(monkeypatch):
    ranking = ranking_function()
    engine = db.get_engine()

    with engine.connect() as connection:
        transaction = connection.begin()

        try:
            monkeypatch.setattr(db, "get_engine", lambda: connection)

            # sales_monthly contains multiple model rows per dealer/month.
            # Zero all rows first, then place the desired dealer-month total
            # on exactly one existing row.
            connection.execute(text("""
                    UPDATE sales_monthly
                    SET units_sold = 0
                    WHERE dealer_id IN (101, 102)
                      AND month = '2026-09'
                    """))

            # Dealer 102: 101 / 102 = 99.019607...
            # Dealer 101: 100 / 101 = 99.009900...
            #
            # Both round to 99.0 at one decimal, but dealer 102 must rank
            # ahead of dealer 101 using the raw achievement percentage.
            connection.execute(text("""
                    UPDATE sales_monthly
                    SET units_sold = 101
                    WHERE ctid = (
                        SELECT ctid
                        FROM sales_monthly
                        WHERE dealer_id = 102
                          AND month = '2026-09'
                        LIMIT 1
                    )
                    """))

            connection.execute(text("""
                    UPDATE sales_monthly
                    SET units_sold = 100
                    WHERE ctid = (
                        SELECT ctid
                        FROM sales_monthly
                        WHERE dealer_id = 101
                          AND month = '2026-09'
                        LIMIT 1
                    )
                    """))

            connection.execute(text("""
                    UPDATE dealer_targets
                    SET target_units = 102
                    WHERE dealer_id = 102
                      AND month = '2026-09'
                    """))

            connection.execute(text("""
                    UPDATE dealer_targets
                    SET target_units = 101
                    WHERE dealer_id = 101
                      AND month = '2026-09'
                    """))

            result = ranking("2026-09")

            rows = result[result["dealer_id"].isin([101, 102])].set_index("dealer_id")

            assert round(float(rows.loc[101, "achievement_pct"]), 1) == 99.0
            assert round(float(rows.loc[102, "achievement_pct"]), 1) == 99.0

            assert rows.loc[102, "achievement_pct"] > rows.loc[101, "achievement_pct"]
            assert rows.loc[102, "rank"] < rows.loc[101, "rank"]

        finally:
            transaction.rollback()


def test_missing_target_dealer_is_excluded_and_rollback_restores_data(
    monkeypatch,
):
    ranking = ranking_function()
    engine = db.get_engine()

    with engine.connect() as connection:
        transaction = connection.begin()

        try:
            original = connection.execute(text("""
                    SELECT target_units
                    FROM dealer_targets
                    WHERE dealer_id = 101
                      AND month = '2026-09'
                    """)).scalar_one()

            monkeypatch.setattr(db, "get_engine", lambda: connection)

            connection.execute(text("""
                    DELETE FROM dealer_targets
                    WHERE dealer_id = 101
                      AND month = '2026-09'
                    """))

            result = ranking("2026-09")

            assert 101 not in set(result["dealer_id"])
            assert len(result) == 39
            assert result["rank"].tolist() == list(range(1, 40))

        finally:
            transaction.rollback()

    monkeypatch.undo()

    with db.get_engine().connect() as connection:
        restored_value = connection.execute(text("""
                SELECT target_units
                FROM dealer_targets
                WHERE dealer_id = 101
                  AND month = '2026-09'
                """)).scalar_one()

    assert restored_value == original


def test_zero_target_dealer_is_excluded_and_rollback_restores_data(
    monkeypatch,
):
    ranking = ranking_function()
    engine = db.get_engine()

    with engine.connect() as connection:
        transaction = connection.begin()

        try:
            original = connection.execute(text("""
                    SELECT target_units
                    FROM dealer_targets
                    WHERE dealer_id = 101
                      AND month = '2026-09'
                    """)).scalar_one()

            monkeypatch.setattr(db, "get_engine", lambda: connection)

            connection.execute(text("""
                    UPDATE dealer_targets
                    SET target_units = 0
                    WHERE dealer_id = 101
                      AND month = '2026-09'
                    """))

            result = ranking("2026-09")

            assert 101 not in set(result["dealer_id"])
            assert len(result) == 39
            assert result["rank"].tolist() == list(range(1, 40))

        finally:
            transaction.rollback()

    monkeypatch.undo()

    with db.get_engine().connect() as connection:
        restored_value = connection.execute(text("""
                SELECT target_units
                FROM dealer_targets
                WHERE dealer_id = 101
                  AND month = '2026-09'
                """)).scalar_one()

    assert restored_value == original


def test_existing_month_with_no_rankable_dealers_returns_empty(monkeypatch):
    ranking = ranking_function()
    engine = db.get_engine()

    with engine.connect() as connection:
        transaction = connection.begin()

        try:
            monkeypatch.setattr(db, "get_engine", lambda: connection)

            connection.execute(text("""
                    UPDATE dealer_targets
                    SET target_units = 0
                    WHERE month = '2026-09'
                    """))

            result = ranking("2026-09")

            assert result.empty
            assert list(result.columns) == EXPECTED_COLUMNS

        finally:
            transaction.rollback()


def test_missing_and_zero_target_dealers_never_receive_rank(monkeypatch):
    ranking = ranking_function()
    engine = db.get_engine()

    with engine.connect() as connection:
        transaction = connection.begin()

        try:
            monkeypatch.setattr(db, "get_engine", lambda: connection)

            connection.execute(text("""
                    DELETE FROM dealer_targets
                    WHERE dealer_id = 101
                      AND month = '2026-09'
                    """))

            connection.execute(text("""
                    UPDATE dealer_targets
                    SET target_units = 0
                    WHERE dealer_id = 102
                      AND month = '2026-09'
                    """))

            result = ranking("2026-09")

            assert 101 not in set(result["dealer_id"])
            assert 102 not in set(result["dealer_id"])
            assert len(result) == 38
            assert result["rank"].tolist() == list(range(1, 39))

        finally:
            transaction.rollback()


def test_ranking_executes_required_sql_structure():
    ranking = ranking_function()
    engine = db.get_engine()
    statements = []

    def capture(
        connection,
        cursor,
        statement,
        parameters,
        context,
        executemany,
    ):
        statements.append(" ".join(statement.split()).lower())

    event.listen(engine, "before_cursor_execute", capture)

    try:
        ranking("2026-09", limit=5)
    finally:
        event.remove(engine, "before_cursor_execute", capture)

    ranked = [statement for statement in statements if "row_number" in statement]

    assert len(ranked) == 1

    sql = ranked[0]

    assert "row_number() over " "(order by achievement_pct desc, dealer_id asc)" in sql
    assert "achievement_pct is not null" in sql

    assert sql.index("row_number") < sql.rindex("order by rank")
    assert sql.rindex("order by rank") < sql.index("limit")

    assert "limit cast(%(limit)s as bigint)" in sql
