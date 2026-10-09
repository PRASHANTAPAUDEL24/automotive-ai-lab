# Program: src/day4_dealer_scorecard.py
# Created on: 2026-10-08
# Author: Prashanta Paudel
# Purpose: Build a combined dealer scorecard using sales performance
# and inventory-risk metrics.

import pandas as pd
import numpy as np

# Business-rule thresholds
MONTH = "2026-09"
ATTENTION_THRESHOLD = 80
AGED_DAYS = 90
MOS_THRESHOLD = 4
AGED_PCT_THRESHOLD = 30

# Load dealer master, sales, targets, and inventory data.
dealers = pd.read_csv("data/dealers.csv")
sales = pd.read_csv("data/sales_monthly.csv")
targets = pd.read_csv("data/dealer_targets.csv")
inventory = pd.read_csv("data/inventory_snapshot.csv")

# ---- Sales performance ----

# Aggregate September sales to one row per dealer.
september_sales = sales[sales["month"] == MONTH]

sales_by_dealer = (
    september_sales
    .groupby("dealer_id", as_index=False)
    .agg(units_sold=("units_sold", "sum"))
)

# Keep September targets only.
september_targets = targets[
    targets["month"] == MONTH
][["dealer_id", "target_units"]]

# Start from the dealer master so dealers with zero sales
# are not silently dropped from the scorecard.
sales_summary = dealers[
    ["dealer_id", "dealer_name", "region", "size_class"]
].merge(
    sales_by_dealer,
    on="dealer_id",
    how="left",
    validate="one_to_one"
)

sales_summary = sales_summary.merge(
    september_targets,
    on="dealer_id",
    how="left",
    validate="one_to_one"
)

sales_summary["units_sold"] = sales_summary["units_sold"].fillna(0)
sales_summary["target_units"] = sales_summary["target_units"].fillna(0)

sales_summary["achievement_pct"] = (
    sales_summary["units_sold"]
    / sales_summary["target_units"].replace(0, np.nan)
    * 100
)

print("Dealer count:", len(sales_summary))


# ---- Inventory risk ----

# Available inventory includes only vehicles marked "In Stock".
# "In Transit" is excluded because it is not yet physically at the dealer.
# "Hold" is excluded because those units are not currently available for sale.
in_stock = inventory[inventory["status"] == "In Stock"]

# Count available units and units aged more than 90 days.
available_units = (
    in_stock
    .groupby("dealer_id", as_index=False)
    .agg(available_units=("vin", "count"))
)

aged_units = (
    in_stock[in_stock["days_in_stock"] > AGED_DAYS]
    .groupby("dealer_id", as_index=False)
    .agg(aged_units=("vin", "count"))
)

# Start from the full dealer list so dealers with zero available inventory
# remain visible in the analysis.
inventory_summary = dealers[
    ["dealer_id"]
].merge(
    available_units,
    on="dealer_id",
    how="left",
    validate="one_to_one"
)

inventory_summary = inventory_summary.merge(
    aged_units,
    on="dealer_id",
    how="left",
    validate="one_to_one"
)

inventory_summary["available_units"] = (
    inventory_summary["available_units"].fillna(0)
)

inventory_summary["aged_units"] = (
    inventory_summary["aged_units"]
    .fillna(0)
    .astype(int)
)


# Aged percentage measures how much of currently available inventory
# has been in stock for more than 90 days.
inventory_summary["aged_pct"] = (
    inventory_summary["aged_units"]
    / inventory_summary["available_units"]
    * 100
)

inventory_summary["aged_pct"] = (
    inventory_summary["aged_pct"].fillna(0)
)


# Months of supply estimates how long current available inventory would last
# at the dealer's September sales pace.
inventory_summary = inventory_summary.merge(
    sales_by_dealer,
    on="dealer_id",
    how="left",
    validate="one_to_one"
)

inventory_summary["units_sold"] = (
    inventory_summary["units_sold"].fillna(0)
)


# Business rule for zero-sales cases:
# - zero stock and zero sales -> 0 months of supply
# - inventory exists but sales are zero -> infinite months of supply
inventory_summary["months_of_supply"] = inventory_summary.apply(
    lambda row: (
        0
        if row["available_units"] == 0 and row["units_sold"] == 0
        else float("inf")
        if row["units_sold"] == 0
        else row["available_units"] / row["units_sold"]
    ),
    axis=1
)


