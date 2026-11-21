from fractions import Fraction
from pathlib import Path

import pandas as pd
import pytest
from sqlalchemy import text

import db

DATA_DIR = Path(__file__).resolve().parents[1] / "data"

MONTH = "2026-09"

EXPECTED_COLUMNS = [
    "region",
    "leads",
    "test_drives",
    "units_sold",
    "test_drive_rate_pct",
    "drive_to_sale_pct",
    "lead_to_sale_pct",
]


# ============================================================
# Independent CSV oracle
# ============================================================


def _expected_from_csv(month):
    dealers = pd.read_csv(DATA_DIR / "dealers.csv")
    leads = pd.read_csv(DATA_DIR / "leads_monthly.csv")
    sales = pd.read_csv(DATA_DIR / "sales_monthly.csv")

    month_leads = leads.loc[leads["month"] == month].copy()
    month_sales = sales.loc[sales["month"] == month].copy()

    sales_by_dealer = month_sales.groupby("dealer_id", as_index=False)[
        "units_sold"
    ].sum()

    lead_rows = month_leads.merge(
        dealers[["dealer_id", "region"]],
        on="dealer_id",
        how="inner",
        validate="many_to_one",
    )

    sales_rows = sales_by_dealer.merge(
        dealers[["dealer_id", "region"]],
        on="dealer_id",
        how="inner",
        validate="one_to_one",
    )

    expected = []

    for region in sorted(dealers["region"].unique()):
        region_leads = lead_rows.loc[lead_rows["region"] == region]
        region_sales = sales_rows.loc[sales_rows["region"] == region]

        leads_total = int(region_leads["leads"].sum())
        drives_total = int(region_leads["test_drives"].sum())
        units_total = int(region_sales["units_sold"].sum())

        expected.append(
            {
                "region": region,
                "leads": leads_total,
                "test_drives": drives_total,
                "units_sold": units_total,
                "test_drive_rate_pct": (
                    Fraction(drives_total * 100, leads_total) if leads_total else None
                ),
                "drive_to_sale_pct": (
                    Fraction(units_total * 100, drives_total) if drives_total else None
                ),
                "lead_to_sale_pct": (
                    Fraction(units_total * 100, leads_total) if leads_total else None
                ),
            }
        )

    return expected


def _row_for_region(frame, region):
    matches = frame.loc[frame["region"] == region]

    assert len(matches) == 1

    return matches.iloc[0]


def _assert_numeric_equal(actual, expected):
    if expected is None:
        assert pd.isna(actual)
        return

    assert not pd.isna(actual)
    assert float(actual) == pytest.approx(float(expected), rel=1e-12)


def _assert_region_matches(actual, expected):
    assert actual["region"] == expected["region"]
    assert int(actual["leads"]) == expected["leads"]
    assert int(actual["test_drives"]) == expected["test_drives"]
    assert int(actual["units_sold"]) == expected["units_sold"]

    _assert_numeric_equal(
        actual["test_drive_rate_pct"],
        expected["test_drive_rate_pct"],
    )
    _assert_numeric_equal(
        actual["drive_to_sale_pct"],
        expected["drive_to_sale_pct"],
    )
    _assert_numeric_equal(
        actual["lead_to_sale_pct"],
        expected["lead_to_sale_pct"],
    )


def _target_region_and_dealers(connection):
    region = connection.execute(text("""
            SELECT region
            FROM dealers
            GROUP BY region
            ORDER BY region
            LIMIT 1
            """)).scalar_one()

    dealer_ids = list(
        connection.execute(
            text("""
                SELECT dealer_id
                FROM dealers
                WHERE region = :region
                ORDER BY dealer_id
                """),
            {"region": region},
        ).scalars()
    )

    assert dealer_ids

    return region, dealer_ids


