# Program: src/db.py
# Day 9: Reusable PostgreSQL access functions
# Created on: 2026-10-29
# Author: Prashanta Paudel
# Purpose: Centralize database connectivity and provide
# reusable access to the dealer scorecard.

import os
import re
from functools import lru_cache

import pandas as pd
from sqlalchemy import create_engine, text


class InvalidFilterError(ValueError):
    """Raised when a caller passes an unsupported filter value."""


class InvalidMonthError(ValueError):
    """Raised when a month is not a string in YYYY-MM format."""


class InvalidLimitError(ValueError):
    """Raised when a ranking limit is outside the supported range."""


class InvalidMinLeadsError(ValueError):
    """Raised when a minimum-leads threshold is invalid."""


class MonthNotFoundError(ValueError):
    """Raised when a well-formed month has no data."""


class DealerNotFoundError(ValueError):
    """Raised when a requested dealer does not exist."""


class InvalidMonthRangeError(ValueError):
    """Raised when the requested month range is invalid."""


class RegionNotFoundError(ValueError):
    """Raised when a requested region does not exist."""


# Strict ASCII YYYY-MM: four digits, then a month from 01 to 12.
MONTH_FORMAT = r"[0-9]{4}-(0[1-9]|1[0-2])"

# FastAPI Query validation anchors the same rule explicitly.
MONTH_QUERY_PATTERN = rf"^{MONTH_FORMAT}$"

_MONTH_RE = re.compile(MONTH_FORMAT)

MAX_LIMIT = 2**63 - 1


def _validate_month(month):
    """Validate one required month using the shared YYYY-MM contract."""
    if not isinstance(month, str) or not _MONTH_RE.fullmatch(month):
        raise InvalidMonthError(f"Invalid month: {month!r}. Expected YYYY-MM.")


ALLOWED_RISKS = {
    "sales_risk",
    "inventory_risk",
    "combined_risk",
    "early_overstock_watch",
}


@lru_cache
def get_engine():
    # Read the PostgreSQL connection string from the environment.
    database_url = os.getenv("DATABASE_URL")

    if not database_url:
        raise ValueError(
            "DATABASE_URL is not set. Export it before running this script."
        )

    # Create the SQLAlchemy engine once and reuse it.
    return create_engine(database_url)


def get_scorecard(region=None, risk=None):
    """
    Return rows from the dealer_scorecard view.

    Region matching is exact and case-sensitive.
    An unknown region returns an empty DataFrame.
    Risk must be one of the allowed risk-column names;
    otherwise, InvalidFilterError is raised.
    """
    # Start with the reusable dealer scorecard view.
    query = "SELECT * FROM dealer_scorecard"
    conditions = []
    params = {}

    # Region is a value, so use a bound parameter.
    if region is not None:
        conditions.append("region = :region")
        params["region"] = region

    # Risk is a column name, so validate it against a fixed whitelist
    # before inserting it into the SQL text.
    if risk is not None:
        if risk not in ALLOWED_RISKS:
            raise InvalidFilterError(f"Invalid risk filter: {risk}")

        conditions.append(f"{risk} = TRUE")

    # Add WHERE only when at least one filter is supplied.
    if conditions:
        query += " WHERE " + " AND ".join(conditions)

    query += " ORDER BY dealer_id"

    return pd.read_sql(
        text(query),
        get_engine(),
        params=params,
    )


def to_records(df):
    """Convert a DataFrame to JSON-safe records (NaN becomes None)."""
    return df.astype(object).where(df.notna(), None).to_dict(orient="records")


def get_dealer(dealer_id: int):
    """Return one dealer scorecard record, or None if not found."""
    query = text("""
        SELECT *
        FROM dealer_scorecard
        WHERE dealer_id = :dealer_id
        """)

    dealer = pd.read_sql(
        query,
        get_engine(),
        params={"dealer_id": dealer_id},
    )

    if dealer.empty:
        return None

    return to_records(dealer)[0]


