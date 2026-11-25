# Automotive AI Lab: Project Progress Summary

**Last updated:** 25 Nov 2026 · **Latest code commit:** `9534cac` (Add dealer funnel opportunities endpoint) · **Tests:** 1921 passing in CI · **CI:** passing on `main`
**Repository:** https://github.com/PRASHANTAPAUDEL24/automotive-ai-lab
**Author:** Prashanta Paudel

---

## 1. Current state (read this first)

The project builds a data and analytics foundation for AI-powered automotive dealer operations. It uses a fully **synthetic** dataset for the fictional brand **Vertex Motors** with 40 dealers across 5 regions. Sales and target data cover 24 months from October 2024 through September 2026; inventory is a single snapshot as of September 30, 2026.

**What works today**

- Dealer sales and inventory analytics, implemented twice (pandas and PostgreSQL) and cross-checked against each other.
- Five reusable PostgreSQL views, including the dealer-grain `dealer_monthly_performance`, the shared regional/network `monthly_performance_rollup`, and the `dealer_scorecard` view with four business-risk flags.
- A safe, parameterized Python query layer (`src/db.py`).
- A FastAPI service with seventeen endpoints:

| Endpoint | Behaviour |
|---|---|
| `GET /health` | Returns `{"status": "ok"}` |
| `GET /dealers` | Scorecard for all dealers; optional `region` and `risk` filters. Unsupported `risk` returns 400; unknown region returns `[]` |
| `GET /dealers/{dealer_id}` | One dealer scorecard. Unknown id returns 404; non-integer id returns 422 |
| `GET /regions/summary` | One row per region: dealer count and counts of sales-risk, inventory-risk, combined-risk and early-overstock-watch dealers |
| `GET /dealers/at-risk` | The 20 sales-risk or inventory-risk dealers, ranked (1 = most urgent). Optional `limit` accepts 1 through `2**63 - 1` and keeps the global ranks; zero, non-integers, or values above the PostgreSQL `bigint` maximum return 422 |
| `GET /performance` | Dealer sales and target performance for the required `month` (`YYYY-MM`), 2024-10 to 2026-09. 422 for a malformed month, 404 for a well-formed month with no data. |
| `GET /dealers/{dealer_id}/performance` | One dealer's sales and target history, oldest first. Optional inclusive `start` and `end` filters use `YYYY-MM`; no bounds returns all 24 months. A valid dealer with no rows in the window returns `[]`; unknown id returns 404; malformed bounds, `start > end`, or a non-integer id return 422. |
| `GET /regions/{region}/performance` | One region's monthly sales and target history, oldest first. `achievement_pct` is weighted from total units divided by total target. Region names are exact and case-sensitive. Optional inclusive `start` and `end` filters use strict `YYYY-MM`; no bounds returns all 24 months. A valid region with no rows in the window returns `[]`; an unknown region returns 404; malformed or reversed bounds return 422. |
| `GET /performance/trend` | Network-wide monthly sales and target history, oldest first. `achievement_pct` is weighted from total units divided by total target. Optional inclusive `start` and `end` filters use strict `YYYY-MM`; no bounds returns all 24 months. A valid window with no rows returns `[]`; the network has no not-found state; malformed or reversed bounds return 422. |
| `GET /performance/ranking` | Ranks dealers for one required `month=YYYY-MM` by raw, unrounded achievement percentage. Dealers with missing or zero targets are excluded before ranking; ties are broken by `dealer_id`, ranks are contiguous, and optional `limit` is bounded from 1 through `2**63 - 1` while preserving global ranks. A malformed month or invalid limit returns 422, a well-formed month with no data returns 404, and an existing month with no rankable dealers returns `200 []`. |
| `GET /performance/regions` | Compares all five regions for one required `month=YYYY-MM`, ordered by region. Achievement is weighted from regional total units divided by regional total target. A missing dealer target keeps the region in the response with null target and achievement; a zero regional target remains `0` with null achievement. Malformed months return 422 and well-formed months with no data return 404. |
| `GET /performance/models` | Returns one row per vehicle model with sales rows for one required `month=YYYY-MM`, ordered by units sold descending with model as the deterministic tie-break. Includes segment, MSRP, total units sold, share of network units, and unit-weighted average sale price using only priced units. Models with no sales rows for the month are omitted; models with rows but zero total units remain present. Network-zero share and zero priced-unit average are null where undefined. Malformed months return 422 and well-formed months with no sales data return 404. |
| `GET /performance/funnel` | Returns one row per dealer region for one required `month=YYYY-MM`, ordered by region, with leads, test drives, units sold and three funnel rates computed as ratios of regional sums. Missing regional lead data keeps the region but nulls lead metrics and rates; missing regional sales data keeps the region but nulls units sold and the two sale rates. Zero denominators produce null only where the rate is undefined. Malformed months return 422 and a well-formed month with no `leads_monthly` rows returns 404. |
| `GET /dealers/{dealer_id}/funnel` | Returns one dealer's monthly lead-funnel history, oldest first. Optional inclusive `start` and `end` bounds use strict `YYYY-MM`. Missing lead or sales data remains null while real zeros remain zero. A valid dealer with no rows in the window returns `[]`; unknown dealers return 404; malformed or reversed bounds return 422. |
| `GET /performance/funnel/trend` | Returns the network-wide monthly lead-funnel trend, oldest first. Optional inclusive `start` and `end` bounds use strict `YYYY-MM`. Missing lead data nulls leads, test drives and all three rates; missing sales data nulls units sold and the two sale rates. A valid empty window returns `[]`; malformed or reversed bounds return 422. |
| `GET /performance/funnel/ranking` | Ranks eligible dealers by raw lead-to-sale conversion for one required month, with deterministic ties, optional inclusive `min_leads` and bounded `limit`. Existing months without eligible dealers return `[]`; absent lead months return 404; invalid parameters return 422. |
| `GET /performance/funnel/opportunities` | Ranks dealers strictly below their complete regional lead-to-sale benchmark for a required `month=YYYY-MM`, by estimated additional units descending then dealer ID ascending. Inclusive `min_leads` (default 0) filters before ranking; optional `limit` trims afterward. Both filters are bounded by signed PostgreSQL `bigint` maximum; `limit` must be positive. Invalid parameters return 422, absent lead months return 404, and existing months without eligible dealers return `200 []`. |

- Pydantic response models (`Dealer`: 17 fields, 5 nullable; `RegionSummary`: region plus 5 count fields; `RankedDealer`: `Dealer` plus `rank` and `risk_tier`; `MonthlyPerformance`: 6 fields, 2 nullable; `RegionMonthlyPerformance`: 6 fields, 2 nullable; `NetworkMonthlyPerformance`: 5 fields, 2 nullable; `RankedMonthlyPerformance`: 7 required non-null fields; `ModelMonthlyPerformance`: 6 fields with nullable share and weighted average price; `RegionalFunnel`: 7 required fields with six nullable metrics; `DealerMonthlyFunnel`: 9 required fields with six nullable metrics; `NetworkMonthlyFunnel`: 7 required fields with six nullable metrics; `RankedDealerFunnel`: 11 required fields with only `drive_to_sale_pct` nullable; `RankedDealerOpportunity`: 11 required non-null fields) that validate API output and drive the schemas shown in `/docs`.
- A pytest suite with 1920 local passes plus 1 JIT-only skip, and 1921 passing tests in CI. Day 34 added 238 database opportunity tests, 159 API tests and one centralized month-contract case (398 new tests). The final database campaign killed 41/44 mutants with three justified equivalents; the API campaign killed 74/74 (71 behavioral-classified, three structural), with no equivalents. Combined: 115/118 killed, 97.46% raw and 100% adjusted, zero unresolved survivors and zero execution errors. Both isolated campaigns restored protected files and focused baselines. Day 33 added 229 database ranking tests, 154 API ranking tests and one shared month-contract case. Database mutation testing killed 54 of 56 mutants with two justified equivalent survivors; API mutation testing killed all 63 primary mutants and all 4 supplementary probes. Day 31 added the canonical `dealer_monthly_funnel` view, `get_dealer_funnel_history()`, and `GET /dealers/{dealer_id}/funnel?start=&end=`. Day 30 added 44 database tests and 21 API/model tests for regional lead funnel analytics. Database mutation testing killed all 29 implemented non-equivalent mutants, and API/model mutation testing killed all 17 mutants with no survivors. Day 29 added 19 database tests and 17 API/model tests for monthly vehicle-model performance, with database mutation testing killing all 10 non-equivalent mutants (one equivalent survivor) and API/model mutation testing killing all 13 (one equivalent raw-record survivor). Day 28 added 8 focused `/dealers/at-risk` large-limit regression tests covering three valid values above the former 32-bit ceiling, DB/API parity with the unbounded ranking, the one-above-`bigint` 422 boundary, and the SQL `bigint` cast contract. Day 27 added 12 direct `monthly_performance_rollup` view-contract tests, 1 consumer-contract test, 1 deterministic load-script statistics guard and 1 JIT-aware rollup plan-cost guard. All seventeen FastAPI month parameters now use the shared strict ASCII `YYYY-MM` query pattern and are enumerated by the centralized month-format contract. On the local PostgreSQL build the JIT-specific guard skips because JIT is unavailable; CI has JIT available and all 1921 tests pass there.
- GitHub Actions CI on every push and pull request: a fresh `ubuntu-24.04` runner with a `postgres:18.6` service rebuilds the database from the SQL scripts, then runs Black, Ruff and the full test suite.

**Day 31 — Dealer-level lead funnel drill-down**

- Added the canonical `dealer_monthly_funnel` view at dealer-month grain over the lead-defined month spine.
- Missing lead rows preserve available sales while lead metrics and rates remain null; missing sales rows preserve available lead metrics while sale-dependent metrics remain null. Real zeros remain zero.
- Added `get_dealer_funnel_history(dealer_id, start=None, end=None)` with oldest-first results, inclusive month bounds, known-dealer empty-window behavior and unknown-dealer detection.
- Added `GET /dealers/{dealer_id}/funnel?start=&end=` with the `DealerMonthlyFunnel` response model and null-safe `to_records()` serialization.
- Expanded the centralized month-format contract from 11 to 13 FastAPI parameters.
- View mutation testing killed all 23 implemented required mutants (19 primary plus 4 supplemental). Query-layer mutation testing killed all 17 required mutants, plus the ORDER BY-removal diagnostic. API/model mutation testing killed all 34 implemented mutants with zero survivors and zero harness errors.
- Final verification: 1006 passed and 1 JIT-only skip locally; GitHub Actions CI #37 passed all 1007 tests.

