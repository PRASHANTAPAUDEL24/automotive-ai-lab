from fractions import Fraction
from pathlib import Path

import pandas as pd
import pytest
from sqlalchemy import text

import db

DATA_DIR = Path(__file__).resolve().parents[1] / "data"
MONTH = "2026-09"
EXPECTED_MODELS = 8


def _expected_from_csv(month):
    sales = pd.read_csv(DATA_DIR / "sales_monthly.csv")
    models = pd.read_csv(DATA_DIR / "vehicle_models.csv")

    month_sales = sales[sales["month"] == month].copy()
    network_units = int(month_sales["units_sold"].sum())

    rows = []

    for model, group in month_sales.groupby("model"):
        units_sold = int(group["units_sold"].sum())

        priced = group[group["avg_sale_price"].notna()]
        priced_units = int(priced["units_sold"].sum())

        if priced_units == 0:
            avg_sale_price = None
        else:
            numerator = sum(
                Fraction(str(price)) * int(units)
                for price, units in zip(
                    priced["avg_sale_price"],
                    priced["units_sold"],
                )
            )
            avg_sale_price = float(numerator / priced_units)

        share_pct = (
            None
            if network_units == 0
            else float(Fraction(units_sold * 100, network_units))
        )

        catalog = models.loc[models["model"] == model].iloc[0]

        rows.append(
            {
                "model": model,
                "segment": catalog["segment"],
                "msrp": int(catalog["msrp"]),
                "units_sold": units_sold,
                "share_pct": share_pct,
                "avg_sale_price": avg_sale_price,
            }
        )

    return sorted(
        rows,
        key=lambda row: (-row["units_sold"], row["model"]),
    )


def test_model_performance_returns_one_row_per_model():
    result = db.get_model_performance(MONTH)

    assert len(result) == EXPECTED_MODELS
    assert result["model"].nunique() == EXPECTED_MODELS


def test_model_performance_has_exact_columns():
    result = db.get_model_performance(MONTH)

    assert list(result.columns) == [
        "model",
        "segment",
        "msrp",
        "units_sold",
        "share_pct",
        "avg_sale_price",
    ]


def test_model_performance_matches_csv_recomputation():
    result = db.get_model_performance(MONTH)
    expected = _expected_from_csv(MONTH)

    assert result["model"].tolist() == [row["model"] for row in expected]

    for actual, expected_row in zip(
        result.to_dict("records"),
        expected,
    ):
        assert actual["model"] == expected_row["model"]
        assert actual["segment"] == expected_row["segment"]
        assert actual["msrp"] == expected_row["msrp"]
        assert actual["units_sold"] == expected_row["units_sold"]
        assert actual["share_pct"] == pytest.approx(expected_row["share_pct"])
        assert actual["avg_sale_price"] == pytest.approx(expected_row["avg_sale_price"])


def test_model_performance_is_ordered_by_units_then_model():
    result = db.get_model_performance(MONTH)

    expected = result.sort_values(
        ["units_sold", "model"],
        ascending=[False, True],
        kind="stable",
    ).reset_index(drop=True)

    pd.testing.assert_frame_equal(
        result.reset_index(drop=True),
        expected,
    )


def test_model_units_equal_network_rollup_units():
    result = db.get_model_performance(MONTH)

    network = pd.read_sql(
        text("""
            SELECT units_sold
            FROM monthly_performance_rollup
            WHERE month = :month
              AND region IS NULL
        """),
        db.get_engine(),
        params={"month": MONTH},
    )

    assert len(network) == 1
    assert int(result["units_sold"].sum()) == int(network.iloc[0]["units_sold"])


def test_share_pct_sums_to_100_for_positive_network_units():
    result = db.get_model_performance(MONTH)

    assert result["share_pct"].sum() == pytest.approx(100.0)


def test_catalog_fields_match_vehicle_models():
    result = db.get_model_performance(MONTH)

    catalog = pd.read_sql(
        text("""
            SELECT model, segment, msrp
            FROM vehicle_models
            ORDER BY model
        """),
        db.get_engine(),
    )

    actual = (
        result[["model", "segment", "msrp"]].sort_values("model").reset_index(drop=True)
    )

    expected = catalog.reset_index(drop=True)

    pd.testing.assert_frame_equal(actual, expected)


