from pathlib import Path

import pandas as pd
import pytest
from sqlalchemy import text

import db

DATA_DIR = Path(__file__).resolve().parents[1] / "data"

EXPECTED_COLUMNS = [
    "dealer_id",
    "dealer_name",
    "month",
    "leads",
    "test_drives",
    "units_sold",
    "test_drive_rate_pct",
    "drive_to_sale_pct",
    "lead_to_sale_pct",
]


def _expected_from_csv(dealer_id, start=None, end=None):
    dealers = pd.read_csv(DATA_DIR / "dealers.csv")
    leads = pd.read_csv(DATA_DIR / "leads_monthly.csv")
    sales = pd.read_csv(DATA_DIR / "sales_monthly.csv")

    dealer = dealers.loc[
        dealers["dealer_id"] == dealer_id,
        ["dealer_id", "dealer_name"],
    ]

    if dealer.empty:
        return pd.DataFrame(columns=EXPECTED_COLUMNS)

    months = sorted(leads["month"].unique())

    expected = dealer.merge(
        pd.DataFrame({"month": months}),
        how="cross",
    )

    dealer_leads = leads.loc[
        leads["dealer_id"] == dealer_id,
        ["dealer_id", "month", "leads", "test_drives"],
    ]

    sales_by_dealer = (
        sales.loc[sales["dealer_id"] == dealer_id]
        .groupby(
            ["dealer_id", "month"],
            as_index=False,
        )["units_sold"]
        .sum()
    )

    expected = expected.merge(
        dealer_leads,
        on=["dealer_id", "month"],
        how="left",
        validate="one_to_one",
    )

    expected = expected.merge(
        sales_by_dealer,
        on=["dealer_id", "month"],
        how="left",
        validate="one_to_one",
    )

    expected["test_drive_rate_pct"] = (
        expected["test_drives"]
        * 100.0
        / expected["leads"].where(expected["leads"].ne(0))
    )

    expected["drive_to_sale_pct"] = (
        expected["units_sold"]
        * 100.0
        / expected["test_drives"].where(expected["test_drives"].ne(0))
    )

    expected["lead_to_sale_pct"] = (
        expected["units_sold"]
        * 100.0
        / expected["leads"].where(expected["leads"].ne(0))
    )

    if start is not None:
        expected = expected.loc[expected["month"] >= start]

    if end is not None:
        expected = expected.loc[expected["month"] <= end]

    return expected[EXPECTED_COLUMNS].sort_values("month").reset_index(drop=True)


@pytest.fixture
def rolled_back_connection(monkeypatch):
    engine = db.get_engine()

    with engine.connect() as connection:
        transaction = connection.begin()

        monkeypatch.setattr(
            db,
            "get_engine",
            lambda: connection,
        )

        try:
            yield connection
        finally:
            transaction.rollback()


# ============================================================
# Full-history contract
# ============================================================


def test_dealer_funnel_history_returns_all_24_months():
    history = db.get_dealer_funnel_history(101)

    assert len(history) == 24
    assert history.iloc[0]["month"] == "2024-10"
    assert history.iloc[-1]["month"] == "2026-09"


def test_dealer_funnel_history_has_exact_columns():
    history = db.get_dealer_funnel_history(101)

    assert history.columns.tolist() == EXPECTED_COLUMNS


def test_dealer_funnel_history_is_oldest_first():
    history = db.get_dealer_funnel_history(101)

    assert history["month"].tolist() == sorted(history["month"].tolist())


def test_dealer_funnel_history_contains_only_requested_dealer():
    history = db.get_dealer_funnel_history(101)

    assert history["dealer_id"].nunique() == 1
    assert int(history.iloc[0]["dealer_id"]) == 101

    dealers = pd.read_csv(DATA_DIR / "dealers.csv")
    expected_name = dealers.loc[
        dealers["dealer_id"] == 101,
        "dealer_name",
    ].iloc[0]

    assert history["dealer_name"].nunique() == 1
    assert history.iloc[0]["dealer_name"] == expected_name


