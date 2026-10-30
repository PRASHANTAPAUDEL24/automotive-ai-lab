# Program: src/day9_query_scorecard.py
# Day 9: Parameterized dealer scorecard queries
# Created on: 2026-10-29
# Author: Prashanta Paudel
# Purpose: Validate reusable PostgreSQL filters for region and risk.

from db import get_scorecard


# No filters should return all dealers.
all_dealers = get_scorecard()

assert len(all_dealers) == 40, (
    f"Expected 40 dealers, got {len(all_dealers)}"
)


# Region filter should use a bound parameter.
west = get_scorecard(region="West")

assert len(west) == 8, (
    f"Expected 8 West-region dealers, got {len(west)}"
)

print("West-region dealers:", len(west))


# Combined-risk should return only dealer 111.
combined = get_scorecard(risk="combined_risk")

assert len(combined) == 1, (
    f"Expected 1 combined-risk dealer, got {len(combined)}"
)

assert combined.iloc[0]["dealer_id"] == 111, (
    f"Expected dealer 111, got {combined.iloc[0]['dealer_id']}"
)

print("Combined-risk dealers:", len(combined))


# Early-overstock watch should return dealers 102, 105, and 130.
early_watch = get_scorecard(risk="early_overstock_watch")
expected_early_watch = {102, 105, 130}
actual_early_watch = set(early_watch["dealer_id"])

assert actual_early_watch == expected_early_watch, (
    f"Expected early-watch dealers {expected_early_watch}, "
    f"got {actual_early_watch}"
)

print("Early-watch dealers:", sorted(actual_early_watch))


# Combining region and risk filters should work together.
west_early_watch = get_scorecard(
    region="West",
    risk="early_overstock_watch",
)

expected_west_early_watch = {105, 130}
actual_west_early_watch = set(west_early_watch["dealer_id"])

assert actual_west_early_watch == expected_west_early_watch, (
    f"Expected West early-watch dealers {expected_west_early_watch}, "
    f"got {actual_west_early_watch}"
)

print("West early-watch dealers:", sorted(actual_west_early_watch))


# Invalid risk names must be rejected before they reach the SQL query.
try:
    get_scorecard(risk="dealer_name")
except ValueError as error:
    print("Invalid risk rejected:", error)
else:
    raise AssertionError(
        "Expected invalid risk filter to raise ValueError"
    )


# Injection-like input must be treated as a region value, not executable SQL.
injection_test = get_scorecard(
    region="West'; DROP TABLE dealers; --"
)

assert len(injection_test) == 0, (
    "Injection-like region input should return no rows"
)

# Confirm the database is still intact after the injection test.
assert len(get_scorecard()) == 40, (
    "Dealer scorecard should still contain 40 dealers"
)


# Validate region-by-risk counts.
expected_region_counts = {
    "Northeast": (3, 2),
    "Southeast": (3, 1),
    "Midwest": (2, 2),
    "Southwest": (2, 2),
    "West": (2, 2),
}

for region, (expected_sales, expected_inventory) in expected_region_counts.items():
    actual_sales = len(
        get_scorecard(region=region, risk="sales_risk")
    )
    actual_inventory = len(
        get_scorecard(region=region, risk="inventory_risk")
    )

    assert actual_sales == expected_sales, (
        f"{region}: expected {expected_sales} sales-risk dealers, "
        f"got {actual_sales}"
    )

    assert actual_inventory == expected_inventory, (
        f"{region}: expected {expected_inventory} inventory-risk dealers, "
        f"got {actual_inventory}"
    )


# Validate network-wide risk counts.
assert len(get_scorecard(risk="sales_risk")) == 12, (
    "Expected 12 sales-risk dealers"
)

assert len(get_scorecard(risk="inventory_risk")) == 9, (
    "Expected 9 inventory-risk dealers"
)

# An unknown region should return an empty DataFrame.
unknown_region = get_scorecard(region="Atlantis")

assert len(unknown_region) == 0, (
    "Unknown region should return an empty DataFrame"
)

# Injection-like input must not broaden the query.
leakage_test = get_scorecard(
    region="West' OR '1'='1"
)

assert len(leakage_test) == 0, (
    "Injection-like region input should not broaden the query"
)

# Confirm the database still contains all dealers.
assert len(get_scorecard()) == 40, (
    "Dealer scorecard should still contain 40 dealers"
)

print("Region-by-risk validation passed.")
print("Unknown-region test passed.")
print("Injection tests passed.")
print("Day 9 validation passed.")