**Day 32 — Network-wide lead-funnel trend**

- Added `get_network_funnel_trend(start=None, end=None)` over the canonical
  `dealer_monthly_funnel` view, returning one row per lead-defined month in
  oldest-first order.
- Network rates are ratios of network sums, not averages of dealer rates.
  Missing any dealer lead row nulls network leads, test drives and all three
  rates while complete sales totals remain available. Missing any dealer
  sales dealer-month nulls units sold and the two sale rates while complete
  lead metrics remain available.
- Added `GET /performance/funnel/trend?start=&end=` with the
  `NetworkMonthlyFunnel` response model. Optional bounds are inclusive;
  valid empty windows return `200 []`; malformed or reversed bounds return
  422.
- Expanded the centralized month-format contract from thirteen to fifteen
  FastAPI parameters.
- Database mutation testing killed all 31 focused non-equivalent mutants
  after one initial survivor, the removed `bigint` cast, was closed by a
  count-column dtype test.
- For the API/model layer, 36 route/model mutants plus two inline-regex
  contract probes were killed; one initial survivor, the 422 `detail` text,
  was closed with exact assertions, while removing exception chaining was
  treated as behaviorally equivalent.
- Code commits: `0e686e9` (network funnel trend query), `d9cb06f` (count
  dtype contract), and `1a9d608` (network funnel trend endpoint).
- Final verification: 1138 passed plus 1 JIT-only skip locally; GitHub
  Actions passed all 1139 tests.

**Day 33 — Dealer funnel ranking**

- Added `get_dealer_funnel_ranking(month, limit=None, min_leads=0)` over
  `dealer_monthly_funnel`, ranking by raw lead-to-sale conversion descending
  and dealer ID ascending. Undefined conversion rates and dealers below the
  inclusive minimum-leads threshold are excluded before contiguous ranking;
  the optional limit applies afterward.
- Added `GET /performance/funnel/ranking` with `RankedDealerFunnel`, eleven
  required fields and only `drive_to_sale_pct` nullable. A lead-defined month
  with no eligible dealers returns `200 []`; an absent lead month returns
  404; malformed or invalid parameters return 422.
- Expanded the centralized month-format contract from fifteen to sixteen
  parameters; the API now has sixteen registered paths.
- Final focused coverage: 229 database tests and 154 API tests, plus the
  additional shared month-contract case. Database mutations: 54/56 killed,
  with two justified equivalent survivors (100% adjusted). API mutations:
  63/63 primary and 4/4 supplementary killed; M32 was closed structurally.
- Code commits: `0f03bf8`, `9a0f53b`, `1aeb638` and `a1290b3`.
- Final verification: 1522 passed plus 1 JIT-only skip locally; GitHub
  Actions CI #46 passed all 1523 tests.

**Day 34 — Dealer funnel opportunities**

- Added `get_dealer_funnel_opportunities(month, limit=None, min_leads=0)` over
  `dealer_monthly_funnel`. The benchmark is regional units / regional leads,
  including the evaluated dealer; it is calculated before candidate filters.
  Only complete regions with positive total leads and strictly positive
  opportunity numerators contribute candidates. Rank by estimated additional
  units descending, then dealer ID ascending. Apply inclusive minimum leads
  before contiguous ranking and limit afterward.
- Added `GET /performance/funnel/opportunities` with `RankedDealerOpportunity`
  (eleven required non-null fields), shared month pattern, bigint bounds,
  exact argument forwarding, 422/404 mapping and `to_records()` delegation.
  Existing lead months with no eligible dealers return `200 []`.
- Database RED: 232 failed, 5 passed (237 tests); initial GREEN: 237 passed.
  A surviving missing-sales completeness mutation (M12) prompted one new
  behavioral test, giving 238 focused passes. Final database campaign:
  41/44 killed, three justified equivalents (M08 redundant numeric cast,
  M21 sales coalescing under completeness, M23 RANK with unique order keys),
  zero errors and 100% adjusted score. CI #48: 1761 passed in 12.77s;
  workflow 1m 7s, commit `26ca757`.
- API RED: 156 failed, 22 passed (178 focused tests, including the shared
  month contract); GREEN: 178 passed in 2.49s. Final API campaign: 74/74
  killed, 71 behavioral-classified and three structural (M12, M72, M73),
  no survivors or errors, 100% raw and adjusted. Restored baseline: 178 passed.
- Combined final campaigns: 118 distinct definitions, 115 killed, three
  accepted equivalents, 97.46% raw and 100% adjusted; no unresolved
  survivors or execution errors. These are targeted, not exhaustive scores.
- Final local regression: 1920 passed, one JIT-only skip (24.86s), Black and
  Ruff clean. CI #49: 1921 passed in 14.39s; test job 1m 7s, workflow
  1m 11s, commit `9534cac`. API paths and centralized month parameters: 17 each.

**Next step:** Day 35 — design first; scope to be decided.


**Architecture**

```
Synthetic CSV data
  -> PostgreSQL tables
  -> PostgreSQL analytical views, including monthly_performance_rollup
  -> reusable Python database layer (src/db.py)
  -> FastAPI endpoints (src/api.py)
  -> pytest integration tests
```

**Technical stack:** Python, pandas, NumPy, PostgreSQL, SQL, SQLAlchemy, psycopg, FastAPI, Uvicorn, pytest, FastAPI TestClient, Git, virtual environments, Black, Ruff, GitHub Actions.

---

## 2. How to run it

```bash
# one-time setup
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.txt

# database connection (never committed; .env is in .gitignore)
export DATABASE_URL="postgresql+psycopg://<user>@localhost:5432/automotive_ai_lab"

# tests
pytest -v

# API server
uvicorn api:app --app-dir src --reload
# then open http://127.0.0.1:8000/docs
```

---

## 3. Business rules (single reference)

| Term | Rule |
|---|---|
| Available inventory | Units with status "In Stock" |
| Aged inventory | Available units older than 90 days |
| Aged percentage | Aged units / available units |
| Months of supply | Available units / September units sold (0 if both are zero; stock with zero sales counts as high supply) |
| High supply | More than 4 months of supply |
| `sales_risk` | September target achievement below 80% |
| `inventory_risk` | High supply AND more than 30% aged inventory |
| `combined_risk` | `sales_risk` AND `inventory_risk` |
| `early_overstock_watch` | `sales_risk` AND high supply AND NOT `inventory_risk` |
| Risk tier | 1 = `combined_risk`, 2 = `early_overstock_watch`, 3 = `sales_risk` only, 4 = `inventory_risk` only |
| Rank | Position in the at-risk list: by risk tier, then months of supply (highest first, NULL first), then `dealer_id` |
| Regional conversion benchmark | Regional units sold / regional leads, including all dealers, with complete lead and aggregated sales rows and positive total leads |
| Estimated opportunity units | Dealer leads times regional benchmark minus actual dealer units; strictly positive values qualify, ranked before limit |

Flags use unrounded values. Rounding is for display only.

---

## 4. Current business findings (synthetic September 2026 data)

- 12 of 40 dealers are sales-risk.
- 9 dealers meet the inventory-risk rule.
- 1 dealer has both risks: **Buffalo Sunset (dealer 111)**, with 75.0% achievement, 33.3% aged and 5.375 months of supply.
- 3 dealers are on the early-overstock watch: **102 Orlando, 105 San Diego, 130 Seattle**.
- 8 inventory-risk dealers are not sales-risk, and all 8 are at or above 100% of their September target (range 100.0% to 127.3%).
- 11 dealers are sales-risk only.
- Each region has 8 dealers. Region × risk counts (sales / inventory): Northeast 3/2, Southeast 3/1, Midwest 2/2, Southwest 2/2, West 2/2.
- The one combined-risk dealer is in the Northeast; early-overstock-watch dealers are in the West (2) and the Southeast (1), per `GET /regions/summary`.
- The ranked at-risk list (`GET /dealers/at-risk`) has 20 dealers: 1 in tier 1 (dealer 111), 3 in tier 2 (102, 105, 130), 8 in tier 3 and 8 in tier 4. Rank 20 is dealer 125.
- In this synthetic dataset, dealer size does not appear to explain inventory risk.

---

## 5. Engineering practices demonstrated

- Environment-based configuration; no credentials in code or the repository.
- Reusable database functions with parameterized SQL.
- Whitelist validation for dynamic SQL identifiers (bound parameters protect values, not column names).
- SQL-injection tests, both destructive (`DROP TABLE`) and harmless (`' OR '1'='1`).
- Explicit client-versus-server error handling: bad input gives 400/404/422; a server misconfiguration gives 500 without leaking `DATABASE_URL`.
- One shared, NaN-safe `to_records` function so JSON output never contains NaN.
- A typed response model that validates API output; nullable fields are explicit and documented in `/docs`.
- Pandas-versus-SQL cross-validation, kept as automated tests.
- Test-first workflow (red, then green) for new behaviour.
- Mutation check on the ranking logic: the supply ordering was temporarily removed from the SQL to confirm the ordering tests fail, then restored.
- Deterministic query ordering.
- Reproducible virtual environment; small, single-purpose Git commits; code and README committed separately.
- Formatting and linting with Black and Ruff.

---

## 6. Known limitations

