# Program: tests/test_dealer_performance.py
# Day 19: database tests for dealer-level monthly performance history.
# Created on: 2026-11-10
# Author: Prashanta Paudel
# Purpose: Validate dealer-level monthly performance history against the source CSV files.


from pathlib import Path

import pandas as pd
import pytest

import db

# Project data directory used to build independent expected results.
DATA_DIR = Path(__file__).resolve().parents[1] / "data"

# Exact column order expected from get_dealer_performance_history().
HISTORY_COLUMNS = [
    "dealer_id",
    "dealer_name",
    "month",
    "units_sold",
    "target_units",
    "achievement_pct",
]


def expected_history_from_csv(dealer_id):
    """
    Build one dealer's expected monthly history directly from committed CSV files.

    This gives us an independent pandas calculation to compare against the
    PostgreSQL/Python query result.
    """

    dealers = pd.read_csv(DATA_DIR / "dealers.csv")
    sales = pd.read_csv(DATA_DIR / "sales_monthly.csv")
    targets = pd.read_csv(DATA_DIR / "dealer_targets.csv")

    # Available months come from the union of sales and target months.
    months = sorted(set(sales["month"]).union(targets["month"]))

    # Keep only the requested dealer.
    dealer = dealers.loc[
        dealers["dealer_id"] == dealer_id,
        ["dealer_id", "dealer_name"],
    ]

    # Unknown dealer: return an empty frame with the expected schema.
    if dealer.empty:
        return pd.DataFrame(columns=HISTORY_COLUMNS)

    # Create one row for every available month.
    month_frame = pd.DataFrame({"month": months})
    expected = dealer.merge(month_frame, how="cross")

    # Aggregate sales in case the source ever contains multiple rows
    # for the same dealer and month.
    sales_agg = sales.groupby(
        ["dealer_id", "month"],
        as_index=False,
    )["units_sold"].sum()

    expected = expected.merge(
        sales_agg,
        on=["dealer_id", "month"],
        how="left",
    )

    # Missing sales activity should appear as zero units sold.
    expected["units_sold"] = expected["units_sold"].fillna(0).astype(int)

    # Attach dealer targets for each month.
    expected = expected.merge(
        targets[
            [
                "dealer_id",
                "month",
                "target_units",
            ]
        ],
        on=["dealer_id", "month"],
        how="left",
    )

    # A missing or zero target must not be used as a denominator.
    valid_target = expected["target_units"].where(expected["target_units"].ne(0))

    expected["achievement_pct"] = expected["units_sold"] * 100.0 / valid_target

    # Match the database function's expected schema and chronological order.
    return expected[HISTORY_COLUMNS].sort_values("month").reset_index(drop=True)


def test_dealer_history_returns_24_months():
    """A known dealer should have the complete 24-month history."""

    history = db.get_dealer_performance_history(111)

    assert len(history) == 24
    assert history["month"].iloc[0] == "2024-10"
    assert history["month"].iloc[-1] == "2026-09"


def test_dealer_history_months_are_sorted():
    """History should be returned oldest month first."""

    history = db.get_dealer_performance_history(111)

    months = history["month"].tolist()

    assert months == sorted(months)


def test_dealer_history_has_expected_columns():
    """The function should return exactly the MonthlyPerformance fields."""

    history = db.get_dealer_performance_history(111)

    assert history.columns.tolist() == HISTORY_COLUMNS


def test_dealer_history_contains_only_requested_dealer():
    """No rows from another dealer should leak into the result."""

    history = db.get_dealer_performance_history(111)

    assert history["dealer_id"].nunique() == 1
    assert history["dealer_id"].iloc[0] == 111


@pytest.mark.parametrize(
    "dealer_id",
    pd.read_csv(DATA_DIR / "dealers.csv")["dealer_id"].tolist(),
)
def test_every_dealer_has_24_months(dealer_id):
    """Every dealer in the committed dealer list should have 24 history rows."""

    history = db.get_dealer_performance_history(dealer_id)

    assert len(history) == 24


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
def test_unknown_dealer_raises_dealer_not_found_error(dealer_id):
    """Unknown dealer IDs should raise the dedicated exception."""

    with pytest.raises(
        db.DealerNotFoundError,
        match=f"Dealer {dealer_id} not found",
    ):
        db.get_dealer_performance_history(dealer_id)


@pytest.mark.parametrize(
    "dealer_id",
    pd.read_csv(DATA_DIR / "dealers.csv")["dealer_id"].tolist(),
)
def test_dealer_history_matches_csv_calculation(dealer_id):
    """Each dealer history should match an independent pandas calculation."""

    actual = db.get_dealer_performance_history(dealer_id)
    expected = expected_history_from_csv(dealer_id)

    pd.testing.assert_frame_equal(
        actual.reset_index(drop=True),
        expected,
        check_dtype=False,
        check_exact=False,
        rtol=1e-10,
        atol=1e-10,
    )


def test_september_history_matches_scorecard():
    """
    The September history row should preserve existing scorecard behavior.

    This protects compatibility between the new historical query and the
    established September-specific scorecard.
    """

    history = db.get_dealer_performance_history(111)
    scorecard = db.get_scorecard()

    september = history.loc[history["month"] == "2026-09"].iloc[0]

    dealer = scorecard.loc[scorecard["dealer_id"] == 111].iloc[0]

    assert september["units_sold"] == dealer["units_sold"]
    assert september["target_units"] == dealer["target_units"]

    assert september["achievement_pct"] == pytest.approx(dealer["achievement_pct"])


def test_dealer_not_found_error_hierarchy():
    """DealerNotFoundError should remain a distinct ValueError subtype."""

    assert issubclass(db.DealerNotFoundError, ValueError)
    assert not issubclass(
        db.DealerNotFoundError,
        db.MonthNotFoundError,
    )
    assert not issubclass(
        db.DealerNotFoundError,
        db.InvalidMonthError,
    )
