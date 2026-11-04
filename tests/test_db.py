# Program: tests/test_db.py
# Day 11: pytest tests for reusable PostgreSQL query functions
# Created on: 2026-11-01
# Author: Prashanta Paudel
# Purpose: Validate dealer scorecard filtering and query safety.

import pandas as pd
import pytest

from db import InvalidFilterError, get_dealer, get_region_summary, get_scorecard


def test_no_filters_returns_all_dealers():
    scorecard = get_scorecard()

    assert len(scorecard) == 40


def test_west_region_returns_eight_dealers():
    scorecard = get_scorecard(region="West")

    assert len(scorecard) == 8


def test_combined_risk_returns_dealer_111():
    scorecard = get_scorecard(risk="combined_risk")

    assert len(scorecard) == 1
    assert scorecard.iloc[0]["dealer_id"] == 111


def test_early_overstock_watch_dealers():
    scorecard = get_scorecard(risk="early_overstock_watch")

    assert set(scorecard["dealer_id"]) == {102, 105, 130}


def test_combined_region_and_risk_filter():
    scorecard = get_scorecard(
        region="West",
        risk="early_overstock_watch",
    )

    assert set(scorecard["dealer_id"]) == {105, 130}


def test_invalid_risk_raises_error():
    with pytest.raises(
        InvalidFilterError,
        match="Invalid risk filter: dealer_name",
    ):
        get_scorecard(risk="dealer_name")


def test_unknown_region_returns_empty_dataframe():
    scorecard = get_scorecard(region="Atlantis")

    assert len(scorecard) == 0


@pytest.mark.parametrize(
    "region, expected_sales, expected_inventory",
    [
        ("Northeast", 3, 2),
        ("Southeast", 3, 1),
        ("Midwest", 2, 2),
        ("Southwest", 2, 2),
        ("West", 2, 2),
    ],
)
def test_region_risk_counts(
    region,
    expected_sales,
    expected_inventory,
):
    sales_risk = get_scorecard(
        region=region,
        risk="sales_risk",
    )

    inventory_risk = get_scorecard(
        region=region,
        risk="inventory_risk",
    )

    assert len(sales_risk) == expected_sales
    assert len(inventory_risk) == expected_inventory


def test_network_wide_risk_counts():
    assert len(get_scorecard(risk="sales_risk")) == 12
    assert len(get_scorecard(risk="inventory_risk")) == 9


def test_drop_table_injection_string_returns_no_rows():
    scorecard = get_scorecard(region="West'; DROP TABLE dealers; --")

    assert len(scorecard) == 0
    assert len(get_scorecard()) == 40


def test_or_injection_string_returns_no_rows():
    scorecard = get_scorecard(region="West' OR '1'='1")

    assert len(scorecard) == 0
    assert len(get_scorecard()) == 40


def test_get_dealer_111():
    dealer = get_dealer(111)

    assert dealer is not None
    assert dealer["dealer_id"] == 111
    assert dealer["dealer_name"] == "Buffalo Sunset Vertex Automotive"
    assert dealer["combined_risk"] is True


def test_get_unknown_dealer_returns_none():
    dealer = get_dealer(999)

    assert dealer is None


def test_get_dealer_converts_nan_to_none(monkeypatch):
    fake = pd.DataFrame(
        {
            "dealer_id": [111],
            "aged_pct": [float("nan")],
        }
    )

    monkeypatch.setattr(
        "db.pd.read_sql",
        lambda *args, **kwargs: fake,
    )

    dealer = get_dealer(111)

    assert dealer["aged_pct"] is None


def test_region_summary_returns_five_regions():
    summary = get_region_summary()

    assert len(summary) == 5
    assert list(summary["region"]) == [
        "Midwest",
        "Northeast",
        "Southeast",
        "Southwest",
        "West",
    ]


@pytest.mark.parametrize(
    "region, dealers, sales, inventory, combined, early_watch",
    [
        ("Midwest", 8, 2, 2, 0, 0),
        ("Northeast", 8, 3, 2, 1, 0),
        ("Southeast", 8, 3, 1, 0, 1),
        ("Southwest", 8, 2, 2, 0, 0),
        ("West", 8, 2, 2, 0, 2),
    ],
)
def test_region_summary_values(
    region,
    dealers,
    sales,
    inventory,
    combined,
    early_watch,
):
    summary = get_region_summary()
    row = summary.loc[summary["region"] == region].iloc[0]

    assert row["dealers"] == dealers
    assert row["sales_risk_dealers"] == sales
    assert row["inventory_risk_dealers"] == inventory
    assert row["combined_risk_dealers"] == combined
    assert row["early_overstock_watch_dealers"] == early_watch


def test_region_summary_network_totals():
    summary = get_region_summary()

    assert summary["dealers"].sum() == 40
    assert summary["sales_risk_dealers"].sum() == 12
    assert summary["inventory_risk_dealers"].sum() == 9
    assert summary["combined_risk_dealers"].sum() == 1
    assert summary["early_overstock_watch_dealers"].sum() == 3