- Month-aware performance analytics are available across SQL, Python and FastAPI through `dealer_monthly_performance`, `GET /performance?month=YYYY-MM`, `GET /dealers/{dealer_id}/performance`, `GET /regions/{region}/performance`, `GET /performance/trend`, `GET /performance/ranking?month=YYYY-MM`, `GET /performance/regions?month=YYYY-MM`, `GET /performance/models?month=YYYY-MM`, `GET /performance/funnel?month=YYYY-MM`, `GET /performance/funnel/trend?start=&end=`, `GET /dealers/{dealer_id}/funnel?start=&end=`, `GET /performance/funnel/ranking`, and `GET /performance/funnel/opportunities`, covering October 2024 through September 2026.
- `inventory_supply`, `dealer_scorecard` and the endpoints built on them (`GET /dealers`, `GET /dealers/{dealer_id}`, `GET /dealers/at-risk` and `GET /regions/summary`) remain fixed to September 2026. Inventory is a single snapshot as of September 30, 2026, so historical inventory and risk analysis is not yet month-aware.
- `GET /performance` returns all 40 dealers for one month, `GET /dealers/{dealer_id}/performance` returns one dealer's monthly history, `GET /regions/{region}/performance` returns weighted regional monthly history, `GET /performance/trend` returns weighted network-wide monthly history, `GET /performance/ranking` ranks rankable dealers for one required month, `GET /performance/regions` compares all five regions for one required month, `GET /performance/models` returns network vehicle-model performance for one required month, `GET /performance/funnel` returns regional lead-funnel metrics for one required month, `GET /performance/funnel/trend` returns the network-wide monthly lead-funnel trend, and `GET /dealers/{dealer_id}/funnel` returns one dealer's monthly lead-funnel history. Dealer, regional and network history accept optional inclusive `start` and `end` bounds; ranking accepts an optional bounded `limit`. Filtering is month-precision only (`YYYY-MM`); daily or arbitrary-date filtering is not implemented.
- `GET /performance/models` returns only vehicle models that have at least one `sales_monthly` row for the requested month. A model with rows but zero total units remains in the response; a catalog model with no sales rows for that month is omitted.
- `GET /performance/funnel` defines sales completeness at dealer-month grain: a dealer is sales-complete when an aggregated sales dealer-month exists. It does not require all eight vehicle-model rows to be present.
- The funnel rates are same-month operational approximations. They compare leads, test drives and units sold recorded in the same month and do not track lead cohorts, conversion lag or attribution across months.
- Funnel analytics now expose regional snapshots through `GET /performance/funnel`, dealer-level monthly history through `GET /dealers/{dealer_id}/funnel`, the network-wide monthly trend through `GET /performance/funnel/trend`, dealer ranking through `GET /performance/funnel/ranking`, and opportunities through `GET /performance/funnel/opportunities`.
- `GET /dealers/{dealer_id}/funnel` returns raw, unrounded rates for every dealer-month, including months with very small lead counts; there is no minimum-leads threshold yet.
- `GET /performance/funnel/trend` defines its month spine by `leads_monthly`: a month with sales rows but no lead rows is absent rather than zero-filled.
- `GET /performance/funnel/trend` computes network completeness by row existence: if any dealer lacks a lead row, that month's network leads, test drives and all three rates are null; if any dealer lacks an aggregated sales dealer-month, network units sold and the two sale rates are null. Rates are raw, unrounded ratios of network sums with no minimum-leads threshold, and a zero denominator yields null.
- Dealer funnel ranking and regional benchmark opportunities are implemented; both support inclusive `min_leads` and bounded `limit`.
- Opportunity estimates are same-month benchmark scenarios, not forecasts, causal estimates or guaranteed recoverable sales. The regional benchmark includes the evaluated dealer and all other dealers, not just eligible candidates. A missing lead or aggregated sales dealer-month excludes the entire region; a region with zero total leads is excluded. An individual missing model row is not itself a completeness failure. Operational counts are assumed nonnegative; no new check constraints enforce this. Positive leads with zero sales can qualify; zero individual leads cannot qualify under that assumption. Zero test drives do not independently exclude a dealer.
- Opportunity ranking uses a positive exact numeric numerator and a controlled 30-decimal-place truncated quotient before serialization. For regional lead totals below `10**15`, distinct rational opportunities remain distinguishable at that precision; this is not a guarantee over arbitrary bigint totals. JSON floats can coincide for distinct opportunities, so clients must preserve returned rank rather than re-sort displayed values. Percentage gaps are differences of computed rates and are subject to numeric precision. No minimum materiality threshold is imposed.
- The opportunity query checks month existence separately from the ranked read; concurrent lead changes may affect 404 versus empty-result behavior because a shared snapshot is not guaranteed.
- M12 (default `min_leads` changed from 0 to 10) is killed by schema and forwarding checks, not real-data response differences: the committed fixture has no dealer below 10 leads. M22 (month passed as a keyword) is behavioral-classified by the harness because mock-based exception-mapping tests also fail, not proof of a client-visible difference. Mutation scores cover the selected definitions only, including structural contracts.
- A real dealer with no lead or sales rows returns one row with all six funnel metrics null per funnel month, not a 404; only an unknown dealer ID returns 404. Funnel months are defined by `leads_monthly`, so a month that exists only in sales data does not create a funnel month.
- The ratio-of-sums contract is independently pinned by the 24-month oracle and a deliberately divergent transactional fixture. A dedicated mean-of-dealer-rates source mutant was not generated because that alternative requires a structural SQL rewrite rather than a safe local substitution.
- The strict ASCII `YYYY-MM` rule is centralized in `src/db.py` as `MONTH_FORMAT`. `MONTH_QUERY_PATTERN` and the compiled `_MONTH_RE` are derived from that one value. All seventeen FastAPI month parameters now use the shared query pattern and are enumerated by the centralized month-format contract. Required-month and optional-bound validators still intentionally keep their different existing error messages.
- `GET /performance/ranking` excludes dealers whose achievement is undefined because the target is missing or zero. Ranking uses raw, unrounded achievement highest-first with `dealer_id` as the deterministic tie-break. `ROW_NUMBER()` gives contiguous positional ranks; the optional `limit` is applied after ranking and capped at PostgreSQL bigint maximum (`2**63 - 1`).
- `get_monthly_dealer_ranking()` performs two database reads: one to establish that the requested month exists and one to return the rankable rows. With the project's static analytical dataset this is harmless, but under concurrent writes the two reads could theoretically observe different states unless they share a transaction or snapshot.
- `GET /performance/ranking` currently supports highest-achievement-first ordering only; there is no ascending/descending sort-direction parameter.
- `get_at_risk_dealers()` has no Python-side limit validation, unlike `get_monthly_dealer_ranking()`: a direct call with a limit above `2**63 - 1` raises a database error. The API is protected by the `le=MAX_LIMIT` bound and returns 422.
- Regional and network weighted performance now share one PostgreSQL `monthly_performance_rollup` view built with `GROUPING SETS`; the missing-target, zero-target and weighted-achievement rules are defined once in SQL instead of repeated by the three Python consumers. The view intentionally contains two grains: non-NULL `region` rows represent `(region, month)` results, while `region IS NULL` represents the whole-network `(month)` result. That convention relies on `dealers.region` remaining `NOT NULL`, and each consumer must filter the intended grain explicitly.
- Region-specific consumers filter the rollup result after aggregation; the implementation does not rely on PostgreSQL pushing `WHERE region = ...` beneath the `GROUPING SETS` aggregate. With the current 960 dealer-month base rows, the additional aggregation work is negligible, but the design should be revisited if the dataset grows substantially.
- Fresh database loads now end with `ANALYZE;` so planner statistics exist before queries run. Without statistics, the representative regional rollup query was estimated at about 584,068 cost; after `ANALYZE` the estimate fell to about 12,917, below PostgreSQL's default `jit_above_cost` of 100,000. The earlier CI slowdown is consistent with a JIT-enabled server treating the un-analyzed rollup query as an expensive compilation candidate; JIT time was not measured directly.
- Region matching is exact and case-sensitive. An unknown region returns 404 on `GET /regions/{region}/performance`, while `GET /dealers?region=` returns an empty list for an unknown region. Both behaviors are tested, but the convention is not unified.
- The regional-history, network-trend and cross-region snapshot NULL and zero-target rules are covered by automated tests that run the real queries inside rolled-back transactions. The tests temporarily remove a target or set the relevant targets to zero, execute the real aggregation against that transaction, then roll it back and verify the committed data is restored. The committed dataset itself has no such rows. API-level null serialization is covered both with deterministic stubbed frames and, for the Day 26 snapshot, a real rolled-back missing-target transaction.
- The range filter compares `YYYY-MM` text in SQL. That sorts chronologically only because both bounds are validated first, so the comparison must be revisited if the `month` column ever changes type or format.
- `get_dealer()` returns `None` for an unknown dealer, while `get_dealer_performance_history()` raises `DealerNotFoundError`. Both behaviors are tested, but the query-layer not-found convention could be standardized later.
- `get_dealer_performance_history()` relies on FastAPI to enforce an integer `dealer_id`; the database-layer function does not perform its own explicit type validation.
- The dealer-history CSV cross-check intentionally has its own helper instead of sharing the Day 18 monthly-performance helper. This keeps the validation independent at the cost of a small amount of duplication.
- Database-backed tests depend on `DATABASE_URL` being exported in the current shell. Because `get_engine()` is cached, tests that deliberately remove the variable must clear the engine cache before exercising that path.
- The current dataset has no zero-sales or missing-target dealer-months, so the zero-fill and `NULL`-achievement paths of the monthly view were checked once with a rolled-back test transaction, not by an automated test.
- Direct dependencies are pinned in `requirements.txt` and `requirements-dev.txt`, but transitive packages (for example Starlette) are not locked.
- The Day 16 clean-clone test reused the existing local PostgreSQL database; since Day 21 the CI workflow rebuilds the database from the SQL scripts on a fresh runner on every push.
- CI covers one pinned environment (`ubuntu-24.04`, Python 3.12.7, PostgreSQL 18.6) and lints only `src/db.py`, `src/api.py`, `src/models.py` and `tests`; other versions and the old Day 1-4 scripts are not covered. The Ubuntu release, `postgres:18.6` tag and action versions are pinned by hand and must be updated deliberately, although GitHub still updates the contents of the `ubuntu-24.04` image over time. The job has a 15-minute timeout, but branch protection is not configured, so a red run does not block a merge.
- `/health` has no response model, so `/docs` shows a generic example for it.
- The region summary query exists both in `sql/day14_region_summary.sql` and in `src/db.py`; update both if the logic changes.
- The at-risk ranking query exists both in `sql/day15_at_risk_dealers.sql` and in `src/db.py`; update both if the logic changes.
- `NULLS FIRST` for a NULL `months_of_supply` is in the ranking SQL but untested: no at-risk dealer has a NULL value today.
- Within tier 3 the order uses months of supply, a weak signal there (all under 3.2 months), so a dealer at 45.5% of target can rank below one at 47.4%. This follows from the chosen rule.
- Old Day 1-4 scripts have import-order lint warnings (Ruff I001), deliberately left unchanged.
- All data is synthetic, so findings are illustrative.
- Terminal `git push` prompts for credentials; pushes currently go through GitHub Desktop.

---

## 7. Lessons learned

