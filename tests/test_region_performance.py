"""
Tests for regional monthly sales and target performance.

Day 22 introduces region-level historical aggregation with optional
inclusive month bounds while preserving the existing monthly data grain.
"""

import re
from pathlib import Path

import pandas as pd
import pytest
from sqlalchemy import text

import db

DATA_DIR = Path(__file__).resolve().parents[1] / "data"

REGIONS = [
    "Midwest",
    "Northeast",
    "Southeast",
    "Southwest",
    "West",
]

EXPECTED_COLUMNS = [
    "region",
    "month",
    "dealer_count",
    "units_sold",
    "target_units",
    "achievement_pct",
]


def expected_region_history_from_csv(region, start=None, end=None):
    """
    Build one region's monthly performance directly from the source CSV files.

    This calculation is intentionally independent of the database query so the
    tests can detect aggregation, filtering and weighting mistakes.
    """
    dealers = pd.read_csv(DATA_DIR / "dealers.csv")
    sales = pd.read_csv(DATA_DIR / "sales_monthly.csv")
    targets = pd.read_csv(DATA_DIR / "dealer_targets.csv")

    region_dealers = dealers.loc[
        dealers["region"] == region,
        ["dealer_id", "region"],
    ]

    if region_dealers.empty:
        return pd.DataFrame(columns=EXPECTED_COLUMNS)

    dealer_ids = region_dealers["dealer_id"].tolist()

    months = sorted(set(sales["month"].tolist()) | set(targets["month"].tolist()))

    rows = []

    for month in months:
        if start is not None and month < start:
            continue

        if end is not None and month > end:
            continue

        month_sales = sales[
            (sales["dealer_id"].isin(dealer_ids)) & (sales["month"] == month)
        ]

        month_targets = targets[
            (targets["dealer_id"].isin(dealer_ids)) & (targets["month"] == month)
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
                "region": region,
                "month": month,
                "dealer_count": len(dealer_ids),
                "units_sold": units_sold,
                "target_units": target_units,
                "achievement_pct": achievement_pct,
            }
        )

    return pd.DataFrame(rows, columns=EXPECTED_COLUMNS)


@pytest.mark.parametrize("region", REGIONS)
def test_region_history_returns_all_24_months(region):
    history = db.get_region_performance_history(region)

    assert len(history) == 24
    assert list(history.columns) == EXPECTED_COLUMNS
    assert history["month"].iloc[0] == "2024-10"
    assert history["month"].iloc[-1] == "2026-09"
    assert history["month"].tolist() == sorted(history["month"].tolist())
    assert set(history["region"]) == {region}
    assert set(history["dealer_count"]) == {8}


@pytest.mark.parametrize("region", REGIONS)
def test_region_history_matches_independent_csv_calculation(region):
    actual = db.get_region_performance_history(region).reset_index(drop=True)

    expected = expected_region_history_from_csv(region)

    pd.testing.assert_frame_equal(
        actual,
        expected,
        check_dtype=False,
    )


def test_region_achievement_uses_ratio_of_sums_not_average_percentage():
    history = db.get_region_performance_history(
        "Midwest",
        start="2026-01",
        end="2026-01",
    )

    row = history.iloc[0]

    assert row["dealer_count"] == 8
    assert row["achievement_pct"] == pytest.approx(
        row["units_sold"] / row["target_units"] * 100
    )

    assert row["achievement_pct"] == pytest.approx(92.51336898395722)

    assert row["achievement_pct"] != pytest.approx(100.58333333333333)


def test_midwest_october_2024_anchor_row():
    history = db.get_region_performance_history(
        "Midwest",
        start="2024-10",
        end="2024-10",
    )

    row = history.iloc[0]

    assert row["region"] == "Midwest"
    assert row["month"] == "2024-10"
    assert row["dealer_count"] == 8
    assert row["units_sold"] == 211
    assert row["target_units"] == 220
    assert row["achievement_pct"] == pytest.approx(211 / 220 * 100)


