import pandas as pd
import pytest
from pandas.testing import assert_frame_equal
from sqlalchemy import text

import db

VIEW_NAME = "monthly_performance_rollup"

EXPECTED_SCHEMA = [
    ("region", "text"),
    ("month", "text"),
    ("dealer_count", "bigint"),
    ("units_sold", "bigint"),
    ("target_units", "bigint"),
    ("achievement_pct", "numeric"),
]

REGIONS = [
    "Midwest",
    "Northeast",
    "Southeast",
    "Southwest",
    "West",
]


def _view_exists(connection):
    return connection.execute(
        text("SELECT to_regclass(:view_name)"),
        {"view_name": f"public.{VIEW_NAME}"},
    ).scalar_one()


def _read_month(connection, month):
    return pd.read_sql(
        text("""
            SELECT
                region,
                month,
                dealer_count,
                units_sold,
                target_units,
                achievement_pct
            FROM monthly_performance_rollup
            WHERE month = :month
            ORDER BY region NULLS LAST
            """),
        connection,
        params={"month": month},
    ).reset_index(drop=True)


def test_rollup_is_regular_view_not_materialized_view():
    with db.get_engine().connect() as connection:
        regular_view = connection.execute(
            text("""
                SELECT COUNT(*)
                FROM pg_views
                WHERE schemaname = 'public'
                  AND viewname = :view_name
                """),
            {"view_name": VIEW_NAME},
        ).scalar_one()

        materialized_view = connection.execute(
            text("""
                SELECT COUNT(*)
                FROM pg_matviews
                WHERE schemaname = 'public'
                  AND matviewname = :view_name
                """),
            {"view_name": VIEW_NAME},
        ).scalar_one()

    assert regular_view == 1
    assert materialized_view == 0


def test_rollup_has_exact_columns_order_and_types():
    query = text("""
        SELECT
            column_name,
            data_type
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = :view_name
        ORDER BY ordinal_position
        """)

    with db.get_engine().connect() as connection:
        actual = connection.execute(
            query,
            {"view_name": VIEW_NAME},
        ).all()

    assert actual == EXPECTED_SCHEMA


def test_rollup_has_exact_regional_and_network_grains():
    with db.get_engine().connect() as connection:
        assert (
            _view_exists(connection) is not None
        ), "monthly_performance_rollup view does not exist"

        frame = pd.read_sql(
            text("""
                SELECT
                    region,
                    month,
                    dealer_count,
                    units_sold,
                    target_units,
                    achievement_pct
                FROM monthly_performance_rollup
                ORDER BY month, region NULLS LAST
                """),
            connection,
        )

    regional = frame[frame["region"].notna()].reset_index(drop=True)
    network = frame[frame["region"].isna()].reset_index(drop=True)

    assert len(frame) == 144
    assert len(regional) == 120
    assert len(network) == 24

    assert regional["region"].nunique() == 5
    assert regional["month"].nunique() == 24
    assert network["month"].nunique() == 24

    assert not regional.duplicated(["region", "month"]).any()
    assert not network.duplicated(["month"]).any()

    assert (regional.groupby("month").size() == 5).all()


@pytest.mark.parametrize("region", REGIONS)
def test_regional_rollup_matches_existing_region_history(region):
    with db.get_engine().connect() as connection:
        assert (
            _view_exists(connection) is not None
        ), "monthly_performance_rollup view does not exist"

        actual = pd.read_sql(
            text("""
                SELECT
                    region,
                    month,
                    dealer_count,
                    units_sold,
                    target_units,
                    achievement_pct
                FROM monthly_performance_rollup
                WHERE region = :region
                ORDER BY month
                """),
            connection,
            params={"region": region},
        ).reset_index(drop=True)

    expected = db.get_region_performance_history(region).reset_index(drop=True)

    assert_frame_equal(
        actual,
        expected,
        check_exact=True,
    )


def test_network_rollup_matches_existing_network_history():
    with db.get_engine().connect() as connection:
        assert (
            _view_exists(connection) is not None
        ), "monthly_performance_rollup view does not exist"

        actual = pd.read_sql(
            text("""
                SELECT
                    month,
                    dealer_count,
                    units_sold,
                    target_units,
                    achievement_pct
                FROM monthly_performance_rollup
                WHERE region IS NULL
                ORDER BY month
                """),
            connection,
        ).reset_index(drop=True)

    expected = db.get_network_performance_history().reset_index(drop=True)

    assert_frame_equal(
        actual,
        expected,
        check_exact=True,
    )


