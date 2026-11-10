# Automotive AI Lab: Project Progress Summary

**Last updated:** 10 Nov 2026 · **Latest code commit:** `fc34fbd` (Add monthly performance endpoint with tests) · **Tests:** 129 passing
**Repository:** https://github.com/PRASHANTAPAUDEL24/automotive-ai-lab
**Author:** Prashanta Paudel

---

## 1. Current state (read this first)

The project builds a data and analytics foundation for AI-powered automotive dealer operations. It uses a fully **synthetic** dataset for the fictional brand **Vertex Motors** with 40 dealers across 5 regions. Sales and target data cover 24 months from October 2024 through September 2026; inventory is a single snapshot as of September 30, 2026.

**What works today**

- Dealer sales and inventory analytics, implemented twice (pandas and PostgreSQL) and cross-checked against each other.
- Four reusable PostgreSQL views, from a monthly `dealer_monthly_performance` view to a `dealer_scorecard` view with four business-risk flags.
- A safe, parameterized Python query layer (`src/db.py`).
- A FastAPI service with five endpoints:

| Endpoint | Behaviour |
|---|---|
| `GET /health` | Returns `{"status": "ok"}` |
| `GET /dealers` | Scorecard for all dealers; optional `region` and `risk` filters. Unsupported `risk` returns 400; unknown region returns `[]` |
| `GET /dealers/{dealer_id}` | One dealer scorecard. Unknown id returns 404; non-integer id returns 422 |
| `GET /regions/summary` | One row per region: dealer count and counts of sales-risk, inventory-risk, combined-risk and early-overstock-watch dealers |
| `GET /dealers/at-risk` | The 20 sales-risk or inventory-risk dealers, ranked (1 = most urgent). Optional `limit` (minimum 1) keeps the global ranks; 0 or a non-integer returns 422 |
| `GET /performance` | Dealer sales and target performance for the required `month` (`YYYY-MM`), 2024-10 to 2026-09. 422 for a malformed month, 404 for a well-formed month with no data. |

- Pydantic response models (`Dealer`: 17 fields, 5 nullable; `RegionSummary`: region plus 5 count fields; `RankedDealer`: `Dealer` plus `rank` and `risk_tier`; `MonthlyPerformance`: 6 fields, 2 nullable) that validate API output and drive the schemas shown in `/docs`.
- A pytest suite of 129 tests: 33 core database-layer tests, 48 monthly-performance database/query tests, and 48 API-layer tests, run without starting a server.

**Next step:** Day 19: add a per-dealer monthly performance history beyond the single-month `/performance` endpoint, keeping inventory and risk metrics explicitly September-snapshot-specific.

**Architecture**

```
Synthetic CSV data
  -> PostgreSQL tables
  -> PostgreSQL analytical views
  -> reusable Python database layer (src/db.py)
  -> FastAPI endpoints (src/api.py)
  -> pytest integration tests
```

**Technical stack:** Python, pandas, NumPy, PostgreSQL, SQL, SQLAlchemy, psycopg, FastAPI, Uvicorn, pytest, FastAPI TestClient, Git, virtual environments, Black, Ruff.

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

- Sales and target performance are month-aware across SQL, Python and FastAPI through `dealer_monthly_performance` and `GET /performance?month=YYYY-MM`, covering October 2024 through September 2026.
- `inventory_supply`, `dealer_scorecard` and the endpoints built on them (`GET /dealers`, `GET /dealers/{dealer_id}`, `GET /dealers/at-risk` and `GET /regions/summary`) remain fixed to September 2026. Inventory is a single snapshot as of September 30, 2026, so historical inventory and risk analysis is not yet month-aware.
- `GET /performance` returns all 40 dealers for one month; there is no per-dealer history or month range yet.
- The month format rule exists in two places: the `Query` pattern in `src/api.py` and the regular expression in `src/db.py`; update both if the format changes.
- The current dataset has no zero-sales or missing-target dealer-months, so the zero-fill and `NULL`-achievement paths of the monthly view were checked once with a rolled-back test transaction, not by an automated test.
- Direct dependencies are pinned in `requirements.txt` and `requirements-dev.txt`, but transitive packages (for example Starlette) are not locked.
- The Day 16 clean-clone test validated a fresh Python environment against the existing local PostgreSQL database; it did not rebuild PostgreSQL from scratch.
- No CI pipeline yet; tests run locally.
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

---

## 9. Roadmap

**Next:** dealer-level monthly performance history, keeping historical sales and target analytics separate from the September-specific inventory and risk metrics.

**Then:**

- Richer FastAPI endpoints
- Additional sales and inventory queries, with more automated API tests
- CI that runs the tests on every push, and a full lock file for transitive dependencies
- LLM APIs and retrieval-augmented generation (RAG)
- Dealer operations copilot and supply-chain risk assistant
- AI agents
- Docker and Azure/cloud deployment
