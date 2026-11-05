-- Program: sql/day15_at_risk_dealers.sql
-- Day 15: Ranked at-risk dealer list
-- Created on: 2026.11.05
-- Author: Prashanta Paudel
-- Purpose: Rank dealers requiring management attention by risk tier.

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
ORDER BY rank;
