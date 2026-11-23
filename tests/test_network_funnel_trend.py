"""
Database tests for the network-wide monthly lead-funnel trend.

Day 32 aggregates dealer_monthly_funnel to one row per lead-defined month.
Completeness is evaluated at dealer-month grain before network totals are
exposed, and rates are ratios of gated network sums rather than averages of
dealer rates.
"""

from fractions import Fraction
from pathlib import Path

import pandas as pd
import pytest
from sqlalchemy import text

import db

DATA_DIR = Path(__file__).resolve().parents[1] / "data"

EXPECTED_COLUMNS = [
    "month",
    "leads",
    "test_drives",
    "units_sold",
    "test_drive_rate_pct",
    "drive_to_sale_pct",
    "lead_to_sale_pct",
]

FIRST_MONTH = "2024-10"
LAST_MONTH = "2026-09"
TEST_MONTH = "2026-09"


# ============================================================
# Independent CSV oracle
# ============================================================


def _ratio(numerator, denominator):
    if denominator == 0:
        return None

    return float(
        Fraction(
            int(numerator) * 100,
            int(denominator),
        )
    )


def _expected_from_csv():
    dealers = pd.read_csv(DATA_DIR / "dealers.csv")
    leads = pd.read_csv(DATA_DIR / "leads_monthly.csv")
    sales = pd.read_csv(DATA_DIR / "sales_monthly.csv")

    dealer_count = len(dealers)

    lead_counts = leads.groupby("month")["dealer_id"].nunique()
    sales_by_dealer = sales.groupby(
        ["dealer_id", "month"],
        as_index=False,
    )["units_sold"].sum()
    sales_counts = sales_by_dealer.groupby("month")["dealer_id"].nunique()

    assert (lead_counts == dealer_count).all()
    assert (sales_counts == dealer_count).all()

    lead_monthly = leads.groupby(
        "month",
        as_index=False,
    ).agg(
        leads=("leads", "sum"),
        test_drives=("test_drives", "sum"),
    )

    sales_monthly = sales_by_dealer.groupby(
        "month",
        as_index=False,
    ).agg(
        units_sold=("units_sold", "sum"),
    )

    expected = lead_monthly.merge(
        sales_monthly,
        on="month",
        how="left",
        validate="one_to_one",
    )

    expected["test_drive_rate_pct"] = [
        _ratio(drives, leads)
        for drives, leads in zip(
            expected["test_drives"],
            expected["leads"],
            strict=True,
        )
    ]

    expected["drive_to_sale_pct"] = [
        _ratio(units, drives)
        for units, drives in zip(
            expected["units_sold"],
            expected["test_drives"],
            strict=True,
        )
    ]

    expected["lead_to_sale_pct"] = [
        _ratio(units, leads)
        for units, leads in zip(
            expected["units_sold"],
            expected["leads"],
            strict=True,
        )
    ]

    return expected[EXPECTED_COLUMNS].sort_values(
        "month",
        ignore_index=True,
    )


# ============================================================
# Transaction helper
# ============================================================


@pytest.fixture
def transaction_connection(monkeypatch):
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
# Baseline shape and oracle
# ============================================================


def test_network_funnel_trend_returns_exact_columns():
    trend = db.get_network_funnel_trend()

    assert list(trend.columns) == EXPECTED_COLUMNS


def test_network_funnel_trend_returns_all_24_lead_defined_months():
    trend = db.get_network_funnel_trend()

    assert len(trend) == 24
    assert trend["month"].nunique() == 24
    assert trend.iloc[0]["month"] == FIRST_MONTH
    assert trend.iloc[-1]["month"] == LAST_MONTH


def test_network_funnel_count_columns_use_integer_dtype():
    trend = db.get_network_funnel_trend()

    for column in ("leads", "test_drives", "units_sold"):
        assert pd.api.types.is_integer_dtype(trend[column]), column


def test_network_funnel_trend_is_oldest_first():
    trend = db.get_network_funnel_trend()

    assert trend["month"].tolist() == sorted(trend["month"].tolist())