def get_region_summary():
    """Return one scorecard summary row per region."""
    query = text("""
        SELECT
            region,
            COUNT(*) AS dealers,
            COUNT(*) FILTER (WHERE sales_risk) AS sales_risk_dealers,
            COUNT(*) FILTER (WHERE inventory_risk) AS inventory_risk_dealers,
            COUNT(*) FILTER (WHERE combined_risk) AS combined_risk_dealers,
            COUNT(*) FILTER (
                WHERE early_overstock_watch
            ) AS early_overstock_watch_dealers
        FROM dealer_scorecard
        GROUP BY region
        ORDER BY region
        """)

    return pd.read_sql(
        query,
        get_engine(),
    )


def get_at_risk_dealers(limit=None):
    """Return globally ranked at-risk dealers, optionally limited."""

    query = text("""
        WITH tiered AS (
            SELECT
                dealer_id,
                dealer_name,
                region,
                size_class,
                units_sold,
                target_units,
                achievement_pct,
                available_units,
                aged_units,
                avg_days_available,
                aged_pct,
                months_of_supply,
                high_supply,
                inventory_risk,
                sales_risk,
                combined_risk,
                early_overstock_watch,
                CASE
                    WHEN combined_risk THEN 1
                    WHEN early_overstock_watch THEN 2
                    WHEN sales_risk THEN 3
                    WHEN inventory_risk THEN 4
                END AS risk_tier
            FROM dealer_scorecard
            WHERE sales_risk OR inventory_risk
        ),
        ranked AS (
            SELECT
                *,
                ROW_NUMBER() OVER (
                    ORDER BY
                        risk_tier,
                        months_of_supply DESC NULLS FIRST,
                        dealer_id
                ) AS rank
            FROM tiered
        )
        SELECT
            dealer_id,
            dealer_name,
            region,
            size_class,
            units_sold,
            target_units,
            achievement_pct,
            available_units,
            aged_units,
            avg_days_available,
            aged_pct,
            months_of_supply,
            high_supply,
            inventory_risk,
            sales_risk,
            combined_risk,
            early_overstock_watch,
            rank,
            risk_tier
        FROM ranked
        ORDER BY rank
        LIMIT CAST(:limit AS bigint)
        """)

    return pd.read_sql(
        query,
        get_engine(),
        params={"limit": limit},
    )


def get_available_months():
    """Return the sorted months available in dealer_monthly_performance."""

    query = text("""
        SELECT DISTINCT month
        FROM dealer_monthly_performance
        ORDER BY month
        """)

    months = pd.read_sql(
        query,
        get_engine(),
    )

    return months["month"].tolist()


def get_monthly_performance(month):
    """
    Return dealer sales and target performance for one month.

    Raises InvalidMonthError for malformed month input and
    MonthNotFoundError when a well-formed month has no data.
    """

    _validate_month(month)

    query = text("""
        SELECT
            dealer_id,
            dealer_name,
            month,
            units_sold,
            target_units,
            achievement_pct
        FROM dealer_monthly_performance
        WHERE month = :month
        ORDER BY dealer_id
        """)

    performance = pd.read_sql(
        query,
        get_engine(),
        params={"month": month},
    )

    if performance.empty:
        raise MonthNotFoundError(f"Month {month} not found")

    return performance


