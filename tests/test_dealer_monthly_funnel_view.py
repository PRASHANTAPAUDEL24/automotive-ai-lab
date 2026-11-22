from pathlib import Path

import pandas as pd
import pytest
from sqlalchemy import text

import db

DATA_DIR = Path(__file__).resolve().parents[1] / "data"

EXPECTED_COLUMNS = [
    "dealer_id",
    "month",
    "leads",
    "test_drives",
    "units_sold",
    "test_drive_rate_pct",
    "drive_to_sale_pct",
    "lead_to_sale_pct",
]


def _view_row(connection, dealer_id, month):
    return (
        connection.execute(
            text("""
                SELECT
                    dealer_id,
                    month,
                    leads,
                    test_drives,
                    units_sold,
                    test_drive_rate_pct,
                    drive_to_sale_pct,
                    lead_to_sale_pct
                FROM dealer_monthly_funnel
                WHERE dealer_id = :dealer_id
                  AND month = :month
            """),
            {"dealer_id": dealer_id, "month": month},
        )
        .mappings()
        .one()
    )


def _target_dealer_month(connection):
    return connection.execute(text("""
                SELECT
                    l.dealer_id,
                    l.month
                FROM leads_monthly l
                JOIN sales_monthly s
                  ON s.dealer_id = l.dealer_id
                 AND s.month = l.month
                GROUP BY
                    l.dealer_id,
                    l.month
                HAVING COUNT(*) > 1
                ORDER BY
                    l.dealer_id,
                    l.month
                LIMIT 1
            """)).mappings().one()


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
# Shape, oracle and types
# ============================================================


def test_dealer_monthly_funnel_has_exact_shape_and_unique_grain():
    result = pd.read_sql(
        text("""
            SELECT *
            FROM dealer_monthly_funnel
            ORDER BY dealer_id, month
        """),
        db.get_engine(),
    )

    assert list(result.columns) == EXPECTED_COLUMNS
    assert len(result) == 960
    assert result["dealer_id"].nunique() == 40
    assert result["month"].nunique() == 24
    assert not result.duplicated(["dealer_id", "month"]).any()


def test_dealer_monthly_funnel_matches_independent_csv_oracle():
    leads = pd.read_csv(DATA_DIR / "leads_monthly.csv")
    sales = pd.read_csv(DATA_DIR / "sales_monthly.csv")

    sales_by_dealer = (
        sales.groupby(
            ["dealer_id", "month"],
            as_index=False,
        )["units_sold"]
        .sum()
        .sort_values(["dealer_id", "month"])
        .reset_index(drop=True)
    )

    expected = (
        leads.merge(
            sales_by_dealer,
            on=["dealer_id", "month"],
            how="left",
            validate="one_to_one",
        )
        .sort_values(["dealer_id", "month"])
        .reset_index(drop=True)
    )

    actual = pd.read_sql(
        text("""
            SELECT
                dealer_id,
                month,
                leads,
                test_drives,
                units_sold,
                test_drive_rate_pct,
                drive_to_sale_pct,
                lead_to_sale_pct
            FROM dealer_monthly_funnel
            ORDER BY dealer_id, month
        """),
        db.get_engine(),
    )

    assert len(actual) == len(expected) == 960

    assert actual["dealer_id"].astype(int).tolist() == (
        expected["dealer_id"].astype(int).tolist()
    )
    assert actual["month"].tolist() == expected["month"].tolist()
    assert actual["leads"].astype(int).tolist() == expected["leads"].tolist()
    assert actual["test_drives"].astype(int).tolist() == (
        expected["test_drives"].tolist()
    )
    assert actual["units_sold"].astype(int).tolist() == (
        expected["units_sold"].astype(int).tolist()
    )

    for actual_row, expected_row in zip(
        actual.to_dict("records"),
        expected.to_dict("records"),
        strict=True,
    ):
        expected_test_drive_rate = (
            expected_row["test_drives"] * 100.0 / expected_row["leads"]
        )
        expected_drive_to_sale = (
            expected_row["units_sold"] * 100.0 / expected_row["test_drives"]
        )
        expected_lead_to_sale = (
            expected_row["units_sold"] * 100.0 / expected_row["leads"]
        )

        assert float(actual_row["test_drive_rate_pct"]) == pytest.approx(
            expected_test_drive_rate,
            rel=1e-12,
        )
        assert float(actual_row["drive_to_sale_pct"]) == pytest.approx(
            expected_drive_to_sale,
            rel=1e-12,
        )
        assert float(actual_row["lead_to_sale_pct"]) == pytest.approx(
            expected_lead_to_sale,
            rel=1e-12,
        )