def _set_dealer_sales_total(connection, dealer_id, month, units):
    connection.execute(
        text("""
            UPDATE sales_monthly
            SET units_sold = CASE
                WHEN model = (
                    SELECT MIN(model)
                    FROM sales_monthly
                    WHERE dealer_id = :dealer_id
                      AND month = :month
                )
                THEN :units
                ELSE 0
            END
            WHERE dealer_id = :dealer_id
              AND month = :month
            """),
        {
            "dealer_id": dealer_id,
            "month": month,
            "units": units,
        },
    )


@pytest.fixture
def rolled_back_connection(monkeypatch):
    engine = db.get_engine()

    with engine.connect() as connection:
        transaction = connection.begin()

        monkeypatch.setattr(
            db,
            "get_engine",
            lambda: connection,
        )

        try:
            yield connection
        finally:
            transaction.rollback()


# ============================================================
# Oracle and shape
# ============================================================


@pytest.mark.parametrize(
    "month",
    pd.read_csv(DATA_DIR / "leads_monthly.csv")["month"]
    .drop_duplicates()
    .sort_values()
    .tolist(),
)
def test_regional_funnel_snapshot_matches_csv_oracle_for_all_months(month):
    expected = _expected_from_csv(month)

    actual = db.get_regional_funnel_snapshot(month)

    assert len(actual) == 5

    for actual_row, expected_row in zip(
        actual.to_dict("records"),
        expected,
        strict=True,
    ):
        _assert_region_matches(actual_row, expected_row)


def test_regional_funnel_snapshot_has_exact_shape_and_order():
    result = db.get_regional_funnel_snapshot(MONTH)

    assert list(result.columns) == EXPECTED_COLUMNS
    assert len(result) == 5
    assert result["region"].tolist() == sorted(result["region"].tolist())
    assert result["region"].is_unique


def test_regional_leads_and_test_drives_reconcile_to_direct_source_totals():
    result = db.get_regional_funnel_snapshot(MONTH)

    leads = pd.read_csv(DATA_DIR / "leads_monthly.csv")
    month_rows = leads.loc[leads["month"] == MONTH]

    assert int(result["leads"].sum()) == int(month_rows["leads"].sum())
    assert int(result["test_drives"].sum()) == int(month_rows["test_drives"].sum())


def test_regional_units_match_monthly_performance_rollup():
    result = db.get_regional_funnel_snapshot(MONTH)

    expected = pd.read_sql(
        text("""
            SELECT
                region,
                units_sold
            FROM monthly_performance_rollup
            WHERE month = :month
              AND region IS NOT NULL
            ORDER BY region
            """),
        db.get_engine(),
        params={"month": MONTH},
    )

    assert result["region"].tolist() == expected["region"].tolist()
    assert result["units_sold"].astype(int).tolist() == (
        expected["units_sold"].astype(int).tolist()
    )


# ============================================================
# Rolled-back behavioral fixtures
# ============================================================


