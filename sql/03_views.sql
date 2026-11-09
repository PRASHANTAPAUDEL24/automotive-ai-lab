-- Day 7: Reusable PostgreSQL views
-- Re-running this file rebuilds the view layer.

DROP VIEW IF EXISTS dealer_scorecard CASCADE;
DROP VIEW IF EXISTS inventory_supply CASCADE;
DROP VIEW IF EXISTS dealer_performance CASCADE;
DROP VIEW IF EXISTS dealer_monthly_performance CASCADE;

-- One row per dealer and month. A dealer with no sales in a month gets units_sold = 0.
CREATE VIEW dealer_monthly_performance AS
WITH months AS (
    SELECT month
    FROM sales_monthly

    UNION

    SELECT month
    FROM dealer_targets
),
monthly_sales AS (
    SELECT
        dealer_id,
        month,
        SUM(units_sold) AS units_sold
    FROM sales_monthly
    GROUP BY
        dealer_id,
        month
)
SELECT
    d.dealer_id,
    d.dealer_name,
    m.month,
    COALESCE(s.units_sold, 0) AS units_sold,
    t.target_units,
    COALESCE(s.units_sold, 0) * 100.0
        / NULLIF(t.target_units, 0) AS achievement_pct
FROM dealers d
CROSS JOIN months m
LEFT JOIN monthly_sales s
    ON d.dealer_id = s.dealer_id
    AND m.month = s.month
LEFT JOIN dealer_targets t
    ON d.dealer_id = t.dealer_id
    AND m.month = t.month;


CREATE VIEW dealer_performance AS
SELECT
    dealer_id,
    dealer_name,
    units_sold,
    target_units,
    achievement_pct
FROM dealer_monthly_performance
WHERE month = '2026-09';


-- Inventory metrics describe the snapshot as of 2026-09-30.
CREATE VIEW inventory_supply AS

WITH inventory_by_dealer AS (
    SELECT
        d.dealer_id,
        d.dealer_name,
        COUNT(i.vin) AS available_units,
        COUNT(i.vin) FILTER (
            WHERE i.days_in_stock > 90
        ) AS aged_units,
        AVG(i.days_in_stock) AS avg_days_available
    FROM dealers d
    LEFT JOIN inventory_snapshot i
        ON d.dealer_id = i.dealer_id
        AND i.status = 'In Stock'
    GROUP BY
        d.dealer_id,
        d.dealer_name
),
september_sales AS (
    SELECT
        dealer_id,
        SUM(units_sold) AS units_sold
    FROM sales_monthly
    WHERE month = '2026-09'
    GROUP BY dealer_id
),
supply AS (
    SELECT
        i.dealer_id,
        i.dealer_name,
        i.available_units,
        i.aged_units,
        i.avg_days_available,
        COALESCE(s.units_sold, 0) AS units_sold,
        i.aged_units * 100.0
            / NULLIF(i.available_units, 0) AS aged_pct,
        CASE
            WHEN i.available_units = 0
                 AND COALESCE(s.units_sold, 0) = 0
                THEN 0
            WHEN COALESCE(s.units_sold, 0) = 0
                THEN NULL
            ELSE i.available_units * 1.0 / s.units_sold
        END AS months_of_supply
    FROM inventory_by_dealer i
    LEFT JOIN september_sales s
        ON i.dealer_id = s.dealer_id
),
supply_flags AS (
    SELECT
        *,
        COALESCE(
            months_of_supply > 4
            OR (units_sold = 0 AND available_units > 0),
            FALSE
        ) AS high_supply
    FROM supply
)

SELECT
    *,
    COALESCE(
        high_supply
        AND aged_pct > 30,
        FALSE
    ) AS inventory_risk
FROM supply_flags;


CREATE VIEW dealer_scorecard AS

WITH scorecard_base AS (
    SELECT
        d.dealer_id,
        d.dealer_name,
        d.region,
        d.size_class,
        p.units_sold,
        p.target_units,
        p.achievement_pct,
        i.available_units,
        i.aged_units,
        i.avg_days_available,
        i.aged_pct,
        i.months_of_supply,
        COALESCE(i.high_supply, FALSE) AS high_supply,
        COALESCE(i.inventory_risk, FALSE) AS inventory_risk,
        COALESCE(
            p.achievement_pct < 80,
            FALSE
        ) AS sales_risk
    FROM dealers d
    LEFT JOIN dealer_performance p
        ON d.dealer_id = p.dealer_id
    LEFT JOIN inventory_supply i
        ON d.dealer_id = i.dealer_id
)

SELECT
    *,
    COALESCE(
        sales_risk AND inventory_risk,
        FALSE
    ) AS combined_risk,
    COALESCE(
        sales_risk
        AND high_supply
        AND NOT inventory_risk,
        FALSE
    ) AS early_overstock_watch
FROM scorecard_base;
