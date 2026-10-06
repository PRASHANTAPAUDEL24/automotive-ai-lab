import csv

MONTH = "2026-09"
ATTENTION_THRESHOLD = 80
TARGET_ACHIEVED = 100

def calculate_achievement(sales, target):
    if target == 0:
        return None

    return sales / target * 100


def get_performance_status(achievement):
    if achievement is None:
        return "No target set"
    elif achievement < ATTENTION_THRESHOLD:
        return "Needs attention"
    elif achievement < TARGET_ACHIEVED:
        return "Below target"
    else:
        return "Target achieved"


def load_csv(path):
    with open(path, newline="") as file:
        return list(csv.DictReader(file))
        

sales_rows = load_csv("data/sales_monthly.csv")
target_rows = load_csv("data/dealer_targets.csv")
dealer_rows = load_csv("data/dealers.csv")



sales_by_dealer = {}

for row in sales_rows:
    if row["month"] == MONTH:
        dealer_id = row["dealer_id"]
        units = int(row["units_sold"])

        if dealer_id not in sales_by_dealer:
            sales_by_dealer[dealer_id] = 0

        sales_by_dealer[dealer_id] += units



target_by_dealer = {}

for row in target_rows:
    if row["month"] == MONTH:
        dealer_id = row["dealer_id"]
        target_by_dealer[dealer_id] = int(row["target_units"])


names_by_dealer = {}

for row in dealer_rows:
    dealer_id = row["dealer_id"]
    names_by_dealer[dealer_id] = row["dealer_name"]




print("\nDealer Performance:")
    
attention_count = 0

for dealer_id, name in names_by_dealer.items():
    sales = sales_by_dealer.get(dealer_id, 0)
    target = target_by_dealer.get(dealer_id, 0)

    achievement = calculate_achievement(sales, target)
    status = get_performance_status(achievement)

    if status == "Needs attention":
        attention_count += 1

    if achievement is None:
        print(f"{name}: No target set - {status}")
    else:
        print(f"{name}: {achievement:.1f}% - {status}")

print(f"\nDealers needing attention: {attention_count}")
