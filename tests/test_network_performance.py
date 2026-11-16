"""
Tests for network-wide monthly sales and target performance.

Day 24 introduces one monthly trend across the complete dealer network,
with optional inclusive month bounds and the same weighted aggregation
semantics used by regional performance.
"""

from pathlib import Path

import pandas as pd
import pytest
from sqlalchemy import text

import db

DATA_DIR = Path(__file__).resolve().parents[1] / "data"

EXPECTED_COLUMNS = [
    "month",
    "dealer_count",
    "units_sold",
    "target_units",
    "achievement_pct",
]


def expected_network_history_from_csv(start=None, end=None):
    """Build network monthly performance independently from the source CSVs."""
    dealers = pd.read_csv(DATA_DIR / "dealers.csv")
    sales = pd.read_csv(DATA_DIR / "sales_monthly.csv")
    targets = pd.read_csv(DATA_DIR / "dealer_targets.csv")

    dealer_ids = dealers["dealer_id"].tolist()
    months = sorted(set(sales["month"]) | set(targets["month"]))

    rows = []

    for month in months:
        if start is not None and month < start:
            continue

        if end is not None and month > end:
            continue

        month_sales = sales[
            sales["dealer_id"].isin(dealer_ids) & sales["month"].eq(month)
        ]

        month_targets = targets[
            targets["dealer_id"].isin(dealer_ids) & targets["month"].eq(month)
        ]

        units_sold = int(month_sales["units_sold"].sum())

        if len(month_targets) < len(dealer_ids):
            target_units = None
            achievement_pct = None
        else:
            target_units = int(month_targets["target_units"].sum())

            if target_units == 0:
                achievement_pct = None
            else:
                achievement_pct = units_sold * 100.0 / target_units

        rows.append(
            {
                "month": month,
                "dealer_count": len(dealer_ids),
                "units_sold": units_sold,
                "target_units": target_units,
                "achievement_pct": achievement_pct,
            }
        )

    return pd.DataFrame(rows, columns=EXPECTED_COLUMNS)


def test_network_history_returns_all_24_months():
    history = db.get_network_performance_history()

    assert len(history) == 24
    assert list(history.columns) == EXPECTED_COLUMNS
    assert history["month"].iloc[0] == "2024-10"
    assert history["month"].iloc[-1] == "2026-09"
    assert history["month"].tolist() == sorted(history["month"])
    assert set(history["dealer_count"]) == {40}


def test_network_history_matches_independent_csv_calculation():
    actual = db.get_network_performance_history().reset_index(drop=True)
    expected = expected_network_history_from_csv()

    pd.testing.assert_frame_equal(
        actual,
        expected,
        check_dtype=False,
    )


def test_network_achievement_uses_ratio_of_sums():
    history = db.get_network_performance_history(
        start="2026-01",
        end="2026-01",
    )

    assert len(history) == 1

    row = history.iloc[0]

    assert row["dealer_count"] == 40
    assert row["achievement_pct"] == pytest.approx(
        row["units_sold"] * 100.0 / row["target_units"]
    )


@pytest.mark.parametrize(
    ("start", "end", "first_month", "last_month", "count"),
    [
        ("2026-01", None, "2026-01", "2026-09", 9),
        (None, "2025-03", "2024-10", "2025-03", 6),
        ("2025-04", "2025-08", "2025-04", "2025-08", 5),
        ("2026-09", "2026-09", "2026-09", "2026-09", 1),
    ],
)
def test_network_history_range_is_inclusive(
    start,
    end,
    first_month,
    last_month,
    count,
):
    history = db.get_network_performance_history(
        start=start,
        end=end,
    )

    assert len(history) == count
    assert history["month"].iloc[0] == first_month
    assert history["month"].iloc[-1] == last_month


@pytest.mark.parametrize(
    ("start", "end"),
    [
        ("2020-01", "2020-12"),
        ("2030-01", "2030-12"),
    ],
)
def test_valid_empty_window_returns_empty(start, end):
    history = db.get_network_performance_history(
        start=start,
        end=end,
    )

    assert history.empty
    assert list(history.columns) == EXPECTED_COLUMNS


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
        202601,
    ],
)
def test_invalid_start_raises_invalid_month(start):
    with pytest.raises(
        db.InvalidMonthError,
        match=r"^start month must use YYYY-MM format$",
    ):
        db.get_network_performance_history(start=start)


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
        202601,
    ],
)
def test_invalid_end_raises_invalid_month(end):
    with pytest.raises(
        db.InvalidMonthError,
        match=r"^end month must use YYYY-MM format$",
    ):
        db.get_network_performance_history(end=end)


@pytest.mark.parametrize(
    ("start", "end"),
    [
        ("2026-09", "2026-08"),
        ("2025-12", "2025-01"),
    ],
)
def test_reversed_range_raises_invalid_month_range(start, end):
    with pytest.raises(
        db.InvalidMonthRangeError,
        match=r"^start month must not be after end month$",
    ):
        db.get_network_performance_history(
            start=start,
            end=end,
        )


