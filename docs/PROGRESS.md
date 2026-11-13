# Automotive AI Lab: Project Progress Summary

**Last updated:** 13 Nov 2026 · **Latest code commit:** `93ba0b0` (Pin CI runner to ubuntu-24.04) · **Tests:** 343 passing · **CI:** passing on `main`
**Repository:** https://github.com/PRASHANTAPAUDEL24/automotive-ai-lab
**Author:** Prashanta Paudel

---

## 1. Current state (read this first)

The project builds a data and analytics foundation for AI-powered automotive dealer operations. It uses a fully **synthetic** dataset for the fictional brand **Vertex Motors** with 40 dealers across 5 regions. Sales and target data cover 24 months from October 2024 through September 2026; inventory is a single snapshot as of September 30, 2026.

**What works today**

- Dealer sales and inventory analytics, implemented twice (pandas and PostgreSQL) and cross-checked against each other.
- Four reusable PostgreSQL views, from a monthly `dealer_monthly_performance` view to a `dealer_scorecard` view with four business-risk flags.
- A safe, parameterized Python query layer (`src/db.py`).
- A FastAPI service with seven endpoints:

| Endpoint | Behaviour |
|---|---|
| `GET /health` | Returns `{"status": "ok"}` |
| `GET /dealers` | Scorecard for all dealers; optional `region` and `risk` filters. Unsupported `risk` returns 400; unknown region returns `[]` |
| `GET /dealers/{dealer_id}` | One dealer scorecard. Unknown id returns 404; non-integer id returns 422 |
| `GET /regions/summary` | One row per region: dealer count and counts of sales-risk, inventory-risk, combined-risk and early-overstock-watch dealers |
| `GET /dealers/at-risk` | The 20 sales-risk or inventory-risk dealers, ranked (1 = most urgent). Optional `limit` (minimum 1) keeps the global ranks; 0 or a non-integer returns 422 |
| `GET /performance` | Dealer sales and target performance for the required `month` (`YYYY-MM`), 2024-10 to 2026-09. 422 for a malformed month, 404 for a well-formed month with no data. |
| `GET /dealers/{dealer_id}/performance` | One dealer's sales and target history, oldest first. Optional inclusive `start` and `end` filters use `YYYY-MM`; no bounds returns all 24 months. A valid dealer with no rows in the window returns `[]`; unknown id returns 404; malformed bounds, `start > end`, or a non-integer id return 422. |

- Pydantic response models (`Dealer`: 17 fields, 5 nullable; `RegionSummary`: region plus 5 count fields; `RankedDealer`: `Dealer` plus `rank` and `risk_tier`; `MonthlyPerformance`: 6 fields, 2 nullable) that validate API output and drive the schemas shown in `/docs`.
- A pytest suite of 343 tests: 276 tests through Day 19, plus 35 dealer-history range database/query tests and 32 dealer-history range API tests, run without starting a server.
- GitHub Actions CI on every push and pull request: a fresh `ubuntu-24.04` runner with a `postgres:18.6` service rebuilds the database from the SQL scripts, then runs Black, Ruff and the full test suite.

**Next step:** Day 22: add a regional or network-wide monthly trend endpoint (units, target and achievement per month), test-first, while keeping historical sales/target analytics separate from the September-specific inventory and risk metrics.

**Architecture**

```
Synthetic CSV data
  -> PostgreSQL tables
  -> PostgreSQL analytical views
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

- Sales and target performance are month-aware across SQL, Python and FastAPI through `dealer_monthly_performance`, `GET /performance?month=YYYY-MM` and `GET /dealers/{dealer_id}/performance`, covering October 2024 through September 2026.
- `inventory_supply`, `dealer_scorecard` and the endpoints built on them (`GET /dealers`, `GET /dealers/{dealer_id}`, `GET /dealers/at-risk` and `GET /regions/summary`) remain fixed to September 2026. Inventory is a single snapshot as of September 30, 2026, so historical inventory and risk analysis is not yet month-aware.
- `GET /performance` returns all 40 dealers for one month, while `GET /dealers/{dealer_id}/performance` returns one dealer's monthly history with optional inclusive `start` and `end` bounds. Range filtering is month-precision only (`YYYY-MM`); daily or arbitrary-date filtering is not implemented.
- The strict month-format rule is duplicated across FastAPI `Query` patterns in `src/api.py` and regular-expression validation in `src/db.py`; update both layers together if the format changes.
- The range filter compares `YYYY-MM` text in SQL. That sorts chronologically only because both bounds are validated first, so the comparison must be revisited if the `month` column ever changes type or format.
- `get_dealer()` returns `None` for an unknown dealer, while `get_dealer_performance_history()` raises `DealerNotFoundError`. Both behaviors are tested, but the query-layer not-found convention could be standardized later.
- `get_dealer_performance_history()` relies on FastAPI to enforce an integer `dealer_id`; the database-layer function does not perform its own explicit type validation.
- The dealer-history CSV cross-check intentionally has its own helper instead of sharing the Day 18 monthly-performance helper. This keeps the validation independent at the cost of a small amount of duplication.
- Database-backed tests depend on `DATABASE_URL` being exported in the current shell. Because `get_engine()` is cached, tests that deliberately remove the variable must clear the engine cache before exercising that path.
- The current dataset has no zero-sales or missing-target dealer-months, so the zero-fill and `NULL`-achievement paths of the monthly view were checked once with a rolled-back test transaction, not by an automated test.
- Direct dependencies are pinned in `requirements.txt` and `requirements-dev.txt`, but transitive packages (for example Starlette) are not locked.
- The Day 16 clean-clone test reused the existing local PostgreSQL database; since Day 21 the CI workflow rebuilds the database from the SQL scripts on a fresh runner on every push.
- CI covers one pinned environment (`ubuntu-24.04`, Python 3.12.7, PostgreSQL 18.6) and lints only `src/db.py`, `src/api.py`, `src/models.py` and `tests`; other versions and the old Day 1-4 scripts are not covered. The Ubuntu release, `postgres:18.6` tag and action versions are pinned by hand and must be updated deliberately, although GitHub still updates the contents of the `ubuntu-24.04` image over time. Branch protection is not configured, so a red run does not block a merge, and the job has no `timeout-minutes` yet.
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

---

## 9. Roadmap

**Next:** a regional or network-wide monthly trend endpoint (Day 22), then centralizing the duplicated month-format rule now that CI protects the refactor (Day 23), keeping historical sales and target analytics separate from the September-specific inventory and risk metrics.

**Then:**

- Richer FastAPI endpoints
- Additional sales and inventory queries, with more automated API tests
- A full lock file for transitive dependencies, and `timeout-minutes` plus branch protection for CI
- LLM APIs and retrieval-augmented generation (RAG)
- Dealer operations copilot and supply-chain risk assistant
- AI agents
- Docker and Azure/cloud deployment
