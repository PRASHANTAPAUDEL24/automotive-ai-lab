"""Query-layer tests for dealer funnel opportunities (Day 34).

Contract under test: ``db.get_dealer_funnel_opportunities(month, limit=None,
min_leads=0)`` finds dealers whose lead-to-sale conversion is strictly below
their region's benchmark and estimates how many units the gap is worth.

Benchmark: the regional ratio of sums, ``100 * regional units / regional
leads``, over every dealer in the region. It exists only when every dealer in
the region has a lead row and an aggregated sales dealer-month and the region
has positive total leads, so one missing row removes the whole region. It is
never changed by ``min_leads`` or ``limit``.

A dealer qualifies when it has positive leads, at least ``min_leads`` leads,
and ``dealer_units * regional_leads < regional_units * dealer_leads`` (exact
integer cross-multiplication, never rounded rates).

``estimated_opportunity_units`` is the units the dealer would have sold at
the regional rate minus its actual units, which equals ``leads *
conversion_gap_pp / 100``. In SQL it is the exact integer cross-product
difference ``N = leads * regional_units - units_sold * regional_leads``
divided once by ``regional_leads``, at a fixed scale of 30 decimal places
(``DIV(N * 1e30, regional_leads) * 1e-30``). That division truncates, which
is a controlled scale and not display rounding. PostgreSQL's default numeric
division chooses its scale from an estimate of the quotient's size, so it can
give mathematically equal opportunities different digits; a fixed scale gives
equal rationals identical digits. Distinct opportunities differ by at least
``1 / (L1 * L2)`` for regional lead totals ``L1`` and ``L2``, so they stay
distinct while both totals are below 1e15 (INTEGER leads, so far fewer than
460,000 dealers per region): an assumption about the supported data, not a
claim about the whole bigint range. The value stays numeric through ranking;
it becomes a float only when pandas reads the result.

Ranks are contiguous ``ROW_NUMBER()`` values over opportunity descending then
``dealer_id`` ascending, assigned after eligibility filtering and before
``limit``.

Error contract: a malformed month raises ``InvalidMonthError``; an invalid
``limit`` raises ``InvalidLimitError``; an invalid ``min_leads`` raises
``InvalidMinLeadsError``; all are checked, in that order, before any database
read. A well-formed month with no ``leads_monthly`` rows raises
``MonthNotFoundError``; an existing month with no qualifying dealers returns
an empty DataFrame.

Expected values come from an independent recomputation over the source CSVs
with exact ``Fraction`` arithmetic. The real data has no zero-lead, zero-drive
or missing rows, so every eligibility rule is exercised inside rolled-back
transactions. The module reaches the new function only through ``db.`` so a
missing implementation fails each test individually.
"""

import csv
from collections import defaultdict
from fractions import Fraction
from pathlib import Path

import pandas as pd
import pytest
from sqlalchemy import text

import db

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

EXPECTED_COLUMNS = [
    "dealer_id",
    "dealer_name",
    "region",
    "month",
    "leads",
    "units_sold",
    "dealer_lead_to_sale_pct",
    "regional_lead_to_sale_pct",
    "conversion_gap_pp",
    "estimated_opportunity_units",
    "rank",
]
EXACT_KEYS = [
    "dealer_id",
    "dealer_name",
    "region",
    "month",
    "leads",
    "units_sold",
    "rank",
]
FLOAT_KEYS = [
    "dealer_lead_to_sale_pct",
    "regional_lead_to_sale_pct",
    "conversion_gap_pp",
    "estimated_opportunity_units",
]
INTEGER_COLUMNS = ["dealer_id", "leads", "units_sold", "rank"]


def _read_rows(filename):
    with (DATA_DIR / filename).open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


DEALERS = {int(row["dealer_id"]): row for row in _read_rows("dealers.csv")}
LEADS = {
    (int(row["dealer_id"]), row["month"]): (
        int(row["leads"]),
        int(row["test_drives"]),
    )
    for row in _read_rows("leads_monthly.csv")
}
_sales_totals = defaultdict(int)
for _row in _read_rows("sales_monthly.csv"):
    _sales_totals[(int(_row["dealer_id"]), _row["month"])] += int(_row["units_sold"])
SALES = dict(_sales_totals)
MONTHS = sorted({month for _, month in LEADS})
FIXTURE_MONTH = MONTHS[-1]
REGIONS = sorted({dealer["region"] for dealer in DEALERS.values()})
TARGET_REGION = REGIONS[0]


def make_row(dealer_id, month, leads, test_drives, units_sold):
    dealer = DEALERS[dealer_id]
    return {
        "dealer_id": dealer_id,
        "dealer_name": dealer["dealer_name"],
        "region": dealer["region"],
        "month": month,
        "leads": leads,
        "test_drives": test_drives,
        "units_sold": units_sold,
    }


def base_rows(month):
    """One oracle row per dealer for a month, with None where data is missing."""
    rows = []
    for dealer_id in sorted(DEALERS):
        leads, test_drives = LEADS.get((dealer_id, month), (None, None))
        rows.append(
            make_row(
                dealer_id, month, leads, test_drives, SALES.get((dealer_id, month))
            )
        )
    return rows


def replace_row(rows, new_row):
    return [
        new_row if row["dealer_id"] == new_row["dealer_id"] else row for row in rows
    ]