def get_network_funnel_trend(start=None, end=None):
    """
    Return the network-wide monthly lead-funnel trend.

    Months are defined by the lead-based spine in dealer_monthly_funnel.
    Completeness is evaluated at dealer-month grain:

    - if any dealer lacks a lead row, network leads, test drives, and all
      three rates are NULL;
    - if any dealer lacks a sales dealer-month, network units sold and the
      two sale-dependent rates are NULL.

    Real zeros remain zero. Rates are ratios of gated network sums and are
    NULL only when their denominator or a required gated total is NULL.

    Optional start and end bounds are inclusive. A valid range with no
    lead-defined months returns an empty DataFrame.
    """
    _validate_optional_month(start, "start")
    _validate_optional_month(end, "end")

    if start is not None and end is not None and start > end:
        raise InvalidMonthRangeError("start month must not be after end month")

    clauses = []
    params = {}

    if start is not None:
        clauses.append("f.month >= :start")
        params["start"] = start

    if end is not None:
        clauses.append("f.month <= :end")
        params["end"] = end

    where_sql = ""
    if clauses:
        where_sql = "WHERE " + " AND ".join(clauses)

    query = text(f"""
        WITH network AS (
            SELECT
                f.month,
                COUNT(*) AS dealer_count,
                COUNT(f.leads) AS lead_row_count,
                COUNT(f.units_sold) AS sales_row_count,
                SUM(f.leads) AS leads_sum,
                SUM(f.test_drives) AS test_drives_sum,
                CAST(SUM(f.units_sold) AS bigint) AS units_sold_sum
            FROM dealer_monthly_funnel f
            {where_sql}
            GROUP BY f.month
        ),
        gated AS (
            SELECT
                month,
                CASE
                    WHEN lead_row_count = dealer_count
                    THEN leads_sum
                    ELSE NULL
                END AS leads,
                CASE
                    WHEN lead_row_count = dealer_count
                    THEN test_drives_sum
                    ELSE NULL
                END AS test_drives,
                CASE
                    WHEN sales_row_count = dealer_count
                    THEN units_sold_sum
                    ELSE NULL
                END AS units_sold
            FROM network
        )
        SELECT
            month,
            leads,
            test_drives,
            units_sold,
            test_drives * 100.0
                / NULLIF(leads, 0) AS test_drive_rate_pct,
            units_sold * 100.0
                / NULLIF(test_drives, 0) AS drive_to_sale_pct,
            units_sold * 100.0
                / NULLIF(leads, 0) AS lead_to_sale_pct
        FROM gated
        ORDER BY month
        """)

    return pd.read_sql(
        query,
        get_engine(),
        params=params,
    )


def get_regional_funnel_snapshot(month):
    """
    Return one funnel snapshot row per dealer region for one month.

    The query is anchored on dealers so every configured region remains
    present. Leads/test drives and sales have independent completeness
    contracts at dealer-month grain:

    - if any dealer in a region lacks a leads_monthly row, regional leads,
      test drives and all three rates are NULL;
    - if any dealer in a region lacks a sales dealer-month aggregate,
      regional units sold and the two sale rates are NULL.

    A real zero value is not treated as missing. Rates are ratios of regional
    sums and are NULL when their denominator is zero or unavailable.

    Month existence is defined by leads_monthly. A well-formed month with no
    lead rows raises MonthNotFoundError.
    """
    _validate_month(month)

    query = text("""
        WITH sales_by_dealer AS (
            SELECT
                dealer_id,
                SUM(units_sold) AS units_sold
            FROM sales_monthly
            WHERE month = :month
            GROUP BY dealer_id
        ),
        regional AS (
            SELECT
                d.region,
                COUNT(*) AS dealer_count,
                COUNT(l.dealer_id) AS lead_row_count,
                COUNT(s.dealer_id) AS sales_row_count,
                SUM(l.leads) AS leads_sum,
                SUM(l.test_drives) AS test_drives_sum,
                CAST(SUM(s.units_sold) AS bigint) AS units_sold_sum
            FROM dealers d
            LEFT JOIN leads_monthly l
                ON l.dealer_id = d.dealer_id
               AND l.month = :month
            LEFT JOIN sales_by_dealer s
                ON s.dealer_id = d.dealer_id
            GROUP BY d.region
        )
        SELECT
            region,
            CASE
                WHEN lead_row_count = dealer_count
                THEN leads_sum
                ELSE NULL
            END AS leads,
            CASE
                WHEN lead_row_count = dealer_count
                THEN test_drives_sum
                ELSE NULL
            END AS test_drives,
            CASE
                WHEN sales_row_count = dealer_count
                THEN units_sold_sum
                ELSE NULL
            END AS units_sold,
            CASE
                WHEN lead_row_count < dealer_count
                THEN NULL
                ELSE test_drives_sum * 100.0
                    / NULLIF(leads_sum, 0)
            END AS test_drive_rate_pct,
            CASE
                WHEN lead_row_count < dealer_count
                    OR sales_row_count < dealer_count
                THEN NULL
                ELSE units_sold_sum * 100.0
                    / NULLIF(test_drives_sum, 0)
            END AS drive_to_sale_pct,
            CASE
                WHEN lead_row_count < dealer_count
                    OR sales_row_count < dealer_count
                THEN NULL
                ELSE units_sold_sum * 100.0
                    / NULLIF(leads_sum, 0)
            END AS lead_to_sale_pct
        FROM regional
        WHERE EXISTS (
            SELECT 1
            FROM leads_monthly
            WHERE month = :month
        )
        ORDER BY region
        """)

    snapshot = pd.read_sql(
        query,
        get_engine(),
        params={"month": month},
    )

    if snapshot.empty:
        raise MonthNotFoundError(f"Month {month} not found")

    return snapshot