def test_network_funnel_trend_matches_independent_csv_oracle():
    actual = db.get_network_funnel_trend().reset_index(drop=True)
    expected = _expected_from_csv()

    assert actual["month"].tolist() == expected["month"].tolist()

    for field in (
        "leads",
        "test_drives",
        "units_sold",
    ):
        assert actual[field].tolist() == expected[field].tolist()

    for field in (
        "test_drive_rate_pct",
        "drive_to_sale_pct",
        "lead_to_sale_pct",
    ):
        assert actual[field].tolist() == pytest.approx(expected[field].tolist())


@pytest.mark.parametrize(
    "field",
    [
        "leads",
        "test_drives",
        "units_sold",
        "test_drive_rate_pct",
        "drive_to_sale_pct",
        "lead_to_sale_pct",
    ],
)
def test_baseline_network_funnel_metrics_are_non_null(field):
    trend = db.get_network_funnel_trend()

    assert trend[field].notna().all()


# ============================================================
# Ratio-of-sums contract
# ============================================================


def test_rates_are_ratios_of_network_sums_not_mean_of_dealer_rates():
    leads = pd.read_csv(DATA_DIR / "leads_monthly.csv")
    sales = pd.read_csv(DATA_DIR / "sales_monthly.csv")

    month_leads = leads.loc[leads["month"] == TEST_MONTH].copy()

    sales_by_dealer = (
        sales.loc[sales["month"] == TEST_MONTH]
        .groupby(
            "dealer_id",
            as_index=False,
        )["units_sold"]
        .sum()
    )

    dealer_rows = month_leads.merge(
        sales_by_dealer,
        on="dealer_id",
        how="inner",
        validate="one_to_one",
    )

    expected_ratio = (
        dealer_rows["units_sold"].sum() * 100.0 / dealer_rows["leads"].sum()
    )

    mean_dealer_rate = (dealer_rows["units_sold"] * 100.0 / dealer_rows["leads"]).mean()

    assert expected_ratio != pytest.approx(mean_dealer_rate)

    trend = db.get_network_funnel_trend(
        start=TEST_MONTH,
        end=TEST_MONTH,
    )

    assert len(trend) == 1
    assert trend.iloc[0]["lead_to_sale_pct"] == pytest.approx(expected_ratio)


# ============================================================
# Reconciliation to regional funnel snapshots
# ============================================================


@pytest.mark.parametrize(
    "month",
    sorted(pd.read_csv(DATA_DIR / "leads_monthly.csv")["month"].unique()),
)
def test_network_totals_match_sum_of_regions_for_every_month(month):
    network = db.get_network_funnel_trend(
        start=month,
        end=month,
    )

    regions = db.get_regional_funnel_snapshot(month)

    assert len(network) == 1

    row = network.iloc[0]

    assert row["leads"] == regions["leads"].sum()
    assert row["test_drives"] == regions["test_drives"].sum()
    assert row["units_sold"] == regions["units_sold"].sum()

    assert row["test_drive_rate_pct"] == pytest.approx(
        regions["test_drives"].sum() * 100.0 / regions["leads"].sum()
    )

    assert row["drive_to_sale_pct"] == pytest.approx(
        regions["units_sold"].sum() * 100.0 / regions["test_drives"].sum()
    )

    assert row["lead_to_sale_pct"] == pytest.approx(
        regions["units_sold"].sum() * 100.0 / regions["leads"].sum()
    )


# ============================================================
# Lead completeness
# ============================================================


def test_missing_one_lead_row_nulls_network_lead_side_only(
    transaction_connection,
):
    before = db.get_network_funnel_trend()

    transaction_connection.execute(
        text("""
            DELETE FROM leads_monthly
            WHERE dealer_id = 101
              AND month = :month
            """),
        {"month": TEST_MONTH},
    )

    after = db.get_network_funnel_trend()

    row = after.loc[after["month"] == TEST_MONTH].iloc[0]

    assert pd.isna(row["leads"])
    assert pd.isna(row["test_drives"])
    assert not pd.isna(row["units_sold"])

    assert pd.isna(row["test_drive_rate_pct"])
    assert pd.isna(row["drive_to_sale_pct"])
    assert pd.isna(row["lead_to_sale_pct"])

    pd.testing.assert_frame_equal(
        before.loc[before["month"] != TEST_MONTH].reset_index(drop=True),
        after.loc[after["month"] != TEST_MONTH].reset_index(drop=True),
        check_dtype=False,
    )