def region_benchmarks(rows):
    """Exact (leads, units) totals for each complete region with positive leads."""
    members_by_region = defaultdict(list)
    for row in rows:
        members_by_region[row["region"]].append(row)

    benchmarks = {}
    for region, members in members_by_region.items():
        if any(m["leads"] is None or m["units_sold"] is None for m in members):
            continue
        leads = sum(m["leads"] for m in members)
        units = sum(m["units_sold"] for m in members)
        if leads > 0:
            benchmarks[region] = (leads, units)
    return benchmarks


def opportunity_rows(rows, min_leads=0, limit=None):
    benchmarks = region_benchmarks(rows)
    found = []
    for row in rows:
        benchmark = benchmarks.get(row["region"])
        if benchmark is None:
            continue
        leads, units = row["leads"], row["units_sold"]
        region_leads, region_units = benchmark
        if not leads or leads < min_leads:
            continue
        if not units * region_leads < region_units * leads:
            continue
        regional_pct = Fraction(region_units * 100, region_leads)
        dealer_pct = Fraction(units * 100, leads)
        found.append(
            {
                "dealer_id": row["dealer_id"],
                "dealer_name": row["dealer_name"],
                "region": row["region"],
                "month": row["month"],
                "leads": leads,
                "units_sold": units,
                "dealer_lead_to_sale_pct": dealer_pct,
                "regional_lead_to_sale_pct": regional_pct,
                "conversion_gap_pp": regional_pct - dealer_pct,
                "estimated_opportunity_units": (
                    Fraction(leads * region_units, region_leads) - units
                ),
            }
        )
    found.sort(key=lambda r: (-r["estimated_opportunity_units"], r["dealer_id"]))
    ranked = [dict(row, rank=position) for position, row in enumerate(found, 1)]
    return ranked if limit is None else ranked[:limit]


def _same_value(actual, wanted):
    if actual is None or bool(pd.isna(actual)):
        return False
    return float(actual) == pytest.approx(float(wanted), rel=1e-9, abs=1e-9)


def assert_matches(result, expected):
    assert isinstance(result, pd.DataFrame)
    assert list(result.columns) == EXPECTED_COLUMNS
    records = result.to_dict("records")
    assert len(records) == len(expected)
    for actual, wanted in zip(records, expected):
        label = f"rank {wanted['rank']} dealer {wanted['dealer_id']}"
        for key in EXACT_KEYS:
            assert actual[key] == wanted[key], f"{label}: {key}"
        for key in FLOAT_KEYS:
            assert _same_value(actual[key], wanted[key]), f"{label}: {key}"


def tie_boundaries(ranked):
    """Limits that cut between two dealers with exactly equal opportunity."""
    return [
        k
        for k in range(1, len(ranked))
        if ranked[k - 1]["estimated_opportunity_units"]
        == ranked[k]["estimated_opportunity_units"]
    ]


