-- Day 6 Stage 1: Inventory aging by dealer
-- Available inventory includes only vehicles with status = 'In Stock'
-- Aged inventory means more than 90 days in stock

SELECT 
    dealer_id,
    COUNT(*) AS available_units,
    COUNT(*) FILTER (
        WHERE days_in_stock > 90
    ) AS aged_units,
    ROUND(
        AVG(days_in_stock),
        1
    ) AS avg_days_available
FROM inventory_snapshot
WHERE status = 'In Stock'
GROUP BY dealer_id
ORDER BY avg_days_available DESC;

SELECT
    COUNT(DISTINCT dealer_id) AS dealers,
    COUNT(*) AS available_units,
    COUNT(*) FILTER (
        WHERE days_in_stock > 90
    ) AS aged_units
FROM inventory_snapshot
WHERE status = 'In Stock';


-- Day 6 Stage 2: Inventory aging starting from all dealers
-- LEFT JOIN keeps dealers visible even if they have no available inventory.

WITH inventory_by_dealer AS (
    SELECT
        d.dealer_id,
        d.dealer_name,
        COUNT(i.vin) AS available_units,
        COUNT(i.vin) FILTER (
           WHERE i.days_in_stock > 90
        ) AS aged_units,
        ROUND(
            AVG(i.days_in_stock),
            1
        ) AS avg_days_available
    FROM dealers d
    LEFT JOIN inventory_snapshot i
        ON d.dealer_id = i.dealer_id
        AND i.status = 'In Stock'
    GROUP BY
        d.dealer_id,
        d.dealer_name
)


SELECT
    dealer_id,
    dealer_name,
    available_units,
    aged_units,
    ROUND(
        aged_units * 100.0 / NULLIF(available_units, 0),
        1
    ) AS aged_pct,
    avg_days_available
FROM inventory_by_dealer
ORDER BY avg_days_available DESC NULLS LAST;


-- Day 6 Stage 3: Add September sales and months of supply
-- Available inventory includes only vehicles with status = 'In Stock'.
-- Aged inventory means more than 90 days in stock.
-- Months of supply = available units / September units sold.
-- If September sales are zero, months of supply is left as NULL because the
-- ratio is undefined. Stage 4 treats stock with zero sales as high supply
-- when it sets the inventory-risk flag.

WITH inventory_by_dealer AS (
    SELECT
        d.dealer_id,
        d.dealer_name,
        COUNT(i.vin) AS available_units,
        COUNT(i.vin) FILTER (
           WHERE i.days_in_stock > 90
        ) AS aged_units,
        ROUND(
            AVG(i.days_in_stock),
            1
        ) AS avg_days_available
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
        i.aged_units * 100.0 / NULLIF(i.available_units, 0) AS aged_pct,
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
)


SELECT
    dealer_id,
    dealer_name,
    available_units,
    aged_units,
    ROUND(aged_pct, 1) AS aged_pct,
    units_sold,
    ROUND(months_of_supply, 1) AS months_of_supply,
    avg_days_available
FROM supply
ORDER BY supply.months_of_supply DESC NULLS LAST;

-- Day 6 Stage 4: Flag inventory-risk dealers
-- Business rule: more than 4 months of supply AND more than 30% aged.
-- Dealers with available stock but zero September sales are also treated
-- as high supply, matching the Python implementation.

WITH inventory_by_dealer AS (
    SELECT
        d.dealer_id,
        d.dealer_name,
        COUNT(i.vin) AS available_units,
        COUNT(i.vin) FILTER (
           WHERE i.days_in_stock > 90
        ) AS aged_units,
        ROUND(
            AVG(i.days_in_stock),
            1
        ) AS avg_days_available
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
        i.aged_units * 100.0 / NULLIF(i.available_units, 0) AS aged_pct,
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
risk_flagged AS (
    SELECT 
        *,
        COALESCE(
            (
                months_of_supply > 4
                OR (units_sold = 0 AND available_units > 0)
            )
            AND aged_pct > 30,
            FALSE
        ) AS inventory_risk
    FROM supply
)

SELECT
    dealer_id,
    dealer_name,
    available_units,
    aged_units,
    ROUND(aged_pct, 1) AS aged_pct,
    units_sold,
    ROUND(months_of_supply, 1) AS months_of_supply,
    inventory_risk
FROM risk_flagged
WHERE inventory_risk
ORDER BY risk_flagged.months_of_supply DESC NULLS LAST;

-- Dealers with high months of supply (> 4) that are not inventory-risk.
-- This is NOT the Day 4 early-overstock watch, which also requires sales risk.

WITH inventory_by_dealer AS (
    SELECT
        d.dealer_id,
        d.dealer_name,
        COUNT(i.vin) AS available_units,
        COUNT(i.vin) FILTER (
            WHERE i.days_in_stock > 90
        ) AS aged_units,
        ROUND(
            AVG(i.days_in_stock),
            1
        ) AS avg_days_available
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
        i.aged_units * 100.0 / NULLIF(i.available_units, 0) AS aged_pct,
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
        ON s.dealer_id = i.dealer_id
),
risk_flagged AS (
    SELECT
        *,
        COALESCE(
            (
                months_of_supply > 4
                OR (units_sold = 0 AND available_units > 0)
            )
            AND aged_pct > 30,
            FALSE
        ) AS inventory_risk
    FROM supply
)

SELECT
    dealer_id,
    dealer_name,
    ROUND(aged_pct, 1) AS aged_pct,
    ROUND(months_of_supply, 1) AS months_of_supply
FROM risk_flagged
WHERE months_of_supply > 4
  AND NOT inventory_risk
ORDER BY risk_flagged.months_of_supply DESC;