- **Duplicate test names silently shadow each other.** Two functions named `test_get_dealer_111` meant the HTTP test never ran. Linters such as Ruff (F811) catch this.
- **Test-first caught a real bug.** `get_dealer` bypassed the NaN conversion; the failing test (`assert nan is None`) exposed it before any client could see it.
- **A response model must match the SQL's NULL behaviour.** The first draft typed every field as non-null and passed on today's data. A test with real nulls failed with five validation errors until the five nullable fields were typed `| None`.
- **A green subset is not a green suite.** After a refactor, three tests passed while nine failed on a missing import. Run the whole suite before every commit.
- **`git diff --check` ignores untracked files.** Stage first, then run `git diff --cached --check`.
- **Formatters touch more than you expect.** `black src tests` reformatted seven old scripts; they were reverted so the Day 12 commit stayed focused.
- **Check that the setup file installs.** `requirements.txt` once contained a pasted shell command (`printf '\n' >> requirements.txt`) that would have broken `pip install -r` for anyone cloning the repo. It was found by re-reading the setup steps and fixed in `d0b7ef6`.
- **Rounding differs by tool.** Python/NumPy round ties to even; PostgreSQL `numeric` rounds half up. Keep flags on unrounded values.
- **Check your own numbers.** Several counts were corrected during the project by re-running the query (for example, the sales-risk count is 12, not 17), and a claim is only quoted after a query confirms it: all 8 inventory-only dealers were verified at 100% of target or higher (range 100.0% to 127.3%) before it went into this report.
- **Declare static routes before dynamic ones.** `/dealers/at-risk` registered after `/dealers/{dealer_id}` would be read as an id and return 422. The static route comes first, and a test for the 200 response protects it.
- **A passing test is not proof it can fail.** Removing the supply ordering from the ranking SQL made exactly the two within-tier tests fail (2 failed, 31 passed); restoring it gave 57 passed.
- **SQL NULL becomes NaN in pandas.** A test that checks `is None` on a DataFrame value never fires, so NULL branches written that way looked tested but were not. They were removed.
- **Verify which executable ran.** In the clean-clone test, a bare `black` reported version 24.8.0 instead of the pinned 26.10.1, and `which -a` showed Conda copies of `black` and `pytest` further down the PATH. The likely cause is that zsh had cached the venv's `bin` folder before the install. Because it was unclear which `pytest` the first run used, the proof is the later `python -m pytest` run (57 passed). Running tools as `python -m` (or `hash -r` after installing) uses the environment's own copy.
- **Formatting depends on the exact tool version.** The older Black wanted to re-wrap three SQL query strings in `src/db.py` that the pinned version leaves alone, so Black is pinned in `requirements-dev.txt` and tools are run through `python -m`.
- **Refactor behind a stable interface.** `dealer_performance` became a September filter over the new monthly view, so the views that depend on it did not change, and an export of the September scorecard before and after the change was identical.
- **Define the grain, then make absence explicit.** Cross-joining dealers with the months from both sales and targets turns a missing sales row into `units_sold = 0` instead of a missing row.
- **Prove a fallback path the data never exercises.** A test transaction inserted a dealer with no sales, queried the view and rolled back, leaving the data unchanged.
- **A spot check is not a full check.** An independent pandas calculation from the CSV files matched all 960 dealer-months, not just one month.
- **Do not reuse a broad exception type for a narrow meaning.** `ValueError` already meant a missing `DATABASE_URL` in `get_engine()`, so the month errors are their own classes (`InvalidMonthError`, `MonthNotFoundError`) and the route never catches a bare `ValueError`. A test that removes `DATABASE_URL` proves a configuration error still returns 500, not a 4xx.
- **Make a test fail for the right reason.** Two layers return 422 for a bad month (the `Query` pattern and the `InvalidMonthError` handler), so the status code alone cannot tell them apart; checking `detail[0]['loc'] == ['query', 'month']` proves the pattern produced it. Likewise the unknown-month test checks the message, because a missing route also returns 404.
- **Prove regex traps with a mutation.** `\d` accepts non-ASCII digits and `$` can accept a trailing newline. Changing `[0-9]` to `\d` made the Arabic-Indic digit case fail, and changing `fullmatch` to `match` made three format cases fail, so both guards are tested, not assumed.
- **A cached dependency can hide an environment test.** `get_engine()` is cached, so deleting `DATABASE_URL` had no effect and the first run returned 200 where 500 was expected. The test has to call `get_engine.cache_clear()` after removing the variable; otherwise it passes or fails depending on which tests ran earlier.
- **Framework validation is part of the API contract.** Typing `dealer_id` as `int` gives FastAPI's 422 for bad input and keeps oversized numbers from reaching the database as text; changing it to `str` made the non-integer cases and the oversized-id case return 500. `response_model=list[MonthlyPerformance]` stops malformed database output reaching clients. Mutating either one made targeted tests fail.
- **An empty filtered result is not the same as a missing entity.** A real dealer can legitimately have no rows inside a requested month window, so dealer existence is checked separately only when the filtered history is empty. Mutating the logic in either direction proved both `200 []` and 404 are protected.
- **Mutation tests should exercise both sides of an ambiguous branch.** Removing the dealer-existence raise proved unknown dealers cannot become empty results; forcing the raise for every empty result produced eight failures and proved valid empty windows cannot become 404s.
- **Read the staged diff, not just the test results.** While adding the range handler, the Day 18 `/performance` handler was also changed to catch `InvalidMonthRangeError`. No test covers an edit nobody intended, so only `git diff --cached src/api.py` showed it; it was reverted before the commit.
- **A safety-net handler can hide weakened validation.** The dealer history route has both a `Query` pattern and a handler that return 422, so the status code cannot say which layer rejected the input. Asserting `detail[0]['loc'] == ['query', 'start']` proves the pattern did; removing the anchors from either pattern failed one test each.
- **A floating label is a hidden dependency.** The first CI run failed after 24 seconds: the runner reported that Python 3.12.7 (x64) was not found for Ubuntu 26.04, and GitHub's notice on the same run said the `ubuntu-latest` label would migrate to a newer Ubuntu release. Pinning `runs-on: ubuntu-24.04`, `postgres:18.6` and Python 3.12.7 reduces environment drift, so a newer image or patch release is adopted deliberately rather than by surprise; GitHub still updates the contents of the `ubuntu-24.04` image over time.
- **A local rehearsal cannot catch runner differences.** A fresh clone, a fresh virtual environment and a scratch database rebuilt from the SQL scripts passed all 343 tests on the Mac, yet the first CI run still failed because the runner's operating system differed. Rehearse locally to remove your own mistakes, expect the platform to reveal the rest, and iterate on a branch so `main` never shows a red run.
- **Read the real status, not a stale page.** A signed-out Actions page kept showing a run as in progress for over five minutes after it had finished green in 54 seconds, which led to a wrong first guess about a slow install. Reload, sign in, and check the step list and annotations before drawing conclusions.
- **A PostgreSQL aggregate can change a column's type.** The monthly `dealer_monthly_performance.units_sold` value was verified with `pg_typeof` as `bigint`; summing it again for the regional aggregation yields PostgreSQL `numeric`, which initially surfaced as `211.0` instead of `211`. Casting the regional `SUM(units_sold)` back to `bigint` preserves the integer API contract at the SQL source instead of hiding the type change in Python.
- **Test a real query against states the dataset does not contain.** The committed data has no missing or zero targets. Opening a connection, starting a transaction, changing the rows, pointing `get_engine` at that connection with `monkeypatch`, calling the real function and rolling back exercised the NULL and zero-target rules for real, followed by a restore check. Patching `pandas.read_sql` globally is safe for one call but silently wrong if the same test also runs a real query.
- **A correct-looking result does not prove an ordering contract.** Removing `ORDER BY dmp.month` from the regional query initially left all 75 behavioral tests green because PostgreSQL happened to return the grouped rows in chronological order. A focused query-contract test that captures the generated SQL killed the mutation and raised the regional database suite to 76 tests.
- **Value equality does not prove a JSON numeric type.** Changing `units_sold` or `dealer_count` from `int` to `float` in `RegionMonthlyPerformance` initially survived because values such as `211` and `211.0` compare equal in Python. A focused API test now checks parsed JSON types explicitly; mutations of `dealer_count`, `units_sold` and `target_units` to floats each fail that test.
- **Runtime behavior tests do not protect an architectural invariant.** All 458 existing tests could pass even if the same month regex were copied back into several files. Day 23 added focused contract tests that inspect the OpenAPI schemas and source files so the single-source design itself is enforced, not just the values it currently accepts.
- **Derive representations from one canonical rule.** `MONTH_FORMAT` holds the only strict ASCII `YYYY-MM` regex literal. `MONTH_QUERY_PATTERN` adds the FastAPI anchors and `_MONTH_RE` compiles the same value for database-layer `fullmatch` checks, so changing the format has one source of truth while preserving layer-specific behavior.
- **An aggregate endpoint does not automatically need a not-found state.** Dealer and region history identify entities that can be invalid, but the network itself always exists. For `GET /performance/trend`, a valid range outside the data therefore returns `200 []` rather than introducing a `NetworkNotFoundError`.
- **Mutation checks are strongest when scoped to the exact function or model under test.** Day 24 mutation scripts limited replacements to `get_network_performance_history()`, the `/performance/trend` route and `NetworkMonthlyPerformance`, restored files byte-for-byte after every mutation, and treated a skipped mutation as no evidence rather than a pass.
- **List the exceptions you mean to translate, not their base class.** The month errors and the missing-`DATABASE_URL` error all subclass or are plain `ValueError`, so a bare `except ValueError` in the trend route would report a server misconfiguration as a client 422. In a local mutation check, widening the handler failed the missing-URL test.
- **Validate at the API boundary even when the database also validates.** Removing or weakening the ranking month pattern and limit bounds could still end in 422 from the database layer. The tests therefore pin `detail[0]['loc']` so they prove FastAPI query validation rejected the request at the intended layer.
- **Know the grain of the source table before writing synthetic tests.** `sales_monthly` has several model rows per dealer-month. The first tie and rounding fixtures did not account for those multiple rows, so the resulting totals were inflated. The corrected tests zero all matching rows first and then set exactly one controlled row.
- **An equivalent mutant is not necessarily a behavioral gap.** Replacing `ROW_NUMBER()` with `RANK()` produces the same rank values here because `dealer_id` is a unique final tie-break. That mutation is therefore killed only by the SQL-structure contract, which intentionally protects the chosen implementation contract.
- **Synthetic edge cases are valuable when committed data has no natural example.** The real dataset has no pair whose raw achievement order differs while the displayed one-decimal values tie. The behavioral evidence that ranking uses raw rather than rounded achievement therefore comes from a deliberately constructed transactional fixture; the SQL contract also pins the raw expression structurally.
- **Rank before limiting when ranks are part of the contract.** The query assigns `ROW_NUMBER()` over the full eligible month first, then applies the optional limit, so a limited response preserves global ranks instead of recomputing a local ranking.
- **An empty ranking is not the same as a missing month.** Month existence is checked separately from rankability. An existing month with all targets missing or zero returns `200 []`, while a well-formed month with no data raises `MonthNotFoundError` and returns 404.
- **Centralize an aggregation rule at the grain where it is defined.** The regional-history, network-trend and cross-region snapshot queries repeated the same weighted-achievement and missing-target logic. A single `GROUPING SETS` view now produces both regional and network grains directly from dealer-month rows, so the business rule is defined once while each consumer only filters and orders its required grain.
- **Fresh data still needs planner statistics.** A database can be logically correct yet perform badly immediately after loading. The Day 27 rollup exposed this in CI: adding `ANALYZE;` after the load reduced the representative estimated plan cost from about 584k to 12.9k and restored pytest from 84–124 seconds to 9.21 seconds.
- **Pin external numeric boundaries independently of production constants.** The Day 28 tests use the PostgreSQL signed-`bigint` boundary `2**63 - 1` directly rather than deriving it from `db.MAX_LIMIT`, so an accidental change to the production constant cannot move the test boundary with the bug.
- **Test observable contracts rather than forcing an internal implementation.** The Day 29 API mutation replacing `to_records()` with raw `to_dict("records")` survived. A direct Pydantic probe showed the two paths are behaviorally equivalent at this response boundary because NaN is serialized as JSON null. The test therefore pins the HTTP null contract rather than requiring a particular conversion helper.
- **Serialization equivalence depends on the response field type.** Day 30 provided the contrasting case: funnel counts are `int | None`. Missing regional data makes pandas promote an integer column to float with NaN, so `to_records()` must normalize that missing value to `None` before response validation. Replacing it with raw `to_dict("records")` was therefore non-equivalent and was killed by three focused API tests.

