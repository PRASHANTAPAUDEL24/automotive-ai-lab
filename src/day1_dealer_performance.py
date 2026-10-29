# Program: src/day1_dealer_performance.py
# Day 1: Dealer performance vs. target using pandas
# Author: Prashanta Paudel
# Purpose: Analyze September 2026 dealer sales performance
# against monthly sales targets.

import pandas as pd


# Analysis settings.
MONTH = "2026-09"
ALERT_THRESHOLD = 80


# Load the sales, target, and dealer reference datasets.
sales = pd.read_csv("data/sales_monthly.csv")
targets = pd.read_csv("data/dealer_targets.csv")
dealers = pd.read_csv("data/dealers.csv")


# Filter monthly sales to the selected analysis month.
september_sales = sales[sales["month"] == MONTH]


# Aggregate September sales so there is one sales total per dealer.
dealer_sales = (
    september_sales.groupby("dealer_id", as_index=False)["units_sold"]
    .sum()
)


# Keep only September targets and the columns needed for the analysis.
september_targets = targets[
    targets["month"] == MONTH
][["dealer_id", "target_units"]]


# Join September sales with September targets.
# validate="one_to_one" confirms that each dealer appears only once
# on both sides of the merge.
performance = dealer_sales.merge(
    september_targets,
    on="dealer_id",
    validate="one_to_one",
)


# Add the dealer name for a more readable report.
performance = performance.merge(
    dealers[["dealer_id", "dealer_name"]],
    on="dealer_id",
    validate="one_to_one",
)


# Calculate each dealer's percentage of target achieved.
performance["achievement_pct"] = (
    performance["units_sold"]
    / performance["target_units"]
    * 100
)

# Round the percentage for display.
performance["achievement_pct"] = performance["achievement_pct"].round(1)


# Arrange the output columns in a business-friendly order.
performance = performance[
    [
        "dealer_id",
        "dealer_name",
        "units_sold",
        "target_units",
        "achievement_pct",
    ]
]


# Rank dealers from highest to lowest target achievement.
performance = performance.sort_values(
    "achievement_pct",
    ascending=False,
)


# Print the complete dealer performance report.
print(performance.to_string(index=False))


# Print dealers performing below the alert threshold.
print("\nDEALERS NEEDING ATTENTION (<80% OF TARGET)")
print("-" * 50)

needs_attention = performance[
    performance["achievement_pct"] < ALERT_THRESHOLD
]

print(
    needs_attention[
        ["dealer_name", "units_sold", "target_units", "achievement_pct"]
    ].to_string(index=False)
)