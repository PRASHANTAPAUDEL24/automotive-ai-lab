# Program: src/day7_compare_scorecards.py
# Created on: 2026-10-25 (Day 7)
# Author: Prashanta Paudel
# Purpose: Compare pandas and PostgreSQL dealer scorecard flags
# The goal is to confirm that both implementations produce
# the same business-risk classifications for all dealers.

import pandas as pd

# Load the Day 4 pandas scorecard and the Day 7 SQL export.
python_df = pd.read_csv("data/dealer_scorecard.csv")
sql_df = pd.read_csv("data/dealer_scorecard_sql.csv")


# These are the four business flags that should match exactly.
flag_cols = [
    "sales_risk",
    "inventory_risk",
    "combined_risk",
    "early_overstock_watch",
]

# PostgreSQL exports booleans through psql as "t" and "f".
# Convert them to Python True/False before comparing.
for col in flag_cols:
    sql_df[col] = sql_df[col].map({"t": True, "f": False})

# Merge both scorecards on dealer_id so each dealer can be
# compared directly across the pandas and SQL implementations.
merged = python_df[["dealer_id"] + flag_cols].merge(
    sql_df[["dealer_id"] + flag_cols],
    on="dealer_id",
    suffixes=("_python", "_sql"),
    how="outer",
    indicator=True,
)

# Compare each business flag separately.
for col in flag_cols:
    merged[f"{col}_match"] = (
        merged[f"{col}_python"] == merged[f"{col}_sql"]
    )

# A dealer matches only when all four flags are identical.
match_cols = [f"{col}_match" for col in flag_cols]
merged["all_flags_match"] = merged[match_cols].all(axis=1)

# Keep any dealer that is missing from one source or has
# at least one mismatched flag.
differences = merged[
    (merged["_merge"] != "both")
    | (~merged["all_flags_match"])
]

# Print the validation result.
print("Rows compared:", len(merged))
print("Rows with any flag difference:", len(differences))

if differences.empty:
    print("All four flags match for every dealer.")
else:
    print(differences.to_string(index=False))
