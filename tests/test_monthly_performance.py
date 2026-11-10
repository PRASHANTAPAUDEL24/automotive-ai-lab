# Program: tests/test_monthly_performance.py
# Day 18: pytest tests for month-aware dealer performance
# Created on: 2026-11-09
# Author: Prashanta Paudel
# Purpose: Validate monthly performance queries against the source CSV files.

from pathlib import Path

import pandas as pd
import pytest

import db

DATA_DIR = Path(__file__).resolve().parents[1] / "data"

MONTHLY_COLUMNS = [
    "dealer_id",
    "dealer_name",
    "month",
    "units_sold",
    "target_units",
    "achievement_pct",
]


def expected_months_from_csv():
    sales = pd.read_csv(DATA_DIR / "sales_monthly.csv")
    targets = pd.read_csv(DATA_DIR / "dealer_targets.csv")

    return sorted(set(sales["month"]) | set(targets["month"]))


CSV_MONTHS = expected_months_from_csv()


def expected_monthly_performance_from_csv():
    dealers = pd.read_csv(
        DATA_DIR / "dealers.csv",
        usecols=["dealer_id", "dealer_name"],
    )
    sales = pd.read_csv(DATA_DIR / "sales_monthly.csv")
    targets = pd.read_csv(DATA_DIR / "dealer_targets.csv")

    dealer_months = (
        pd.MultiIndex.from_product(
            [dealers["dealer_id"], CSV_MONTHS],
            names=["dealer_id", "month"],
        )
        .to_frame(index=False)
        .merge(
            dealers,
            on="dealer_id",
            how="left",
        )
    )

    monthly_sales = sales.groupby(
        ["dealer_id", "month"],
        as_index=False,
    )["units_sold"].sum()

    expected = dealer_months.merge(
        monthly_sales,
        on=["dealer_id", "month"],
        how="left",
    ).merge(
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

    expected["units_sold"] = expected["units_sold"].fillna(0).astype(int)

    valid_target = expected["target_units"].where(expected["target_units"].ne(0))

    expected["achievement_pct"] = expected["units_sold"] * 100.0 / valid_target

    return (
        expected[MONTHLY_COLUMNS]
        .sort_values(["month", "dealer_id"])
        .reset_index(drop=True)
    )


def test_month_errors_are_distinct_value_error_subclasses():
    assert issubclass(db.InvalidMonthError, ValueError)
    assert issubclass(db.MonthNotFoundError, ValueError)

    assert not issubclass(
        db.InvalidMonthError,
        db.MonthNotFoundError,
    )
    assert not issubclass(
        db.MonthNotFoundError,
        db.InvalidMonthError,
    )


def test_available_months_match_csv_files():
    actual = db.get_available_months()

    assert actual == CSV_MONTHS
    assert len(actual) == 24
    assert actual[0] == "2024-10"
    assert actual[-1] == "2026-09"


@pytest.mark.parametrize("month", CSV_MONTHS)
def test_every_available_month_returns_all_40_dealers(month):
    performance = db.get_monthly_performance(month)

    assert len(performance) == 40
    assert performance["dealer_id"].nunique() == 40
    assert set(performance["month"]) == {month}
    assert list(performance["dealer_id"]) == sorted(performance["dealer_id"])


def test_monthly_performance_has_expected_columns_in_order():
    performance = db.get_monthly_performance("2025-03")

    assert list(performance.columns) == MONTHLY_COLUMNS


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
        "2026-03' OR '1'='1",
        "\u0662\u0660\u0662\u0666-03",  # Arabic-Indic 2026, ASCII month
        None,
    ],
)
def test_invalid_month_format_raises_invalid_month_error(month):
    with pytest.raises(db.InvalidMonthError):
        db.get_monthly_performance(month)


@pytest.mark.parametrize(
    "month",
    [
        "2026-3",
        "2026-13",
        "abc",
        "",
    ],
)
def test_invalid_month_does_not_raise_month_not_found(month):
    with pytest.raises(db.InvalidMonthError) as exc_info:
        db.get_monthly_performance(month)

    assert not isinstance(
        exc_info.value,
        db.MonthNotFoundError,
    )


@pytest.mark.parametrize(
    "month",
    [
        "2024-09",
        "2026-10",
        "2030-01",
    ],
)
def test_unknown_well_formed_month_raises_month_not_found(month):
    with pytest.raises(
        db.MonthNotFoundError,
        match=month,
    ):
        db.get_monthly_performance(month)


def test_september_monthly_performance_matches_scorecard():
    monthly = db.get_monthly_performance("2026-09")[
        [
            "dealer_id",
            "dealer_name",
            "units_sold",
            "target_units",
            "achievement_pct",
        ]
    ].reset_index(drop=True)

    scorecard = (
        db.get_scorecard()[
            [
                "dealer_id",
                "dealer_name",
                "units_sold",
                "target_units",
                "achievement_pct",
            ]
        ]
        .sort_values("dealer_id")
        .reset_index(drop=True)
    )

    pd.testing.assert_frame_equal(
        monthly,
        scorecard,
        check_dtype=False,
        rtol=1e-12,
    )


def test_monthly_performance_matches_csv_for_all_dealer_months():
    expected = expected_monthly_performance_from_csv()

    actual = pd.concat(
        [db.get_monthly_performance(month) for month in CSV_MONTHS],
        ignore_index=True,
    )

    actual = (
        actual[MONTHLY_COLUMNS]
        .sort_values(["month", "dealer_id"])
        .reset_index(drop=True)
    )

    assert len(actual) == 960

    actual = actual.set_index(["month", "dealer_id"])
    expected = expected.set_index(["month", "dealer_id"])

    pd.testing.assert_frame_equal(
        actual,
        expected,
        check_dtype=False,
        rtol=1e-12,
    )