def test_missing_lead_row_matches_regional_null_propagation(
    transaction_connection,
):
    transaction_connection.execute(
        text("""
            DELETE FROM leads_monthly
            WHERE dealer_id = 101
              AND month = :month
            """),
        {"month": TEST_MONTH},
    )

    network = db.get_network_funnel_trend(
        start=TEST_MONTH,
        end=TEST_MONTH,
    ).iloc[0]

    regions = db.get_regional_funnel_snapshot(TEST_MONTH)

    assert regions["leads"].isna().any()
    assert regions["test_drives"].isna().any()

    assert pd.isna(network["leads"])
    assert pd.isna(network["test_drives"])
    assert pd.isna(network["test_drive_rate_pct"])

    assert not regions["units_sold"].isna().any()
    assert not pd.isna(network["units_sold"])


# ============================================================
# Sales completeness
# ============================================================


def test_missing_all_sales_rows_for_one_dealer_nulls_sale_side_only(
    transaction_connection,
):
    transaction_connection.execute(
        text("""
            DELETE FROM sales_monthly
            WHERE dealer_id = 101
              AND month = :month
            """),
        {"month": TEST_MONTH},
    )

    row = db.get_network_funnel_trend(
        start=TEST_MONTH,
        end=TEST_MONTH,
    ).iloc[0]

    assert not pd.isna(row["leads"])
    assert not pd.isna(row["test_drives"])
    assert pd.isna(row["units_sold"])

    assert not pd.isna(row["test_drive_rate_pct"])
    assert pd.isna(row["drive_to_sale_pct"])
    assert pd.isna(row["lead_to_sale_pct"])


def test_missing_sales_dealer_month_matches_regional_null_propagation(
    transaction_connection,
):
    transaction_connection.execute(
        text("""
            DELETE FROM sales_monthly
            WHERE dealer_id = 101
              AND month = :month
            """),
        {"month": TEST_MONTH},
    )

    network = db.get_network_funnel_trend(
        start=TEST_MONTH,
        end=TEST_MONTH,
    ).iloc[0]

    regions = db.get_regional_funnel_snapshot(TEST_MONTH)

    assert regions["units_sold"].isna().any()
    assert pd.isna(network["units_sold"])

    assert not regions["leads"].isna().any()
    assert not regions["test_drives"].isna().any()

    assert not pd.isna(network["leads"])
    assert not pd.isna(network["test_drives"])
    assert not pd.isna(network["test_drive_rate_pct"])


def test_deleting_only_some_sales_model_rows_keeps_month_sales_complete(
    transaction_connection,
):
    original = db.get_network_funnel_trend(
        start=TEST_MONTH,
        end=TEST_MONTH,
    ).iloc[0]

    deleted_units = transaction_connection.execute(
        text("""
            SELECT units_sold
            FROM sales_monthly
            WHERE dealer_id = 101
              AND month = :month
            ORDER BY model
            LIMIT 1
            """),
        {"month": TEST_MONTH},
    ).scalar_one()

    transaction_connection.execute(
        text("""
            DELETE FROM sales_monthly
            WHERE ctid IN (
                SELECT ctid
                FROM sales_monthly
                WHERE dealer_id = 101
                  AND month = :month
                ORDER BY model
                LIMIT 1
            )
            """),
        {"month": TEST_MONTH},
    )

    row = db.get_network_funnel_trend(
        start=TEST_MONTH,
        end=TEST_MONTH,
    ).iloc[0]

    assert not pd.isna(row["units_sold"])
    assert row["units_sold"] == original["units_sold"] - deleted_units

    assert not pd.isna(row["drive_to_sale_pct"])
    assert not pd.isna(row["lead_to_sale_pct"])


# ============================================================
# Lead-defined month spine
# ============================================================


def test_removing_all_lead_rows_for_month_removes_month_from_trend(
    transaction_connection,
):
    transaction_connection.execute(
        text("""
            DELETE FROM leads_monthly
            WHERE month = :month
            """),
        {"month": TEST_MONTH},
    )

    trend = db.get_network_funnel_trend()

    assert TEST_MONTH not in trend["month"].tolist()
    assert len(trend) == 23