def get_model_performance(month):
    """
    Return network sales performance aggregated by vehicle model for one month.

    units_sold includes all sales rows. share_pct is each model's share of
    total network units and is NULL when network units are zero.

    avg_sale_price is weighted by units using only rows with a non-NULL
    avg_sale_price and is NULL when the priced-unit denominator is zero.

    Models with no sales_monthly rows for the requested month are omitted.
    A well-formed month with no sales rows raises MonthNotFoundError.
    """
    _validate_month(month)

    query = text("""
        WITH model_sales AS (
            SELECT
                sm.model,
                vm.segment,
                vm.msrp,
                SUM(sm.units_sold) AS units_sold,
                SUM(sm.avg_sale_price * sm.units_sold)
                    FILTER (WHERE sm.avg_sale_price IS NOT NULL)
                    / NULLIF(
                        SUM(sm.units_sold)
                            FILTER (WHERE sm.avg_sale_price IS NOT NULL),
                        0
                    ) AS avg_sale_price
            FROM sales_monthly sm
            JOIN vehicle_models vm
                ON vm.model = sm.model
            WHERE sm.month = :month
            GROUP BY
                sm.model,
                vm.segment,
                vm.msrp
        ),
        network AS (
            SELECT
                SUM(units_sold) AS network_units
            FROM model_sales
        )
        SELECT
            ms.model,
            ms.segment,
            ms.msrp,
            ms.units_sold,
            ms.units_sold * 100.0
                / NULLIF(n.network_units, 0) AS share_pct,
            ms.avg_sale_price
        FROM model_sales ms
        CROSS JOIN network n
        ORDER BY
            ms.units_sold DESC,
            ms.model
        """)

    performance = pd.read_sql(
        query,
        get_engine(),
        params={"month": month},
    )

    if performance.empty:
        raise MonthNotFoundError(f"Month {month} not found")

    return performance


def get_monthly_dealer_ranking(month, limit=None):
    """
    Return dealers ranked by monthly achievement percentage.

    Dealers without a defined achievement percentage are excluded.
    Ranking uses the raw achievement value, with dealer_id as the
    deterministic tie-break. A well-formed month with no data raises
    MonthNotFoundError; an existing month with no rankable dealers
    returns an empty DataFrame.
    """
    _validate_month(month)

    if limit is not None and (
        isinstance(limit, bool)
        or not isinstance(limit, int)
        or limit < 1
        or limit > MAX_LIMIT
    ):
        raise InvalidLimitError(
            f"Invalid limit: {limit!r}. "
            f"Expected an integer between 1 and {MAX_LIMIT}."
        )

    source = get_engine()

    existence_query = text("""
        SELECT 1
        FROM dealer_monthly_performance
        WHERE month = :month
        LIMIT 1
        """)

    month_exists = pd.read_sql(
        existence_query,
        source,
        params={"month": month},
    )

    if month_exists.empty:
        raise MonthNotFoundError(f"Month {month} not found")

    query_sql = """
        WITH ranked AS (
            SELECT
                dealer_id,
                dealer_name,
                month,
                units_sold,
                target_units,
                achievement_pct,
                ROW_NUMBER() OVER (ORDER BY achievement_pct DESC, dealer_id ASC) AS rank
            FROM dealer_monthly_performance
            WHERE month = :month
              AND achievement_pct IS NOT NULL
        )
        SELECT
            dealer_id,
            dealer_name,
            month,
            units_sold,
            target_units,
            achievement_pct,
            rank
        FROM ranked
        ORDER BY rank
    """

    params = {"month": month}

    if limit is not None:
        query_sql += "\nLIMIT CAST(:limit AS bigint)"
        params["limit"] = limit

    return pd.read_sql(
        text(query_sql),
        source,
        params=params,
    )


