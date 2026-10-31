# Automotive AI Lab

Portfolio project building the data and analytics foundation for AI-powered
automotive dealer operations using a fully synthetic dataset for the fictional
brand **Vertex Motors**.

No real company data is used.

## Business Problem

Regional managers need to quickly identify underperforming dealers,
sales gaps, aging inventory, and potential stock risks.

This project starts with dealer analytics and progressively adds databases,
APIs, LLMs, RAG, agents, and cloud deployment.

## Dataset

Synthetic automotive data for 40 dealers across 24 months.

The dataset includes:

- Dealer information
- Vehicle models
- Monthly sales
- Dealer targets
- Monthly leads and test drives
- Inventory snapshot

## Progress

> “Day” labels represent project milestones rather than consecutive calendar days.

- [x] Day 1: September dealer performance vs. target using pandas
- [x] Day 2: Same analysis using plain Python and the `csv` module, with data-integrity checks
- [x] Day 3: Inventory aging, months of supply, and inventory-risk flags
- [x] Day 4: Combined dealer scorecard with sales and inventory risk flags
- [x] Day 5: PostgreSQL schema, CSV data load, and September dealer performance queries
- [x] Day 6: Inventory aging, months of supply, and inventory-risk analysis in PostgreSQL
- [x] Day 7: Combined dealer scorecard in PostgreSQL
- [x] Day 8: Read the PostgreSQL scorecard into pandas with SQLAlchemy and validate counts
- [x] Day 9: Reusable, parameterized scorecard queries in Python
- [x] Day 10: FastAPI health and dealer endpoints with safe filtering and automated tests
- [ ] Week 3: FastAPI
- [ ] Week 4: Automotive Dealer Analytics API
- [ ] Later: LLM APIs, RAG, agents, Docker, Azure

## Project Structure

- `scripts/generate_dealer_data.py` generates the synthetic dataset
- `data/` contains generated CSV files and the dealer scorecard output
- `src/` contains the analysis scripts, the reusable database module (`db.py`) and the FastAPI app (`api.py`)
- `sql/` contains the PostgreSQL schema, loader, and SQL analysis queries

## How to Run

Create and activate a virtual environment, then install dependencies:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Generate the synthetic dataset:

```bash
python scripts/generate_dealer_data.py --out data
```

Run the analyses:

```bash
python src/day1_dealer_performance.py
python src/day2_python_basics.py
python src/day2_dealer_totals.py
python src/day3_inventory_aging.py
python src/day4_dealer_scorecard.py
```

Day 4 generates:

```text
data/dealer_scorecard.csv
```

## PostgreSQL

Run the schema first, then the loader, in that order.

> Re-running `sql/01_schema.sql` resets the database because it drops and recreates the tables.

```bash
psql automotive_ai_lab -f sql/01_schema.sql
psql automotive_ai_lab -f sql/02_load.sql
psql automotive_ai_lab -f sql/03_views.sql
psql -P pager=off automotive_ai_lab -f sql/day5_dealer_performance.sql
psql -P pager=off automotive_ai_lab -f sql/day5_dealer_status_cte.sql
psql -P pager=off automotive_ai_lab -f sql/day6_inventory_aging.sql
psql -P pager=off automotive_ai_lab -f sql/day7_dealer_scorecard.sql
```

Export the SQL flags and compare them with the Day 4 pandas scorecard. Run `src/day4_dealer_scorecard.py` first so `data/dealer_scorecard.csv` exists.

```bash
psql automotive_ai_lab -c "\copy (SELECT dealer_id, sales_risk, inventory_risk, combined_risk, early_overstock_watch FROM dealer_scorecard ORDER BY dealer_id) TO 'data/dealer_scorecard_sql.csv' CSV HEADER"
python src/day7_compare_scorecards.py
```

## Python and PostgreSQL

Set the PostgreSQL connection string in the environment before running Day 8:

```bash
export DATABASE_URL="postgresql+psycopg://<user>@localhost:5432/automotive_ai_lab"
python src/day8_read_scorecard.py
```

Run the parameterized query tests:

```bash
python src/day9_query_scorecard.py
```

## API

With the virtual environment active, set the database connection:

```bash
export DATABASE_URL="postgresql+psycopg://<user>@localhost:5432/automotive_ai_lab"
```

The `export` only lasts for the current terminal window, so run it again in each new terminal.

The PostgreSQL database must be built first (see the PostgreSQL section above).

Run the API tests:

```bash
python src/day10_test_api.py
```

Start the API (press Ctrl+C to stop it):

```bash
uvicorn api:app --reload --app-dir src
```

Interactive documentation is available at http://127.0.0.1:8000/docs.

| Endpoint | Description |
|---|---|
| `GET /health` | Confirms the API is running |
| `GET /dealers` | Returns the dealer scorecard. Optional filters: `region` (for example `West`) and `risk` (`sales_risk`, `inventory_risk`, `combined_risk` or `early_overstock_watch`) |

Example:

```bash
curl "http://127.0.0.1:8000/dealers?region=West&risk=early_overstock_watch"
```

An unsupported `risk` value returns HTTP 400. An unknown `region` returns an empty list.

## Definitions

- **Available inventory:** vehicles with status `"In Stock"`; excludes `In Transit` and `Hold`
- **Aged inventory:** available vehicles with more than 90 days in stock
- **Months of supply:** available units divided by September units sold. If both are zero, months of supply is 0.
- **Zero-sales inventory rule:** if a dealer has available inventory but zero September sales, months of supply is undefined (`NULL` in SQL, infinity in Python) and the dealer is treated as high supply. It is flagged as inventory-risk only if more than 30% of its available units are also aged. No dealer in the current dataset triggers this case.
- **Sales risk:** achievement below 80% of the September sales target
- **Inventory risk:** more than 4 months of supply and more than 30% aged inventory
- **Combined risk:** both sales risk and inventory risk
- **Early overstock watch:** sales risk and more than 4 months of supply, but not yet inventory risk

## Key Findings

For September 2026 synthetic data:

- 12 of 40 dealers are classified as sales-risk.
- 9 dealers meet the inventory-risk rule.
- 1 dealer, Buffalo Sunset Vertex Automotive, has both sales risk and inventory risk.
- 3 additional dealers are on the early-overstock watch list: Orlando, San Diego, and Seattle.
- 8 inventory-risk dealers are not sales-risk; in this dataset, all 8 are at or above 100% of their September target.
- Inventory-risk dealers are 5 Medium, 2 Large, and 2 Small, compared with a network mix of 20 Medium, 10 Large, and 10 Small.
- Dealer size does not appear to explain inventory risk in this dataset.

## Validation

The PostgreSQL scorecard was cross-checked against the Day 4 pandas scorecard. All four risk flags matched for all 40 dealers.

## Limitations

- All data is synthetic, so the findings demonstrate the analytical method, not real-world conclusions.
- Months of supply currently uses September sales only.
- The 80%, 90-day, 4-month, and 30% thresholds are business-rule assumptions and should be validated and tuned with stakeholders in a real deployment.
- PostgreSQL views are currently fixed to September 2026; future API work will need month-parameterized logic.

## Planned Projects

- **Dealer Analytics API:** expose dealer performance and inventory-risk metrics through an API.
- **Supply Chain Risk Assistant:** analyze sourcing, inventory, logistics, and supplier risks.
- **Dealer Operations Copilot:** combine structured dealer data with LLM-based decision support.
