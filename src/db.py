# Program: src/db.py
# Day 9: Reusable PostgreSQL access functions
# Created on: 2026-10-29
# Author: Prashanta Paudel
# Purpose: Centralize database connectivity and provide
# reusable access to the dealer scorecard.

import os
from functools import lru_cache

import pandas as pd
from sqlalchemy import create_engine, text


class InvalidFilterError(ValueError):
    """Raised when a caller passes an unsupported filter value."""


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