def _validate_optional_month(value, field_name):
    """
    Validate an optional month bound in strict ASCII YYYY-MM format.

    None represents an omitted bound. Invalid types or formats raise
    InvalidMonthError.
    """
    if value is None:
        return

    if not isinstance(value, str):
        raise InvalidMonthError(f"{field_name} month must use YYYY-MM format")

    if _MONTH_RE.fullmatch(value) is None:
        raise InvalidMonthError(f"{field_name} month must use YYYY-MM format")


def get_dealer_performance_history(
    dealer_id,
    start=None,
    end=None,
):
    """
    Return monthly sales and target performance for one dealer.

    Optional start and end bounds use strict YYYY-MM format and are
    inclusive. When neither bound is supplied, the complete available
    history is returned.

    Raises DealerNotFoundError when the dealer does not exist.
    Raises InvalidMonthError for malformed month bounds.
    Raises InvalidMonthRangeError when start is after end.
    """
    _validate_optional_month(start, "start")
    _validate_optional_month(end, "end")

    if start is not None and end is not None and start > end:
        raise InvalidMonthRangeError("start month must not be after end month")

    clauses = ["dealer_id = :dealer_id"]
    params = {"dealer_id": dealer_id}

    if start is not None:
        clauses.append("month >= :start")
        params["start"] = start

    if end is not None:
        clauses.append("month <= :end")
        params["end"] = end

    # Only fixed SQL fragments are joined here; user values stay bound parameters.
    query = text(f"""
    SELECT
        dealer_id,
        dealer_name,
        month,
        units_sold,
        target_units,
        achievement_pct
    FROM dealer_monthly_performance
    WHERE {" AND ".join(clauses)}
    ORDER BY month
    """)

    history = pd.read_sql(
        query,
        get_engine(),
        params=params,
    )

    if history.empty:
        dealer_exists = pd.read_sql(
            text("""
                SELECT 1
                FROM dealers
                WHERE dealer_id = :dealer_id
                """),
            get_engine(),
            params={"dealer_id": dealer_id},
        )

        if dealer_exists.empty:
            raise DealerNotFoundError(f"Dealer {dealer_id} not found")

    return history


def get_dealer_funnel_history(
    dealer_id,
    start=None,
    end=None,
):
    """
    Return monthly lead-funnel history for one dealer.

    Optional start and end bounds use strict YYYY-MM format and are
    inclusive. When neither bound is supplied, the complete lead-defined
    history is returned.

    Raises DealerNotFoundError when the dealer does not exist.
    Raises InvalidMonthError for malformed month bounds.
    Raises InvalidMonthRangeError when start is after end.
    """
    _validate_optional_month(start, "start")
    _validate_optional_month(end, "end")

    if start is not None and end is not None and start > end:
        raise InvalidMonthRangeError("start month must not be after end month")

    clauses = ["f.dealer_id = :dealer_id"]
    params = {"dealer_id": dealer_id}

    if start is not None:
        clauses.append("f.month >= :start")
        params["start"] = start

    if end is not None:
        clauses.append("f.month <= :end")
        params["end"] = end

    query = text(f"""
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
        WHERE {" AND ".join(clauses)}
        ORDER BY f.month
    """)

    history = pd.read_sql(
        query,
        get_engine(),
        params=params,
    )

    if history.empty:
        dealer_exists = pd.read_sql(
            text("""
                SELECT 1
                FROM dealers
                WHERE dealer_id = :dealer_id
            """),
            get_engine(),
            params={"dealer_id": dealer_id},
        )

        if dealer_exists.empty:
            raise DealerNotFoundError(f"Dealer {dealer_id} not found")

    return history


