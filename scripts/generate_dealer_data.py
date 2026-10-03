"""
Synthetic automotive dealer dataset generator.

All data is FAKE: invented dealers, a fictional brand ("Vertex Motors"),
and randomly generated numbers. Safe to publish on GitHub.

Usage:
    python generate_dealer_data.py            # clean data (good for Week 1)
    python generate_dealer_data.py --messy    # adds realistic data-quality problems
    python generate_dealer_data.py --seed 7   # different random dataset

Outputs (CSV, written to ./data/):
    dealers.csv             one row per dealer
    vehicle_models.csv      model catalog with MSRP
    sales_monthly.csv       units sold per dealer / model / month
    dealer_targets.csv      monthly unit target per dealer
    leads_monthly.csv       leads and test drives per dealer / month
    inventory_snapshot.csv  one row per vehicle in stock on the snapshot date
"""

import argparse
import os

import numpy as np
import pandas as pd

# ---------------------------------------------------------------- config
N_DEALERS = 40
START_MONTH = "2024-10-01"
N_MONTHS = 24                      # Oct 2024 .. Sep 2026
SNAPSHOT_DATE = pd.Timestamp("2026-09-30")

REGIONS = {
    "Northeast": ["PA", "NY", "NJ", "MA", "CT"],
    "Southeast": ["FL", "GA", "NC", "SC", "TN"],
    "Midwest":   ["OH", "IL", "MI", "IN", "WI"],
    "Southwest": ["TX", "AZ", "NM", "OK"],
    "West":      ["CA", "WA", "OR", "NV", "CO"],
}

# model, segment, MSRP, base monthly demand weight
MODELS = [
    ("Aria",     "Compact Sedan",  24500, 1.00),
    ("Brisa",    "Midsize Sedan",  29900, 0.80),
    ("Cirrus",   "Compact SUV",    31500, 1.30),
    ("Dune",     "Midsize SUV",    38900, 1.10),
    ("Everest",  "Full-size SUV",  52500, 0.50),
    ("Flux EV",  "Electric SUV",   47900, 0.45),
    ("Granite",  "Pickup Truck",   43500, 0.75),
    ("Harbor",   "Hybrid Sedan",   32900, 0.60),
]

DEALER_WORDS = ["Summit", "Lakeside", "Riverbend", "Crossroads", "Heritage",
                "Metro", "Valley", "Pioneer", "Northgate", "Sunset", "Ridgeway",
                "Harbor View", "Oakwood", "Cedar Point", "Westfield", "Eastside"]
CITIES = ["Pittsburgh", "Erie", "Columbus", "Atlanta", "Tampa", "Charlotte",
          "Dallas", "Phoenix", "Denver", "Seattle", "Portland", "Sacramento",
          "Chicago", "Detroit", "Nashville", "Boston", "Hartford", "Albany",
          "Newark", "Milwaukee", "Austin", "Tulsa", "Las Vegas", "Orlando"]


def make_dealers(rng):
    rows = []
    region_names = list(REGIONS)
    for i in range(1, N_DEALERS + 1):
        region = region_names[(i - 1) % len(region_names)]
        state = rng.choice(REGIONS[region])
        size = rng.choice(["Small", "Medium", "Large"], p=[0.30, 0.45, 0.25])
        size_factor = {"Small": 0.6, "Medium": 1.0, "Large": 1.7}[size]
        # hidden behavior used to build the data; kept out of the CSV on purpose
        trend = rng.choice(["growing", "stable", "declining"], p=[0.25, 0.50, 0.25])
        overstock = rng.random() < 0.20
        rows.append({
            "dealer_id": 100 + i,
            "dealer_name": f"{rng.choice(DEALER_WORDS)} Vertex {rng.choice(['Motors', 'Auto', 'Automotive'])}",
            "city": rng.choice(CITIES),
            "state": state,
            "region": region,
            "size_class": size,
            "opened_year": int(rng.integers(1985, 2022)),
            "_size_factor": size_factor,
            "_trend": trend,
            "_overstock": overstock,
        })
    return pd.DataFrame(rows)


