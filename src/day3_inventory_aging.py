import pandas as pd

inventory = pd.read_csv("data/inventory_snapshot.csv")
dealers = pd.read_csv("data/dealers.csv")
sales = pd.read_csv("data/sales_monthly.csv")


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

aged_inventory = (
    in_stock[in_stock["days_in_stock"] > AGED_DAYS]
    .groupby("dealer_id", as_index=False)
    .agg(aged_units=("vin", "count"))
)

available_units = (
    in_stock
    .groupby("dealer_id", as_index=False)
    .agg(available_units=("vin","count"))
)

aging_summary = available_units.merge(
    aged_inventory,
    on="dealer_id",
    how="left",
    validate="one_to_one"
)

aging_summary["aged_units"] = (
    aging_summary["aged_units"]
    .fillna(0)
    .astype(int)
) 

aging_summary["aged_pct"] = (
    aging_summary["aged_units"]
    /aging_summary["available_units"]
    * 100
)

september_sales = sales[sales["month"] == MONTH]

sales_by_dealer = (
    september_sales
    .groupby("dealer_id", as_index=False)
    .agg(september_sales =("units_sold","sum"))
)

inventory_summary = aging_summary.merge(
    sales_by_dealer,
    on = "dealer_id",
    how = "left",
    validate = "one_to_one"
)

inventory_summary["september_sales"] = (
    inventory_summary["september_sales"]
    .fillna(0)
)

# If September sales are zero, months of supply is undefined/infinite.
# We use float("inf"), so the dealer is treated as serious stock-risk case.
inventory_summary["months_of_supply"] = inventory_summary.apply(
    lambda row: (
        float("inf")
        if row["september_sales"] == 0
        else row["available_units"] / row["september_sales"]
    ),
    axis=1
    )

inventory_summary = inventory_summary.merge(
    dealers[["dealer_id","dealer_name"]],
    on="dealer_id",
    validate="one_to_one"
)

inventory_summary["overstock_flag"] = (
    (inventory_summary["months_of_supply"] > MOS_THRESHOLD)
    & (inventory_summary["aged_pct"] > AGED_PCT_THRESHOLD)
)

flagged = inventory_summary[
    inventory_summary["overstock_flag"]
    ].copy()

flagged = flagged.sort_values(
    "months_of_supply",
    ascending=False
)

flagged["aged_pct"] = flagged["aged_pct"].round(1)
flagged["months_of_supply"] = flagged["months_of_supply"].round(1)


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
            "months_of_supply"
        ]
    ].to_string(index=False)
)


print("Dealers_in_inventory_summary:", len(inventory_summary))


print("\nIn-stock rows:")
print(len(in_stock))

average_age = (
    in_stock
    .groupby("dealer_id", as_index=False)
    .agg(avg_days_available=("days_in_stock", "mean"))
)

average_age["avg_days_available"] = (
    average_age["avg_days_available"].round(1)
)

average_age = average_age.merge(
    dealers[["dealer_id", "dealer_name"]],
    on="dealer_id",
    validate="one_to_one"  
)

average_age = average_age[
    ["dealer_id", "dealer_name", "avg_days_available"]
]

average_age = average_age.sort_values(
    "avg_days_available",
    ascending=False
)

print("\nTop 5 dealers by average available inventory age")
print(average_age.head(5).to_string(index=False))
