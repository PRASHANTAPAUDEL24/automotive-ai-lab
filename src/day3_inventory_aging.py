# Program: src/day3_inventory_aging.py
# Day 3: Inventory aging and months-of-supply analysis
# Author: Prashanta Paudel
# Purpose: Measure available inventory, aged stock, months of supply,
# and identify dealers with potential overstock risk.

import pandas as pd


# Load the inventory, dealer, and monthly sales datasets.
inventory = pd.read_csv("data/inventory_snapshot.csv")
dealers = pd.read_csv("data/dealers.csv")
sales = pd.read_csv("data/sales_monthly.csv")


# Analysis settings and business-rule thresholds.
MONTH = "2026-09"
AGED_DAYS = 90
MOS_THRESHOLD = 4
AGED_PCT_THRESHOLD = 30


# Available inventory = vehicles currently marked "In Stock".
# "In Transit" is not physically at the dealer yet.
# "Hold" is on the lot but not currently available for sale.
print("\nInventory status values:")
print(inventory["status"].value_counts())

in_stock = inventory[inventory["status"] == "In Stock"]


# Count available vehicles that have been in stock for more than 90 days.
aged_inventory = (
    in_stock[in_stock["days_in_stock"] > AGED_DAYS]
    .groupby("dealer_id", as_index=False)
    .agg(aged_units=("vin", "count"))
)


# Count all currently available vehicles by dealer.
available_units = (
    in_stock
    .groupby("dealer_id", as_index=False)
    .agg(available_units=("vin", "count"))
)


# Combine available inventory and aged inventory.
aging_summary = available_units.merge(
    aged_inventory,
    on="dealer_id",
    how="left",
    validate="one_to_one",
)


# Dealers with no aged vehicles receive an aged-unit count of zero.
aging_summary["aged_units"] = (
    aging_summary["aged_units"]
    .fillna(0)
    .astype(int)
)


# Calculate the percentage of available inventory that is aged.
aging_summary["aged_pct"] = (
    aging_summary["aged_units"]
    / aging_summary["available_units"]
    * 100
)


# Filter sales data to September 2026.
september_sales = sales[sales["month"] == MONTH]


# Aggregate September sales to one row per dealer.
sales_by_dealer = (
    september_sales
    .groupby("dealer_id", as_index=False)
    .agg(september_sales=("units_sold", "sum"))
)


# Combine inventory metrics with September sales.
inventory_summary = aging_summary.merge(
    sales_by_dealer,
    on="dealer_id",
    how="left",
    validate="one_to_one",
)


# Treat dealers with no September sales row as zero sales.
inventory_summary["september_sales"] = (
    inventory_summary["september_sales"]
    .fillna(0)
)


# If September sales are zero, months of supply is undefined/infinite.
# We use float("inf"), so the dealer is treated as a high-supply case.
inventory_summary["months_of_supply"] = inventory_summary.apply(
    lambda row: (
        float("inf")
        if row["september_sales"] == 0
        else row["available_units"] / row["september_sales"]
    ),
    axis=1,
)


# Add dealer names to the inventory summary.
inventory_summary = inventory_summary.merge(
    dealers[["dealer_id", "dealer_name"]],
    on="dealer_id",
    validate="one_to_one",
)


# Flag dealers with both high months of supply and high aged inventory.
inventory_summary["overstock_flag"] = (
    (inventory_summary["months_of_supply"] > MOS_THRESHOLD)
    & (inventory_summary["aged_pct"] > AGED_PCT_THRESHOLD)
)


# Keep only flagged dealers and rank them by months of supply.
flagged = inventory_summary[
    inventory_summary["overstock_flag"]
].copy()

flagged = flagged.sort_values(
    "months_of_supply",
    ascending=False,
)


# Round display columns after the risk logic has already been calculated.
flagged["aged_pct"] = flagged["aged_pct"].round(1)
flagged["months_of_supply"] = flagged["months_of_supply"].round(1)


# Print dealers that meet the inventory-risk rule.
print("\nOverstock candidates:")
print(
    flagged[
        [
            "dealer_id",
            "dealer_name",
            "available_units",
            "aged_units",
            "aged_pct",
            "september_sales",
            "months_of_supply",
        ]
    ].to_string(index=False)
)


# Print the number of dealers represented in the inventory summary.
print("Dealers_in_inventory_summary:", len(inventory_summary))


# Print the total number of available inventory rows.
print("\nIn-stock rows:")
print(len(in_stock))


# Calculate the average age of available inventory for each dealer.
average_age = (
    in_stock
    .groupby("dealer_id", as_index=False)
    .agg(avg_days_available=("days_in_stock", "mean"))
)

average_age["avg_days_available"] = (
    average_age["avg_days_available"].round(1)
)


# Add dealer names to the average-age report.
average_age = average_age.merge(
    dealers[["dealer_id", "dealer_name"]],
    on="dealer_id",
    validate="one_to_one",
)

average_age = average_age[
    ["dealer_id", "dealer_name", "avg_days_available"]
]


# Rank dealers from oldest to youngest average available inventory.
average_age = average_age.sort_values(
    "avg_days_available",
    ascending=False,
)


# Print the five dealers with the oldest average available inventory.
print("\nTop 5 dealers by average available inventory age")
print(average_age.head(5).to_string(index=False))