# City/state pairs that actually belong together, grouped by region.
REGION_CITIES = {
    "Northeast": [("Pittsburgh", "PA"), ("Erie", "PA"), ("Philadelphia", "PA"), ("Albany", "NY"),
                  ("Buffalo", "NY"), ("Newark", "NJ"), ("Boston", "MA"), ("Hartford", "CT"),
                  ("Worcester", "MA"), ("Syracuse", "NY")],
    "Southeast": [("Tampa", "FL"), ("Orlando", "FL"), ("Jacksonville", "FL"), ("Atlanta", "GA"),
                  ("Savannah", "GA"), ("Charlotte", "NC"), ("Raleigh", "NC"), ("Greenville", "SC"),
                  ("Charleston", "SC"), ("Nashville", "TN")],
    "Midwest":   [("Columbus", "OH"), ("Cleveland", "OH"), ("Chicago", "IL"), ("Springfield", "IL"),
                  ("Detroit", "MI"), ("Grand Rapids", "MI"), ("Indianapolis", "IN"),
                  ("Milwaukee", "WI"), ("Madison", "WI"), ("Fort Wayne", "IN")],
    "Southwest": [("Dallas", "TX"), ("Austin", "TX"), ("Houston", "TX"), ("Phoenix", "AZ"),
                  ("Tucson", "AZ"), ("Albuquerque", "NM"), ("Tulsa", "OK"),
                  ("Oklahoma City", "OK"), ("San Antonio", "TX"), ("Santa Fe", "NM")],
    "West":      [("Los Angeles", "CA"), ("Sacramento", "CA"), ("San Diego", "CA"), ("Seattle", "WA"),
                  ("Portland", "OR"), ("Las Vegas", "NV"), ("Denver", "CO"), ("Spokane", "WA"),
                  ("Reno", "NV"), ("Boulder", "CO")],
}


def fix_locations(dealers, seed):
    """Give every dealer a real city/state pair within its region and a unique name.

    Uses its own random generator so the sales, targets, leads and inventory
    data are NOT affected by this step.
    """
    loc_rng = np.random.default_rng(seed + 1000)
    dealers = dealers.copy()
    for region, group in dealers.groupby("region"):
        pairs = REGION_CITIES[region]
        picks = loc_rng.choice(len(pairs), size=len(group), replace=False)
        for idx, pick in zip(group.index, picks):
            city, state = pairs[pick]
            word = loc_rng.choice(DEALER_WORDS)
            suffix = loc_rng.choice(["Motors", "Auto", "Automotive"])
            dealers.at[idx, "city"] = city
            dealers.at[idx, "state"] = state
            dealers.at[idx, "dealer_name"] = f"{city} {word} Vertex {suffix}"
    return dealers


def seasonality(month):
    # spring and year-end peaks, summer/winter dips
    return {1: 0.80, 2: 0.85, 3: 1.05, 4: 1.10, 5: 1.10, 6: 1.05,
            7: 0.95, 8: 0.95, 9: 1.00, 10: 1.00, 11: 1.10, 12: 1.20}[month]


def make_sales_targets_leads(rng, dealers):
    months = pd.date_range(START_MONTH, periods=N_MONTHS, freq="MS")
    sales, targets, leads = [], [], []

    for _, d in dealers.iterrows():
        base_monthly = 28 * d["_size_factor"]          # total units / month at average
        for t, m in enumerate(months):
            drift = {"growing": 0.012, "stable": 0.0, "declining": -0.018}[d["_trend"]]
            trend_mult = (1 + drift) ** t
            season = seasonality(m.month)
            month_total = base_monthly * trend_mult * season

            month_units = 0
            for model, segment, msrp, weight in MODELS:
                # regional preference nudges
                pref = 1.0
                if segment == "Pickup Truck" and d["region"] in ("Southwest", "Midwest"):
                    pref = 1.5
                if segment == "Electric SUV" and d["region"] == "West":
                    pref = 1.8
                if segment == "Electric SUV" and d["region"] == "Southeast":
                    pref = 0.6
                lam = month_total * (weight / sum(w for *_, w in MODELS)) * pref
                units = int(rng.poisson(max(lam, 0.1)))
                month_units += units
                if units > 0:
                    discount = rng.normal(0.04, 0.015)          # avg discount off MSRP
                    price = round(msrp * (1 - max(discount, 0)) * rng.normal(1.0, 0.01), 0)
                else:
                    price = np.nan
                sales.append({
                    "dealer_id": d["dealer_id"],
                    "month": m.strftime("%Y-%m"),
                    "model": model,
                    "units_sold": units,
                    "avg_sale_price": price,
                })

            # targets: set a bit optimistically vs. a stable baseline
            target = int(round(base_monthly * season * 1.05 * (1 + 0.004 * t)))
            targets.append({"dealer_id": d["dealer_id"], "month": m.strftime("%Y-%m"),
                            "target_units": target})

            # leads: loosely tied to sales, conversion around 12-18%
            conv = rng.uniform(0.12, 0.18)
            n_leads = int(max(month_units / conv + rng.normal(0, 4), 5))
            drives = int(n_leads * rng.uniform(0.30, 0.45))
            leads.append({"dealer_id": d["dealer_id"], "month": m.strftime("%Y-%m"),
                          "leads": n_leads, "test_drives": drives})

    return pd.DataFrame(sales), pd.DataFrame(targets), pd.DataFrame(leads)


