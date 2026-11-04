# Automotive AI Lab: Project Progress Summary

**Last updated:** 4 Nov 2026 · **Latest code commit:** `ec0f00c` (Add region summary endpoint with tests) · **Tests:** 44 passing
**Repository:** https://github.com/PRASHANTAPAUDEL24/automotive-ai-lab
**Author:** Prashanta Paudel

---

## 1. Current state (read this first)

The project builds a data and analytics foundation for AI-powered automotive dealer operations. It uses a fully **synthetic** dataset for the fictional brand **Vertex Motors** (40 dealers, 5 regions, September 2026).

**What works today**

- Dealer sales and inventory analytics, implemented twice (pandas and PostgreSQL) and cross-checked against each other.
- Three reusable PostgreSQL views, ending in a `dealer_scorecard` view with four business-risk flags.
- A safe, parameterized Python query layer (`src/db.py`).
- A FastAPI service with four endpoints:

| Endpoint | Behaviour |
|---|---|
| `GET /health` | Returns `{"status": "ok"}` |
| `GET /dealers` | Scorecard for all dealers; optional `region` and `risk` filters. Unsupported `risk` returns 400; unknown region returns `[]` |
| `GET /dealers/{dealer_id}` | One dealer scorecard. Unknown id returns 404; non-integer id returns 422 |
| `GET /regions/summary` | One row per region: dealer count and counts of sales-risk, inventory-risk, combined-risk and early-overstock-watch dealers |

- Pydantic response models (`Dealer`: 17 fields, 5 nullable; `RegionSummary`: region plus 5 count fields) that validate API output and drive the schemas shown in `/docs`.
- A pytest suite of 44 tests (25 database-layer, 19 API-layer), run without starting a server.

**Next step:** more dealer analytics endpoints reusing the response-model pattern (for example, a ranked list of at-risk dealers).

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
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

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
- Deterministic query ordering.
- Reproducible virtual environment; small, single-purpose Git commits; code and README committed separately.
- Formatting and linting with Black and Ruff.

---

## 6. Known limitations

- All views are fixed to month `2026-09`. Month-parameterized views are planned.
- `requirements.txt` is unpinned. Dependencies are not locked.
- No CI pipeline yet; tests run locally.
- `/health` has no response model, so `/docs` shows a generic example for it.
- The region summary query exists both in `sql/day14_region_summary.sql` and in `src/db.py`; update both if the logic changes.
- Dev tools (Black, Ruff) are not yet in a separate dev requirements file.
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

---

## 9. Roadmap

**Next:** more dealer analytics endpoints, reusing the response-model pattern (for example, a ranked list of at-risk dealers).

**Then:**

- Richer FastAPI endpoints
- Month-parameterized views
- Additional sales and inventory queries, with more automated API tests
- Dev requirements, pinned dependencies and CI
- LLM APIs and retrieval-augmented generation (RAG)
- Dealer operations copilot and supply-chain risk assistant
- AI agents
- Docker and Azure/cloud deployment
