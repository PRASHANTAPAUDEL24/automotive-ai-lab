# Program: tests/test_db.py
# Day 11: pytest tests for reusable PostgreSQL query functions
# Created on: 2026-11-01
# Author: Prashanta Paudel
# Purpose: Validate dealer scorecard filtering and query safety.

import pytest

from db import InvalidFilterError, get_scorecard


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