def test_rates_use_ratio_of_regional_sums_not_mean_of_dealer_rates(
    rolled_back_connection,
):
    connection = rolled_back_connection
    region, dealer_ids = _target_region_and_dealers(connection)

    assert len(dealer_ids) >= 2

    # One high-conversion small dealer and several lower-conversion
    # large dealers make mean-of-rates materially different from the
    # ratio of regional sums.
    first, *rest = dealer_ids

    connection.execute(
        text("""
            UPDATE leads_monthly
            SET leads = 10,
                test_drives = 9
            WHERE dealer_id = :dealer_id
              AND month = :month
            """),
        {"dealer_id": first, "month": MONTH},
    )
    _set_dealer_sales_total(
        connection,
        first,
        MONTH,
        8,
    )

    for dealer_id in rest:
        connection.execute(
            text("""
                UPDATE leads_monthly
                SET leads = 1000,
                    test_drives = 100
                WHERE dealer_id = :dealer_id
                  AND month = :month
                """),
            {"dealer_id": dealer_id, "month": MONTH},
        )
        _set_dealer_sales_total(
            connection,
            dealer_id,
            MONTH,
            10,
        )

    result = db.get_regional_funnel_snapshot(MONTH)
    row = _row_for_region(result, region)

    leads_total = 10 + 1000 * len(rest)
    drives_total = 9 + 100 * len(rest)
    units_total = 8 + 10 * len(rest)

    expected_drive_rate = Fraction(
        drives_total * 100,
        leads_total,
    )
    expected_drive_to_sale = Fraction(
        units_total * 100,
        drives_total,
    )
    expected_lead_to_sale = Fraction(
        units_total * 100,
        leads_total,
    )

    mean_drive_rate = (
        Fraction(9 * 100, 10)
        + sum(
            (Fraction(100 * 100, 1000) for _ in rest),
            Fraction(0, 1),
        )
    ) / len(dealer_ids)

    mean_drive_to_sale = (
        Fraction(8 * 100, 9)
        + sum(
            (Fraction(10 * 100, 100) for _ in rest),
            Fraction(0, 1),
        )
    ) / len(dealer_ids)

    mean_lead_to_sale = (
        Fraction(8 * 100, 10)
        + sum(
            (Fraction(10 * 100, 1000) for _ in rest),
            Fraction(0, 1),
        )
    ) / len(dealer_ids)

    assert expected_drive_rate != mean_drive_rate
    assert expected_drive_to_sale != mean_drive_to_sale
    assert expected_lead_to_sale != mean_lead_to_sale

    assert int(row["leads"]) == leads_total
    assert int(row["test_drives"]) == drives_total
    assert int(row["units_sold"]) == units_total

    _assert_numeric_equal(
        row["test_drive_rate_pct"],
        expected_drive_rate,
    )
    _assert_numeric_equal(
        row["drive_to_sale_pct"],
        expected_drive_to_sale,
    )
    _assert_numeric_equal(
        row["lead_to_sale_pct"],
        expected_lead_to_sale,
    )


def test_zero_regional_leads_nulls_all_three_rates(
    rolled_back_connection,
):
    connection = rolled_back_connection
    region, dealer_ids = _target_region_and_dealers(connection)

    connection.execute(
        text("""
            UPDATE leads_monthly
            SET leads = 0,
                test_drives = 0
            WHERE dealer_id = ANY(:dealer_ids)
              AND month = :month
            """),
        {
            "dealer_ids": dealer_ids,
            "month": MONTH,
        },
    )

    result = db.get_regional_funnel_snapshot(MONTH)
    row = _row_for_region(result, region)

    assert int(row["leads"]) == 0
    assert int(row["test_drives"]) == 0

    assert pd.isna(row["test_drive_rate_pct"])
    assert pd.isna(row["drive_to_sale_pct"])
    assert pd.isna(row["lead_to_sale_pct"])


def test_zero_test_drives_and_zero_units_distinguish_zero_from_null(
    rolled_back_connection,
):
    connection = rolled_back_connection
    region, dealer_ids = _target_region_and_dealers(connection)

    connection.execute(
        text("""
            UPDATE leads_monthly
            SET test_drives = 0
            WHERE dealer_id = ANY(:dealer_ids)
              AND month = :month
            """),
        {
            "dealer_ids": dealer_ids,
            "month": MONTH,
        },
    )

    connection.execute(
        text("""
            UPDATE sales_monthly
            SET units_sold = 0
            WHERE dealer_id = ANY(:dealer_ids)
              AND month = :month
            """),
        {
            "dealer_ids": dealer_ids,
            "month": MONTH,
        },
    )

    result = db.get_regional_funnel_snapshot(MONTH)
    row = _row_for_region(result, region)

    assert int(row["leads"]) > 0
    assert int(row["test_drives"]) == 0
    assert int(row["units_sold"]) == 0

    assert float(row["test_drive_rate_pct"]) == pytest.approx(0.0)
    assert pd.isna(row["drive_to_sale_pct"])
    assert float(row["lead_to_sale_pct"]) == pytest.approx(0.0)