# ---- Combined dealer scorecard ----
scorecard = sales_summary.merge(
    inventory_summary[
        [
            "dealer_id",
            "available_units",
            "aged_units",
            "aged_pct",
            "months_of_supply"
        ]
    ],
    on="dealer_id",
    how="left",
    validate="one_to_one"
)


# Missing targets are tracked separately so they do not silently
# appear as healthy sales performance.
scorecard["missing_target"] = scorecard["target_units"] == 0


# Sales risk = dealer achieves less than 80% of monthly target.
scorecard["sales_risk"] = (
    (~scorecard["missing_target"])
    & (scorecard["achievement_pct"] < ATTENTION_THRESHOLD)
)


# Inventory risk = more than 4 months of supply
# AND more than 30% of available inventory aged over 90 days.
scorecard["inventory_risk"] = (
    (scorecard["months_of_supply"] > MOS_THRESHOLD)
    & (scorecard["aged_pct"] > AGED_PCT_THRESHOLD)
)


# Combined risk identifies dealers with both weak sales
# and a confirmed inventory-aging problem.
scorecard["combined_risk"] = (
    scorecard["sales_risk"]
    & scorecard["inventory_risk"]
)


# Early warning identifies dealers with weak sales and high stock levels
# before their aged-inventory percentage crosses the full-risk threshold.
scorecard["early_overstock_watch"] = (
    scorecard["sales_risk"]
    & (scorecard["months_of_supply"] > MOS_THRESHOLD)
    & ~scorecard["inventory_risk"]
)


# Round only for presentation after all risk decisions are calculated.
scorecard["achievement_pct"] = scorecard["achievement_pct"].round(1)
scorecard["aged_pct"] = scorecard["aged_pct"].round(1)
scorecard["months_of_supply"] = scorecard["months_of_supply"].round(1)

# ---- Management output ----

# Sort the most urgent dealers to the top:
# combined risk first, then inventory risk, then sales risk.
management_view = scorecard[
    [
        "dealer_id",
        "dealer_name",
        "region",
        "size_class",
        "units_sold",
        "target_units",
        "achievement_pct",
        "available_units",
        "aged_units",
        "aged_pct",
        "months_of_supply",
        "sales_risk",
        "inventory_risk",
        "combined_risk",
        "early_overstock_watch",
        "missing_target"
    ]
]

management_view = management_view.sort_values(
    [
        "combined_risk",
        "inventory_risk",
        "sales_risk",
        "months_of_supply"
    ],
    ascending=[False, False, False, False]
)

management_view.to_csv(
    "data/dealer_scorecard.csv",
    index=False
)

print("\nInventory-risk but not sales-risk:")
print(
    management_view[
        management_view["inventory_risk"]
        & ~management_view["sales_risk"]
    ].to_string(index=False)
)

print("\nBehind target without full inventory-risk flag:")
print(
    management_view[
        management_view["sales_risk"]
        & ~management_view["inventory_risk"]
    ].to_string(index=False)
)

print("\nEarly overstock watch:")
print(
    management_view[
        management_view["early_overstock_watch"]
    ].to_string(index=False)
)

print("\nInventory-risk dealers by size class:")
print(
    scorecard.groupby("size_class")["inventory_risk"].sum()
)

print("\nAll dealers by size class:")
print(
    scorecard["size_class"].value_counts()
)

print("\nDealer scorecard:")
print(management_view.to_string(index=False))

print("\nCombined-risk dealers:")
print(
    management_view[
        management_view["combined_risk"]
    ].to_string(index=False)
)

print("\nRisk summary:")
print("Sales-risk dealers:", scorecard["sales_risk"].sum())
print("Inventory-risk dealers:", scorecard["inventory_risk"].sum())
print("Combined-risk dealers:", scorecard["combined_risk"].sum())

print("Early-watch dealers:", scorecard["early_overstock_watch"].sum())
print(
    "Inventory-risk but not sales-risk:",
    (
        scorecard["inventory_risk"]
        & ~scorecard["sales_risk"]
    ).sum()
)

print(
    "Behind target without full inventory-risk flag:",
    (
        scorecard["sales_risk"]
        & ~scorecard["inventory_risk"]
    ).sum()
)