def test_sales_only_month_does_not_create_network_funnel_month(
    transaction_connection,
):
    sales_only_month = "2030-01"

    transaction_connection.execute(
        text("""
            INSERT INTO sales_monthly (
                dealer_id,
                month,
                model,
                units_sold,
                avg_sale_price
            )
            VALUES (
                101,
                :month,
                (SELECT model FROM vehicle_models ORDER BY model LIMIT 1),
                5,
                25000
            )
            """),
        {"month": sales_only_month},
    )

    trend = db.get_network_funnel_trend()

    assert sales_only_month not in trend["month"].tolist()


# ============================================================
# Real zeros and zero denominators
# ============================================================


def test_zero_network_leads_stays_zero_and_nulls_only_lead_rates(
    transaction_connection,
):
    transaction_connection.execute(
        text("""
            UPDATE leads_monthly
            SET leads = 0
            WHERE month = :month
            """),
        {"month": TEST_MONTH},
    )

    row = db.get_network_funnel_trend(
        start=TEST_MONTH,
        end=TEST_MONTH,
    ).iloc[0]

    assert row["leads"] == 0
    assert row["test_drives"] > 0
    assert row["units_sold"] > 0

    assert pd.isna(row["test_drive_rate_pct"])
    assert not pd.isna(row["drive_to_sale_pct"])
    assert pd.isna(row["lead_to_sale_pct"])


def test_zero_network_test_drives_stays_zero_with_only_drive_rate_undefined(
    transaction_connection,
):
    transaction_connection.execute(
        text("""
            UPDATE leads_monthly
            SET test_drives = 0
            WHERE month = :month
            """),
        {"month": TEST_MONTH},
    )

    row = db.get_network_funnel_trend(
        start=TEST_MONTH,
        end=TEST_MONTH,
    ).iloc[0]

    assert row["leads"] > 0
    assert row["test_drives"] == 0
    assert row["units_sold"] > 0

    assert row["test_drive_rate_pct"] == pytest.approx(0.0)
    assert pd.isna(row["drive_to_sale_pct"])
    assert not pd.isna(row["lead_to_sale_pct"])


def test_zero_network_sales_stays_zero_with_valid_zero_sale_rates(
    transaction_connection,
):
    transaction_connection.execute(
        text("""
            UPDATE sales_monthly
            SET units_sold = 0
            WHERE month = :month
            """),
        {"month": TEST_MONTH},
    )

    row = db.get_network_funnel_trend(
        start=TEST_MONTH,
        end=TEST_MONTH,
    ).iloc[0]

    assert row["units_sold"] == 0

    assert not pd.isna(row["test_drive_rate_pct"])
    assert row["drive_to_sale_pct"] == pytest.approx(0.0)
    assert row["lead_to_sale_pct"] == pytest.approx(0.0)


# ============================================================
# Inclusive range filtering
# ============================================================


