-- Day 7: Validate dealer scorecard
-- Requires: sql/03_views.sql

SELECT
    COUNT(*) AS dealers,
    COUNT(*) FILTER (WHERE sales_risk) AS sales_risk,
    COUNT(*) FILTER (WHERE inventory_risk) AS inventory_risk,
    COUNT(*) FILTER (WHERE combined_risk) AS combined_risk,
    COUNT(*) FILTER (WHERE early_overstock_watch) AS early_overstock_watch,
    COUNT(*) FILTER (
        WHERE inventory_risk AND NOT sales_risk
    ) AS inventory_only,
    COUNT(*) FILTER (
        WHERE sales_risk AND NOT inventory_risk
    ) AS sales_only
FROM dealer_scorecard;


-- Final dealer scorecard output

SELECT
    dealer_id,
    dealer_name,
    region,
    size_class,
    units_sold,
    target_units,
    ROUND(achievement_pct, 1) AS achievement_pct,
    available_units,
    aged_units,
    ROUND(aged_pct, 1) AS aged_pct,
    ROUND(months_of_supply, 1) AS months_of_supply,
    sales_risk,
    inventory_risk,
    combined_risk,
    early_overstock_watch
FROM dealer_scorecard
ORDER BY
    combined_risk DESC,
    early_overstock_watch DESC,
    sales_risk DESC,
    inventory_risk DESC,
    dealer_id;