def get_regional_performance_snapshot(month):
    """
    Return one weighted performance row per region for a required month.

    Regions are ordered alphabetically. If any contributing dealer is
    missing a target, that region's target_units and achievement_pct are
    NULL. A zero regional target keeps target_units at 0 and makes
    achievement_pct NULL.

    A well-formed month with no data raises MonthNotFoundError.
    """
    _validate_month(month)

    query = text("""
        SELECT
            region,
            month,
            dealer_count,
            units_sold,
            target_units,
            achievement_pct
        FROM monthly_performance_rollup
        WHERE month = :month
          AND region IS NOT NULL
        ORDER BY region
        """)

    snapshot = pd.read_sql(
        query,
        get_engine(),
        params={"month": month},
    )

    if snapshot.empty:
        raise MonthNotFoundError(f"Month {month} not found")

    return snapshot


def get_region_performance_history(
    region,
    start=None,
    end=None,
):
    """
    Return monthly sales and target performance for one region.

    Optional start and end bounds use strict YYYY-MM format and are
    inclusive. Regional achievement is calculated from total units divided
    by total target, not by averaging dealer achievement percentages.

    Raises RegionNotFoundError when the region does not exist.
    Raises InvalidMonthError for malformed month bounds.
    Raises InvalidMonthRangeError when start is after end.
    """
    _validate_optional_month(start, "start")
    _validate_optional_month(end, "end")

    if start is not None and end is not None and start > end:
        raise InvalidMonthRangeError("start month must not be after end month")

    clauses = ["region = :region"]
    params = {"region": region}

    if start is not None:
        clauses.append("month >= :start")
        params["start"] = start

    if end is not None:
        clauses.append("month <= :end")
        params["end"] = end

    # Only fixed SQL fragments are joined here; user values stay bound parameters.
    query = text(f"""
        SELECT
            region,
            month,
            dealer_count,
            units_sold,
            target_units,
            achievement_pct
        FROM monthly_performance_rollup
        WHERE {" AND ".join(clauses)}
        ORDER BY month
        """)

    history = pd.read_sql(
        query,
        get_engine(),
        params=params,
    )

    if history.empty:
        region_exists = pd.read_sql(
            text("""
                SELECT 1
                FROM dealers
                WHERE region = :region
                LIMIT 1
                """),
            get_engine(),
            params={"region": region},
        )

        if region_exists.empty:
            raise RegionNotFoundError(f"Region {region} not found")

    return history


def get_network_performance_history(
    start=None,
    end=None,
):
    """
    Return monthly sales and target performance for the whole dealer network.

    Optional start and end bounds use strict YYYY-MM format and are
    inclusive. Network achievement is calculated from total units divided
    by total target, not by averaging dealer achievement percentages. A valid
    window with no data returns an empty result; a network has no not-found
    state.

    Raises InvalidMonthError for malformed month bounds.
    Raises InvalidMonthRangeError when start is after end.
    """
    _validate_optional_month(start, "start")
    _validate_optional_month(end, "end")

    if start is not None and end is not None and start > end:
        raise InvalidMonthRangeError("start month must not be after end month")

    clauses = ["region IS NULL"]
    params = {}

    if start is not None:
        clauses.append("month >= :start")
        params["start"] = start

    if end is not None:
        clauses.append("month <= :end")
        params["end"] = end

    where_clause = "WHERE " + " AND ".join(clauses)

    # Only fixed SQL fragments are joined here; user values stay bound parameters.
    query = text(f"""
        SELECT
            month,
            dealer_count,
            units_sold,
            target_units,
            achievement_pct
        FROM monthly_performance_rollup
        {where_clause}
        ORDER BY month
        """)

    return pd.read_sql(
        query,
        get_engine(),
        params=params,
    )


