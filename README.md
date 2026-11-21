# Automotive AI Lab

[![CI](https://github.com/PRASHANTAPAUDEL24/automotive-ai-lab/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/PRASHANTAPAUDEL24/automotive-ai-lab/actions/workflows/ci.yml)

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
- [x] Day 18: Month-aware Python query and FastAPI endpoint (`GET /performance?month=YYYY-MM`) with validation, response model, and tests
- [x] Day 19: Dealer monthly performance history (`GET /dealers/{dealer_id}/performance`) with query, dedicated 404 handling, response validation, and tests
- [x] Day 20: Optional inclusive `start` and `end` month filters for `GET /dealers/{dealer_id}/performance`, with empty-window handling, validation, and tests
- [x] Day 21: GitHub Actions CI that rebuilds PostgreSQL from the repository's SQL scripts and tracked CSV files on a fresh runner, then runs Black, Ruff and the full test suite on every push and pull request
- [x] Day 22: Regional monthly performance history (`GET /regions/{region}/performance`) with weighted achievement, inclusive month ranges, dedicated 404 handling, response validation, and tests
- [x] Day 23: Single-source strict ASCII `YYYY-MM` month validation in `src/db.py`, reused across the original five FastAPI month parameters, with contract tests that prevent regex drift or duplicated literals
- [x] Day 24: Network-wide monthly performance trend (`GET /performance/trend`) with weighted achievement, inclusive month ranges, nullable target handling, response validation, and tests
- [x] Day 25: Month-aware dealer performance ranking (`GET /performance/ranking`) with deterministic raw-achievement ranking, bounded limits, non-null ranked responses, mutation testing, and CI
- [x] Day 26: Cross-region monthly performance snapshot (`GET /performance/regions?month=YYYY-MM`) with weighted achievement, missing/zero-target handling, shared response-model reuse, mutation testing, and CI
- [x] Day 27: Shared monthly performance rollup using PostgreSQL `GROUPING SETS`, with regional/network grain contracts, exact before/after regression comparison, planner-statistics protection, mutation testing, and CI
- [x] Day 28: Fix legacy `/dealers/at-risk` large-limit overflow with a PostgreSQL `bigint` cast, FastAPI upper-bound validation, regression tests, mutation checks, and CI
- [x] Day 29: Monthly vehicle-model performance (`GET /performance/models?month=YYYY-MM`) with catalog attributes, network sales share, unit-weighted average sale price, null/zero handling, mutation testing, and CI
- [x] Day 30: Regional lead funnel analytics (`GET /performance/funnel?month=YYYY-MM`) with ratio-of-sums conversion rates, regional completeness rules, null/zero handling, mutation testing, and CI
- [x] Week 3: FastAPI
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

`sql/03_views.sql` now creates `dealer_monthly_performance`, with one row per dealer and month for sales and target performance, plus `monthly_performance_rollup`, which uses `GROUPING SETS` to produce both regional `(region, month)` rows and whole-network `(month)` rows from one weighted-aggregation definition. The rollup contains 120 regional rows plus 24 network rows; `region IS NULL` identifies the network grain because `dealers.region` is `NOT NULL`. `sql/02_load.sql` now finishes with `ANALYZE;` so fresh databases have planner statistics before these queries run. The existing `dealer_performance` view remains a September 2026 compatibility view so the downstream inventory and scorecard logic is unchanged.

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
| `GET /regions/{region}/performance` | Returns one region's monthly sales and target history, oldest first. Optional `start` and `end` parameters use strict `YYYY-MM` format and are inclusive. Unknown regions return 404; malformed or reversed bounds return 422. A valid region with no rows in the requested window returns `200 []`. |
| `GET /performance/trend` | Returns network-wide monthly sales and target history, oldest first. Optional `start` and `end` parameters use strict `YYYY-MM` format and are inclusive. Achievement is weighted from total units divided by total target. Malformed or reversed bounds return 422, and a valid window with no rows returns `200 []`; the network has no not-found state. |
| `GET /performance/ranking` | Ranks dealers for one required `month=YYYY-MM` by raw, unrounded achievement percentage. Dealers with missing or zero targets are excluded before ranking; ties are broken by `dealer_id`, ranks are contiguous, and optional `limit` is bounded from 1 through `2**63 - 1` while preserving global ranks. A malformed month or invalid limit returns 422, a well-formed month with no data returns 404, and an existing month with no rankable dealers returns `200 []`. |
| `GET /performance/regions` | Compares all five regions for one required `month=YYYY-MM`, ordered by region. Achievement is weighted from regional total units divided by regional total target. A missing dealer target keeps the region in the response with null target and achievement; a zero regional target remains `0` with null achievement. Malformed months return 422 and well-formed months with no data return 404. |
| `GET /performance/models` | Returns one row per vehicle model with sales rows for one required `month=YYYY-MM`, ordered by units sold descending with model as the deterministic tie-break. Includes segment, MSRP, total units sold, share of network units, and unit-weighted average sale price using only priced units. Models with no sales rows for the month are omitted; models with rows but zero total units remain present. Network-zero share and zero priced-unit average are null where undefined. Malformed months return 422 and well-formed months with no sales data return 404. |
| `GET /performance/funnel` | Returns one row per dealer region for one required `month=YYYY-MM` with leads, test drives, units sold and three ratio-of-sums funnel rates. Incomplete regional lead or sales data remains represented through required-but-nullable fields. Malformed months return 422 and a well-formed month with no lead data returns 404. |
| `GET /dealers/at-risk` | Returns the 20 sales-risk or inventory-risk dealers, ranked from most to least urgent. Optional `limit` accepts values from 1 through `2**63 - 1` and keeps the global ranks; zero, non-integers, or values above the PostgreSQL `bigint` maximum return 422 |
| `GET /performance` | Returns dealer sales and target performance for the required `month` (`YYYY-MM`), for any month from 2024-10 to 2026-09. A malformed month returns 422, a well-formed month with no data returns 404, and target and achievement stay nullable. |
| `GET /dealers/{dealer_id}/performance` | Returns one dealer's monthly sales and target history, oldest first. Optional `start` and `end` parameters use `YYYY-MM` and are inclusive. With no bounds, all 24 months are returned. An unknown dealer returns 404; malformed bounds, `start > end`, or a non-integer dealer id return 422. A valid dealer with no rows in the requested window returns `200 []`. |

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

`GET /performance?month=YYYY-MM` returns `MonthlyPerformance` records with six fields: `dealer_id`, `dealer_name`, `month`, `units_sold`, `target_units` and `achievement_pct`. The month is required and must match `YYYY-MM`. Malformed values return 422, while a well-formed month with no data returns 404. `target_units` is null when the dealer has no target row for the month; `achievement_pct` is null when the target is missing or zero (a zero target is returned as `0`). The response is ordered by `dealer_id`.

`GET /dealers/{dealer_id}/performance` returns the same `MonthlyPerformance` records for one dealer, ordered oldest first, with the same nullable `target_units` and `achievement_pct`. Optional `start` and `end` query parameters use strict `YYYY-MM` format and are inclusive. With neither bound, all 24 months are returned; `start` alone runs through the latest month, `end` alone begins at the earliest month, and equal bounds return one month. A valid dealer with no rows in the requested window returns `200 []`. An unknown dealer returns 404 (for example `Dealer 999 not found`), while malformed bounds, `start > end`, and a non-integer dealer id return 422.

`GET /regions/{region}/performance` returns `RegionMonthlyPerformance` records with six fields: `region`, `month`, `dealer_count`, `units_sold`, `target_units` and `achievement_pct`. Regional achievement is weighted as total units sold divided by total target, not as the average of dealer percentages. `target_units` and `achievement_pct` are null when any contributing dealer is missing a target; a zero regional target keeps `target_units` as `0` and makes `achievement_pct` null. Region names are exact and case-sensitive, and an unknown region returns 404 (for example `Region Atlantis not found`). This differs from `GET /dealers?region=`, which returns an empty list for an unknown region. With no bounds, all 24 months are returned; `start` and `end` are inclusive when supplied. A valid region with no rows in the requested window returns `200 []`, while malformed or reversed bounds return 422.

`GET /performance/trend` returns `NetworkMonthlyPerformance` records with five fields: `month`, `dealer_count`, `units_sold`, `target_units` and `achievement_pct`. Network achievement is weighted as total units sold divided by total target, not as the average of dealer percentages. `target_units` and `achievement_pct` are null when any contributing dealer is missing a target; a zero network target keeps `target_units` as `0` and makes `achievement_pct` null. With no bounds, all 24 months are returned; `start` and `end` use the shared strict ASCII `YYYY-MM` rule and are inclusive when supplied. A valid window with no rows returns `200 []`; there is no network not-found state. Malformed or reversed bounds return 422.

`GET /performance/ranking` returns `RankedMonthlyPerformance` records with seven required, non-null fields: `dealer_id`, `dealer_name`, `month`, `units_sold`, `target_units`, `achievement_pct` and `rank`. Ranking is computed from raw, unrounded achievement percentage with `dealer_id` as the deterministic tie-break. Dealers whose achievement is undefined because the target is missing or zero are excluded before `ROW_NUMBER()` is assigned, so returned ranks are contiguous. The optional `limit` is applied after ranking and therefore preserves global ranks. The endpoint reuses the shared strict ASCII `YYYY-MM` query pattern and caps `limit` at PostgreSQL bigint maximum.

`GET /performance/regions?month=YYYY-MM` returns five `RegionMonthlyPerformance` records for one required month, ordered by region. Regional achievement is weighted as total units sold divided by total target, not as the average of dealer percentages. If any dealer in a region is missing a target, that region remains in the response with `target_units` and `achievement_pct` null; a zero regional target remains `0` with null achievement. The endpoint reuses the existing regional response model and shared strict ASCII `YYYY-MM` query pattern. A malformed month returns 422, while a well-formed month with no data returns 404.

`GET /performance/funnel?month=YYYY-MM` returns five `RegionalFunnel` records, ordered by region, with leads, test drives, units sold and three raw ratio-of-sums conversion rates. All six metrics are required but nullable. Missing lead data nulls the lead metrics and rates while complete sales totals remain available; missing sales data nulls `units_sold` and the two sale rates while complete lead metrics remain available. Zero denominators produce null only where a rate is undefined. The route reuses the shared strict ASCII month pattern; malformed months return 422 and a well-formed month with no `leads_monthly` rows returns 404.

## Testing

The pytest suite covers the reusable PostgreSQL query layer, FastAPI endpoints, response models, shared validation contracts and regression behavior. Day 30 added 44 regional-funnel database tests and 21 API/model tests covering 24-month oracle parity, aggregation grain, regional completeness, ratio-of-sums rates, JSON types, OpenAPI contracts, month validation, null handling, response coercion and existing-route regressions. Day 29 added 19 database tests for monthly vehicle-model aggregation and 17 API/model tests covering database parity, JSON types, OpenAPI contracts, month validation, null handling, response validation, NaN-to-null serialization and transactional zero-unit behavior. Day 30 database mutation testing killed all 29 implemented non-equivalent mutants and API/model mutation testing killed all 17 mutants with no survivors. For Day 29, database mutation testing killed all 10 non-equivalent mutants with one equivalent survivor; API/model mutation testing killed all 13 non-equivalent mutants with one equivalent raw `to_dict("records")` survivor because Pydantic normalizes NaN to JSON null. Day 28 added 8 focused `/dealers/at-risk` large-limit regression tests covering three valid values above the former 32-bit ceiling, API parity with the unbounded ranking, the one-above-`bigint` 422 boundary, and the SQL `bigint` cast contract. Day 27 added 12 direct `monthly_performance_rollup` view-contract tests, 1 consumer-contract test, 1 load-script statistics guard and 1 JIT-aware plan-cost guard. The full local suite is 843 passed with the JIT-specific plan guard skipped; CI runs all 844 tests.

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
- dealer monthly history across all 24 months
- inclusive `start` and `end` dealer-history range filtering
- empty history windows for valid dealers versus 404 for unknown dealers
- strict month-format validation and reversed-range handling
- regional monthly performance across all 5 regions and 24 months
- independent CSV-to-database checks for all regional monthly results
- weighted regional achievement versus average dealer percentages
- inclusive regional history ranges and empty-window handling
- unknown-region 404 behavior and strict query-bound validation
- nullable regional target and achievement serialization
- response-model enforcement and JSON numeric type guarantees
- network-wide monthly aggregation matched independently against the source CSVs and reconciled to the sum of the five regional rows
- network trend range filtering, empty-window behavior, strict query-validation locations, nullable target serialization and existing `/performance` route regression
- month-format contract tests: the centralized contract currently covers nine FastAPI month parameters; eleven FastAPI month parameters use the same shared strict ASCII `YYYY-MM` pattern, while `/performance/models` and `/performance/funnel` independently pin it through focused OpenAPI/API tests, and the rule's values are pinned
- monthly dealer-ranking tests: all 24 months are checked against an independent CSV oracle using exact `Fraction` arithmetic; limit behavior, raw-versus-rounded ordering, deterministic ties, missing/zero-target exclusion, SQL structure, API validation/error mapping, non-null response fields and regression behavior are pinned
- cross-region snapshot tests: all 24 months are checked against an independent CSV oracle and reconciled to the regional-history and network-trend queries; weighted achievement, alphabetical region ordering, missing/zero-target states, integer JSON types, OpenAPI model reuse, error translation and regression behavior are pinned
- single-source protection: the month regex literal must appear exactly once in `src/`, in `src/db.py`

### Continuous integration

GitHub Actions (`.github/workflows/ci.yml`) runs on every push and pull request and can also be started manually. On a fresh `ubuntu-24.04` runner it installs Python 3.12.7 and `requirements-dev.txt`, starts a `postgres:18.6` service container, builds the database from `sql/01_schema.sql`, `sql/02_load.sql` and `sql/03_views.sql` (the loader reads the CSV files committed in `data/`), then runs Black, Ruff and the full pytest suite. The Ubuntu release, PostgreSQL version and Python version are pinned to reduce environment drift. Black and Ruff check `src/db.py`, `src/api.py`, `src/models.py` and `tests`; the old Day 1-4 scripts are not linted in CI.

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

The cross-check is now automated: `tests/test_monthly_performance.py` recomputes all 960 dealer-months from the source CSV files in pandas and compares them with `get_monthly_performance` for every month.

`tests/test_dealer_performance.py` extends the cross-check to dealer-level history. It recomputes each dealer's 24-month history from the source CSV files in pandas and compares it with `get_dealer_performance_history` for all 40 dealers, and compares the September rows with `get_scorecard`.

## Limitations

- All data is synthetic, so the findings demonstrate the analytical method, not real-world conclusions.
- Months of supply currently uses September sales only.
- The 80%, 90-day, 4-month, and 30% thresholds are business-rule assumptions and should be validated and tuned with stakeholders in a real deployment.
- Sales and target performance are available through SQL, the Python query layer, `GET /performance?month=YYYY-MM` (all dealers for one month), `GET /dealers/{dealer_id}/performance` (one dealer's monthly history), `GET /regions/{region}/performance` (weighted regional monthly history), `GET /performance/trend` (weighted network-wide monthly history), `GET /performance/ranking?month=YYYY-MM` (ranked dealers for one month), `GET /performance/regions?month=YYYY-MM` (all five regions for one month), `GET /performance/models?month=YYYY-MM` (network vehicle-model performance for one month) and `GET /performance/funnel?month=YYYY-MM` (regional lead funnel performance for one month). Dealer, regional and network history can be limited with inclusive `start` and `end` bounds; ranking has its own optional bounded `limit`. The month-aware sales/target data cover October 2024 through September 2026.
- `inventory_supply`, `dealer_scorecard` and the endpoints built on them (`GET /dealers`, `GET /dealers/{dealer_id}`, `GET /dealers/at-risk` and `GET /regions/summary`) remain fixed to September 2026. Inventory is a single snapshot as of September 30, 2026, so historical inventory and risk analysis is not yet month-aware.
- Dealer, regional and network history range filters are limited to month precision (`YYYY-MM`); daily or arbitrary-date filtering is not implemented.
- `GET /performance/funnel` defines sales completeness at dealer-month grain: an aggregated sales dealer-month is enough, so completeness does not require all eight vehicle-model rows.
- Funnel rates are same-month operational approximations rather than cohort measures; the current endpoint does not model lead-to-sale lag or attribution across months.
- The funnel endpoint currently returns five regional rows only; it does not expose a network-wide funnel row.
- The ratio-of-sums contract is independently pinned by a 24-month oracle and a deliberately divergent transactional fixture. A dedicated mean-of-dealer-rates source mutant was not generated because that alternative requires a structural SQL rewrite rather than a safe local substitution.
- The strict ASCII `YYYY-MM` rule is centralized in `src/db.py` as `MONTH_FORMAT`; `MONTH_QUERY_PATTERN` and the compiled database regex are derived from it. Eleven FastAPI month parameters now use the shared query pattern; the centralized month-format contract enumerates nine of them, while `/performance/models` and `/performance/funnel` independently pin the same pattern through focused OpenAPI/API tests. Required-month and optional-bound validators still keep their different existing error messages by design.
- Regional history, network trend and cross-region snapshots now share `monthly_performance_rollup`, a single `GROUPING SETS` definition for weighted achievement and missing/zero-target handling. The view intentionally contains both regional and network grains, so consumers must filter them explicitly; `region IS NULL` means the whole network and relies on `dealers.region` remaining `NOT NULL`. Region-specific filtering is applied to the rollup result, and the implementation does not rely on PostgreSQL pushing that predicate beneath the aggregate. At the current 960 dealer-month base rows, the extra aggregation work is negligible.
- Fresh loads explicitly run `ANALYZE;` after the final `\copy`. Without planner statistics, the representative rollup query's estimated cost was about 584k; after analysis it fell to about 12.9k. The earlier CI slowdown is consistent with a JIT-enabled server treating the un-analyzed rollup query as an expensive compilation candidate; JIT time was not measured directly.
- `get_at_risk_dealers()` has no Python-side limit validation, unlike `get_monthly_dealer_ranking()`: a direct call with a limit above `2**63 - 1` raises a database error. The API is protected by the `le=MAX_LIMIT` bound and returns 422.
- The at-risk ranking order (risk tier, then months of supply) is a prioritization heuristic, not a validated predictive metric. Within the sales-risk-only tier, months of supply is a weak signal because all of those dealers are under 3.2 months.

## Planned Projects

- **Dealer Analytics API:** expose dealer performance and inventory-risk metrics through an API.
- **Supply Chain Risk Assistant:** analyze sourcing, inventory, logistics, and supplier risks.
- **Dealer Operations Copilot:** combine structured dealer data with LLM-based decision support.
