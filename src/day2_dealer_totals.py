# Program: src/day2_dealer_totals.py
# Day 2: Dealer performance using plain Python and csv
# Author: Prashanta Paudel
# Purpose: Reproduce the dealer performance analysis without pandas
# and add simple data-integrity checks.

import csv


# Analysis settings.
MONTH = "2026-09"
ATTENTION_THRESHOLD = 80
TARGET_ACHIEVED = 100


# Calculate target achievement percentage.
# Return None when no valid target is available.
def calculate_achievement(sales, target):
    if target == 0:
        return None

    return sales / target * 100


# Convert the achievement percentage into a business status.
def get_performance_status(achievement):
    if achievement is None:
        return "No target set"
    elif achievement < ATTENTION_THRESHOLD:
        return "Needs attention"
    elif achievement < TARGET_ACHIEVED:
        return "Below target"
    else:
        return "Target achieved"


# Load a CSV file as a list of dictionaries.
def load_csv(path):
    with open(path, newline="") as file:
        return list(csv.DictReader(file))


# Load the sales, target, and dealer reference datasets.
sales_rows = load_csv("data/sales_monthly.csv")
target_rows = load_csv("data/dealer_targets.csv")
dealer_rows = load_csv("data/dealers.csv")


# Aggregate sales for the selected month by dealer.
sales_by_dealer = {}

for row in sales_rows:
    if row["month"] == MONTH:
        dealer_id = row["dealer_id"]
        units = int(row["units_sold"])

        if dealer_id not in sales_by_dealer:
            sales_by_dealer[dealer_id] = 0

        sales_by_dealer[dealer_id] += units


# Build a lookup dictionary for September dealer targets.
targets_by_dealer = {}

for row in target_rows:
    if row["month"] == MONTH:
        dealer_id = row["dealer_id"]
        targets_by_dealer[dealer_id] = int(row["target_units"])


# Build a lookup dictionary for dealer names.
names_by_dealer = {}

for row in dealer_rows:
    dealer_id = row["dealer_id"]
    names_by_dealer[dealer_id] = row["dealer_name"]


# Print dealer-level performance and count dealers needing attention.
print("\nDealer Performance:")

attention_count = 0

for dealer_id, name in names_by_dealer.items():
    sales = sales_by_dealer.get(dealer_id, 0)
    target = targets_by_dealer.get(dealer_id, 0)

    achievement = calculate_achievement(sales, target)
    status = get_performance_status(achievement)

    if status == "Needs attention":
        attention_count += 1

    if achievement is None:
        print(f"{name}: No target set - {status}")
    else:
        print(f"{name}: {achievement:.1f}% - {status}")


# Print the total number of dealers below the attention threshold.
print(f"\nDealers needing attention: {attention_count}")


# Data-integrity check:
# identify any dealer IDs found in sales data but missing from dealers.csv.
unknown = set(sales_by_dealer) - set(names_by_dealer)

print(
    "Dealer IDs in sales but not in dealers.csv:",
    unknown,
)