---

## 8. Daily log

**Day 1: Dealer performance with pandas.** Loaded sales, targets and dealer master data; filtered September 2026; aggregated by dealer; calculated target achievement; flagged dealers under 80%.

**Day 2: Python fundamentals and plain-CSV analysis.** Rebuilt the same logic with the built-in `csv` module, functions, dictionaries and loops, including a data-integrity check for unknown dealer IDs. Showed the logic was understood without pandas.

**Day 3: Inventory aging and overstock risk.** Added available and aged inventory, aged percentage, months of supply, zero-sales handling and ranking by inventory aging.

**Day 4: Combined dealer scorecard.** Merged sales and inventory analytics into one scorecard with four flags: `sales_risk`, `inventory_risk`, `combined_risk`, `early_overstock_watch`.

**Day 5: PostgreSQL schema and data loading.** Created the relational schema, loaded the CSVs, and wrote joins, aggregations and CTE-based September performance queries.

**Day 6: Inventory analytics in PostgreSQL.** Recreated the inventory logic in SQL, with NULL-safe flags via `COALESCE` and `high_supply` defined once.

**Day 7: Reusable views and SQL scorecard.** Created `dealer_performance`, `inventory_supply` and `dealer_scorecard` views. A cross-check script compared pandas and PostgreSQL for 40 dealers; all four flags matched for every dealer.

**Day 8: Python-to-PostgreSQL integration.** Connected through SQLAlchemy and psycopg with `DATABASE_URL`. Validated 40 dealers, unique IDs, risk counts (12 / 9 / 1 / 3) and no NULLs in the flags.

**Day 9: Safe parameterized query layer.** Built `get_scorecard(region, risk)` in `src/db.py` with bound parameters, a whitelist for risk columns, exact case-sensitive region matching and deterministic ordering. Both injection strings return no records.

**Day 10: FastAPI application.** Added `GET /health` and `GET /dealers` with 200, 400 and 500 behaviour, no `DATABASE_URL` leakage, NaN-to-null conversion and Swagger UI at `/docs`.

**Day 11: Pytest test suite.** Converted script-style validations to pytest using `parametrize`, `pytest.raises`, `TestClient` and `monkeypatch`; added `pytest.ini` so `src/` is importable. Region × risk counts are tested across all five regions.

**Day 12: Single-dealer endpoint.** Added `GET /dealers/{dealer_id}` (200 / 404 / 422) with `get_dealer` in `db.py`. Moved `to_records` into `db.py` as the shared NaN-safe conversion. Suite grew from 25 to 31 tests. Pushed as `64d3f7b` (code and tests) and `c6577f1` (README). Follow-up fix `d0b7ef6` removed a stray shell command from `requirements.txt`.

**Day 13: Pydantic response model.** Added `src/models.py` with a 17-field `Dealer` model. The five fields the SQL can return as NULL (`target_units`, `achievement_pct`, `avg_days_available`, `aged_pct`, `months_of_supply`) are typed `| None` with descriptions. Applied it with `response_model` to both endpoints. Added tests for the exact field set, null acceptance and invalid data returning HTTP 500 (suite 31 to 34). Pushed as `ea7e19d` (code and tests) and `37f4b71` (README).

**Day 14: Region summary endpoint.** Added `sql/day14_region_summary.sql` and `get_region_summary()` in `db.py` (one row per region, `COUNT(*) FILTER` per risk flag), a six-field `RegionSummary` model, and `GET /regions/summary`. Tests check every region's counts against independently derived values, the network totals (40 / 12 / 9 / 1 / 3), the field set and the alphabetical order (suite 34 to 44). Pushed as `e7eddf7` (SQL) and `ec0f00c` (code and tests).

**Day 15: Ranked at-risk dealers endpoint.** Added `sql/day15_at_risk_dealers.sql` (risk tiers and `ROW_NUMBER()`), `get_at_risk_dealers(limit)` in `db.py` with a bound `LIMIT`, a `RankedDealer` model (the `Dealer` fields plus `rank` and `risk_tier`) and `GET /dealers/at-risk`, registered before `/dealers/{dealer_id}`. Ranking: tier, then months of supply (highest first), then dealer id. Tests cover tier counts (1 / 3 / 8 / 8), continuous ranks, within-tier order, anchor positions and `limit` handling (suite 44 to 57). A mutation check confirmed the ordering tests fail when the supply ordering is removed. Pushed as `59ee7c1` (SQL) and `0488e1e` (code and tests).

**Day 16: Reproducible setup.** Pinned the direct dependencies to the versions the suite passes with, split `requirements.txt` (runtime) from a new `requirements-dev.txt` (pytest, httpx2, Black, Ruff), and updated the setup steps. A clean-clone test (fresh clone, new virtual environment, install from `requirements-dev.txt` only) gave 57 passed with Ruff and Black clean. An initial bare `black` command reported Black 24.8.0 instead of the pinned 26.10.1, and `which -a` showed Conda copies of `black` and `pytest` on the PATH, so the final checks were run through `python -m`. Committed as `6178da2`.

**Day 17: Monthly dealer performance SQL layer.** Added `dealer_monthly_performance` to `sql/03_views.sql`, with one row per dealer and month. Months are derived from the union of sales and target months, sales are aggregated by dealer and month before joining, and every dealer is crossed with every available month so missing sales become zero. The existing `dealer_performance` view is now a thin September 2026 compatibility view, leaving `inventory_supply` and `dealer_scorecard` unchanged. The new view contains 960 rows across 40 dealers and 24 months. A rollback test with a temporary dealer confirmed all 24 dealer-month rows appear with zero sales when no activity exists. An independent pandas comparison matched SQL for all 960 dealer-months, the September scorecard matched the pre-refactor export byte-for-byte, and the existing suite remained at 57 passed. Inventory was verified as a single snapshot: all 4,041 inventory rows imply September 30, 2026. Committed as `cfdade0`; README documentation as `0b31cad`.

**Day 18: Monthly performance Python/API layer.** Wrote the tests first and reviewed the red run before implementing. Added `get_available_months()` and `get_monthly_performance(month)` in `src/db.py`, with strict ASCII `YYYY-MM` validation (`re.fullmatch` on `[0-9]{4}-(0[1-9]|1[0-2])`, checked before any database call), dedicated `InvalidMonthError` and `MonthNotFoundError` exceptions, and deterministic dealer ordering. Added the `MonthlyPerformance` Pydantic model and the `GET /performance?month=YYYY-MM` endpoint. The endpoint requires a month, returns 422 for malformed input, 404 (`Month 2030-01 not found`) for a well-formed month with no data, and preserves nullable target and achievement fields; a missing `DATABASE_URL` still returns 500. Tests cover all 24 months, CSV-to-SQL equivalence across all 960 dealer-month rows, boundary months, malformed formats, nullability, missing `DATABASE_URL`, response validation and exception translation. Mutation checks: removing `ORDER BY` failed 25 tests; disabling the empty-result rule failed the three unknown-month tests; weakening `fullmatch` to `match` failed three format cases; replacing `[0-9]` with `\d` failed the Arabic-Indic digit case; weakening the API pattern, removing the `MonthNotFoundError` handler and removing the `InvalidMonthError` handler each failed their targeted tests. Suite 57 to 129. Committed as `4753341` (query and tests) and `fc34fbd` (endpoint and tests).

**Day 19: Dealer-level monthly performance history.** Wrote the database and API tests first, then added `get_dealer_performance_history(dealer_id)` in `src/db.py` and `GET /dealers/{dealer_id}/performance` in `src/api.py`. The query returns all monthly sales and target rows for one dealer, ordered from 2024-10 through 2026-09, and raises the dedicated `DealerNotFoundError` when the dealer has no history. The API reuses the `MonthlyPerformance` response model, translates only `DealerNotFoundError` to HTTP 404 (`Dealer {id} not found`), leaves FastAPI path validation responsible for non-integer ids (422), and keeps unrelated configuration failures such as a missing `DATABASE_URL` as HTTP 500. Tests cover all 40 dealers with 24 months each, independent CSV-to-database equivalence, chronological ordering, exact fields, nullability, unknown dealers (including a very large integer id), non-integer ids, response validation, a missing `DATABASE_URL`, and regression protection for the existing dealer routes. Database mutation checks: removing `ORDER BY month` failed 42 tests; removing the dealer filter failed 89; disabling the empty-result rule failed exactly the six unknown-dealer cases. API mutation checks: catching a bare `ValueError` failed one test (the missing-`DATABASE_URL` case); removing the `DealerNotFoundError` handler failed the six unknown-dealer cases; changing `dealer_id` from `int` to `str` failed four, including the oversized id, which reached the database as text and returned 500; removing `response_model` failed the invalid-response test. The first run of the missing-`DATABASE_URL` test returned 200 instead of 500 because `get_engine()` is cached; clearing the cache in the test fixed it. Suite grew from 129 to 276 tests. Committed as `2dfecdb` (query and tests), `aba85b2` (endpoint and tests) and `f3523ec` (README).