def leads_threshold(month, label):
    values = sorted(
        row["leads"] for row in base_rows(month) if row["leads"] is not None
    )
    return {
        "median": values[len(values) // 2],
        "max": values[-1],
        "above_max": values[-1] + 1,
    }[label]


@pytest.fixture
def forbid_database_access(monkeypatch):
    """Invalid input must be rejected before acquiring the database."""

    def unexpected_database_access():
        pytest.fail("Database accessed before input validation")

    monkeypatch.setattr(db, "get_engine", unexpected_database_access)


@pytest.fixture
def transaction_connection(monkeypatch):
    engine = db.get_engine()
    connection = engine.connect()
    transaction = connection.begin()
    monkeypatch.setattr(db, "get_engine", lambda: connection)
    try:
        yield connection
    finally:
        transaction.rollback()
        connection.close()


def _ids_in(region):
    return sorted(i for i, dealer in DEALERS.items() if dealer["region"] == region)


def _set_counts(connection, dealer_id, leads, drives, units):
    """Rewrite one dealer-month and return the matching oracle row."""
    connection.execute(
        text(
            "UPDATE leads_monthly SET leads = :l, test_drives = :t "
            "WHERE dealer_id = :d AND month = :m"
        ),
        {"l": leads, "t": drives, "d": dealer_id, "m": FIXTURE_MONTH},
    )
    connection.execute(
        text("DELETE FROM sales_monthly WHERE dealer_id = :d AND month = :m"),
        {"d": dealer_id, "m": FIXTURE_MONTH},
    )
    model = connection.execute(
        text("SELECT model FROM vehicle_models ORDER BY model LIMIT 1")
    ).scalar_one()
    connection.execute(
        text(
            "INSERT INTO sales_monthly "
            "(dealer_id, month, model, units_sold, avg_sale_price) "
            "VALUES (:d, :m, :model, :u, NULL)"
        ),
        {"d": dealer_id, "m": FIXTURE_MONTH, "model": model, "u": units},
    )
    return make_row(dealer_id, FIXTURE_MONTH, leads, drives, units)


def _rewrite(connection, counts):
    """Apply {dealer_id: (leads, drives, units)} and return all oracle rows."""
    rows = base_rows(FIXTURE_MONTH)
    for dealer_id, (leads, drives, units) in counts.items():
        rows = replace_row(
            rows, _set_counts(connection, dealer_id, leads, drives, units)
        )
    return rows


def _run(rows, **kwargs):
    return (
        db.get_dealer_funnel_opportunities(FIXTURE_MONTH, **kwargs),
        opportunity_rows(rows, **kwargs),
    )


def _regions_in(result):
    return set(result["region"])


# ---------------------------------------------------------------------------
# Oracle sanity: these guard the tests themselves and do not need the new query.
# ---------------------------------------------------------------------------


def test_oracle_covers_the_24_month_span_all_dealers_and_regions():
    assert len(MONTHS) == 24
    assert len(DEALERS) == 40
    assert len(REGIONS) == 5
    assert all(len(_ids_in(region)) >= 5 for region in REGIONS)


def test_oracle_finds_some_but_not_all_dealers_below_benchmark_every_month():
    for month in MONTHS:
        assert 0 < len(opportunity_rows(base_rows(month))) < 40


def test_oracle_opportunity_equals_leads_times_gap_over_100_exactly():
    for month in MONTHS:
        for row in opportunity_rows(base_rows(month)):
            assert row["conversion_gap_pp"] > 0
            assert (
                row["estimated_opportunity_units"]
                == row["leads"] * row["conversion_gap_pp"] / 100
            )


# ---------------------------------------------------------------------------
# Real-data parity across every month
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("month", MONTHS)
def test_opportunities_match_independent_oracle_for_every_month(month):
    expected = opportunity_rows(base_rows(month))

    result = db.get_dealer_funnel_opportunities(month)

    assert_matches(result, expected)
    assert result["rank"].tolist() == list(range(1, len(expected) + 1))


@pytest.mark.parametrize("month", MONTHS)
def test_every_row_is_below_benchmark_and_obeys_the_opportunity_identity(month):
    result = db.get_dealer_funnel_opportunities(month)

    assert (result["conversion_gap_pp"] > 0).all()
    assert (result["estimated_opportunity_units"] > 0).all()
    assert (
        result["dealer_lead_to_sale_pct"] < result["regional_lead_to_sale_pct"]
    ).all()
    for row in result.to_dict("records"):
        assert row["conversion_gap_pp"] == pytest.approx(
            row["regional_lead_to_sale_pct"] - row["dealer_lead_to_sale_pct"],
            rel=1e-9,
        )
        assert row["estimated_opportunity_units"] == pytest.approx(
            row["leads"] * row["conversion_gap_pp"] / 100, rel=1e-9
        )


@pytest.mark.parametrize("month", MONTHS)
def test_regional_benchmark_reconciles_with_the_regional_funnel_snapshot(month):
    snapshot = db.get_regional_funnel_snapshot(month).set_index("region")
    result = db.get_dealer_funnel_opportunities(month)

    assert not result.empty
    for row in result.to_dict("records"):
        wanted = snapshot.loc[row["region"], "lead_to_sale_pct"]
        assert pd.notna(wanted)
        assert row["regional_lead_to_sale_pct"] == pytest.approx(
            float(wanted), rel=1e-9
        )


def test_columns_keep_integer_and_float_dtypes_and_are_never_null():
    result = db.get_dealer_funnel_opportunities(MONTHS[0])

    assert not result.empty
    for column in INTEGER_COLUMNS:
        assert pd.api.types.is_integer_dtype(result[column]), column
    for column in FLOAT_KEYS:
        assert pd.api.types.is_float_dtype(result[column]), column
    assert result.notna().all().all()


def test_limit_is_accepted_positionally():
    month = MONTHS[3]

    assert_matches(
        db.get_dealer_funnel_opportunities(month, 4),
        opportunity_rows(base_rows(month), limit=4),
    )


# ---------------------------------------------------------------------------
# limit
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("month", MONTHS)
def test_limit_returns_exact_prefix_including_cuts_through_tie_groups(month):
    full = opportunity_rows(base_rows(month))
    limits = sorted({1, 2, len(full) - 1, len(full), *tie_boundaries(full)})

    for limit in limits:
        assert_matches(
            db.get_dealer_funnel_opportunities(month, limit=limit),
            full[:limit],
        )


@pytest.mark.parametrize("limit", [41, 1000, 2**31, 99_999_999_999, db.MAX_LIMIT])
def test_limit_above_row_count_returns_every_ranked_dealer(limit):
    month = MONTHS[5]

    assert_matches(
        db.get_dealer_funnel_opportunities(month, limit=limit),
        opportunity_rows(base_rows(month)),
    )


@pytest.mark.parametrize("limit", [0, -1, 2**63, True, False, 1.5, "5"])
def test_invalid_limit_raises_with_exact_message(limit, forbid_database_access):
    with pytest.raises(db.InvalidLimitError) as error:
        db.get_dealer_funnel_opportunities(MONTHS[0], limit=limit)

    assert str(error.value) == (
        f"Invalid limit: {limit!r}. Expected an integer between 1 and {db.MAX_LIMIT}."
    )


# ---------------------------------------------------------------------------
# min_leads
# ---------------------------------------------------------------------------


def test_min_leads_zero_is_the_default():
    month = MONTHS[7]

    pd.testing.assert_frame_equal(
        db.get_dealer_funnel_opportunities(month),
        db.get_dealer_funnel_opportunities(month, min_leads=0),
    )


@pytest.mark.parametrize("label", ["median", "max", "above_max"])
@pytest.mark.parametrize("month", MONTHS)
def test_min_leads_filters_inclusively_and_reranks_contiguously(month, label):
    threshold = leads_threshold(month, label)
    expected = opportunity_rows(base_rows(month), min_leads=threshold)

    result = db.get_dealer_funnel_opportunities(month, min_leads=threshold)

    assert_matches(result, expected)
    assert result["rank"].tolist() == list(range(1, len(expected) + 1))
    if label == "above_max":
        assert result.empty
    if label == "median":
        assert not result.empty


def test_min_leads_never_changes_the_regional_benchmark_on_real_data():
    month = MONTHS[7]
    everyone = db.get_dealer_funnel_opportunities(month)
    benchmark = dict(zip(everyone["region"], everyone["regional_lead_to_sale_pct"]))

    filtered = db.get_dealer_funnel_opportunities(
        month, min_leads=leads_threshold(month, "median")
    )

    assert not filtered.empty
    assert len(filtered) < len(everyone)
    for row in filtered.to_dict("records"):
        assert row["regional_lead_to_sale_pct"] == pytest.approx(
            benchmark[row["region"]], rel=1e-9
        )


def test_min_leads_at_bigint_maximum_is_valid_and_returns_empty_frame():
    result = db.get_dealer_funnel_opportunities(MONTHS[0], min_leads=db.MAX_LIMIT)

    assert result.empty
    assert list(result.columns) == EXPECTED_COLUMNS


@pytest.mark.parametrize("min_leads", [-1, 2**63, True, False, 1.5, "5", None])
def test_invalid_min_leads_raises_with_exact_message(min_leads, forbid_database_access):
    with pytest.raises(db.InvalidMinLeadsError) as error:
        db.get_dealer_funnel_opportunities(MONTHS[0], min_leads=min_leads)

    assert str(error.value) == (
        f"Invalid min_leads: {min_leads!r}. "
        f"Expected an integer between 0 and {db.MAX_LIMIT}."
    )


def test_min_leads_error_is_a_value_error():
    assert issubclass(db.InvalidMinLeadsError, ValueError)


# ---------------------------------------------------------------------------
# Month validation and existence
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "month",
    ["2026-9", "2026-13", "2026/09", "", None, 202609, "2026-09\n", "２０２６-09"],
)
def test_malformed_month_raises_invalid_month_error(month, forbid_database_access):
    with pytest.raises(db.InvalidMonthError):
        db.get_dealer_funnel_opportunities(month)


