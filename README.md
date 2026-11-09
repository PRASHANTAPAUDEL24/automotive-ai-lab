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
- [x] Day 11: Pytest coverage for database queries and FastAPI endpoints
- [x] Day 12: Single-dealer API endpoint with 404/422 handling and NaN-safe records
- [x] Day 13: Pydantic `Dealer` response model with nullable-field handling, response validation, and OpenAPI documentation
- [x] Day 14: Region summary endpoint (`GET /regions/summary`) with SQL, database function, response model, and tests
- [x] Day 15: Ranked at-risk dealers endpoint (`GET /dealers/at-risk`) with SQL ranking, `RankedDealer` response model, optional `limit`, and tests
- [x] Day 16: Pinned dependencies, separate dev requirements, and a clean-clone install test
- [x] Day 17: Monthly dealer performance SQL view across 24 months, with September compatibility preserved
- [ ] Week 3: FastAPI
- [ ] Week 4: Automotive Dealer Analytics API
- [ ] Later: LLM APIs, RAG, agents, Docker, Azure

## Project Structure

- `scripts/generate_dealer_data.py` generates the synthetic dataset
- `data/` contains generated CSV files and the dealer scorecard output
- `src/` contains the analysis scripts, reusable database module (`db.py`), Pydantic response models (`models.py`), and FastAPI app (`api.py`)
- `sql/` contains the PostgreSQL schema, loader, views, and SQL analysis queries
- `tests/` contains pytest coverage for the database/query layer and FastAPI endpoints
- `pytest.ini` configures pytest discovery and adds `src/` to the Python import path
- `requirements.txt` pins the runtime dependencies; `requirements-dev.txt` adds the test and lint tools

## How to Run

