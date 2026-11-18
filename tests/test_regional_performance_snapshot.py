"""
Tests for the Day 26 cross-region monthly performance snapshot.

The snapshot compares every region for one required month. It reuses the
existing regional weighted-achievement and missing-target semantics, but
provides a month-first cross-section rather than one region's history.
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
    "region",
    "month",
    "dealer_count",
    "units_sold",
    "target_units",
    "achievement_pct",
]

EXPECTED_REGIONS = [
    "Midwest",
    "Northeast",
    "Southeast",
    "Southwest",
    "West",
]


def snapshot_function():
    """
    Resolve the Day 26 function at runtime so the RED suite still collects
    before get_regional_performance_snapshot() exists.
    """
    return db.get_regional_performance_snapshot


def available_months_from_csv():
    sales = pd.read_csv(DATA_DIR / "sales_monthly.csv")
    targets = pd.read_csv(DATA_DIR / "dealer_targets.csv")

    return sorted(set(sales["month"]) | set(targets["month"]))


def expected_snapshot_from_csv(month):
    """
    Build one month's regional snapshot independently from the source CSVs.

    Achievement is calculated with exact Fraction arithmetic before conversion
    to float so the oracle does not depend on pandas/PostgreSQL rounding.
    """
    dealers = pd.read_csv(DATA_DIR / "dealers.csv")
    sales = pd.read_csv(DATA_DIR / "sales_monthly.csv")
    targets = pd.read_csv(DATA_DIR / "dealer_targets.csv")

    rows = []

    for region in sorted(dealers["region"].dropna().unique()):
        region_dealers = dealers[dealers["region"].eq(region)]
        dealer_ids = region_dealers["dealer_id"].tolist()

        month_sales = sales[
            sales["dealer_id"].isin(dealer_ids) & sales["month"].eq(month)
        ]

        month_targets = targets[
            targets["dealer_id"].isin(dealer_ids) & targets["month"].eq(month)
        ]

        units_sold = int(month_sales["units_sold"].sum())
        dealer_count = len(dealer_ids)

        if len(month_targets) < dealer_count:
            target_units = None
            achievement_pct = None
        else:
            target_units = int(month_targets["target_units"].sum())

            if target_units == 0:
                achievement_pct = None
            else:
                achievement_pct = float(
                    Fraction(
                        units_sold * 100,
                        target_units,
                    )
                )

        rows.append(
            {
                "region": region,
                "month": month,
                "dealer_count": dealer_count,
                "units_sold": units_sold,
                "target_units": target_units,
                "achievement_pct": achievement_pct,
            }
        )

    return pd.DataFrame(
        rows,
        columns=EXPECTED_COLUMNS,
    )


def first_weighted_vs_average_example():
    """
    Find a committed region-month where ratio-of-sums differs from the
    arithmetic mean of dealer achievement percentages.
    """
    dealers = pd.read_csv(DATA_DIR / "dealers.csv")
    sales = pd.read_csv(DATA_DIR / "sales_monthly.csv")
    targets = pd.read_csv(DATA_DIR / "dealer_targets.csv")

    monthly_sales = sales.groupby(
        ["dealer_id", "month"],
        as_index=False,
    )["units_sold"].sum()

    dealer_month = (
        dealers[["dealer_id", "region"]]
        .merge(
            monthly_sales,
            on="dealer_id",
            how="inner",
        )
        .merge(
            targets[["dealer_id", "month", "target_units"]],
            on=["dealer_id", "month"],
            how="inner",
        )
    )

    for month in available_months_from_csv():
        for region in EXPECTED_REGIONS:
            frame = dealer_month[
                dealer_month["month"].eq(month) & dealer_month["region"].eq(region)
            ]

            if frame.empty:
                continue

            if (frame["target_units"] <= 0).any():
                continue

            weighted = Fraction(
                int(frame["units_sold"].sum()) * 100,
                int(frame["target_units"].sum()),
            )

            percentages = [
                Fraction(
                    int(row.units_sold) * 100,
                    int(row.target_units),
                )
                for row in frame.itertuples(index=False)
            ]

            average = sum(percentages, Fraction(0, 1)) / len(percentages)

            if weighted != average:
                return (
                    month,
                    region,
                    float(weighted),
                    float(average),
                )

    raise AssertionError(
        "Committed data has no region-month where weighted achievement "
        "differs from the average dealer percentage."
    )


@pytest.mark.parametrize(
    "month",
    available_months_from_csv(),
)
def test_every_real_month_returns_five_regions_and_matches_csv(month):
    snapshot = snapshot_function()

    actual = snapshot(month).reset_index(drop=True)
    expected = expected_snapshot_from_csv(month)

    assert list(actual.columns) == EXPECTED_COLUMNS
    assert len(actual) == 5
    assert actual["region"].tolist() == EXPECTED_REGIONS
    assert actual["month"].tolist() == [month] * 5
    assert actual["region"].tolist() == sorted(actual["region"].tolist())

    assert actual["dealer_count"].tolist() == expected["dealer_count"].tolist()
    assert actual["units_sold"].tolist() == expected["units_sold"].tolist()
    assert actual["target_units"].tolist() == expected["target_units"].tolist()

    assert actual["achievement_pct"].tolist() == pytest.approx(
        expected["achievement_pct"].tolist()
    )


@pytest.mark.parametrize(
    "month",
    available_months_from_csv(),
)
def test_snapshot_matches_region_history_for_every_month(month):
    snapshot = snapshot_function()

    actual = snapshot(month).reset_index(drop=True)

    expected_rows = []

    for region in EXPECTED_REGIONS:
        history = db.get_region_performance_history(
            region,
            start=month,
            end=month,
        )

        assert len(history) == 1

        expected_rows.append(history.iloc[0].to_dict())

    expected = (
        pd.DataFrame(
            expected_rows,
            columns=EXPECTED_COLUMNS,
        )
        .sort_values(
            "region",
            kind="stable",
        )
        .reset_index(drop=True)
    )

    pd.testing.assert_frame_equal(
        actual,
        expected,
        check_dtype=False,
    )


@pytest.mark.parametrize(
    "month",
    available_months_from_csv(),
)
def test_snapshot_reconciles_to_network_trend_for_every_month(
    month,
):
    snapshot = snapshot_function()

    regional = snapshot(month)

    network = db.get_network_performance_history(
        start=month,
        end=month,
    )

    assert len(regional) == 5
    assert len(network) == 1

    network_row = network.iloc[0]

    assert int(regional["dealer_count"].sum()) == int(network_row["dealer_count"])

    assert int(regional["units_sold"].sum()) == int(network_row["units_sold"])

    assert regional["target_units"].notna().all()

    regional_target = int(regional["target_units"].sum())

    assert regional_target == int(network_row["target_units"])

    expected_achievement = int(regional["units_sold"].sum()) * 100.0 / regional_target

    assert network_row["achievement_pct"] == pytest.approx(expected_achievement)


def test_snapshot_uses_weighted_achievement_not_average_dealer_percentage():
    snapshot = snapshot_function()

    (
        month,
        region,
        weighted,
        average,
    ) = first_weighted_vs_average_example()

    result = snapshot(month)

    row = result[result["region"].eq(region)].iloc[0]

    assert weighted != pytest.approx(average)

    assert row["achievement_pct"] == pytest.approx(weighted)

    assert row["achievement_pct"] != pytest.approx(average)


def test_missing_target_nulls_only_affected_region_and_keeps_five_rows(
    monkeypatch,
):
    snapshot = snapshot_function()
    engine = db.get_engine()

    dealers = pd.read_csv(DATA_DIR / "dealers.csv")

    affected_region = EXPECTED_REGIONS[0]

    affected_dealer = int(
        dealers.loc[
            dealers["region"].eq(affected_region),
            "dealer_id",
        ].iloc[0]
    )

    with engine.connect() as connection:
        transaction = connection.begin()

        try:
            monkeypatch.setattr(
                db,
                "get_engine",
                lambda: connection,
            )

            baseline = snapshot("2026-09").reset_index(drop=True)

            deleted = connection.execute(
                text("""
                    DELETE FROM dealer_targets
                    WHERE dealer_id = :dealer_id
                      AND month = :month
                    """),
                {
                    "dealer_id": affected_dealer,
                    "month": "2026-09",
                },
            )

            assert deleted.rowcount == 1

            changed = snapshot("2026-09").reset_index(drop=True)

            assert len(changed) == 5
            assert changed["region"].tolist() == EXPECTED_REGIONS

            affected = changed[changed["region"].eq(affected_region)].iloc[0]
            baseline_affected = baseline[baseline["region"].eq(affected_region)].iloc[0]

            assert affected["dealer_count"] == baseline_affected["dealer_count"]

            assert pd.isna(affected["target_units"])
            assert pd.isna(affected["achievement_pct"])

            baseline_other = baseline[
                ~baseline["region"].eq(affected_region)
            ].reset_index(drop=True)

            changed_other = changed[~changed["region"].eq(affected_region)].reset_index(
                drop=True
            )

            pd.testing.assert_frame_equal(
                changed_other,
                baseline_other,
                check_dtype=False,
            )

            transaction.rollback()

            monkeypatch.undo()

            restored = snapshot("2026-09").reset_index(drop=True)

            pd.testing.assert_frame_equal(
                restored,
                baseline,
                check_dtype=False,
            )

        finally:
            if transaction.is_active:
                transaction.rollback()


def test_zero_targets_return_zero_target_and_null_achievement_for_one_region(
    monkeypatch,
):
    snapshot = snapshot_function()
    engine = db.get_engine()

    dealers = pd.read_csv(DATA_DIR / "dealers.csv")

    affected_region = EXPECTED_REGIONS[0]

    affected_dealers = [
        int(value)
        for value in dealers.loc[
            dealers["region"].eq(affected_region),
            "dealer_id",
        ].tolist()
    ]

    with engine.connect() as connection:
        transaction = connection.begin()

        try:
            monkeypatch.setattr(
                db,
                "get_engine",
                lambda: connection,
            )

            baseline = snapshot("2026-09").reset_index(drop=True)

            updated = connection.execute(
                text("""
                    UPDATE dealer_targets
                    SET target_units = 0
                    WHERE dealer_id = ANY(:dealer_ids)
                      AND month = :month
                    """),
                {
                    "dealer_ids": affected_dealers,
                    "month": "2026-09",
                },
            )

            assert updated.rowcount == len(affected_dealers)

            changed = snapshot("2026-09").reset_index(drop=True)

            assert len(changed) == 5
            assert changed["region"].tolist() == EXPECTED_REGIONS

            affected = changed[changed["region"].eq(affected_region)].iloc[0]

            assert affected["target_units"] == 0
            assert pd.isna(affected["achievement_pct"])

            baseline_other = baseline[
                ~baseline["region"].eq(affected_region)
            ].reset_index(drop=True)

            changed_other = changed[~changed["region"].eq(affected_region)].reset_index(
                drop=True
            )

            pd.testing.assert_frame_equal(
                changed_other,
                baseline_other,
                check_dtype=False,
            )

            transaction.rollback()

            monkeypatch.undo()

            restored = snapshot("2026-09").reset_index(drop=True)

            pd.testing.assert_frame_equal(
                restored,
                baseline,
                check_dtype=False,
            )

        finally:
            if transaction.is_active:
                transaction.rollback()


def test_unknown_month_raises_month_not_found():
    snapshot = snapshot_function()

    with pytest.raises(
        db.MonthNotFoundError,
        match=r"^Month 2030-01 not found$",
    ):
        snapshot("2030-01")


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
    snapshot = snapshot_function()

    expected_value = re.escape(repr(month))

    with pytest.raises(
        db.InvalidMonthError,
        match=(rf"^Invalid month: {expected_value}\. " r"Expected YYYY-MM\.$"),
    ):
        snapshot(month)


def test_sql_injection_string_is_rejected_as_invalid_month():
    snapshot = snapshot_function()

    value = "2026-09' OR '1'='1"

    expected_value = re.escape(repr(value))

    with pytest.raises(
        db.InvalidMonthError,
        match=(rf"^Invalid month: {expected_value}\. " r"Expected YYYY-MM\.$"),
    ):
        snapshot(value)


def test_snapshot_runs_one_ordered_query():
    snapshot = snapshot_function()
    engine = db.get_engine()

    statements = []

    def record_statement(
        conn,
        cursor,
        statement,
        parameters,
        context,
        executemany,
    ):
        statements.append(" ".join(statement.split()))

    event.listen(
        engine,
        "before_cursor_execute",
        record_statement,
    )

    try:
        result = snapshot("2026-09")
    finally:
        event.remove(
            engine,
            "before_cursor_execute",
            record_statement,
        )

    assert len(result) == 5

    relevant = [
        statement
        for statement in statements
        if "dealer_monthly_performance" in statement
    ]

    # One query is sufficient because an empty result
    # is the not-found signal.
    assert len(relevant) == 1

    sql = relevant[0]

    assert re.search(
        r"ORDER BY (\w+\.)?region\s*$",
        sql,
    )


def test_snapshot_binds_month_instead_of_interpolating_it():
    snapshot = snapshot_function()
    engine = db.get_engine()

    captured = []

    def record_statement(
        conn,
        cursor,
        statement,
        parameters,
        context,
        executemany,
    ):
        captured.append(
            (
                " ".join(statement.split()),
                parameters,
            )
        )

    event.listen(
        engine,
        "before_cursor_execute",
        record_statement,
    )

    try:
        result = snapshot("2026-09")
    finally:
        event.remove(
            engine,
            "before_cursor_execute",
            record_statement,
        )

    assert len(result) == 5

    relevant = [
        (statement, parameters)
        for statement, parameters in captured
        if "dealer_monthly_performance" in statement
    ]

    assert len(relevant) == 1

    sql, parameters = relevant[0]

    # The requested month must be bound rather than
    # interpolated into the SQL text.
    assert "2026-09" not in sql

    if isinstance(parameters, dict):
        assert "2026-09" in parameters.values()
    else:
        assert "2026-09" in parameters


def test_snapshot_counts_are_integers_and_achievement_is_float():
    result = snapshot_function()("2026-09")

    for column in [
        "dealer_count",
        "units_sold",
        "target_units",
    ]:
        assert pd.api.types.is_integer_dtype(result[column]), column

    assert pd.api.types.is_float_dtype(result["achievement_pct"])