def test_rollup_missing_target_preserves_counts_and_propagates_nulls():
    engine = db.get_engine()

    with engine.connect() as connection:
        transaction = connection.begin()

        try:
            baseline = _read_month(connection, "2026-09")

            dealer_id = connection.execute(text("""
                    SELECT dealer_id
                    FROM dealers
                    WHERE region = 'Midwest'
                    ORDER BY dealer_id
                    LIMIT 1
                    """)).scalar_one()

            connection.execute(
                text("""
                    DELETE FROM dealer_targets
                    WHERE dealer_id = :dealer_id
                      AND month = '2026-09'
                    """),
                {"dealer_id": dealer_id},
            )

            changed = _read_month(connection, "2026-09")
        finally:
            transaction.rollback()

    baseline_midwest = baseline[baseline["region"].eq("Midwest")].iloc[0]
    changed_midwest = changed[changed["region"].eq("Midwest")].iloc[0]

    baseline_network = baseline[baseline["region"].isna()].iloc[0]
    changed_network = changed[changed["region"].isna()].iloc[0]

    assert changed_midwest["dealer_count"] == baseline_midwest["dealer_count"]
    assert changed_midwest["units_sold"] == baseline_midwest["units_sold"]
    assert pd.isna(changed_midwest["target_units"])
    assert pd.isna(changed_midwest["achievement_pct"])

    assert changed_network["dealer_count"] == baseline_network["dealer_count"]
    assert changed_network["units_sold"] == baseline_network["units_sold"]
    assert pd.isna(changed_network["target_units"])
    assert pd.isna(changed_network["achievement_pct"])

    other_regions = [region for region in REGIONS if region != "Midwest"]

    baseline_other = baseline[baseline["region"].isin(other_regions)].reset_index(
        drop=True
    )
    changed_other = changed[changed["region"].isin(other_regions)].reset_index(
        drop=True
    )

    assert_frame_equal(
        changed_other,
        baseline_other,
        check_exact=True,
        check_dtype=False,
    )


def test_rollup_zero_target_recomputes_network_from_other_regions():
    engine = db.get_engine()

    with engine.connect() as connection:
        transaction = connection.begin()

        try:
            baseline = _read_month(connection, "2026-09")

            connection.execute(text("""
                    UPDATE dealer_targets AS t
                    SET target_units = 0
                    FROM dealers AS d
                    WHERE d.dealer_id = t.dealer_id
                      AND d.region = 'Midwest'
                      AND t.month = '2026-09'
                    """))

            changed = _read_month(connection, "2026-09")
        finally:
            transaction.rollback()

    baseline_midwest = baseline[baseline["region"].eq("Midwest")].iloc[0]
    changed_midwest = changed[changed["region"].eq("Midwest")].iloc[0]

    baseline_network = baseline[baseline["region"].isna()].iloc[0]
    changed_network = changed[changed["region"].isna()].iloc[0]

    assert changed_midwest["dealer_count"] == baseline_midwest["dealer_count"]
    assert changed_midwest["units_sold"] == baseline_midwest["units_sold"]
    assert changed_midwest["target_units"] == 0
    assert pd.isna(changed_midwest["achievement_pct"])

    assert changed_network["dealer_count"] == baseline_network["dealer_count"]
    assert changed_network["units_sold"] == baseline_network["units_sold"]

    assert (
        changed_network["target_units"]
        == baseline_network["target_units"] - baseline_midwest["target_units"]
    )

    assert not pd.isna(changed_network["achievement_pct"])


def test_rollup_definition_uses_one_grouping_sets_aggregate():
    with db.get_engine().connect() as connection:
        definition = connection.execute(
            text("SELECT pg_get_viewdef(to_regclass(:name))"),
            {"name": f"public.{VIEW_NAME}"},
        ).scalar_one()

    assert definition is not None, "monthly_performance_rollup view does not exist"
    assert "GROUPING SETS" in definition.upper()
    assert "UNION" not in definition.upper()