@pytest.mark.parametrize("month", ["1999-01", "2030-12"])
def test_well_formed_month_without_lead_rows_raises_month_not_found(month):
    with pytest.raises(db.MonthNotFoundError) as error:
        db.get_dealer_funnel_opportunities(month)

    assert str(error.value) == f"Month {month} not found"


def test_validation_runs_before_the_database_in_documented_order(
    forbid_database_access,
):
    with pytest.raises(db.InvalidMonthError):
        db.get_dealer_funnel_opportunities("bad", limit=0, min_leads=-1)
    with pytest.raises(db.InvalidLimitError):
        db.get_dealer_funnel_opportunities(MONTHS[0], limit=0, min_leads=-1)
    with pytest.raises(db.InvalidMinLeadsError):
        db.get_dealer_funnel_opportunities(MONTHS[0], limit=1, min_leads=-1)


# ---------------------------------------------------------------------------
# Rolled-back fixtures: eligibility and regional completeness
# ---------------------------------------------------------------------------


def test_dealer_without_a_lead_row_removes_its_whole_region(transaction_connection):
    dealer_id = _ids_in(TARGET_REGION)[3]
    transaction_connection.execute(
        text("DELETE FROM leads_monthly WHERE dealer_id = :d AND month = :m"),
        {"d": dealer_id, "m": FIXTURE_MONTH},
    )
    rows = replace_row(
        base_rows(FIXTURE_MONTH),
        make_row(
            dealer_id, FIXTURE_MONTH, None, None, SALES[(dealer_id, FIXTURE_MONTH)]
        ),
    )

    result, expected = _run(rows)

    assert expected
    assert TARGET_REGION not in _regions_in(result)
    assert_matches(result, expected)


def test_dealer_without_a_sales_row_removes_its_whole_region(transaction_connection):
    dealer_id = _ids_in(TARGET_REGION)[3]
    transaction_connection.execute(
        text("DELETE FROM sales_monthly WHERE dealer_id = :d AND month = :m"),
        {"d": dealer_id, "m": FIXTURE_MONTH},
    )
    leads, drives = LEADS[(dealer_id, FIXTURE_MONTH)]
    rows = replace_row(
        base_rows(FIXTURE_MONTH),
        make_row(dealer_id, FIXTURE_MONTH, leads, drives, None),
    )

    result, expected = _run(rows)

    assert expected
    assert TARGET_REGION not in _regions_in(result)
    assert_matches(result, expected)


