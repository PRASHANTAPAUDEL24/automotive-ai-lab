"""
Tests for dealer-level monthly performance range filtering.

Day 20 extends dealer history with optional inclusive start and end
month bounds while preserving Day 19 full-history behavior.
"""

from pathlib import Path

import pandas as pd
import pytest

from db import (
    DealerNotFoundError,
    InvalidMonthError,
    InvalidMonthRangeError,
    get_dealer_performance_history,
)

DATA_DIR = Path(__file__).resolve().parents[1] / "data"


def expected_history_from_csv(dealer_id, start=None, end=None):
    """
    Build one dealer's expected monthly history directly from the source CSVs.

    This calculation is intentionally independent of the database implementation
    so the tests can detect SQL and filtering mistakes rather than reproduce them.
    """
    dealers = pd.read_csv(DATA_DIR / "dealers.csv")
    sales = pd.read_csv(DATA_DIR / "sales_monthly.csv")
    targets = pd.read_csv(DATA_DIR / "dealer_targets.csv")

    dealer = dealers.loc[dealers["dealer_id"] == dealer_id]

    if dealer.empty:
        return pd.DataFrame()

    dealer_name = dealer.iloc[0]["dealer_name"]

    months = sorted(set(sales["month"].tolist()) | set(targets["month"].tolist()))

    rows = []

    for month in months:
        if start is not None and month < start:
            continue

        if end is not None and month > end:
            continue

        month_sales = sales[
            (sales["dealer_id"] == dealer_id) & (sales["month"] == month)
        ]

        units_sold = int(month_sales["units_sold"].sum())

        month_target = targets[
            (targets["dealer_id"] == dealer_id) & (targets["month"] == month)
        ]

        if month_target.empty:
            target_units = None
            achievement_pct = None
        else:
            target_units = int(month_target.iloc[0]["target_units"])

            if target_units == 0:
                achievement_pct = None
            else:
                achievement_pct = units_sold * 100.0 / target_units

        rows.append(
            {
                "dealer_id": dealer_id,
                "dealer_name": dealer_name,
                "month": month,
                "units_sold": units_sold,
                "target_units": target_units,
                "achievement_pct": achievement_pct,
            }
        )

    return pd.DataFrame(rows)


def test_no_range_preserves_full_history():
    """
    Preserve Day 19 behavior when no range bounds are supplied.
    """
    history = get_dealer_performance_history(101)

    assert len(history) == 24
    assert history.iloc[0]["month"] == "2024-10"
    assert history.iloc[-1]["month"] == "2026-09"


def test_start_only_is_inclusive():
    """
    Include the requested start month and continue through the latest month.
    """
    history = get_dealer_performance_history(
        101,
        start="2026-01",
    )

    assert history["month"].tolist() == [
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
    Include the requested end month and begin at the earliest available month.
    """
    history = get_dealer_performance_history(
        101,
        end="2024-12",
    )

    assert history["month"].tolist() == [
        "2024-10",
        "2024-11",
        "2024-12",
    ]


def test_both_bounds_are_inclusive():
    """
    Include both the start and end months in a bounded range.
    """
    history = get_dealer_performance_history(
        101,
        start="2025-03",
        end="2025-05",
    )

    assert history["month"].tolist() == [
        "2025-03",
        "2025-04",
        "2025-05",
    ]


def test_equal_start_and_end_returns_one_month():
    """
    Treat equal start and end values as a valid one-month range.
    """
    history = get_dealer_performance_history(
        101,
        start="2025-03",
        end="2025-03",
    )

    assert history["month"].tolist() == ["2025-03"]


@pytest.mark.parametrize(
    ("start", "end"),
    [
        ("2030-01", "2030-12"),
        ("2020-01", "2020-12"),
        ("2030-01", None),
        (None, "2020-12"),
    ],
)
def test_real_dealer_with_empty_window_returns_empty(start, end):
    """
    Return an empty result when a real dealer has no rows in the range.

    An empty range result is different from an unknown dealer.
    """
    history = get_dealer_performance_history(
        101,
        start=start,
        end=end,
    )

    assert history.empty


def test_unknown_dealer_with_range_still_raises_not_found():
    """
    Raise DealerNotFoundError when the dealer itself does not exist.

    The existence check must distinguish an unknown dealer from a real dealer
    whose requested range contains no rows.
    """
    with pytest.raises(
        DealerNotFoundError,
        match=r"^Dealer 999 not found$",
    ):
        get_dealer_performance_history(
            999,
            start="2030-01",
            end="2030-12",
        )


@pytest.mark.parametrize(
    ("start", "end"),
    [
        ("2026-09", "2026-08"),
        ("2025-12", "2025-01"),
    ],
)
def test_start_after_end_raises_invalid_range(start, end):
    """
    Reject a reversed range after both month values pass format validation.
    """
    with pytest.raises(
        InvalidMonthRangeError,
        match=r"^start month must not be after end month$",
    ):
        get_dealer_performance_history(
            101,
            start=start,
            end=end,
        )


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
def test_invalid_start_format_raises_invalid_month(start):
    """
    Require strict ASCII YYYY-MM formatting for the optional start bound.
    """
    with pytest.raises(InvalidMonthError):
        get_dealer_performance_history(
            101,
            start=start,
        )


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
def test_invalid_end_format_raises_invalid_month(end):
    """
    Require strict ASCII YYYY-MM formatting for the optional end bound.
    """
    with pytest.raises(InvalidMonthError):
        get_dealer_performance_history(
            101,
            end=end,
        )


@pytest.mark.parametrize(
    ("start", "end"),
    [
        (123, None),
        (None, 123),
        (202603, None),
        (None, 202603),
    ],
)
def test_non_string_bound_raises_invalid_month(start, end):
    """
    Return a domain validation error instead of leaking a regex TypeError.

    This protects direct callers of the database-layer function that do not
    pass through FastAPI's query validation.
    """
    with pytest.raises(InvalidMonthError):
        get_dealer_performance_history(
            101,
            start=start,
            end=end,
        )


def test_none_bounds_are_valid():
    """
    Treat None as an absent optional bound.
    """
    history = get_dealer_performance_history(
        101,
        start=None,
        end=None,
    )

    assert len(history) == 24


@pytest.mark.parametrize(
    ("dealer_id", "start", "end"),
    [
        (101, "2024-10", "2024-12"),
        (111, "2025-03", "2025-08"),
        (125, "2026-01", "2026-09"),
        (140, "2024-10", "2026-09"),
    ],
)
def test_range_matches_independent_csv_calculation(
    dealer_id,
    start,
    end,
):
    """
    Cross-check representative dealer ranges against source CSV calculations.
    """
    actual = get_dealer_performance_history(
        dealer_id,
        start=start,
        end=end,
    ).reset_index(drop=True)

    expected = expected_history_from_csv(
        dealer_id,
        start=start,
        end=end,
    ).reset_index(drop=True)

    pd.testing.assert_frame_equal(
        actual,
        expected,
        check_dtype=False,
    )