def make_inventory(rng, dealers, sales):
    # recent run-rate per dealer/model from the last 3 months
    recent = sales[sales["month"] >= "2026-07"].groupby(["dealer_id", "model"])["units_sold"].mean()
    rows, vin_counter = [], 1
    for _, d in dealers.iterrows():
        for model, segment, msrp, weight in MODELS:
            run_rate = recent.get((d["dealer_id"], model), 0.5)
            months_supply = rng.uniform(1.0, 2.5)
            if d["_overstock"]:
                months_supply = rng.uniform(4.0, 8.0)       # overstocked dealers
            elif d["_trend"] == "declining":
                months_supply *= 1.6
            n_units = int(round(run_rate * months_supply))
            for _ in range(n_units):
                age = int(min(rng.gamma(shape=2.0, scale=22.0 if not d["_overstock"] else 40.0), 400))
                received = SNAPSHOT_DATE - pd.Timedelta(days=age)
                rows.append({
                    "vin": f"VTX{vin_counter:08d}",
                    "dealer_id": d["dealer_id"],
                    "model": model,
                    "trim": rng.choice(["Base", "Sport", "Limited"], p=[0.45, 0.35, 0.20]),
                    "color": rng.choice(["White", "Black", "Silver", "Blue", "Red", "Gray"]),
                    "msrp": msrp,
                    "received_date": received.strftime("%Y-%m-%d"),
                    "days_in_stock": age,
                    "status": rng.choice(["In Stock", "In Transit", "Hold"], p=[0.88, 0.09, 0.03]),
                })
                vin_counter += 1
    return pd.DataFrame(rows)


def add_mess(rng, sales, inventory, dealers):
    """Optional realistic data-quality problems for practice."""
    sales = sales.copy()
    inventory = inventory.copy()
    dealers = dealers.copy()

    # missing prices on some rows that DO have units sold
    idx = sales[sales["units_sold"] > 0].sample(frac=0.015, random_state=1).index
    sales.loc[idx, "avg_sale_price"] = np.nan
    # duplicate rows
    sales = pd.concat([sales, sales.sample(frac=0.01, random_state=2)], ignore_index=True)
    # inconsistent model spelling
    idx = sales.sample(frac=0.01, random_state=3).index
    sales.loc[idx, "model"] = sales.loc[idx, "model"].str.lower()
    # impossible negative units (returns booked wrong)
    idx = sales.sample(n=6, random_state=4).index
    sales.loc[idx, "units_sold"] = -sales.loc[idx, "units_sold"].abs() - 1
    # missing dates / bad status labels in inventory
    idx = inventory.sample(frac=0.01, random_state=5).index
    inventory.loc[idx, "received_date"] = np.nan
    idx = inventory.sample(frac=0.02, random_state=6).index
    inventory.loc[idx, "status"] = "in stock "
    # mixed state formatting
    idx = dealers.sample(n=3, random_state=7).index
    dealers.loc[idx, "state"] = dealers.loc[idx, "state"].str.lower()
    return sales, inventory, dealers


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--messy", action="store_true", help="inject data-quality problems")
    ap.add_argument("--out", default="data")
    args = ap.parse_args()

    rng = np.random.default_rng(args.seed)
    os.makedirs(args.out, exist_ok=True)

    dealers = make_dealers(rng)
    sales, targets, leads = make_sales_targets_leads(rng, dealers)
    inventory = make_inventory(rng, dealers, sales)
    models = pd.DataFrame(MODELS, columns=["model", "segment", "msrp", "_w"]).drop(columns="_w")
    dealers = fix_locations(dealers, args.seed)

    if args.messy:
        sales, inventory, dealers_out = add_mess(rng, sales, inventory, dealers)
    else:
        dealers_out = dealers

    public_dealers = dealers_out[[c for c in dealers_out.columns if not c.startswith("_")]]

    public_dealers.to_csv(f"{args.out}/dealers.csv", index=False)
    models.to_csv(f"{args.out}/vehicle_models.csv", index=False)
    sales.to_csv(f"{args.out}/sales_monthly.csv", index=False)
    targets.to_csv(f"{args.out}/dealer_targets.csv", index=False)
    leads.to_csv(f"{args.out}/leads_monthly.csv", index=False)
    inventory.to_csv(f"{args.out}/inventory_snapshot.csv", index=False)

    print(f"Wrote dataset to ./{args.out}/  (seed={args.seed}, messy={args.messy})")
    for name, df in [("dealers", public_dealers), ("vehicle_models", models),
                     ("sales_monthly", sales), ("dealer_targets", targets),
                     ("leads_monthly", leads), ("inventory_snapshot", inventory)]:
        print(f"  {name:20s} {len(df):>6,} rows")


if __name__ == "__main__":
    main()