def test_dealer_monthly_funnel_has_explicit_postgresql_types():
    with db.get_engine().connect() as connection:
        result = connection.execute(text("""
                    SELECT
                        pg_typeof(dealer_id)::text AS dealer_id_type,
                        pg_typeof(month)::text AS month_type,
                        pg_typeof(leads)::text AS leads_type,
                        pg_typeof(test_drives)::text AS test_drives_type,
                        pg_typeof(units_sold)::text AS units_sold_type,
                        pg_typeof(test_drive_rate_pct)::text AS test_drive_rate_type,
                        pg_typeof(drive_to_sale_pct)::text AS drive_to_sale_type,
                        pg_typeof(lead_to_sale_pct)::text AS lead_to_sale_type
                    FROM dealer_monthly_funnel
                    LIMIT 1
                """)).mappings().one()

    assert dict(result) == {
        "dealer_id_type": "integer",
        "month_type": "text",
        "leads_type": "integer",
        "test_drives_type": "integer",
        "units_sold_type": "bigint",
        "test_drive_rate_type": "numeric",
        "drive_to_sale_type": "numeric",
        "lead_to_sale_type": "numeric",
    }


def test_multiple_model_rows_do_not_fan_out_lead_metrics():
    with db.get_engine().connect() as connection:
        target = _target_dealer_month(connection)

        source = (
            connection.execute(
                text("""
                    SELECT
                        l.leads,
                        l.test_drives,
                        SUM(s.units_sold) AS units_sold,
                        COUNT(*) AS model_rows
                    FROM leads_monthly l
                    JOIN sales_monthly s
                      ON s.dealer_id = l.dealer_id
                     AND s.month = l.month
                    WHERE l.dealer_id = :dealer_id
                      AND l.month = :month
                    GROUP BY
                        l.leads,
                        l.test_drives
                """),
                target,
            )
            .mappings()
            .one()
        )

        assert source["model_rows"] > 1

        row = _view_row(
            connection,
            target["dealer_id"],
            target["month"],
        )

        assert row["leads"] == source["leads"]
        assert row["test_drives"] == source["test_drives"]
        assert row["units_sold"] == source["units_sold"]


# ============================================================
# Missing-data and zero semantics
# ============================================================


def test_missing_lead_row_preserves_spine_and_sales(
    rolled_back_connection,
):
    connection = rolled_back_connection
    target = _target_dealer_month(connection)

    units_sold = connection.execute(
        text("""
            SELECT SUM(units_sold)
            FROM sales_monthly
            WHERE dealer_id = :dealer_id
              AND month = :month
        """),
        target,
    ).scalar_one()

    connection.execute(
        text("""
            DELETE FROM leads_monthly
            WHERE dealer_id = :dealer_id
              AND month = :month
        """),
        target,
    )

    row = _view_row(
        connection,
        target["dealer_id"],
        target["month"],
    )

    assert row["leads"] is None
    assert row["test_drives"] is None
    assert row["units_sold"] == units_sold
    assert row["test_drive_rate_pct"] is None
    assert row["drive_to_sale_pct"] is None
    assert row["lead_to_sale_pct"] is None