@pytest.mark.parametrize(
    "dealer_id",
    pd.read_csv(DATA_DIR / "dealers.csv")["dealer_id"].tolist(),
)
def test_dealer_funnel_history_matches_independent_csv_oracle(dealer_id):
    actual = db.get_dealer_funnel_history(dealer_id)
    expected = _expected_from_csv(dealer_id)

    pd.testing.assert_frame_equal(
        actual.reset_index(drop=True),
        expected,
        check_dtype=False,
        check_exact=False,
        rtol=1e-10,
        atol=1e-10,
    )


def test_dealer_funnel_history_matches_direct_view_query():
    actual = db.get_dealer_funnel_history(101)

    expected = pd.read_sql(
        text("""
            SELECT
                f.dealer_id,
                d.dealer_name,
                f.month,
                f.leads,
                f.test_drives,
                f.units_sold,
                f.test_drive_rate_pct,
                f.drive_to_sale_pct,
                f.lead_to_sale_pct
            FROM dealer_monthly_funnel f
            JOIN dealers d
              ON d.dealer_id = f.dealer_id
            WHERE f.dealer_id = :dealer_id
            ORDER BY f.month
        """),
        db.get_engine(),
        params={"dealer_id": 101},
    )

    pd.testing.assert_frame_equal(
        actual.reset_index(drop=True),
        expected.reset_index(drop=True),
        check_dtype=False,
    )


# ============================================================
# Inclusive range filtering
# ============================================================


def test_start_only_is_inclusive():
    history = db.get_dealer_funnel_history(
        101,
        start="2026-01",
    )

    assert history["month"].tolist() == [
        "2026-01",
        "2026-02",
        "2026-03",
        "2026-04",
        "2026-05",
        "2026-06",
        "2026-07",
        "2026-08",
        "2026-09",
    ]


def test_end_only_is_inclusive():
    history = db.get_dealer_funnel_history(
        101,
        end="2024-12",
    )

    assert history["month"].tolist() == [
        "2024-10",
        "2024-11",
        "2024-12",
    ]


def test_both_bounds_are_inclusive():
    history = db.get_dealer_funnel_history(
        101,
        start="2025-03",
        end="2025-05",
    )

    assert history["month"].tolist() == [
        "2025-03",
        "2025-04",
        "2025-05",
    ]


def test_equal_start_and_end_returns_one_month():
    history = db.get_dealer_funnel_history(
        101,
        start="2025-03",
        end="2025-03",
    )

    assert history["month"].tolist() == ["2025-03"]


@pytest.mark.parametrize(
    ("start", "end"),
    [
        ("2030-01", "2030-12"),
        ("2020-01", "2020-12"),
        ("2030-01", None),
        (None, "2020-12"),
    ],
)
def test_real_dealer_with_empty_window_returns_empty(start, end):
    history = db.get_dealer_funnel_history(
        101,
        start=start,
        end=end,
    )

    assert history.empty
    assert history.columns.tolist() == EXPECTED_COLUMNS


# ============================================================
# Dealer existence
# ============================================================


@pytest.mark.parametrize(
    "dealer_id",
    [999, 0, -1, 100, 141, 10**20],
)
def test_unknown_dealer_raises_dealer_not_found(dealer_id):
    with pytest.raises(
        db.DealerNotFoundError,
        match=rf"^Dealer {dealer_id} not found$",
    ):
        db.get_dealer_funnel_history(dealer_id)


def test_dealer_without_source_rows_returns_null_months_not_not_found(
    rolled_back_connection,
):
    connection = rolled_back_connection

    connection.execute(text("""
            INSERT INTO dealers (
                dealer_id,
                dealer_name,
                city,
                state,
                region,
                size_class
            )
            SELECT
                9999,
                'Ghost Motors',
                city,
                state,
                region,
                size_class
            FROM dealers
            WHERE dealer_id = 101
        """))

    history = db.get_dealer_funnel_history(9999)

    assert len(history) == 24
    assert history["dealer_id"].astype(int).tolist() == [9999] * 24
    assert history["dealer_name"].tolist() == ["Ghost Motors"] * 24
    assert history["month"].tolist() == sorted(history["month"].tolist())

    assert (
        history[
            [
                "leads",
                "test_drives",
                "units_sold",
                "test_drive_rate_pct",
                "drive_to_sale_pct",
                "lead_to_sale_pct",
            ]
        ]
        .isna()
        .all()
        .all()
    )

    empty = db.get_dealer_funnel_history(
        9999,
        start="2030-01",
    )

    assert empty.empty
    assert empty.columns.tolist() == EXPECTED_COLUMNS


