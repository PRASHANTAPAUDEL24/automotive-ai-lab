-- Program: sql/day14_region_summary.sql
-- Day 14: Region-level dealer risk summary
-- Created on: 2026-11-04
-- Author: Prashanta Paudel
-- Purpose: Summarize dealer counts and risk counts by region.

SELECT
    region,
    COUNT(*) AS dealers,
    COUNT(*) FILTER (WHERE sales_risk) AS sales_risk_dealers,
    COUNT(*) FILTER (WHERE inventory_risk) AS inventory_risk_dealers,
    COUNT(*) FILTER (WHERE combined_risk) AS combined_risk_dealers,
    COUNT(*) FILTER (WHERE early_overstock_watch) AS early_overstock_watch_dealers
FROM dealer_scorecard
GROUP BY region
ORDER BY region;