def test_missing_sales_dealer_month_nulls_sale_metrics_only(
    rolled_back_connection,
):
    connection = rolled_back_connection
    target = _target_dealer_month(connection)

    lead_row = (
        connection.execute(
            text("""
                SELECT leads, test_drives
                FROM leads_monthly
                WHERE dealer_id = :dealer_id
                  AND month = :month
            """),
            target,
        )
        .mappings()
        .one()
    )

    connection.execute(
        text("""
            DELETE FROM sales_monthly
            WHERE dealer_id = :dealer_id
              AND month = :month
        """),
        target,
    )

    row = _view_row(
        connection,
        target["dealer_id"],
        target["month"],
    )

    assert row["leads"] == lead_row["leads"]
    assert row["test_drives"] == lead_row["test_drives"]
    assert row["units_sold"] is None

    assert float(row["test_drive_rate_pct"]) == pytest.approx(
        lead_row["test_drives"] * 100.0 / lead_row["leads"],
        rel=1e-12,
    )
    assert row["drive_to_sale_pct"] is None
    assert row["lead_to_sale_pct"] is None


def test_missing_one_model_row_keeps_reduced_units_non_null(
    rolled_back_connection,
):
    connection = rolled_back_connection
    target = _target_dealer_month(connection)

    sales_rows = (
        connection.execute(
            text("""
                SELECT model, units_sold
                FROM sales_monthly
                WHERE dealer_id = :dealer_id
                  AND month = :month
                ORDER BY model
            """),
            target,
        )
        .mappings()
        .all()
    )

    assert len(sales_rows) > 1

    original_total = sum(row["units_sold"] for row in sales_rows)
    removed = sales_rows[0]

    connection.execute(
        text("""
            DELETE FROM sales_monthly
            WHERE dealer_id = :dealer_id
              AND month = :month
              AND model = :model
        """),
        {
            **target,
            "model": removed["model"],
        },
    )

    row = _view_row(
        connection,
        target["dealer_id"],
        target["month"],
    )

    assert row["units_sold"] == original_total - removed["units_sold"]
    assert row["units_sold"] is not None


def test_zero_leads_nulls_lead_denominator_rates(
    rolled_back_connection,
):
    connection = rolled_back_connection
    target = _target_dealer_month(connection)

    connection.execute(
        text("""
            UPDATE leads_monthly
            SET leads = 0
            WHERE dealer_id = :dealer_id
              AND month = :month
        """),
        target,
    )

    row = _view_row(
        connection,
        target["dealer_id"],
        target["month"],
    )

    assert row["leads"] == 0
    assert row["test_drive_rate_pct"] is None
    assert row["lead_to_sale_pct"] is None

    assert row["test_drives"] > 0
    assert float(row["drive_to_sale_pct"]) == pytest.approx(
        row["units_sold"] * 100.0 / row["test_drives"],
        rel=1e-12,
    )


def test_zero_test_drives_distinguishes_zero_from_null(
    rolled_back_connection,
):
    connection = rolled_back_connection
    target = _target_dealer_month(connection)

    connection.execute(
        text("""
            UPDATE leads_monthly
            SET test_drives = 0
            WHERE dealer_id = :dealer_id
              AND month = :month
        """),
        target,
    )

    row = _view_row(
        connection,
        target["dealer_id"],
        target["month"],
    )

    assert row["leads"] > 0
    assert row["test_drives"] == 0
    assert float(row["test_drive_rate_pct"]) == pytest.approx(0.0)
    assert row["drive_to_sale_pct"] is None

    assert float(row["lead_to_sale_pct"]) == pytest.approx(
        row["units_sold"] * 100.0 / row["leads"],
        rel=1e-12,
    )


def test_zero_sales_rows_are_complete_not_missing(
    rolled_back_connection,
):
    connection = rolled_back_connection
    target = _target_dealer_month(connection)

    connection.execute(
        text("""
            UPDATE sales_monthly
            SET units_sold = 0
            WHERE dealer_id = :dealer_id
              AND month = :month
        """),
        target,
    )

    row = _view_row(
        connection,
        target["dealer_id"],
        target["month"],
    )

    assert row["units_sold"] == 0
    assert float(row["drive_to_sale_pct"]) == pytest.approx(0.0)
    assert float(row["lead_to_sale_pct"]) == pytest.approx(0.0)


# ============================================================
# Month spine
# ============================================================