def test_unknown_dealer_with_empty_window_still_raises_not_found():
    with pytest.raises(
        db.DealerNotFoundError,
        match=r"^Dealer 999 not found$",
    ):
        db.get_dealer_funnel_history(
            999,
            start="2030-01",
            end="2030-12",
        )


# ============================================================
# Month validation and range validation
# ============================================================


@pytest.mark.parametrize(
    ("start", "end"),
    [
        ("2026-09", "2026-08"),
        ("2025-12", "2025-01"),
    ],
)
def test_start_after_end_raises_invalid_range(start, end):
    with pytest.raises(
        db.InvalidMonthRangeError,
        match=r"^start month must not be after end month$",
    ):
        db.get_dealer_funnel_history(
            101,
            start=start,
            end=end,
        )


@pytest.mark.parametrize(
    "start",
    [
        "2026-9",
        "26-09",
        "2026/09",
        "2026-13",
        "2026-00",
        " 2026-01",
        "2026-01\n",
        "",
    ],
)
def test_invalid_start_raises_invalid_month(start):
    with pytest.raises(
        db.InvalidMonthError,
        match=r"^start month must use YYYY-MM format$",
    ):
        db.get_dealer_funnel_history(
            101,
            start=start,
        )


@pytest.mark.parametrize(
    "end",
    [
        "2026-9",
        "26-09",
        "2026/09",
        "2026-13",
        "2026-00",
        " 2026-01",
        "2026-01\n",
        "",
    ],
)
def test_invalid_end_raises_invalid_month(end):
    with pytest.raises(
        db.InvalidMonthError,
        match=r"^end month must use YYYY-MM format$",
    ):
        db.get_dealer_funnel_history(
            101,
            end=end,
        )


@pytest.mark.parametrize(
    ("start", "end"),
    [
        (202601, None),
        (None, 202609),
        (True, None),
        (None, False),
    ],
)
def test_non_string_bound_raises_invalid_month(start, end):
    with pytest.raises(db.InvalidMonthError):
        db.get_dealer_funnel_history(
            101,
            start=start,
            end=end,
        )


def test_invalid_month_is_rejected_before_unknown_dealer_lookup():
    with pytest.raises(
        db.InvalidMonthError,
        match=r"^start month must use YYYY-MM format$",
    ):
        db.get_dealer_funnel_history(
            999,
            start="2026-9",
        )


def test_reversed_range_is_rejected_before_unknown_dealer_lookup():
    with pytest.raises(
        db.InvalidMonthRangeError,
        match=r"^start month must not be after end month$",
    ):
        db.get_dealer_funnel_history(
            999,
            start="2026-09",
            end="2026-08",
        )


# ============================================================
# View NULL semantics survive the Python query boundary
# ============================================================


def test_missing_lead_row_remains_null_through_history_query(
    rolled_back_connection,
):
    connection = rolled_back_connection

    connection.execute(text("""
            DELETE FROM leads_monthly
            WHERE dealer_id = 101
              AND month = '2026-09'
        """))

    history = db.get_dealer_funnel_history(
        101,
        start="2026-09",
        end="2026-09",
    )

    assert len(history) == 1

    row = history.iloc[0]

    assert pd.isna(row["leads"])
    assert pd.isna(row["test_drives"])
    assert not pd.isna(row["units_sold"])
    assert pd.isna(row["test_drive_rate_pct"])
    assert pd.isna(row["drive_to_sale_pct"])
    assert pd.isna(row["lead_to_sale_pct"])


def test_missing_sales_month_remains_null_through_history_query(
    rolled_back_connection,
):
    connection = rolled_back_connection

    connection.execute(text("""
            DELETE FROM sales_monthly
            WHERE dealer_id = 101
              AND month = '2026-09'
        """))

    history = db.get_dealer_funnel_history(
        101,
        start="2026-09",
        end="2026-09",
    )

    assert len(history) == 1

    row = history.iloc[0]

    assert not pd.isna(row["leads"])
    assert not pd.isna(row["test_drives"])
    assert pd.isna(row["units_sold"])
    assert not pd.isna(row["test_drive_rate_pct"])
    assert pd.isna(row["drive_to_sale_pct"])
    assert pd.isna(row["lead_to_sale_pct"])