def get_dealer_funnel_ranking(month, limit=None, min_leads=0):
    """
    Return dealers ranked by monthly lead-to-sale conversion.

    Dealers with undefined lead-to-sale rates are excluded.
    The optional minimum-leads threshold is inclusive and is
    applied before contiguous ranks are assigned.

    Ranking uses the raw numeric lead-to-sale rate, with dealer_id
    as the deterministic tie-break. The optional limit is applied
    after ranking.

    A well-formed month with no lead rows raises MonthNotFoundError.
    An existing month with no eligible dealers returns an empty
    DataFrame.
    """
    _validate_month(month)

    if limit is not None and (
        isinstance(limit, bool)
        or not isinstance(limit, int)
        or limit < 1
        or limit > MAX_LIMIT
    ):
        raise InvalidLimitError(
            f"Invalid limit: {limit!r}. "
            f"Expected an integer between 1 and {MAX_LIMIT}."
        )

    if (
        isinstance(min_leads, bool)
        or not isinstance(min_leads, int)
        or min_leads < 0
        or min_leads > MAX_LIMIT
    ):
        raise InvalidMinLeadsError(
            f"Invalid min_leads: {min_leads!r}. "
            f"Expected an integer between 0 and {MAX_LIMIT}."
        )

    source = get_engine()

    existence_query = text("""
        SELECT 1
        FROM dealer_monthly_funnel
        WHERE month = :month
        LIMIT 1
        """)

    month_exists = pd.read_sql(
        existence_query,
        source,
        params={"month": month},
    )

    if month_exists.empty:
        raise MonthNotFoundError(f"Month {month} not found")

    query_sql = """
        WITH ranked AS (
            SELECT
                f.dealer_id,
                d.dealer_name,
                d.region,
                f.month,
                f.leads,
                f.test_drives,
                f.units_sold,
                f.test_drive_rate_pct,
                f.drive_to_sale_pct,
                f.lead_to_sale_pct,
                ROW_NUMBER() OVER (
                    ORDER BY f.lead_to_sale_pct DESC, f.dealer_id ASC
                ) AS rank
            FROM dealer_monthly_funnel AS f
            JOIN dealers AS d ON d.dealer_id = f.dealer_id
            WHERE f.month = :month
              AND f.lead_to_sale_pct IS NOT NULL
              AND f.leads >= CAST(:min_leads AS bigint)
        )
        SELECT
            dealer_id,
            dealer_name,
            region,
            month,
            leads,
            test_drives,
            units_sold,
            test_drive_rate_pct,
            drive_to_sale_pct,
            lead_to_sale_pct,
            rank
        FROM ranked
        ORDER BY rank
    """

    params = {
        "month": month,
        "min_leads": min_leads,
    }

    if limit is not None:
        query_sql += "\nLIMIT CAST(:limit AS bigint)"
        params["limit"] = limit

    return pd.read_sql(
        text(query_sql),
        source,
        params=params,
    )


