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


class MonthNotFoundError(ValueError):
    """Raised when a well-formed month has no data."""


class DealerNotFoundError(ValueError):
    """Raised when a requested dealer does not exist."""


class InvalidMonthRangeError(ValueError):
    """Raised when the requested month range is invalid."""


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
        LIMIT CAST(:limit AS integer)
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

    if not isinstance(month, str) or not re.fullmatch(
        r"[0-9]{4}-(0[1-9]|1[0-2])",
        month,
    ):
        raise InvalidMonthError(f"Invalid month: {month!r}. Expected YYYY-MM.")

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

    if (
        re.fullmatch(
            r"[0-9]{4}-(0[1-9]|1[0-2])",
            value,
        )
        is None
    ):
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
