-- Day 5: Rebuild September 2026 dealer performance report
SELECT
    d.dealer_id,
    d.dealer_name,
    SUM (s.units_sold) AS units_sold,
    t.target_units,
    ROUND (
        SUM (s.units_sold) * 100.0 / t.target_units,
        1
    ) AS achievement_pct,
    CASE 
        WHEN SUM(s.units_sold) * 100.0 / t.target_units < 80
            THEN 'Needs attention'
        WHEN SUM(s.units_sold) * 100.0 /t.target_units < 100
            THEN 'Below target'
        ELSE 'Target achieved'
    END AS status
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
ORDER BY achievement_pct ASC;
     
-- Validate dealer count and sales-risk count

SELECT
    COUNT(*) AS dealers,
    COUNT(*) FILTER (WHERE achievement_pct < 80.0) AS needs_attention
FROM (
    SELECT
    d.dealer_id,
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
    t.target_units
) AS performance;

-- Count dealers by performance status

SELECT
    status,
    COUNT(*) AS dealer_count
FROM(
    SELECT
    d.dealer_id,
    CASE 
        WHEN SUM(s.units_sold) * 100.0 / t.target_units < 80
            THEN 'Needs attention'
        WHEN SUM(s.units_sold) * 100.0 / t.target_units < 100
            THEN 'Below target'
        ELSE 'Target achieved'
    END AS status
    FROM dealers d
    JOIN sales_monthly s
        ON d.dealer_id = s.dealer_id
    JOIN dealer_targets t 
        ON d.dealer_id = t.dealer_id
        AND t.month = '2026-09'
    WHERE s.month = '2026-09'
    GROUP BY 
        d.dealer_id,
        t.target_units    
) AS performance
GROUP BY status
ORDER BY dealer_count DESC;