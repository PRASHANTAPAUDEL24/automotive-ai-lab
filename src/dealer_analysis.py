import pandas as pd

sales = pd.read_csv("data/sales_monthly.csv")
targets = pd.read_csv("data/dealer_targets.csv")
dealers = pd.read_csv("data/dealers.csv")

september_sales = sales[sales["month"] == "2026-09"]

dealer_sales = (
    september_sales.groupby("dealer_id", as_index=False)["units_sold"]
    .sum()
    )

september_targets = targets[
    targets["month"] == "2026-09"
][["dealer_id", "target_units"]]

performance = dealer_sales.merge(
    september_targets,
    on="dealer_id"
)

performance = performance.merge(
    dealers[["dealer_id", "dealer_name"]],
    on="dealer_id"
)

performance["achievement_pct"] = (
    performance["units_sold"]
    / performance["target_units"]
    * 100
)
performance["achievement_pct"] = performance["achievement_pct"].round(1)

performance = performance[
    [
        "dealer_id",
        "dealer_name",
        "units_sold",
        "target_units",
        "achievement_pct"
    ]
]

performance = performance.sort_values(
    "achievement_pct",
    ascending=False
)

print(performance.to_string(index=False))

performance["achievement_pct"] = performance["achievement_pct"].round(1)

print("\nDEALERS NEEDING ATTENTION (<80% OF TARGET)")
print("-" * 50)

needs_attention = performance[
    performance["achievement_pct"] < 80
]

print(
    needs_attention[
        ["dealer_name", "units_sold", "target_units", "achievement_pct"]
    ].to_string(index=False)
)