def get_dealer_funnel_opportunities(month, limit=None, min_leads=0):
    """
    Return dealers converting below their regional lead-to-sale benchmark.

    The benchmark is the regional ratio of sums: total units sold divided by
    total leads across every dealer in the region. It exists only when every
    dealer in the region has a lead row and an aggregated sales dealer-month
    and the region has positive total leads, and it is never affected by
    min_leads or limit.

    A dealer qualifies when it has at least min_leads leads and a conversion
    rate strictly below its regional benchmark. With dealer leads/units
    (L_d, S_d) and regional leads/units (L_r, S_r), the exact numerator
    N = L_d * S_r - S_d * L_r is positive exactly then; a dealer with zero
    leads can never satisfy it, so it needs no separate guard. Operands are
    cast to numeric before multiplying so large counts cannot overflow.

    Estimated opportunity units are N / L_r: the units the dealer would have
    sold at the regional rate minus the units it actually sold. The quotient
    is computed once, as an integer division at a fixed scale of 30 decimal
    places (truncated). PostgreSQL's default numeric division picks its result
    scale from an estimate of the quotient's size, which can give
    mathematically equal opportunities different digits, and dividing before
    subtracting makes it worse. A fixed scale makes equal rationals identical
    and keeps distinct ones apart while regional lead totals stay below 1e15
    (INTEGER leads, so far fewer than 460,000 dealers per region): two
    distinct opportunities differ by at least 1 / (L_r1 * L_r2), above 1e-30.
    That is an assumption about the supported data, not a claim about the
    whole bigint range.
    Ranking happens on this numeric value, never on a converted float. Ranks
    are contiguous, ordered by opportunity descending then dealer_id, and
    assigned before the optional limit.

    A well-formed month with no lead rows raises MonthNotFoundError. An
    existing month with no qualifying dealers returns an empty DataFrame.
    """
    _validate_month(month)

    if limit is not None and (
        isinstance(limit, bool)
        or not isinstance(limit, int)
        or limit < 1
        or limit > MAX_LIMIT
    ):
        raise InvalidLimitError(
            f"Invalid limit: {limit!r}. "
            f"Expected an integer between 1 and {MAX_LIMIT}."
        )

    if (
        isinstance(min_leads, bool)
        or not isinstance(min_leads, int)
        or min_leads < 0
        or min_leads > MAX_LIMIT
    ):
        raise InvalidMinLeadsError(
            f"Invalid min_leads: {min_leads!r}. "
            f"Expected an integer between 0 and {MAX_LIMIT}."
        )

    source = get_engine()

    existence_query = text("""
        SELECT 1
        FROM dealer_monthly_funnel
        WHERE month = :month
        LIMIT 1
        """)

    month_exists = pd.read_sql(
        existence_query,
        source,
        params={"month": month},
    )

    if month_exists.empty:
        raise MonthNotFoundError(f"Month {month} not found")

    query_sql = """
        WITH regional AS (
            SELECT
                d.region,
                COUNT(*) AS dealer_count,
                COUNT(f.leads) AS lead_rows,
                COUNT(f.units_sold) AS sales_rows,
                SUM(f.leads) AS leads_sum,
                SUM(f.units_sold) AS units_sum
            FROM dealer_monthly_funnel AS f
            JOIN dealers AS d ON d.dealer_id = f.dealer_id
            WHERE f.month = :month
            GROUP BY d.region
        ),
        benchmark AS (
            SELECT region, leads_sum, units_sum
            FROM regional
            WHERE lead_rows = dealer_count
              AND sales_rows = dealer_count
              AND leads_sum > 0
        ),
        candidates AS (
            SELECT
                f.dealer_id,
                d.dealer_name,
                d.region,
                f.month,
                f.leads,
                f.units_sold,
                f.lead_to_sale_pct AS dealer_lead_to_sale_pct,
                b.units_sum * 100.0 / b.leads_sum
                    AS regional_lead_to_sale_pct,
                CAST(f.leads AS numeric) * b.units_sum
                    - CAST(f.units_sold AS numeric) * b.leads_sum
                    AS numerator,
                b.leads_sum AS regional_leads
            FROM dealer_monthly_funnel AS f
            JOIN dealers AS d ON d.dealer_id = f.dealer_id
            JOIN benchmark AS b ON b.region = d.region
            WHERE f.month = :month
              AND f.leads >= CAST(:min_leads AS bigint)
        ),
        qualified AS (
            SELECT
                dealer_id,
                dealer_name,
                region,
                month,
                leads,
                units_sold,
                dealer_lead_to_sale_pct,
                regional_lead_to_sale_pct,
                DIV(numerator * 1e30, regional_leads) * 1e-30
                    AS estimated_opportunity_units
            FROM candidates
            WHERE numerator > 0
        ),
        ranked AS (
            SELECT
                dealer_id,
                dealer_name,
                region,
                month,
                leads,
                units_sold,
                dealer_lead_to_sale_pct,
                regional_lead_to_sale_pct,
                regional_lead_to_sale_pct - dealer_lead_to_sale_pct
                    AS conversion_gap_pp,
                estimated_opportunity_units,
                ROW_NUMBER() OVER (
                    ORDER BY estimated_opportunity_units DESC, dealer_id ASC
                ) AS rank
            FROM qualified
        )
        SELECT
            dealer_id,
            dealer_name,
            region,
            month,
            leads,
            units_sold,
            dealer_lead_to_sale_pct,
            regional_lead_to_sale_pct,
            conversion_gap_pp,
            estimated_opportunity_units,
            rank
        FROM ranked
        ORDER BY rank
    """

    params = {
        "month": month,
        "min_leads": min_leads,
    }

    if limit is not None:
        query_sql += "\nLIMIT CAST(:limit AS bigint)"
        params["limit"] = limit

    return pd.read_sql(
        text(query_sql),
        source,
        params=params,
    )