def test_start_only_is_inclusive():
    trend = db.get_network_funnel_trend(start="2026-01")

    assert trend["month"].tolist() == [
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
    trend = db.get_network_funnel_trend(end="2024-12")

    assert trend["month"].tolist() == [
        "2024-10",
        "2024-11",
        "2024-12",
    ]


def test_both_bounds_are_inclusive():
    trend = db.get_network_funnel_trend(
        start="2025-03",
        end="2025-05",
    )

    assert trend["month"].tolist() == [
        "2025-03",
        "2025-04",
        "2025-05",
    ]


def test_equal_bounds_return_one_month():
    trend = db.get_network_funnel_trend(
        start="2025-03",
        end="2025-03",
    )

    assert trend["month"].tolist() == ["2025-03"]


@pytest.mark.parametrize(
    ("start", "end"),
    [
        ("2030-01", "2030-12"),
        ("2020-01", "2020-12"),
        ("2030-01", None),
        (None, "2020-12"),
    ],
)
def test_valid_empty_window_returns_empty_dataframe(
    start,
    end,
):
    trend = db.get_network_funnel_trend(
        start=start,
        end=end,
    )

    assert trend.empty
    assert list(trend.columns) == EXPECTED_COLUMNS


# ============================================================
# Validation
# ============================================================


def test_reversed_range_raises_invalid_month_range_error():
    with pytest.raises(
        db.InvalidMonthRangeError,
        match="start month must not be after end month",
    ):
        db.get_network_funnel_trend(
            start="2026-09",
            end="2026-08",
        )


@pytest.mark.parametrize(
    "start",
    [
        "2026-9",
        "26-09",
        "2026/09",
        "2026-13",
        "2026-00",
        " 2026-01",
        "2026-01\n",
        "",
    ],
)
def test_malformed_start_raises_invalid_month_error(start):
    with pytest.raises(
        db.InvalidMonthError,
    ):
        db.get_network_funnel_trend(
            start=start,
        )


@pytest.mark.parametrize(
    "end",
    [
        "2026-9",
        "26-09",
        "2026/09",
        "2026-13",
        "2026-00",
        " 2026-01",
        "2026-01\n",
        "",
    ],
)
def test_malformed_end_raises_invalid_month_error(end):
    with pytest.raises(
        db.InvalidMonthError,
    ):
        db.get_network_funnel_trend(
            end=end,
        )


@pytest.mark.parametrize(
    "start",
    [
        202601,
        True,
        False,
    ],
)
def test_non_string_start_raises_invalid_month_error(start):
    with pytest.raises(
        db.InvalidMonthError,
    ):
        db.get_network_funnel_trend(
            start=start,
        )


@pytest.mark.parametrize(
    "end",
    [
        202601,
        True,
        False,
    ],
)
def test_non_string_end_raises_invalid_month_error(end):
    with pytest.raises(
        db.InvalidMonthError,
    ):
        db.get_network_funnel_trend(
            end=end,
        )


def test_validation_happens_before_query_execution(
    monkeypatch,
):
    def fail_if_called():
        raise AssertionError("database should not be touched")

    monkeypatch.setattr(
        db,
        "get_engine",
        fail_if_called,
    )

    with pytest.raises(db.InvalidMonthError):
        db.get_network_funnel_trend(
            start="2026-9",
        )


def test_reversed_range_is_checked_before_query_execution(
    monkeypatch,
):
    def fail_if_called():
        raise AssertionError("database should not be touched")

    monkeypatch.setattr(
        db,
        "get_engine",
        fail_if_called,
    )

    with pytest.raises(
        db.InvalidMonthRangeError,
        match="start month must not be after end month",
    ):
        db.get_network_funnel_trend(
            start="2026-09",
            end="2026-08",
        )


# ============================================================
# Source-schema assumptions for row-existence completeness
# ============================================================


@pytest.mark.parametrize(
    ("table_name", "column_name"),
    [
        ("leads_monthly", "leads"),
        ("leads_monthly", "test_drives"),
        ("sales_monthly", "units_sold"),
    ],
)
def test_completeness_source_columns_are_not_nullable(
    table_name,
    column_name,
):
    """
    COUNT(column) is a row-existence proxy only because these source
    metrics are guaranteed non-null by the database schema.
    """
    result = pd.read_sql(
        text("""
            SELECT is_nullable
            FROM information_schema.columns
            WHERE table_schema = current_schema()
              AND table_name = :table_name
              AND column_name = :column_name
            """),
        db.get_engine(),
        params={
            "table_name": table_name,
            "column_name": column_name,
        },
    )

    assert len(result) == 1
    assert result.iloc[0]["is_nullable"] == "NO"


def test_dealer_monthly_funnel_units_sold_is_bigint():
    """
    The Day 31 view exposes dealer-month units as bigint.

    Day 32 must therefore cast SUM(bigint) back to bigint because
    PostgreSQL otherwise promotes that aggregate to numeric.
    """
    result = pd.read_sql(
        text("""
            SELECT pg_typeof(units_sold)::text AS units_sold_type
            FROM dealer_monthly_funnel
            WHERE units_sold IS NOT NULL
            LIMIT 1
            """),
        db.get_engine(),
    )

    assert len(result) == 1
    assert result.iloc[0]["units_sold_type"] == "bigint"