def test_null_price_positive_units_do_not_enter_weighted_price_denominator(
    monkeypatch,
):
    engine = db.get_engine()

    with engine.connect() as connection:
        transaction = connection.begin()

        try:
            monkeypatch.setattr(
                db,
                "get_engine",
                lambda: connection,
            )

            model = connection.execute(
                text("SELECT model " "FROM vehicle_models " "ORDER BY model " "LIMIT 1")
            ).scalar_one()

            dealer_ids = [
                row[0]
                for row in connection.execute(
                    text(
                        "SELECT dealer_id "
                        "FROM sales_monthly "
                        "WHERE month = :month "
                        "AND model = :model "
                        "ORDER BY dealer_id "
                        "LIMIT 2"
                    ),
                    {
                        "month": MONTH,
                        "model": model,
                    },
                )
            ]

            assert len(dealer_ids) == 2

            for dealer_id, units, price in (
                (dealer_ids[0], 10, 30000),
                (dealer_ids[1], 90, None),
            ):
                connection.execute(
                    text(
                        "UPDATE sales_monthly "
                        "SET units_sold = :units, "
                        "avg_sale_price = :price "
                        "WHERE dealer_id = :dealer_id "
                        "AND month = :month "
                        "AND model = :model"
                    ),
                    {
                        "units": units,
                        "price": price,
                        "dealer_id": dealer_id,
                        "month": MONTH,
                        "model": model,
                    },
                )

            result = db.get_model_performance(MONTH)
            row = result.loc[result["model"] == model].iloc[0]

            source = pd.read_sql(
                text(
                    "SELECT units_sold, avg_sale_price "
                    "FROM sales_monthly "
                    "WHERE month = :month "
                    "AND model = :model"
                ),
                connection,
                params={
                    "month": MONTH,
                    "model": model,
                },
            )

            priced_source = source[source["avg_sale_price"].notna()]

            numerator = (
                priced_source["avg_sale_price"] * priced_source["units_sold"]
            ).sum()

            expected = float(numerator / priced_source["units_sold"].sum())

            unfiltered = float(numerator / source["units_sold"].sum())

            # Guard against a vacuous fixture: the denominators
            # must produce different answers.
            assert unfiltered != pytest.approx(expected)

            assert row["avg_sale_price"] == pytest.approx(expected)
            assert int(row["units_sold"]) == int(source["units_sold"].sum())
        finally:
            transaction.rollback()


def test_zero_priced_units_make_avg_sale_price_null(monkeypatch):
    engine = db.get_engine()

    with engine.connect() as connection:
        transaction = connection.begin()

        try:
            monkeypatch.setattr(
                db,
                "get_engine",
                lambda: connection,
            )

            model = connection.execute(
                text("SELECT model " "FROM vehicle_models " "ORDER BY model " "LIMIT 1")
            ).scalar_one()

            connection.execute(
                text(
                    "UPDATE sales_monthly "
                    "SET units_sold = 5, "
                    "avg_sale_price = NULL "
                    "WHERE month = :month "
                    "AND model = :model"
                ),
                {
                    "month": MONTH,
                    "model": model,
                },
            )

            result = db.get_model_performance(MONTH)
            row = result.loc[result["model"] == model].iloc[0]

            assert int(row["units_sold"]) > 0
            assert pd.isna(row["avg_sale_price"])
        finally:
            transaction.rollback()