@pytest.mark.parametrize("min_leads", [0, 1])
def test_zero_lead_dealer_is_excluded_alone_and_its_region_stays(
    transaction_connection, min_leads
):
    dealer_id = _ids_in(TARGET_REGION)[2]
    _, drives = LEADS[(dealer_id, FIXTURE_MONTH)]
    transaction_connection.execute(
        text("UPDATE leads_monthly SET leads = 0 WHERE dealer_id = :d AND month = :m"),
        {"d": dealer_id, "m": FIXTURE_MONTH},
    )
    rows = replace_row(
        base_rows(FIXTURE_MONTH),
        make_row(
            dealer_id,
            FIXTURE_MONTH,
            0,
            drives,
            SALES[(dealer_id, FIXTURE_MONTH)],
        ),
    )

    result, expected = _run(rows, min_leads=min_leads)

    assert TARGET_REGION in {row["region"] for row in expected}
    assert dealer_id not in result["dealer_id"].tolist()
    assert TARGET_REGION in _regions_in(result)
    assert_matches(result, expected)


def test_region_with_zero_total_leads_has_no_benchmark(transaction_connection):
    ids = _ids_in(TARGET_REGION)
    rows = base_rows(FIXTURE_MONTH)
    for dealer_id in ids:
        _, drives = LEADS[(dealer_id, FIXTURE_MONTH)]
        transaction_connection.execute(
            text(
                "UPDATE leads_monthly SET leads = 0 WHERE dealer_id = :d AND month = :m"
            ),
            {"d": dealer_id, "m": FIXTURE_MONTH},
        )
        rows = replace_row(
            rows,
            make_row(
                dealer_id,
                FIXTURE_MONTH,
                0,
                drives,
                SALES[(dealer_id, FIXTURE_MONTH)],
            ),
        )

    result, expected = _run(rows)

    assert expected
    assert TARGET_REGION not in _regions_in(result)
    assert_matches(result, expected)


def test_region_with_zero_total_units_has_a_zero_benchmark_and_no_exceptions(
    transaction_connection,
):
    counts = dict.fromkeys(_ids_in(TARGET_REGION), (100, 40, 0))
    rows = _rewrite(transaction_connection, counts)

    result, expected = _run(rows)

    assert expected
    assert TARGET_REGION not in _regions_in(result)
    assert_matches(result, expected)


def test_positive_leads_with_zero_sales_is_eligible_below_benchmark(
    transaction_connection,
):
    dealer_id = _ids_in(TARGET_REGION)[2]
    rows = _rewrite(transaction_connection, {dealer_id: (200, 80, 0)})

    result, expected = _run(rows)

    record = result[result["dealer_id"] == dealer_id].iloc[0]
    assert record["units_sold"] == 0
    assert record["dealer_lead_to_sale_pct"] == 0
    assert record["conversion_gap_pp"] == pytest.approx(
        record["regional_lead_to_sale_pct"]
    )
    assert_matches(result, expected)


def test_zero_test_drives_does_not_exclude_a_dealer_with_a_defined_rate(
    transaction_connection,
):
    dealer_id = _ids_in(TARGET_REGION)[2]
    rows = _rewrite(transaction_connection, {dealer_id: (500, 0, 1)})

    result, expected = _run(rows)

    assert dealer_id in {row["dealer_id"] for row in expected}
    assert dealer_id in result["dealer_id"].tolist()
    assert_matches(result, expected)


def test_dealers_at_or_above_the_regional_benchmark_are_excluded(
    transaction_connection,
):
    ids = _ids_in(TARGET_REGION)
    shaped = [(100, 40, 10), (200, 80, 20), (100, 40, 5), (100, 40, 15)]
    counts = {
        dealer_id: shaped[index] if index < len(shaped) else (100, 40, 10)
        for index, dealer_id in enumerate(ids)
    }
    rows = _rewrite(transaction_connection, counts)

    result, expected = _run(rows)

    in_region = result[result["region"] == TARGET_REGION]
    assert in_region["dealer_id"].tolist() == [ids[2]]
    record = in_region.iloc[0]
    assert record["regional_lead_to_sale_pct"] == pytest.approx(10.0)
    assert record["dealer_lead_to_sale_pct"] == pytest.approx(5.0)
    assert record["conversion_gap_pp"] == pytest.approx(5.0)
    assert record["estimated_opportunity_units"] == pytest.approx(5.0)
    assert_matches(result, expected)


@pytest.mark.parametrize("smaller_id_gets_nine_leads", [True, False])
def test_equal_opportunity_ties_break_on_dealer_id_despite_different_counts(
    transaction_connection, smaller_id_gets_nine_leads
):
    # Region rate is exactly 7/30. A dealer with 9 leads / 2 units and one with
    # 39 leads / 9 units are each worth exactly 0.1 unit, although two separately
    # rounded rates would not reproduce that equality.
    ids = _ids_in(TARGET_REGION)
    nine, thirty_nine = (9, 4, 2), (39, 16, 9)
    first, second = (
        (nine, thirty_nine)
        if smaller_id_gets_nine_leads
        else (
            thirty_nine,
            nine,
        )
    )
    counts = {ids[0]: first, ids[1]: second}
    for dealer_id in ids[2:-1]:
        counts[dealer_id] = (30, 12, 7)
    counts[ids[-1]] = (12, 5, 3)
    rows = _rewrite(transaction_connection, counts)

    result, expected = _run(rows)

    by_id = {row["dealer_id"]: row for row in expected}
    assert (
        by_id[ids[0]]["estimated_opportunity_units"]
        == by_id[ids[1]]["estimated_opportunity_units"]
        == Fraction(1, 10)
    )
    order = result["dealer_id"].tolist()
    assert order.index(ids[0]) < order.index(ids[1])
    assert_matches(result, expected)