def test_sales_only_month_does_not_create_funnel_month(
    rolled_back_connection,
):
    connection = rolled_back_connection

    source = connection.execute(text("""
                SELECT dealer_id, model
                FROM sales_monthly
                ORDER BY dealer_id, model
                LIMIT 1
            """)).mappings().one()

    connection.execute(
        text("""
            INSERT INTO sales_monthly (
                dealer_id,
                month,
                model,
                units_sold
            )
            VALUES (
                :dealer_id,
                '2099-01',
                :model,
                1
            )
        """),
        source,
    )

    count = connection.execute(text("""
            SELECT COUNT(*)
            FROM dealer_monthly_funnel
            WHERE month = '2099-01'
        """)).scalar_one()

    assert count == 0


def test_removing_all_lead_rows_removes_month_from_spine(
    rolled_back_connection,
):
    connection = rolled_back_connection
    month = "2026-09"

    connection.execute(
        text("""
            DELETE FROM leads_monthly
            WHERE month = :month
        """),
        {"month": month},
    )

    count = connection.execute(
        text("""
            SELECT COUNT(*)
            FROM dealer_monthly_funnel
            WHERE month = :month
        """),
        {"month": month},
    ).scalar_one()

    assert count == 0


def test_dealer_with_no_source_rows_appears_for_every_month_with_null_metrics(
    rolled_back_connection,
):
    connection = rolled_back_connection

    connection.execute(text("""
            INSERT INTO dealers (
                dealer_id,
                dealer_name,
                city,
                state,
                region,
                size_class
            )
            SELECT
                9999,
                'Funnel Test Dealer',
                'Testville',
                'TS',
                region,
                size_class
            FROM dealers
            ORDER BY dealer_id
            LIMIT 1
        """))

    rows = connection.execute(text("""
                SELECT
                    month,
                    leads,
                    test_drives,
                    units_sold,
                    test_drive_rate_pct,
                    drive_to_sale_pct,
                    lead_to_sale_pct
                FROM dealer_monthly_funnel
                WHERE dealer_id = 9999
                ORDER BY month
            """)).mappings().all()

    assert len(rows) == 24

    for row in rows:
        assert row["leads"] is None
        assert row["test_drives"] is None
        assert row["units_sold"] is None
        assert row["test_drive_rate_pct"] is None
        assert row["drive_to_sale_pct"] is None
        assert row["lead_to_sale_pct"] is None


# ============================================================
# Reconciliation with Day 30 regional contract
# ============================================================


def test_dealer_view_reconciles_to_regional_funnel_for_all_months():
    dealer_rows = pd.read_sql(
        text("""
            SELECT
                d.region,
                f.month,
                f.leads,
                f.test_drives,
                f.units_sold
            FROM dealer_monthly_funnel f
            JOIN dealers d
              ON d.dealer_id = f.dealer_id
            ORDER BY f.month, d.region, f.dealer_id
        """),
        db.get_engine(),
    )

    months = sorted(dealer_rows["month"].unique())

    for month in months:
        month_rows = dealer_rows.loc[dealer_rows["month"] == month]

        grouped = (
            month_rows.groupby("region", as_index=False)[
                ["leads", "test_drives", "units_sold"]
            ]
            .sum()
            .sort_values("region")
            .reset_index(drop=True)
        )

        regional = db.get_regional_funnel_snapshot(month).reset_index(drop=True)

        assert grouped["region"].tolist() == regional["region"].tolist()

        for dealer_sum, regional_row in zip(
            grouped.to_dict("records"),
            regional.to_dict("records"),
            strict=True,
        ):
            leads = int(dealer_sum["leads"])
            drives = int(dealer_sum["test_drives"])
            units = int(dealer_sum["units_sold"])

            assert int(regional_row["leads"]) == leads
            assert int(regional_row["test_drives"]) == drives
            assert int(regional_row["units_sold"]) == units

            assert float(regional_row["test_drive_rate_pct"]) == pytest.approx(
                drives * 100.0 / leads,
                rel=1e-12,
            )
            assert float(regional_row["drive_to_sale_pct"]) == pytest.approx(
                units * 100.0 / drives,
                rel=1e-12,
            )
            assert float(regional_row["lead_to_sale_pct"]) == pytest.approx(
                units * 100.0 / leads,
                rel=1e-12,
            )