**Day 20: Dealer-history month-range filtering.** Extended `get_dealer_performance_history()` and `GET /dealers/{dealer_id}/performance` with optional inclusive `start` and `end` bounds in strict ASCII `YYYY-MM` format while preserving the Day 19 full-history default. `start` alone runs through the latest month, `end` alone begins at the earliest month, equal bounds return one month, and a valid dealer with no rows in the requested window returns an empty result / HTTP 200 `[]`. Because an empty filtered result no longer means the dealer is unknown, the database layer queries `dealers` only when the range result is empty; an unknown dealer still raises `DealerNotFoundError` and returns 404. Added the dedicated `InvalidMonthRangeError` for `start > end`, while malformed bounds raise `InvalidMonthError`. FastAPI validates the query format first and the dealer-history route also translates database-layer `InvalidMonthError` and `InvalidMonthRangeError` to 422 as a safety net without catching broad `ValueError`. Tests cover full history, one-sided and two-sided ranges, inclusive boundaries, equal bounds, before-data and after-data empty windows, unknown dealers, non-string direct DB inputs, malformed ASCII and Unicode month formats, API validation locations, DB/API equivalence, and the database-layer validation safety net. Database mutations: changing `>=` to `>` on `start` failed 7 tests; changing `<=` to `<` on `end` failed 7; removing the reversed-range guard failed 2; removing the dealer existence check failed 1; forcing every empty result to raise failed 8 across the DB and API range suites; changing `fullmatch` to `match` failed the 2 trailing-newline DB cases. API mutations: removing the `InvalidMonthRangeError` handler failed the 2 reversed-range cases; weakening the `start` or `end` query pattern each failed the corresponding trailing-newline validation-location test; widening the handler to bare `ValueError` failed the missing-`DATABASE_URL` regression test; and removing `InvalidMonthError` from the final safety-net tuple made its targeted test return 500 instead of 422. After the safety net was added, the two weakened-pattern mutations were repeated and still failed on the FastAPI validation-location assertion, proving a DB-generated 422 cannot hide API regex drift. Suite grew from 276 to 343 tests. Committed as `c3731d9` (database range query and tests), `1e1059f` (API range filters and tests), and `1ea6c07` (README).

**Day 21: Continuous integration with GitHub Actions.** Inspected the project for environment assumptions before writing the workflow: `src/db.py` reads only `DATABASE_URL` and passes it to `create_engine`; the three SQL scripts contain no absolute paths, roles or owners; the loader uses relative `data/` paths, and all seven CSV files are committed. Rehearsed locally first: built a scratch database from the three scripts with `ON_ERROR_STOP=1` (loader rows 40 / 8 / 7,680 / 960 / 960 / 4,041; 960 dealer-month rows) and ran the suite against it (343 passed), then repeated the run from a fresh `git clone` with a new virtual environment installed from `requirements-dev.txt` (343 passed). Added `.github/workflows/ci.yml` on branch `ci-day21`: triggers on `push`, `pull_request` and manual dispatch with read-only `contents` permission; a `postgres:18.6` service container with a health check; `actions/checkout@v7` and `actions/setup-python@v7` with Python 3.12.7 and pip caching; install from `requirements-dev.txt`; database build from the three SQL scripts with `ON_ERROR_STOP=1`; `black --check` and `ruff check` on `src/db.py`, `src/api.py`, `src/models.py` and `tests`; then `python -m pytest -q`. CI #1 (`086b7fe`, runner `ubuntu-latest`) failed in 24 seconds in the Python setup step: the annotation read 'The version 3.12.7 with architecture x64 was not found for Ubuntu 26.04', and GitHub's notice on the same run said the `ubuntu-latest` label would migrate to Ubuntu 26 beginning 19 October 2026. Pinning `runs-on: ubuntu-24.04` (`93ba0b0`) fixed it: CI #2 on the branch passed every step in 54 seconds, and after a fast-forward merge CI #3 on `main` passed in 1 minute 45 seconds. A signed-out Actions page briefly showed the green run as still in progress, which led to a wrong first guess about a slow install; the step list showed install taking 16 seconds. Committed as `086b7fe` (workflow) and `93ba0b0` (runner pin) on `ci-day21`, fast-forwarded to `main`; the README badge and CI section followed in a separate documentation commit.

**Day 22: Regional monthly performance history.** Added `get_region_performance_history(region, start=None, end=None)` and `GET /regions/{region}/performance`, using the existing `dealer_monthly_performance` view plus `dealers` for exact, case-sensitive regional aggregation. The query returns one row per region-month with `dealer_count`, total `units_sold`, total `target_units` and weighted `achievement_pct` calculated from total units divided by total target rather than averaging dealer percentages. If any contributing dealer lacks a target, regional `target_units` and `achievement_pct` are NULL; a zero regional target remains `0` while achievement is NULL. Optional `start` and `end` bounds are inclusive, use the same strict ASCII `YYYY-MM` validation as dealer history, and preserve the distinction between a valid region with an empty window (`200 []`) and an unknown region (`RegionNotFoundError` / HTTP 404). Added the six-field `RegionMonthlyPerformance` response model and kept malformed bounds and reversed ranges at 422 while unrelated failures such as a missing `DATABASE_URL` remain 500. Database tests cover all 5 regions × 24 months, independent CSV equivalence, reconciliation to network monthly totals, weighted-versus-average achievement, inclusive ranges, exact region matching, injection attempts, missing-target and zero-target rules, JSON-friendly numeric values and explicit SQL ordering. Database mutation checks killed boundary, region-filter, weighted-calculation, dealer-count, NULL-rule, zero-target, not-found and empty-window mutations; removing `ORDER BY` initially survived, so a focused SQL-contract test was added and then killed that mutation exactly, leaving 76 database/query tests. API tests cover all regions, inclusive range filtering, strict query-validation locations, 404/422 detail, the missing-`DATABASE_URL` 500 regression, response-model validation, NaN-to-null serialization and JSON numeric types. The first API mutation batch killed all 9 handler, regex and response-model mutations. In the second batch, 8 of 10 mutations were killed immediately; changing `units_sold` or `dealer_count` to floats survived until a focused JSON type test was added, after which float mutations for `dealer_count`, `units_sold` and `target_units` were all killed. The suite grew from 343 to 458 tests. Committed as `53502d2` (database query and tests), `0cbf7a6` (endpoint, response model and tests) and `73cdc19` (README). At the start of Day 22, the Day 21 follow-up commit `86fa72e` added a 15-minute timeout to the CI job (merged, CI green). After the three Day 22 commits were pushed, CI #7 on `73cdc19` passed in 54 seconds on the fresh runner, running Black, Ruff and all 458 tests.

**Day 23: Single-source month-format validation.** Refactored the strict ASCII `YYYY-MM` rule without changing API or database behavior. Before the refactor, the same month regex appeared seven times: twice in `src/db.py` and five times in FastAPI `Query` declarations. Added `MONTH_FORMAT = r"[0-9]{4}-(0[1-9]|1[0-2])"` in `src/db.py`, derived `MONTH_QUERY_PATTERN` with explicit `^` and `$` anchors for FastAPI, and compiled `_MONTH_RE` from the same canonical value for database-layer `fullmatch` validation. `get_monthly_performance()` and `_validate_optional_month()` keep their existing distinct `InvalidMonthError` messages, while all five FastAPI month parameters now use `MONTH_QUERY_PATTERN`. Added `tests/test_month_format_contract.py` with 7 tests: five parameterized OpenAPI checks proving every month parameter exposes the shared pattern, one test pinning the canonical and anchored values, and one source-level guard requiring the regex fragment to appear exactly once in `src/`, in `src/db.py`. The red run failed all 7 new tests before implementation while the existing 458 tests still passed; after the refactor the suite reached 465 passing tests. Mutation checks killed every tested drift: weakening the shared month rule failed 24 tests; removing the `^` anchor failed 2; removing the `$` anchor failed 7; replacing `fullmatch` with `match` in the optional-bound validator failed 4 and in the required-month validator failed 3; weakening any one of the five FastAPI month parameters failed its targeted API and contract tests; and adding an exact duplicate regex literal elsewhere failed the single-source guard. Black, Ruff and `git diff --check` were clean, and a source grep showed the regex literal only at `src/db.py:41`. Committed as `add912d` (code and 7 contract tests) and `c552e9b` (README). CI #9 on `add912d` passed in 51 seconds on the runner, running Black, Ruff and all 465 tests.

**Day 24: Network-wide monthly performance trend.** Wrote the database tests first and confirmed a clean red state with all 37 cases failing only because `get_network_performance_history()` did not yet exist. Added the query in `src/db.py`, returning one row per month across all 40 dealers with `dealer_count`, total `units_sold`, nullable `target_units` and weighted `achievement_pct = SUM(units_sold) * 100.0 / SUM(target_units)`. Optional `start` and `end` bounds are inclusive and reuse the shared strict ASCII month validation. If any dealer target is missing, network target and achievement are NULL; a zero total target remains `0` with NULL achievement; and a valid empty window returns an empty result because the network has no not-found state. Database tests cover independent CSV recomputation, reconciliation to the sum of all five regional rows, inclusive ranges, empty windows, JSON-friendly numeric types, real missing- and zero-target states inside rolled-back transactions, and explicit SQL ordering. All 14 tested database mutations were killed, covering inclusive boundaries, wrong bound values, ordering, aggregate type, weighted-versus-average calculation, missing-target rules, zero-target handling, dealer count, reversed ranges, start/end validation and empty-window behavior. The database layer was committed as `7297bd9`, with 502 tests passing. Next, expanded the month-format contract from five to seven FastAPI parameters and wrote the network API tests before adding `NetworkMonthlyPerformance` and `GET /performance/trend`. The endpoint returns all 24 months by default, accepts optional inclusive `start` and `end`, returns `200 []` for a valid empty window, uses FastAPI query validation for malformed bounds, translates only the intended database month/range errors to 422, preserves unrelated failures such as a missing `DATABASE_URL` as 500, validates response output and normalizes nullable values through `to_records()`. The focused API/month-contract set reached 40 passing tests and the full suite reached 535. All 18 tested API/model mutations were killed, including response-model removal/swap, weakened query patterns, swapped or dropped bounds, narrow/broad/wrong exception handlers, status/detail changes, bypassing `to_records()`, nullable-field changes and integer-to-float model changes. The API/model layer was committed as `d341dca`. Black, Ruff and `git diff --check` were clean. Suite grew from 465 to 502 to 535 tests. The README was committed as `7f67878`. CI #11 on `7297bd9` passed in 59 seconds with 502 tests, CI #12 on `d341dca` passed in 1 minute 12 seconds with 535 tests, and CI #13 on `7f67878` passed in 59 seconds with 535 tests, each running Black, Ruff and the full suite.