def test_min_leads_does_not_change_the_regional_benchmark_in_a_constructed_region(
    transaction_connection,
):
    ids = _ids_in(TARGET_REGION)
    counts = {ids[0]: (1000, 400, 100)}
    counts.update(dict.fromkeys(ids[1:], (10, 4, 5)))
    rows = _rewrite(transaction_connection, counts)
    total_leads = 1000 + 10 * (len(ids) - 1)
    total_units = 100 + 5 * (len(ids) - 1)

    result, expected = _run(rows, min_leads=100)

    in_region = result[result["region"] == TARGET_REGION]
    assert in_region["dealer_id"].tolist() == [ids[0]]
    assert in_region.iloc[0]["regional_lead_to_sale_pct"] == pytest.approx(
        100 * total_units / total_leads
    )
    assert_matches(result, expected)


def test_extreme_counts_do_not_overflow_the_exact_eligibility_predicate(
    transaction_connection,
):
    # units * regional_leads exceeds the bigint range here, so the exact
    # cross-multiplication must be carried out in numeric.
    ids = _ids_in(TARGET_REGION)
    counts = {ids[0]: (2_000_000_000, 1, 1_000_000_000)}
    counts.update(dict.fromkeys(ids[1:], (2_000_000_000, 1, 1_500_000_000)))
    rows = _rewrite(transaction_connection, counts)

    result, expected = _run(rows)

    in_region = result[result["region"] == TARGET_REGION]
    assert in_region["dealer_id"].tolist() == [ids[0]]
    assert_matches(result, expected)


def _repeating_tie_counts(ids, big_has_smaller_id):
    """Region at exactly 1/3 where two dealers are each worth exactly 1/3 unit.

    Dealer 10 leads / 3 units and dealer 1,000,000,000 leads / 333,333,333
    units both sit 1/3 unit below the regional rate. The large dealer's
    leads * rate quotient is huge, so dividing before subtracting would cut
    its digits short and break the tie.
    """
    small, big = (10, 4, 3), (1_000_000_000, 1, 333_333_333)
    first, second = (big, small) if big_has_smaller_id else (small, big)
    counts = {ids[0]: first, ids[1]: second}
    counts.update(dict.fromkeys(ids[2:-1], (30, 12, 10)))
    counts[ids[-1]] = (10, 4, 4)
    return counts


@pytest.mark.parametrize("big_has_smaller_id", [True, False])
def test_exactly_equal_repeating_opportunities_tie_across_regions_by_dealer_id(
    transaction_connection, big_has_smaller_id
):
    first_ids, second_ids = _ids_in(REGIONS[0]), _ids_in(REGIONS[1])
    counts = _repeating_tie_counts(first_ids, big_has_smaller_id)
    counts.update(_repeating_tie_counts(second_ids, big_has_smaller_id))
    rows = _rewrite(transaction_connection, counts)

    result, expected = _run(rows)

    tied = [first_ids[0], first_ids[1], second_ids[0], second_ids[1]]
    by_id = {row["dealer_id"]: row for row in expected}
    assert {by_id[i]["estimated_opportunity_units"] for i in tied} == {Fraction(1, 3)}
    assert [i for i in result["dealer_id"].tolist() if i in tied] == sorted(tied)
    assert_matches(result, expected)


def _two_region_fixture(fixture, target_ids):
    """Counts for one region: seven fillers above the benchmark, one target below it.

    Fillers sit at (fl, 1, fu) and the target at (tl, 1, tu). With seven
    fillers the regional totals are L = 7*fl + tl and U = 7*fu + tu, and the
    target's numerator is exactly 7 * (tl*fu - tu*fl).
    """
    ids, target = target_ids
    assert len(ids) == 8
    counts = {i: (fixture["fl"], 1, fixture["fu"]) for i in ids if i != target}
    counts[target] = (fixture["tl"], 1, fixture["tu"])
    assert 7 * fixture["fl"] + fixture["tl"] == fixture["L"]
    assert 7 * fixture["fu"] + fixture["tu"] == fixture["U"]
    return counts


# Two regions whose target dealers are worth 4906.14463840103... units. The
# exact gap is 7 / (L_a * L_b), about 2.0e-13: below one double-precision step
# at this magnitude, so converting to float before ranking merges the pair.
NEAR_TIE_LOW = {
    "fl": 700000, "fu": 560385, "tl": 1000003, "tu": 794645,
    "L": 5900003, "U": 4717340,
}  # fmt: skip
NEAR_TIE_HIGH = {
    "fl": 700055, "fu": 236083, "tl": 1000019, "tu": 331334,
    "L": 5900404, "U": 1983915,
}  # fmt: skip


def test_near_tie_fixture_is_exactly_ordered_but_equal_as_doubles():
    low = Fraction(7 * (1000003 * 560385 - 794645 * 700000), NEAR_TIE_LOW["L"])
    high = Fraction(7 * (1000019 * 236083 - 331334 * 700055), NEAR_TIE_HIGH["L"])
    assert high - low == Fraction(7, NEAR_TIE_LOW["L"] * NEAR_TIE_HIGH["L"])
    assert high > low
    assert float(high) == float(low)