def test_missing_sales_dealer_month_nulls_sale_metrics_only(
    rolled_back_connection,
):
    connection = rolled_back_connection
    region, dealer_ids = _target_region_and_dealers(connection)
    dealer_id = dealer_ids[0]

    before = db.get_regional_funnel_snapshot(MONTH)

    connection.execute(
        text("""
            DELETE FROM sales_monthly
            WHERE dealer_id = :dealer_id
              AND month = :month
            """),
        {
            "dealer_id": dealer_id,
            "month": MONTH,
        },
    )

    after = db.get_regional_funnel_snapshot(MONTH)

    before_region = _row_for_region(before, region)
    after_region = _row_for_region(after, region)

    assert int(after_region["leads"]) == int(before_region["leads"])
    assert int(after_region["test_drives"]) == int(before_region["test_drives"])

    _assert_numeric_equal(
        after_region["test_drive_rate_pct"],
        before_region["test_drive_rate_pct"],
    )

    assert pd.isna(after_region["units_sold"])
    assert pd.isna(after_region["drive_to_sale_pct"])
    assert pd.isna(after_region["lead_to_sale_pct"])

    for other_region in sorted(set(before["region"]) - {region}):
        assert (
            _row_for_region(after, other_region).to_dict()
            == _row_for_region(before, other_region).to_dict()
        )


def test_zero_sales_rows_are_complete_not_missing(
    rolled_back_connection,
):
    connection = rolled_back_connection
    region, dealer_ids = _target_region_and_dealers(connection)
    dealer_id = dealer_ids[0]

    connection.execute(
        text("""
            UPDATE sales_monthly
            SET units_sold = 0
            WHERE dealer_id = :dealer_id
              AND month = :month
            """),
        {
            "dealer_id": dealer_id,
            "month": MONTH,
        },
    )

    result = db.get_regional_funnel_snapshot(MONTH)
    row = _row_for_region(result, region)

    assert not pd.isna(row["units_sold"])
    assert not pd.isna(row["drive_to_sale_pct"])
    assert not pd.isna(row["lead_to_sale_pct"])


def test_missing_lead_row_nulls_lead_metrics_but_preserves_units(
    rolled_back_connection,
):
    connection = rolled_back_connection
    region, dealer_ids = _target_region_and_dealers(connection)
    dealer_id = dealer_ids[0]

    before = db.get_regional_funnel_snapshot(MONTH)
    before_region = _row_for_region(before, region)

    connection.execute(
        text("""
            DELETE FROM leads_monthly
            WHERE dealer_id = :dealer_id
              AND month = :month
            """),
        {
            "dealer_id": dealer_id,
            "month": MONTH,
        },
    )

    after = db.get_regional_funnel_snapshot(MONTH)
    after_region = _row_for_region(after, region)

    assert pd.isna(after_region["leads"])
    assert pd.isna(after_region["test_drives"])
    assert pd.isna(after_region["test_drive_rate_pct"])
    assert pd.isna(after_region["drive_to_sale_pct"])
    assert pd.isna(after_region["lead_to_sale_pct"])

    assert int(after_region["units_sold"]) == int(before_region["units_sold"])

    for other_region in sorted(set(before["region"]) - {region}):
        assert (
            _row_for_region(after, other_region).to_dict()
            == _row_for_region(before, other_region).to_dict()
        )