@pytest.mark.parametrize(
    ("start", "end"),
    [
        (None, None),
        ("2026-01", None),
        (None, "2025-03"),
        ("2025-01", "2025-03"),
        ("2025-06", "2025-06"),
    ],
)
def test_range_matches_independent_csv_calculation(start, end):
    actual = db.get_network_performance_history(
        start=start,
        end=end,
    ).reset_index(drop=True)

    expected = expected_network_history_from_csv(
        start=start,
        end=end,
    )

    assert len(expected) > 0

    pd.testing.assert_frame_equal(
        actual,
        expected,
        check_dtype=False,
    )


def test_network_matches_sum_of_regions_for_every_month():
    regions = [
        "Midwest",
        "Northeast",
        "Southeast",
        "Southwest",
        "West",
    ]

    regional = pd.concat(
        [db.get_region_performance_history(region) for region in regions],
        ignore_index=True,
    )

    regional_totals = regional.groupby("month")[
        ["dealer_count", "units_sold", "target_units"]
    ].sum()

    network = db.get_network_performance_history().set_index("month")

    assert len(network) == 24

    for month in network.index:
        assert (
            network.loc[month, "dealer_count"]
            == regional_totals.loc[month, "dealer_count"]
        )
        assert (
            network.loc[month, "units_sold"] == regional_totals.loc[month, "units_sold"]
        )
        assert (
            network.loc[month, "target_units"]
            == regional_totals.loc[month, "target_units"]
        )


def test_result_values_convert_to_json_friendly_types():
    rows = db.to_records(db.get_network_performance_history())

    for row in rows:
        assert type(row["dealer_count"]) is int
        assert type(row["units_sold"]) is int
        assert type(row["target_units"]) is int
        assert type(row["achievement_pct"]) is float


MISSING_TARGET_SQL = """
    DELETE FROM dealer_targets
    WHERE ctid IN (
        SELECT ctid
        FROM dealer_targets
        WHERE month = '2025-06'
        LIMIT 1
    )
"""


ZERO_TARGET_SQL = """
    UPDATE dealer_targets
    SET target_units = 0
    WHERE month = '2025-07'
"""


def history_inside_rolled_back_transaction(
    monkeypatch,
    statement,
    start,
    end,
):
    """Run the real network query against temporary transactional data."""
    with db.get_engine().connect() as connection:
        transaction = connection.begin()

        try:
            connection.execute(text(statement))
            monkeypatch.setattr(db, "get_engine", lambda: connection)

            return db.to_records(
                db.get_network_performance_history(
                    start=start,
                    end=end,
                )
            )
        finally:
            transaction.rollback()


def test_missing_target_makes_network_target_and_achievement_null(monkeypatch):
    rows = history_inside_rolled_back_transaction(
        monkeypatch,
        MISSING_TARGET_SQL,
        "2025-06",
        "2025-06",
    )

    assert len(rows) == 1
    assert rows[0]["dealer_count"] == 40
    assert rows[0]["target_units"] is None
    assert rows[0]["achievement_pct"] is None

    monkeypatch.undo()

    restored = db.to_records(
        db.get_network_performance_history(
            start="2025-06",
            end="2025-06",
        )
    )

    assert restored[0]["target_units"] is not None
    assert restored[0]["achievement_pct"] is not None


def test_zero_total_target_gives_zero_target_and_null_achievement(monkeypatch):
    rows = history_inside_rolled_back_transaction(
        monkeypatch,
        ZERO_TARGET_SQL,
        "2025-07",
        "2025-07",
    )

    assert len(rows) == 1
    assert rows[0]["dealer_count"] == 40
    assert rows[0]["target_units"] == 0
    assert rows[0]["achievement_pct"] is None

    monkeypatch.undo()

    restored = db.to_records(
        db.get_network_performance_history(
            start="2025-07",
            end="2025-07",
        )
    )

    assert restored[0]["target_units"] != 0
    assert restored[0]["achievement_pct"] is not None


def test_network_query_explicitly_orders_by_month(monkeypatch):
    captured = {}

    expected = pd.DataFrame(
        [
            {
                "month": "2024-10",
                "dealer_count": 40,
                "units_sold": 1,
                "target_units": 1,
                "achievement_pct": 100.0,
            }
        ]
    )

    def fake_read_sql(query, engine, params=None):
        captured["query"] = str(query)
        captured["params"] = params
        return expected.copy()

    monkeypatch.setattr(db.pd, "read_sql", fake_read_sql)

    result = db.get_network_performance_history()

    assert len(result) == 1
    assert "ORDER BY dmp.month" in captured["query"]
    assert captured["params"] == {}
