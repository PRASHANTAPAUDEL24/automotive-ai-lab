# Program: src/day8_read_scorecard.py
# Created on: 2026-10-26 (Day 8)
# Author: Prashanta Paudel
# Purpose: Read the PostgreSQL dealer scorecard into pandas
# and validate the key business-risk counts.


import os

import pandas as pd
from sqlalchemy import create_engine

# Read the PostgreSQL connection string from the environment.
database_url = os.getenv("DATABASE_URL")

if not database_url:
    raise ValueError(
        "DATABASE_URL is not set. Export it before running this script."
    )

# Create the database connection engine.
engine = create_engine(database_url)


# Load the reusable PostgreSQL dealer_scorecard view.
scorecard = pd.read_sql(
    "SELECT * FROM dealer_scorecard",
    engine
)

print("Rows loaded:", len(scorecard))


# Summarize the key business-risk flags.
sales_risk_count = scorecard["sales_risk"].sum()
inventory_risk_count = scorecard["inventory_risk"].sum()
combined_risk_count = scorecard["combined_risk"].sum()
early_watch_count = scorecard["early_overstock_watch"].sum()

print("Sales-risk dealers:", sales_risk_count)
print("Inventory-risk dealers:", inventory_risk_count)
print("Combined-risk dealers:", combined_risk_count)
print("Early-watch dealers:", early_watch_count)


# Validate that the business-risk flags never contain NULL values.
flag_cols = [
    "sales_risk",
    "inventory_risk",
    "combined_risk",
    "early_overstock_watch",
]

assert not scorecard[flag_cols].isna().any().any(), (
    "Flag columns must never be NULL"
)

# Validate the expected Day 7 scorecard results.
assert len(scorecard) == 40, (
    f"Expected 40 dealers, got {len(scorecard)}"
)

assert scorecard["dealer_id"].nunique() == 40, (
    f"Expected 40 unique dealer IDs, "
    f"got {scorecard['dealer_id'].nunique()}"
)

assert sales_risk_count == 12, (
    f"Expected 12 sales-risk dealers, got {sales_risk_count}"
)

assert inventory_risk_count == 9, (
    f"Expected 9 inventory-risk dealers, got {inventory_risk_count}"
)

assert combined_risk_count == 1, (
    f"Expected 1 combined-risk dealer, got {combined_risk_count}"
)

assert early_watch_count == 3, (
    f"Expected 3 early-watch dealers, got {early_watch_count}"
)

print("Day 8 validation passed.")