@pytest.mark.parametrize(
    ("start", "end", "first_month", "last_month", "count"),
    [
        ("2026-01", None, "2026-01", "2026-09", 9),
        (None, "2025-03", "2024-10", "2025-03", 6),
        ("2025-04", "2025-08", "2025-04", "2025-08", 5),
        ("2026-09", "2026-09", "2026-09", "2026-09", 1),
    ],
)
def test_region_history_range_is_inclusive(
    start,
    end,
    first_month,
    last_month,
    count,
):
    history = db.get_region_performance_history(
        "Midwest",
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
def test_valid_region_with_empty_window_returns_empty(start, end):
    history = db.get_region_performance_history(
        "Midwest",
        start=start,
        end=end,
    )

    assert history.empty
    assert list(history.columns) == EXPECTED_COLUMNS


@pytest.mark.parametrize(
    "region",
    [
        "Atlantis",
        "midwest",
        "Northeast ",
        "' OR '1'='1",
    ],
)
def test_unknown_region_raises_region_not_found(region):
    error_type = db.RegionNotFoundError

    with pytest.raises(
        error_type,
        match=rf"^Region {re.escape(region)} not found$",
    ):
        db.get_region_performance_history(region)


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
    with pytest.raises(db.InvalidMonthError):
        db.get_region_performance_history(
            "Midwest",
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
        202601,
    ],
)
def test_invalid_end_raises_invalid_month(end):
    with pytest.raises(db.InvalidMonthError):
        db.get_region_performance_history(
            "Midwest",
            end=end,
        )


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
        db.get_region_performance_history(
            "Midwest",
            start=start,
            end=end,
        )


@pytest.mark.parametrize("region", REGIONS)
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
def test_range_matches_independent_csv_calculation(region, start, end):
    actual = db.get_region_performance_history(
        region,
        start=start,
        end=end,
    ).reset_index(drop=True)

    expected = expected_region_history_from_csv(
        region,
        start=start,
        end=end,
    )

    assert len(expected) > 0

    pd.testing.assert_frame_equal(
        actual,
        expected,
        check_dtype=False,
    )


def test_region_totals_match_network_totals_for_every_month():
    frames = [db.get_region_performance_history(region) for region in REGIONS]

    totals = (
        pd.concat(frames)
        .groupby("month")[["dealer_count", "units_sold", "target_units"]]
        .sum()
    )

    assert len(totals) == 24

    for month in totals.index:
        network = db.get_monthly_performance(month)

        assert totals.loc[month, "dealer_count"] == len(network) == 40
        assert totals.loc[month, "units_sold"] == network["units_sold"].sum()
        assert totals.loc[month, "target_units"] == network["target_units"].sum()


def test_result_values_convert_to_json_friendly_types():
    rows = db.to_records(db.get_region_performance_history("Midwest"))

    for row in rows:
        assert type(row["dealer_count"]) is int
        assert type(row["units_sold"]) is int
        assert type(row["target_units"]) is int
        assert type(row["achievement_pct"]) is float


def test_month_validation_happens_before_region_lookup():
    with pytest.raises(db.InvalidMonthError):
        db.get_region_performance_history(
            "Atlantis",
            start="2026-13",
        )

    with pytest.raises(db.InvalidMonthRangeError):
        db.get_region_performance_history(
            "Atlantis",
            start="2026-09",
            end="2026-08",
        )


def test_region_not_found_error_hierarchy():
    assert issubclass(db.RegionNotFoundError, ValueError)

    for other in (
        db.DealerNotFoundError,
        db.InvalidMonthError,
        db.InvalidMonthRangeError,
        db.MonthNotFoundError,
    ):
        assert not issubclass(db.RegionNotFoundError, other)


def test_injection_attempt_leaves_data_unchanged():
    with pytest.raises(db.RegionNotFoundError):
        db.get_region_performance_history("Northeast'; DROP TABLE dealers; --")

    assert len(db.get_region_performance_history("Northeast")) == 24