This project was developed and tested with Python 3.12.7. Create and activate a virtual environment, then install the development dependencies:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
```

`requirements.txt` contains pinned runtime dependencies. `requirements-dev.txt` includes the runtime file and adds pytest, httpx2, Black, and Ruff for testing and development. To run only the analyses and the API, install `requirements.txt` instead.

If another Python environment (for example Conda) is also active, run tools through `python -m` (for example `python -m pytest`) so the virtual environment's copy is used.

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

`sql/03_views.sql` now creates `dealer_monthly_performance`, with one row per dealer and month for sales and target performance. The existing `dealer_performance` view remains a September 2026 compatibility view so the downstream inventory and scorecard logic is unchanged.

Export the SQL flags and compare them with the Day 4 pandas scorecard. Run `src/day4_dealer_scorecard.py` first so `data/dealer_scorecard.csv` exists.

```bash
psql automotive_ai_lab -c "\copy (SELECT dealer_id, sales_risk, inventory_risk, combined_risk, early_overstock_watch FROM dealer_scorecard ORDER BY dealer_id) TO 'data/dealer_scorecard_sql.csv' CSV HEADER"
python src/day7_compare_scorecards.py
```

## Python and PostgreSQL

Set the PostgreSQL connection string in the environment before running Python code that connects to PostgreSQL:

```bash
export DATABASE_URL="postgresql+psycopg://<user>@localhost:5432/automotive_ai_lab"
python src/day8_read_scorecard.py
```

## API

With the virtual environment active, set the database connection:

```bash
export DATABASE_URL="postgresql+psycopg://<user>@localhost:5432/automotive_ai_lab"
```

The `export` only lasts for the current terminal window, so run it again in each new terminal.

The PostgreSQL database must be built first (see the PostgreSQL section above).

Start the API (press Ctrl+C to stop it):

```bash
uvicorn api:app --reload --app-dir src
```

Interactive documentation is available at http://127.0.0.1:8000/docs.

| Endpoint | Description |
|---|---|
| `GET /health` | Confirms the API is running |
| `GET /dealers` | Returns the dealer scorecard. Optional filters: `region` (for example `West`) and `risk` (`sales_risk`, `inventory_risk`, `combined_risk` or `early_overstock_watch`) |
| `GET /dealers/{dealer_id}` | Returns one dealer scorecard. An unknown dealer id returns HTTP 404. A non-numeric id returns HTTP 422. |
| `GET /regions/summary` | Returns one row per region, ordered by region: dealer count and the number of sales-risk, inventory-risk, combined-risk and early-overstock-watch dealers |
| `GET /dealers/at-risk` | Returns the 20 sales-risk or inventory-risk dealers, ranked from most to least urgent. Optional `limit` (minimum 1) keeps the global ranks; `limit=0` or a non-integer returns 422 |

Example:

```bash
curl "http://127.0.0.1:8000/dealers?region=West&risk=early_overstock_watch"
```

An unsupported `risk` value returns HTTP 400. An unknown `region` returns an empty list.

### Response model

`GET /dealers` and `GET /dealers/{dealer_id}` return records validated by the `Dealer` model in `src/models.py`. All 17 fields are always present. Five can be `null`:

| Field | Null when |
|---|---|
| `target_units` | The dealer has no target row for the month |
| `achievement_pct` | The target is missing or zero |
| `avg_days_available` | The dealer has no available units |
| `aged_pct` | The dealer has no available units |
| `months_of_supply` | The dealer has stock but no sales that month |

If the data layer ever returns a value that does not match the model, the API returns HTTP 500 instead of sending malformed data. The schema is shown in the interactive docs at `/docs`.

`GET /regions/summary` returns `RegionSummary` records. All six fields are required and non-nullable. For example, the Northeast row has 8 dealers, 3 sales-risk, 2 inventory-risk, 1 combined-risk and 0 early-overstock-watch dealers.

`GET /dealers/at-risk` returns `RankedDealer` records: every `Dealer` field plus `rank` (1 is the most urgent dealer) and `risk_tier` (1 = combined risk, 2 = early overstock watch, 3 = sales risk only, 4 = inventory risk only). Dealers are ordered by risk tier, then months of supply (highest first, NULL first), then dealer ID as the tie-breaker. The optional `limit` applies after ranking, so `limit=5` returns ranks 1 to 5.

## Testing

The pytest suite includes integration tests for the reusable PostgreSQL query layer and FastAPI endpoints.

The PostgreSQL database, tables, data, and views must be built before running the integration tests.

Activate the virtual environment and set the database connection:

```bash
source .venv/bin/activate
export DATABASE_URL="postgresql+psycopg://<user>@localhost:5432/automotive_ai_lab"
```

Run the full test suite from the repository root:

```bash
pytest -v
```

The current test suite covers:

- database queries and expected business-rule results
- region and risk filtering
- combined filters
- API endpoints and response behavior
- single-dealer lookup by ID
- client and server error handling
- injection-safety checks
- JSON-safe missing-value conversion
- exact response field set for a dealer record
- null values accepted for the five nullable fields
- invalid data from the data layer returns HTTP 500
- region summary counts for every region, plus network totals
- ranked at-risk list: tier counts, continuous ranks, within-tier ordering, anchor positions and `limit` handling

## Definitions

- **Available inventory:** vehicles with status `"In Stock"`; excludes `In Transit` and `Hold`
- **Aged inventory:** available vehicles with more than 90 days in stock
- **Months of supply:** available units divided by September units sold. If both are zero, months of supply is 0.
- **Zero-sales inventory rule:** if a dealer has available inventory but zero September sales, months of supply is undefined (`NULL` in SQL, infinity in Python) and the dealer is treated as high supply. It is flagged as inventory-risk only if more than 30% of its available units are also aged. No dealer in the current dataset triggers this case.
- **Sales risk:** achievement below 80% of the September sales target
- **Inventory risk:** more than 4 months of supply and more than 30% aged inventory
- **Combined risk:** both sales risk and inventory risk
- **Early overstock watch:** sales risk and more than 4 months of supply, but not yet inventory risk
- **At-risk dealer:** a dealer with sales risk or inventory risk (20 of 40 in this dataset)
- **Risk tier:** the urgency group used to rank at-risk dealers: 1 = combined risk, 2 = early overstock watch, 3 = sales risk only, 4 = inventory risk only
- **Rank:** position in the at-risk list, ordered by risk tier, then months of supply (highest first, `NULL` first), then dealer ID; 1 is the most urgent dealer

## Key Findings

For September 2026 synthetic data:

- 12 of 40 dealers are classified as sales-risk.
- 9 dealers meet the inventory-risk rule.
- 1 dealer, Buffalo Sunset Vertex Automotive, has both sales risk and inventory risk.
- 3 additional dealers are on the early-overstock watch list: Orlando, San Diego, and Seattle.
- 8 inventory-risk dealers are not sales-risk; in this dataset, all 8 are at or above 100% of their September target.
- Inventory-risk dealers are 5 Medium, 2 Large, and 2 Small, compared with a network mix of 20 Medium, 10 Large, and 10 Small.
- Dealer size does not appear to explain inventory risk in this dataset.
- The ranked at-risk list has 20 dealers: 1 in tier 1 (Buffalo Sunset), 3 in tier 2 (Orlando, San Diego, and Seattle), 8 in tier 3, and 8 in tier 4.

## Validation

The PostgreSQL scorecard was cross-checked against the Day 4 pandas scorecard. All four risk flags matched for all 40 dealers.

The Day 17 `dealer_monthly_performance` view was also cross-checked independently against the source CSV files. SQL matched pandas for all 960 dealer-months across 40 dealers and 24 months. The September 2026 scorecard was exported before and after the refactor and matched byte-for-byte.

## Limitations

- All data is synthetic, so the findings demonstrate the analytical method, not real-world conclusions.
- Months of supply currently uses September sales only.
- The 80%, 90-day, 4-month, and 30% thresholds are business-rule assumptions and should be validated and tuned with stakeholders in a real deployment.
- Sales and target performance are available in SQL for all 24 months (October 2024 through September 2026), but the Python layer and API do not use the monthly view yet. Inventory is a single snapshot as of September 30, 2026, so `inventory_supply`, `dealer_scorecard`, and the current API risk outputs remain September-specific until historical inventory snapshots are available.
- The at-risk ranking order (risk tier, then months of supply) is a prioritization heuristic, not a validated predictive metric. Within the sales-risk-only tier, months of supply is a weak signal because all of those dealers are under 3.2 months.

## Planned Projects

- **Dealer Analytics API:** expose dealer performance and inventory-risk metrics through an API.
- **Supply Chain Risk Assistant:** analyze sourcing, inventory, logistics, and supplier risks.
- **Dealer Operations Copilot:** combine structured dealer data with LLM-based decision support.