def test_distinct_opportunities_closer_than_one_double_step_keep_their_exact_order(
    transaction_connection,
):
    first_ids, second_ids = sorted((_ids_in(REGIONS[0]), _ids_in(REGIONS[1])), key=min)
    low_target, high_target = min(first_ids), max(second_ids)
    assert low_target < high_target
    counts = _two_region_fixture(NEAR_TIE_LOW, (first_ids, low_target))
    counts.update(_two_region_fixture(NEAR_TIE_HIGH, (second_ids, high_target)))
    rows = _rewrite(transaction_connection, counts)

    result, expected = _run(rows)

    by_id = {row["dealer_id"]: row for row in expected}
    low_value = by_id[low_target]["estimated_opportunity_units"]
    high_value = by_id[high_target]["estimated_opportunity_units"]
    assert high_value - low_value == Fraction(7, NEAR_TIE_LOW["L"] * NEAR_TIE_HIGH["L"])
    assert float(high_value) == float(low_value)
    # The higher dealer id wins only because its exact opportunity is larger.
    assert result["dealer_id"].tolist()[:2] == [high_target, low_target]
    assert result["rank"].tolist()[:2] == [1, 2]
    assert_matches(result, expected)


# Two dealers worth exactly 2548/2213 units each. PostgreSQL's default numeric
# division gives the first 1.1513782196113873 and the second
# 1.15137821961138725712 because it picks the digit count from an estimate of
# the quotient's size; a fixed scale gives both the same digits.
SPLIT_DIGITS_A = {
    "fl": 260, "fu": 208, "tl": 393, "tu": 313, "L": 2213, "U": 1769,
}  # fmt: skip
SPLIT_DIGITS_B = {
    "fl": 749, "fu": 518, "tl": 5822, "tu": 4024, "L": 11065, "U": 7650,
}  # fmt: skip


@pytest.mark.parametrize("a_region_has_smaller_id", [True, False])
def test_equal_opportunities_with_different_default_division_digits_tie_on_dealer_id(
    transaction_connection, a_region_has_smaller_id
):
    low_ids, high_ids = sorted((_ids_in(REGIONS[0]), _ids_in(REGIONS[1])), key=min)
    if a_region_has_smaller_id:
        a_ids, b_ids = low_ids, high_ids
        a_target, b_target = min(a_ids), max(b_ids)
    else:
        a_ids, b_ids = high_ids, low_ids
        a_target, b_target = max(a_ids), min(b_ids)
    # Regional ids may interleave, so prove the parametrized order really holds.
    assert (a_target < b_target) is a_region_has_smaller_id
    counts = _two_region_fixture(SPLIT_DIGITS_A, (a_ids, a_target))
    counts.update(_two_region_fixture(SPLIT_DIGITS_B, (b_ids, b_target)))
    rows = _rewrite(transaction_connection, counts)

    result, expected = _run(rows)

    by_id = {row["dealer_id"]: row for row in expected}
    assert by_id[a_target]["estimated_opportunity_units"] == Fraction(2548, 2213)
    assert by_id[b_target]["estimated_opportunity_units"] == Fraction(2548, 2213)
    tied = sorted([a_target, b_target])
    assert [i for i in result["dealer_id"].tolist() if i in tied] == tied
    assert_matches(result, expected)


def test_region_where_every_dealer_equals_the_benchmark_has_no_exceptions(
    transaction_connection,
):
    counts = dict.fromkeys(_ids_in(TARGET_REGION), (100, 40, 10))
    rows = _rewrite(transaction_connection, counts)

    result, expected = _run(rows)

    assert expected
    assert TARGET_REGION not in _regions_in(result)
    assert_matches(result, expected)


def test_missing_one_model_row_keeps_the_dealer_month_complete(
    transaction_connection,
):
    dealer_id = _ids_in(TARGET_REGION)[2]
    leads, drives = LEADS[(dealer_id, FIXTURE_MONTH)]
    model, removed = transaction_connection.execute(
        text(
            "SELECT model, units_sold FROM sales_monthly "
            "WHERE dealer_id = :d AND month = :m ORDER BY model LIMIT 1"
        ),
        {"d": dealer_id, "m": FIXTURE_MONTH},
    ).one()
    transaction_connection.execute(
        text(
            "DELETE FROM sales_monthly "
            "WHERE dealer_id = :d AND month = :m AND model = :model"
        ),
        {"d": dealer_id, "m": FIXTURE_MONTH, "model": model},
    )
    rows = replace_row(
        base_rows(FIXTURE_MONTH),
        make_row(
            dealer_id,
            FIXTURE_MONTH,
            leads,
            drives,
            SALES[(dealer_id, FIXTURE_MONTH)] - removed,
        ),
    )

    result, expected = _run(rows)

    assert TARGET_REGION in {row["region"] for row in expected}
    assert TARGET_REGION in _regions_in(result)
    assert_matches(result, expected)


def test_invalid_parameters_are_rejected_before_an_absent_month_is_looked_up(
    forbid_database_access,
):
    with pytest.raises(db.InvalidLimitError):
        db.get_dealer_funnel_opportunities("2030-12", limit=0)
    with pytest.raises(db.InvalidMinLeadsError):
        db.get_dealer_funnel_opportunities("2030-12", min_leads=-1)


def test_limit_is_applied_after_ranking_and_keeps_global_ranks():
    month = MONTHS[9]
    full = opportunity_rows(base_rows(month))

    result = db.get_dealer_funnel_opportunities(month, limit=3)

    assert result["rank"].tolist() == [1, 2, 3]
    assert result["dealer_id"].tolist() == [row["dealer_id"] for row in full[:3]]