**Day 25: Month-aware dealer performance ranking.** Wrote the database tests first and confirmed the red checkpoint at 57 failed / 535 passed because `get_monthly_dealer_ranking()` did not yet exist. Added `get_monthly_dealer_ranking(month, limit=None)` and `GET /performance/ranking?month=YYYY-MM[&limit=N]`. Dealers are ranked by raw, unrounded achievement percentage with `dealer_id` as the deterministic tie-break; missing-target and zero-target dealers are excluded before ranking, and `ROW_NUMBER()` produces contiguous ranks. The optional limit is validated from 1 through `2**63 - 1`, cast to PostgreSQL `bigint`, and applied after ranking so global ranks are preserved. A well-formed month with no data raises `MonthNotFoundError`, while an existing month with no rankable dealers returns an empty result. The database phase added 57 tests using an independent CSV oracle with exact `Fraction` arithmetic, synthetic tie and raw-versus-rounded cases, rolled-back missing/zero-target states and a SQL-structure contract. The green database suite reached 592 tests. A guarded database mutation run killed 18 of 18 mutants with 0 survivors and 0 errors. Two mutations were killed only by the SQL-structure contract: replacing `ROW_NUMBER()` with `RANK()` and removing the outer `ORDER BY rank`. The `RANK()` mutant is behaviorally equivalent with today's query because unique `dealer_id` is the final tie-break; the contract test deliberately pins the chosen SQL structure. The raw-versus-rounded behavioral rule required a synthetic fixture because the committed data has no natural rounding-sensitive pair. The database layer was committed as `7864a86`. Next, added the seven-field fully non-null `RankedMonthlyPerformance` model and the ranking endpoint with the shared strict month pattern, `limit` bounds through `MAX_LIMIT`, explicit `InvalidMonthError`/`InvalidLimitError` to 422 handling, `MonthNotFoundError` to 404 handling and response normalization through `to_records()`. The month-format contract expanded from seven to eight FastAPI parameters. The API red checkpoint was exactly 20 failed / 593 passed; the green full suite reached 613 passing tests. A guarded API/model mutation run killed 19 of 19 mutants with 0 survivors and 0 errors, covering response-model removal, lower/upper limit bounds, required month and pattern validation, narrow/broad exception handling, status/detail changes, serialization, limit forwarding, nullability, numeric rank type and response-field order. The API/model layer was committed as `4efeb23`. CI #15 on `7864a86` passed with 592 tests and CI #16 on `4efeb23` passed with 613 tests; both rebuilt PostgreSQL and passed Black, Ruff and the full test suite.

**Day 26: Cross-region monthly performance snapshot.** Wrote the database tests first and reached the final red checkpoint at 89 failed / 613 passed before implementation. Added `get_regional_performance_snapshot(month)`, returning exactly one row for each of the five regions for a required month, ordered alphabetically by region. Achievement uses the same weighted rule as regional history and network trend: regional `SUM(units_sold) * 100.0 / SUM(target_units)`, never an average of dealer percentages. If any contributing dealer target is missing, the region remains present with null `target_units` and `achievement_pct`; a zero regional target remains `0` with null achievement. The query validates the shared strict ASCII `YYYY-MM` format, binds `:month`, uses one SQL query, raises `MonthNotFoundError` for a well-formed missing month, and casts summed units to PostgreSQL `bigint` to preserve integer semantics. The database phase added 89 tests covering all 24 months against an independent CSV oracle, reconciliation to regional-history and network-trend results, weighted-versus-average behavior, missing- and zero-target states inside rolled-back transactions, SQL execution/binding contracts and pandas dtypes. The database suite reached 702 passing tests. In the first mutation run, `COUNT(*) -> COUNT(target_units)` for `dealer_count` survived because the committed dataset has targets for every dealer. The existing missing-target transaction test was strengthened to require the affected region's `dealer_count` to remain unchanged; the rerun then killed that mutant, leaving 18 of 18 database mutants killed with 0 survivors and 0 errors. The database layer was committed as `9ff3b7e`.

Next, wrote the API tests before exposing `GET /performance/regions?month=YYYY-MM`. The red checkpoints were 1 failed / 10 passed in the shared month-format contract, 16 failed / 1 passed in the new endpoint file, and 17 failed / 703 passed in the full suite. The endpoint reuses the existing six-field `RegionMonthlyPerformance` model, requires the shared strict month pattern, translates `InvalidMonthError` to 422 and `MonthNotFoundError` to 404, normalizes results through `to_records()`, preserves integer JSON types, and keeps unrelated failures such as a missing `DATABASE_URL` at 500. API tests include OpenAPI model reuse, exact field/nullability contracts, mixed-null pandas serialization, a real rolled-back missing-target state, invalid response rejection and regression coverage for the existing performance routes. The shared month-format contract expanded from eight to nine FastAPI parameters. The green suite reached 720 passing tests. A hardened API mutation harness cleared bytecode between runs, enforced a timeout, treated pytest collection errors separately, restored `src/api.py` by SHA256 after every mutant, and killed 19 of 19 mutants with 0 survivors and 0 errors. The API layer was committed as `bc25b0b`. CI #18 for the database commit and CI #19 for the API commit both passed on `main`; CI #19 rebuilt PostgreSQL, passed Black and Ruff, and ran all 720 tests successfully. The three weighted regional/network/snapshot aggregations intentionally remain inline through Day 26 so Day 27 can extract the shared SQL logic behind already-pinned interfaces.

**Day 27: Shared monthly performance rollup.** Chose one PostgreSQL `monthly_performance_rollup` view using `GROUPING SETS` rather than chained aggregate views. The shared view produces both `(region, month)` rows and whole-network `(month)` rows directly from `dealer_monthly_performance`, with `region IS NULL` identifying the network grain because `dealers.region` is `NOT NULL`. This centralizes the weighted-achievement, missing-target and zero-target rules in one SQL definition. A chained-view design was rejected because aggregating already-summed `bigint` values again would promote PostgreSQL `SUM(bigint)` to `numeric`, require additional casts to preserve the existing integer contracts, and re-express the weighted rule instead of truly centralizing it.

The first Day 27 commit, `54623e3` (Add shared monthly performance rollup view with tests), added the view and 12 direct contract tests covering exact columns and PostgreSQL types, 120 regional rows plus 24 network rows, regional/network equivalence, rolled-back missing- and zero-target states, and the single `GROUPING SETS` definition. The suite reached 732 passing tests and CI #21 passed.

Before changing any consumer, a provenance-stamped baseline captured all 5 regions across 6 window variants, the same 6 network windows, all 24 snapshot months, 7 error paths, and baseline, missing-target and zero-target edge states. After each consumer was moved to the shared view, exact before/after comparison preserved DataFrame values, ordering and dtypes across every captured case.

The second Day 27 feature commit, `827edbd` (Refactor performance queries to use shared rollup view), changed `get_region_performance_history()`, `get_network_performance_history()` and `get_regional_performance_snapshot()` into filtered reads of `monthly_performance_rollup`. A consumer-contract test requires all three queries to read from the shared view and forbids `SUM(` and `GROUP BY` in their consumer SQL; existing structural tests continue to pin the required grain filters and deterministic ordering. The suite reached 733 passing tests and CI #22 passed on `main`.

The final Day 27 mutation campaign exercised 16 mutants. All 14 deployable non-equivalent mutants were killed, covering both missing-target CASE branches, dealer counting, zero-target handling, the `bigint` cast, regional and network grouping grains, the target sum, all three grain filters and all three ordering contracts. Two survivors were verified equivalent rather than treated as test gaps: changing `100.0` to `100` produced zero differing region-month results in a direct SQL comparison, and changing `JOIN dealers` to `LEFT JOIN dealers` produced zero unmatched dealer-month rows and zero differences across the complete rollup when compared in both directions with `EXCEPT`. Final result: 14 of 14 non-equivalent mutants killed, 2 verified equivalent survivors, 0 unresolved survivors and 0 errors.

CI #22 then exposed a performance issue that did not reproduce locally. Its original run took 86.02 seconds in pytest and its re-run 123.79 seconds, and CI #23, which added `--durations=15` for observability in commit `e989d31` (Show the slowest tests in CI), took 84.00 seconds. The same suite took about 9 seconds locally. Investigation showed that a freshly loaded database without planner statistics estimated the representative regional rollup query at about 584,068 cost, above the default `jit_above_cost` threshold of 100,000. Running `ANALYZE` reduced the estimate to about 12,917.

Commit `cbd3dd4` (Analyze tables after the load so rollup plans stay cheap) therefore added `ANALYZE;` after the final `\copy` in `sql/02_load.sql`, a deterministic source-level regression test proving that the load ends with analysis, and a JIT-aware plan-cost guard that runs only where PostgreSQL JIT is enabled and available. The source guard was mutation-tested by temporarily removing `ANALYZE;`, which made the test fail exactly as intended. A fresh local database ran 734 tests with the JIT-only guard skipped in 8.50 seconds, and its analyzed rollup plan cost was 12,916.93. CI #24 had JIT available, ran the guard instead of skipping it, passed all 735 tests in 9.21 seconds, and completed the full workflow in about 1 minute 2 seconds. The before/after result strongly supports missing planner statistics on the fresh CI database as the dominant contributor to the Day 27 test slowdown.

**Day 28: At-risk limit bigint boundary fix.** Reproduced the legacy `GET /dealers/at-risk?limit=N` failure for limits above PostgreSQL's 32-bit integer ceiling. The query still used `LIMIT CAST(:limit AS integer)`, while the newer monthly-ranking path already used `bigint` and the shared `MAX_LIMIT = 2**63 - 1` API bound. Added a dedicated 8-test regression file before changing production code. The red run failed all 8 tests for the intended reasons: three direct database large-limit cases overflowed, three API large-limit cases returned 500, the one-above-`bigint` API case returned 500 instead of 422, and the SQL contract still found `AS integer`.

Commit `152ae2d` (Fix at-risk limit overflow with bigint cast and upper bound) changed the legacy query cast to `bigint` and added `le=MAX_LIMIT` to the FastAPI parameter. Valid large limits including `2**31`, `99_999_999_999` and `2**63 - 1` now return the same globally ranked 20 dealers as the unbounded query, while `2**63` is rejected with 422 at `query.limit`. The focused green suite passed all 8 tests; the full local suite reached 742 passed with the JIT-only plan guard skipped.

