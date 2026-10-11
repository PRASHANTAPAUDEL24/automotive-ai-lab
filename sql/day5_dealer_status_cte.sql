-- Day 5: Dealer performance using CTEs
WITH performance AS (
    SELECT
        d.dealer_id,
        d.dealer_name,
        SUM(s.units_sold) AS units_sold,
        t.target_units,
        SUM(s.units_sold) * 100.0 / t.target_units AS achievement_pct
    FROM dealers d 
    JOIN sales_monthly s
        ON d.dealer_id = s.dealer_id
    JOIN dealer_targets t
        ON d.dealer_id = t.dealer_id
        AND t.month = '2026-09'
    WHERE s.month = '2026-09'
    GROUP BY
        d.dealer_id,
        d.dealer_name,
        t.target_units
),
classified AS (
    SELECT 
        *,
        CASE 
            WHEN achievement_pct < 80 THEN 'Needs attention'
            WHEN achievement_pct < 100 THEN 'Below target'
            ELSE 'Target achieved'
        END AS status
    FROM performance
)

SELECT
    dealer_id,
    dealer_name,
    units_sold,
    target_units,
    ROUND(achievement_pct, 1) AS achievement_pct,
    status
FROM classified
ORDER BY classified.achievement_pct ASC;

-- Count dealers by status

WITH performance AS(
    SELECT
        d.dealer_id,
        d.dealer_name,
        SUM(s.units_sold) AS units_sold,
        t.target_units,
        SUM(s.units_sold) * 100.0 / t.target_units AS achievement_pct
    FROM dealers d 
    JOIN sales_monthly s 
        ON d.dealer_id = s.dealer_id
    JOIN dealer_targets t 
        ON d.dealer_id = t.dealer_id
        AND t.month = '2026-09'
    WHERE s.month = '2026-09'
    GROUP BY
        d.dealer_id,
        d.dealer_name,
        t.target_units
),
classified AS (
    SELECT 
        *,
        CASE
            WHEN achievement_pct < 80 THEN 'Needs attention'
            WHEN achievement_pct < 100 THEN 'Below target'
            ELSE 'Target achieved'
        END AS status
    FROM performance
)

SELECT
    status,
    COUNT(*) AS dealer_count
FROM classified
GROUP BY status
ORDER BY dealer_count DESC;