def test_region_stays_present_when_all_its_lead_rows_are_missing(
    rolled_back_connection,
):
    connection = rolled_back_connection
    region, dealer_ids = _target_region_and_dealers(connection)

    before = db.get_regional_funnel_snapshot(MONTH)
    before_region = _row_for_region(before, region)

    connection.execute(
        text("""
            DELETE FROM leads_monthly
            WHERE dealer_id = ANY(:dealer_ids)
              AND month = :month
            """),
        {
            "dealer_ids": dealer_ids,
            "month": MONTH,
        },
    )

    after = db.get_regional_funnel_snapshot(MONTH)

    assert len(after) == 5
    assert after["region"].tolist() == sorted(after["region"].tolist())

    row = _row_for_region(after, region)

    assert pd.isna(row["leads"])
    assert pd.isna(row["test_drives"])
    assert pd.isna(row["test_drive_rate_pct"])
    assert pd.isna(row["drive_to_sale_pct"])
    assert pd.isna(row["lead_to_sale_pct"])

    assert int(row["units_sold"]) == int(before_region["units_sold"])


# ============================================================
# Validation and month existence
# ============================================================


@pytest.mark.parametrize(
    "month",
    [
        "2026-9",
        "2026-00",
        "2026-13",
        "2026-09\n",
        "２０２６-０９",
        None,
    ],
)
def test_regional_funnel_snapshot_rejects_invalid_months(month):
    with pytest.raises(db.InvalidMonthError):
        db.get_regional_funnel_snapshot(month)


def test_regional_funnel_snapshot_rejects_unknown_month():
    with pytest.raises(
        db.MonthNotFoundError,
        match="2099-01",
    ):
        db.get_regional_funnel_snapshot("2099-01")


def test_month_existence_is_defined_by_leads_not_sales(
    rolled_back_connection,
):
    connection = rolled_back_connection

    sales_count = connection.execute(
        text("""
            SELECT COUNT(*)
            FROM sales_monthly
            WHERE month = :month
            """),
        {"month": MONTH},
    ).scalar_one()

    assert sales_count > 0

    connection.execute(
        text("""
            DELETE FROM leads_monthly
            WHERE month = :month
            """),
        {"month": MONTH},
    )

    remaining_sales = connection.execute(
        text("""
            SELECT COUNT(*)
            FROM sales_monthly
            WHERE month = :month
            """),
        {"month": MONTH},
    ).scalar_one()

    assert remaining_sales == sales_count

    with pytest.raises(
        db.MonthNotFoundError,
        match=MONTH,
    ):
        db.get_regional_funnel_snapshot(MONTH)


def test_missing_model_row_keeps_reduced_units_total_not_null(
    rolled_back_connection,
):
    connection = rolled_back_connection
    region, dealer_ids = _target_region_and_dealers(connection)
    dealer_id = dealer_ids[0]

    before = _row_for_region(db.get_regional_funnel_snapshot(MONTH), region)

    model, removed = connection.execute(
        text("""
            SELECT model, units_sold
            FROM sales_monthly
            WHERE dealer_id = :dealer_id
              AND month = :month
            ORDER BY units_sold DESC, model
            LIMIT 1
            """),
        {"dealer_id": dealer_id, "month": MONTH},
    ).one()

    assert removed > 0

    result = connection.execute(
        text("""
            DELETE FROM sales_monthly
            WHERE dealer_id = :dealer_id
              AND month = :month
              AND model = :model
            """),
        {"dealer_id": dealer_id, "month": MONTH, "model": model},
    )

    assert result.rowcount == 1

    after = _row_for_region(db.get_regional_funnel_snapshot(MONTH), region)

    assert int(after["units_sold"]) == int(before["units_sold"]) - removed
    assert not pd.isna(after["drive_to_sale_pct"])
    assert not pd.isna(after["lead_to_sale_pct"])


def test_committed_data_counts_are_integers_and_rates_are_floats():
    result = db.get_regional_funnel_snapshot(MONTH)

    for column in ["leads", "test_drives", "units_sold"]:
        assert pd.api.types.is_integer_dtype(result[column]), column

    for column in [
        "test_drive_rate_pct",
        "drive_to_sale_pct",
        "lead_to_sale_pct",
    ]:
        assert pd.api.types.is_float_dtype(result[column]), column