A block-scoped mutation harness then verified three regression protections. Changing the SQL cast back to `integer` was killed by 7 of the 8 focused tests; removing `le=MAX_LIMIT` was killed by the one-above-maximum 422 test; and changing the bound to `MAX_LIMIT - 1` was killed by the valid `2**63 - 1` API case. Only pytest exit code 1 counted as a valid kill, both source files were restored byte-for-byte by SHA, and stale bytecode was cleared between runs. Final mutation result: 3 of 3 killed. CI #26 passed all 743 tests in 6.32 seconds and completed the workflow in about 56 seconds.

**Day 29: Monthly vehicle-model performance.** Started with the database layer and
defined one row per vehicle model that has `sales_monthly` rows for the requested
month. The query joins `vehicle_models` for `segment` and `msrp`, sums all units,
computes each model's raw share of network units, and calculates unit-weighted
`avg_sale_price` using only rows with a non-null price. Models with no rows are
omitted; a model with rows but zero total units remains present. A zero
network-unit denominator produces null share, a zero priced-unit denominator
produces null average price, malformed months raise `InvalidMonthError`, and a
well-formed month with no sales rows raises `MonthNotFoundError`.

The database phase added 19 tests covering independent CSV recomputation, network
rollup parity, catalog attributes, deterministic ordering, weighted-price edge
cases, zero-unit and all-null-price states, omitted models, month validation and
not-found handling. A transactional fixture proved that units from null-price rows
remain in total units but are excluded from the weighted-price denominator. The
mutation campaign killed all 10 non-equivalent mutants. The only survivor was the
behaviorally equivalent removal of the numerator's null-price filter, because
`avg_sale_price * units_sold` is already null when price is null and PostgreSQL
`SUM` ignores null values. The database layer was committed as `9084c4e`; CI #28
passed all 762 tests.

Next, wrote the API tests before adding the six-field `ModelMonthlyPerformance`
response model and `GET /performance/models?month=YYYY-MM`. The endpoint uses the
shared strict ASCII month pattern, translates `InvalidMonthError` to 422 and
`MonthNotFoundError` to 404, validates response output and returns normalized
records. Tests cover database parity, exact JSON types, OpenAPI field/nullability
and month-pattern contracts, malformed and missing months, explicit exception
translation, invalid response rejection, nullable serialization, a rolled-back
real-database zero-unit/null-price state and NaN-to-JSON-null behavior. The
endpoint's focused API tests pin the shared month pattern directly; the centralized
month-format contract remains at nine FastAPI parameters. The focused API suite
reached 17 passing tests and the full local suite reached 778 passed with the
existing JIT-only test skipped.

The API/model mutation campaign used a green baseline control, block-scoped source
mutations, strict pytest exit-code handling, byte-for-byte restoration and SHA-256
verification. It killed all 13 non-equivalent mutants. The sole survivor replaced
`to_records()` with raw pandas `to_dict("records")`; a direct probe confirmed this
is behaviorally equivalent at this response boundary because
`ModelMonthlyPerformance`/Pydantic serializes NaN as JSON null. The API/model layer
was committed as `0e78f5f`. CI #29 passed Black, Ruff and all 779 tests in 5.16
seconds.

**Day 30: Regional lead funnel analytics.** Started with the database layer and
defined one row per dealer region for one required month with seven fields:
`region`, `leads`, `test_drives`, `units_sold`, `test_drive_rate_pct`,
`drive_to_sale_pct` and `lead_to_sale_pct`. The query is anchored on `dealers`
so all regions remain representable, and sales are first aggregated to one
dealer-month before joining so the eight vehicle-model rows cannot multiply
lead counts. All three funnel rates are computed as ratios of regional sums,
not averages of dealer-level rates. `leads_monthly` defines whether the month
exists.

Completeness is measured against the full dealer count in each region. If any
dealer lacks a lead row, `leads`, `test_drives` and all three rates are null,
while complete sales totals remain available. If any dealer lacks a
sales dealer-month, `units_sold`, `drive_to_sale_pct` and `lead_to_sale_pct`
are null while complete lead metrics remain available. Zero remains distinct
from missing data. A dealer-month is considered sales-complete when an
aggregated sales row exists; all eight vehicle-model rows are not required.

The database phase added 44 focused tests covering all 24 months against an
independent CSV oracle, exact five-region shape and alphabetical ordering,
regional rollup reconciliation, fan-out protection, ratio-of-sums behavior,
missing lead and sales rows, whole-region lead absence, zero-versus-missing
semantics, the vehicle-model-row completeness boundary, strict month
validation and integer/float dtypes. A 29-mutant campaign killed all 29
implemented non-equivalent mutants, including join, completeness,
month-existence, zero-denominator, aggregation-grain and double-aggregation
type-promotion errors. A dedicated mean-of-dealer-rates mutant was not
mechanically generated because it requires a structural query rewrite rather
than a safe local source substitution; the ratio-of-sums contract is
independently pinned by the 24-month oracle and a deliberately divergent
transactional fixture. The database layer was committed as `3756f31`; CI #31
passed all 823 tests.

Next, added the required-but-nullable `RegionalFunnel` response model and
`GET /performance/funnel?month=YYYY-MM`. The route reuses the shared strict
ASCII month pattern, translates `InvalidMonthError` to 422 and
`MonthNotFoundError` to 404, calls the directly imported database function and
returns normalized records. The 21 focused API cases cover database parity,
exact seven-field ordering, JSON numeric types, OpenAPI required/nullability
contracts, missing sales and lead data, float-to-integer response coercion,
malformed and missing months, exact exception translation and existing-route
regressions.

The API/model mutation campaign killed all 17 mutants. Unlike Day 29, raw
pandas `to_dict("records")` was non-equivalent because NaN entering an
`int | None` response field fails validation rather than becoming JSON null;
that mutant was killed by three focused tests. The full local suite reached
843 passed with the JIT-only test skipped. The API layer was committed as
`9e21766`; CI #32 passed Black, Ruff and all 844 tests in 7.63 seconds.

**Day 33: Dealer funnel ranking.** Reused the canonical `dealer_monthly_funnel`
view without adding a new view or duplicating the funnel formulas. The query
joins dealer metadata, checks month existence separately from eligibility,
filters undefined lead-to-sale rates and applies the inclusive `min_leads`
threshold before `ROW_NUMBER()` ranks by raw conversion descending and dealer
ID ascending. The optional limit applies after ranking. Both numeric filters
use explicit PostgreSQL `bigint` casts; Python validates month, limit and
minimum leads in that order before acquiring the database. `limit` accepts
1 through `MAX_LIMIT` or None, and `min_leads` accepts 0 through `MAX_LIMIT`
with default 0. `MAX_LIMIT = 2**63 - 1`.

The database suite uses an independent CSV oracle with exact `Fraction`
arithmetic across all 24 months, plus rolled-back missing-row, zero-count,
tie and precision fixtures. The query was developed test-first. Subsequent
mutation hardening added SQL-capture tests for final ordering and both
explicit bigint casts. A fixture initially classified the inverted
existence check M51 as an execution error; moving the query invocation
into the test body resolved that classification without weakening the
harness. The final 229-test campaign killed 54 of 56 mutants with no errors.
M25 and M26 (`RANK()` and `DENSE_RANK()` in place of `ROW_NUMBER()`) are
behaviorally equivalent under the unique complete ordering keys within one
month. Raw score: 96.43%; adjusted: 54/54, or 100%. Database commits:
`0f03bf8` (CI #43, 1365 passed) and `9a0f53b` (CI #44, 1368 passed).

The API phase added 153 endpoint tests and one shared month-contract case
before implementation (RED: 154 failed, 17 passed). Added the eleven-field
`RankedDealerFunnel` model and `GET /performance/funnel/ranking` with required
strict ASCII month, optional bounded limit and inclusive minimum leads.
Only the required `drive_to_sale_pct` field is nullable. Missing lead or
sales dealer-months and zero leads are ineligible; zero units with positive
leads remain eligible, and zero test drives do not exclude a dealer with a
defined lead-to-sale rate. A valid lead month without eligible dealers
returns `200 []`, a well-formed month without lead rows returns 404, and
invalid parameters return 422. The route delegates to the database and
shared serializer without extra filtering, sorting or rounding. Focused
GREEN: 171 passed; full local regression: 1521 passed plus 1 skip. Commit
`1aeb638` passed all 1522 tests in CI #45.

The initial API/model campaign killed 62 of 63 mutants (98.41%), with M32
(raw pandas records instead of `to_records()`) surviving. Bypassing the
helper preserved HTTP behavior for the tested inputs. The structural test
in `a1290b3` pins exactly one call to the shared helper with the original
DataFrame; it does not establish a new HTTP behavioral difference and
intentionally constrains implementation. The hardened API file has 154
tests; combined with the 18 month-contract cases, the focused suite has 172.
The final primary campaign killed all 63 mutants, including M32. Four
separate supplementary probes (nullable `min_leads`, defaulted rank and two
field-order swaps) were also killed. All final campaigns restored the
production files byte-for-byte, had zero execution errors and no unresolved
survivors. Combined final campaigns executed 123 targeted mutants, killed
121 and retained two justified database equivalents (98.37% raw, 100%
adjusted, including structural contracts). These scores apply only to the
implemented mutation definitions, not exhaustive defect coverage.

Final local regression: 1522 passed and 1 JIT-only skip; CI #46 passed all
1523 tests. The API has 16 paths and the shared month-format contract covers
16 parameters. Known limitations: the two separate reads do not guarantee
a common snapshot under concurrent writes; nonnegative operational counts
are assumed rather than newly enforced; `min_leads` has no business-specific
cap below the signed-bigint maximum. Rates remain same-month operational
approximations, not cohort conversion measures.

**Day 34: Dealer funnel opportunities.** Reused the canonical funnel view and
regional ratio-of-sums benchmark to identify strictly positive opportunities.
Database and API implementations were committed separately (`26ca757`,
`9534cac`). The independent CSV Fraction oracle and transactional fixtures
protect completeness, threshold reranking, deterministic ties and precision.
The 30-place quotient is calculated before pandas/JSON float conversion;
identical serialized values can retain distinct ranks. See the Day 34 summary
above for RED/GREEN counts and mutation evidence, and section 6 for limitations.
CI #48 and #49 passed; final code baseline has 17 paths, 17 month parameters,
1921 CI passes and no failures. Mutation evidence was archived outside the
repository; no mutation harness or transient logs were committed.

---

## 9. Roadmap

**Next:** Day 35 — design first; scope to be decided.

**Then:**

- Richer FastAPI endpoints
- Additional sales and inventory queries, with more automated API tests
- A full lock file for transitive dependencies, plus branch protection for CI
- LLM APIs and retrieval-augmented generation (RAG)
- Dealer operations copilot and supply-chain risk assistant
- AI agents
- Docker and Azure/cloud deployment