@pytest.mark.parametrize(
    "region",
    [
        "MIDWEST",
        " Midwest",
        "",
    ],
)
def test_more_unknown_region_variants_raise_region_not_found(region):
    with pytest.raises(db.RegionNotFoundError):
        db.get_region_performance_history(region)


MISSING_TARGET_SQL = """
    DELETE FROM dealer_targets
    WHERE ctid IN (
        SELECT t.ctid
        FROM dealer_targets t
        JOIN dealers d ON d.dealer_id = t.dealer_id
        WHERE d.region = 'Midwest' AND t.month = '2025-06'
        LIMIT 1
    )
"""

ZERO_TARGET_SQL = """
    UPDATE dealer_targets t
    SET target_units = 0
    FROM dealers d
    WHERE d.dealer_id = t.dealer_id
      AND d.region = 'Midwest'
      AND t.month = '2025-07'
"""


def history_inside_rolled_back_transaction(monkeypatch, statement, start, end):
    """
    Run the real query function inside a transaction that is always rolled back.

    The statement changes the data first. pandas then reads through the same
    open connection, so only this call sees the change.
    """
    with db.get_engine().connect() as connection:
        transaction = connection.begin()

        try:
            connection.execute(text(statement))
            monkeypatch.setattr(db, "get_engine", lambda: connection)

            return db.to_records(
                db.get_region_performance_history("Midwest", start=start, end=end)
            )
        finally:
            transaction.rollback()


def test_missing_dealer_target_makes_region_target_null(monkeypatch):
    rows = history_inside_rolled_back_transaction(
        monkeypatch, MISSING_TARGET_SQL, "2025-05", "2025-07"
    )
    by_month = {row["month"]: row for row in rows}

    assert by_month["2025-06"]["dealer_count"] == 8
    assert by_month["2025-06"]["units_sold"] == 219
    assert by_month["2025-06"]["target_units"] is None
    assert by_month["2025-06"]["achievement_pct"] is None

    assert by_month["2025-05"]["target_units"] == 249
    assert by_month["2025-07"]["target_units"] == 216

    monkeypatch.undo()

    restored = db.to_records(
        db.get_region_performance_history("Midwest", start="2025-06", end="2025-07")
    )

    assert [row["target_units"] for row in restored] == [239, 216]


def test_zero_total_target_gives_zero_target_and_null_achievement(monkeypatch):
    rows = history_inside_rolled_back_transaction(
        monkeypatch, ZERO_TARGET_SQL, "2025-07", "2025-07"
    )

    assert len(rows) == 1
    assert rows[0]["units_sold"] == 195
    assert rows[0]["target_units"] == 0
    assert rows[0]["achievement_pct"] is None

    monkeypatch.undo()

    restored = db.to_records(
        db.get_region_performance_history("Midwest", start="2025-06", end="2025-07")
    )

    assert [row["target_units"] for row in restored] == [239, 216]


def test_region_query_explicitly_orders_by_month(monkeypatch):
    """
    Require the regional query to guarantee chronological ordering explicitly.

    PostgreSQL may happen to return grouped rows in month order without
    ORDER BY, so result-only tests cannot prove this contract.
    """
    captured = {}

    expected = pd.DataFrame(
        [
            {
                "region": "Midwest",
                "month": "2024-10",
                "dealer_count": 8,
                "units_sold": 211,
                "target_units": 220,
                "achievement_pct": 211 * 100.0 / 220,
            }
        ]
    )

    def fake_read_sql(query, engine, params=None):
        captured["query"] = str(query)
        captured["params"] = params
        return expected.copy()

    monkeypatch.setattr(db.pd, "read_sql", fake_read_sql)

    result = db.get_region_performance_history("Midwest")

    assert len(result) == 1
    assert "ORDER BY dmp.month" in captured["query"]
    assert captured["params"] == {"region": "Midwest"}