def test_month_with_leads_but_no_sales_returns_empty_frame_not_an_error(
    transaction_connection,
):
    transaction_connection.execute(
        text("DELETE FROM sales_monthly WHERE month = :m"), {"m": FIXTURE_MONTH}
    )

    result = db.get_dealer_funnel_opportunities(FIXTURE_MONTH)

    assert result.empty
    assert list(result.columns) == EXPECTED_COLUMNS


def test_month_with_all_zero_leads_returns_empty_frame(transaction_connection):
    transaction_connection.execute(
        text("UPDATE leads_monthly SET leads = 0 WHERE month = :m"),
        {"m": FIXTURE_MONTH},
    )

    result = db.get_dealer_funnel_opportunities(FIXTURE_MONTH)

    assert result.empty
    assert list(result.columns) == EXPECTED_COLUMNS


def test_month_with_sales_but_no_lead_rows_raises_month_not_found(
    transaction_connection,
):
    model = transaction_connection.execute(
        text("SELECT model FROM vehicle_models ORDER BY model LIMIT 1")
    ).scalar_one()
    transaction_connection.execute(
        text(
            "INSERT INTO sales_monthly "
            "(dealer_id, month, model, units_sold, avg_sale_price) "
            "VALUES (:d, '2030-01', :model, 5, NULL)"
        ),
        {"d": min(DEALERS), "model": model},
    )

    with pytest.raises(db.MonthNotFoundError):
        db.get_dealer_funnel_opportunities("2030-01")


# ---------------------------------------------------------------------------
# SQL structure contract (captured without connecting to PostgreSQL)
# ---------------------------------------------------------------------------


@pytest.fixture
def captured_opportunities_sql(monkeypatch):
    """Capture generated SQL without connecting to PostgreSQL."""
    statements = []
    fake_source = object()

    def capture_read_sql(statement, source, *args, **kwargs):
        assert source is fake_source

        statements.append(
            {
                "sql": " ".join(str(statement).split()).lower(),
                "params": dict(kwargs.get("params", {})),
            }
        )

        if len(statements) == 1:
            return pd.DataFrame({"exists": [1]})

        if len(statements) == 2:
            return pd.DataFrame()

        pytest.fail("Unexpected additional SQL statement")

    monkeypatch.setattr(db, "get_engine", lambda: fake_source)
    monkeypatch.setattr(db.pd, "read_sql", capture_read_sql)

    def capture():
        db.get_dealer_funnel_opportunities(
            "2026-09",
            limit=5,
            min_leads=10,
        )

        assert len(statements) == 2

        return statements[1]

    return capture


def test_opportunities_query_has_explicit_final_order_by_rank(
    captured_opportunities_sql,
):
    """The final result must explicitly order rows by rank."""
    sql = captured_opportunities_sql()["sql"]

    assert "from ranked order by rank" in sql


def test_opportunities_query_casts_limit_to_bigint(
    captured_opportunities_sql,
):
    """The optional limit must retain its explicit bigint cast."""
    captured = captured_opportunities_sql()

    assert captured["sql"].endswith("limit cast(:limit as bigint)")
    assert captured["params"]["limit"] == 5


def test_opportunities_query_casts_min_leads_to_bigint(
    captured_opportunities_sql,
):
    """The inclusive threshold must use an explicit bigint cast."""
    captured = captured_opportunities_sql()

    assert "f.leads >= cast(:min_leads as bigint)" in captured["sql"]
    assert captured["params"]["min_leads"] == 10


def test_opportunities_benchmark_keeps_the_positive_regional_leads_guard(
    captured_opportunities_sql,
):
    """A benchmark needs positive regional leads, enforced in the benchmark CTE.

    Every query projection divides by regional leads. Whether PostgreSQL
    reaches a zero-lead region's division before the numerator filter is a
    planner detail, not a SQL guarantee, so the guard stays explicit and
    this contract test protects it. It sits between the completeness
    conditions and the end of the benchmark CTE, before candidates.
    """
    sql = captured_opportunities_sql()["sql"]
    benchmark = sql[sql.index("benchmark as") : sql.index("candidates as")]

    assert "sales_rows = dealer_count and leads_sum > 0" in benchmark


def test_missing_sales_cannot_create_a_false_regional_opportunity(
    transaction_connection,
):
    """Incomplete regional sales must not create false opportunities."""
    ids = _ids_in(TARGET_REGION)
    target, missing = ids[0], ids[-1]

    counts = dict.fromkeys(ids, (100, 40, 20))
    counts[target] = (100, 40, 0)
    rows = _rewrite(transaction_connection, counts)

    complete = opportunity_rows(rows)
    assert target in {row["dealer_id"] for row in complete}

    transaction_connection.execute(
        text("DELETE FROM sales_monthly " "WHERE dealer_id = :d AND month = :m"),
        {"d": missing, "m": FIXTURE_MONTH},
    )

    rows = replace_row(
        rows,
        make_row(missing, FIXTURE_MONTH, 100, 40, None),
    )

    result, expected = _run(rows)

    assert expected
    assert TARGET_REGION not in _regions_in(result)
    assert target not in result["dealer_id"].tolist()
    assert_matches(result, expected)