def test_priced_rows_with_zero_units_make_avg_sale_price_null(
    monkeypatch,
):
    engine = db.get_engine()

    with engine.connect() as connection:
        transaction = connection.begin()

        try:
            monkeypatch.setattr(
                db,
                "get_engine",
                lambda: connection,
            )

            model = connection.execute(
                text("SELECT model " "FROM vehicle_models " "ORDER BY model " "LIMIT 1")
            ).scalar_one()

            connection.execute(
                text(
                    "UPDATE sales_monthly "
                    "SET units_sold = 0, "
                    "avg_sale_price = 100 "
                    "WHERE month = :month "
                    "AND model = :model"
                ),
                {
                    "month": MONTH,
                    "model": model,
                },
            )

            result = db.get_model_performance(MONTH)
            row = result.loc[result["model"] == model].iloc[0]

            assert int(row["units_sold"]) == 0
            assert pd.isna(row["avg_sale_price"])
            assert float(row["share_pct"]) == pytest.approx(0.0)
        finally:
            transaction.rollback()


def test_zero_network_units_make_all_share_pct_null(monkeypatch):
    engine = db.get_engine()

    with engine.connect() as connection:
        transaction = connection.begin()

        try:
            monkeypatch.setattr(
                db,
                "get_engine",
                lambda: connection,
            )

            connection.execute(
                text("""
                    UPDATE sales_monthly
                    SET units_sold = 0
                    WHERE month = :month
                """),
                {"month": MONTH},
            )

            result = db.get_model_performance(MONTH)

            assert len(result) == EXPECTED_MODELS
            assert result["share_pct"].isna().all()
        finally:
            transaction.rollback()


def test_model_without_sales_rows_is_omitted(monkeypatch):
    engine = db.get_engine()

    with engine.connect() as connection:
        transaction = connection.begin()

        try:
            monkeypatch.setattr(
                db,
                "get_engine",
                lambda: connection,
            )

            model = connection.execute(
                text("SELECT model " "FROM vehicle_models " "ORDER BY model " "LIMIT 1")
            ).scalar_one()

            deleted = connection.execute(
                text("""
                    DELETE FROM sales_monthly
                    WHERE month = :month
                      AND model = :model
                """),
                {
                    "month": MONTH,
                    "model": model,
                },
            )

            assert deleted.rowcount > 0

            result = db.get_model_performance(MONTH)

            assert len(result) == EXPECTED_MODELS - 1
            assert model not in result["model"].tolist()
        finally:
            transaction.rollback()


def test_equal_units_are_ordered_by_model_name(monkeypatch):
    engine = db.get_engine()

    with engine.connect() as connection:
        transaction = connection.begin()

        try:
            monkeypatch.setattr(
                db,
                "get_engine",
                lambda: connection,
            )

            models = [
                row[0]
                for row in connection.execute(
                    text("SELECT model " "FROM vehicle_models " "ORDER BY model")
                )
            ]

            dealer_id = connection.execute(
                text("SELECT min(dealer_id) " "FROM dealers")
            ).scalar_one()

            connection.execute(
                text(
                    "UPDATE sales_monthly "
                    "SET units_sold = 0, "
                    "avg_sale_price = NULL "
                    "WHERE month = :month"
                ),
                {"month": MONTH},
            )

            for model, units in (
                (models[2], 9),
                (models[0], 5),
                (models[1], 5),
            ):
                connection.execute(
                    text(
                        "UPDATE sales_monthly "
                        "SET units_sold = :units, "
                        "avg_sale_price = 10 "
                        "WHERE dealer_id = :dealer_id "
                        "AND month = :month "
                        "AND model = :model"
                    ),
                    {
                        "units": units,
                        "dealer_id": dealer_id,
                        "month": MONTH,
                        "model": model,
                    },
                )

            result = db.get_model_performance(MONTH)

            assert result["model"].tolist() == [
                models[2],
                models[0],
                models[1],
                *models[3:],
            ]
        finally:
            transaction.rollback()


@pytest.mark.parametrize(
    "month",
    [
        "2026-9",
        "2026-00",
        "2026-13",
        "２０２６-０９",
        None,
    ],
)
def test_model_performance_rejects_invalid_month(month):
    with pytest.raises(db.InvalidMonthError):
        db.get_model_performance(month)


def test_model_performance_missing_month_raises_not_found():
    with pytest.raises(
        db.MonthNotFoundError,
        match="Month 2099-01 not found",
    ):
        db.get_model_performance("2099-01")
