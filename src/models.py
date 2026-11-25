# Program: src/models.py
# Day 13: Pydantic response models
# Created on: 2026-11-03
# Author: Prashanta Paudel
# Purpose: Define validated API response schemas for dealer and regional analytics.

from pydantic import BaseModel, Field


class Dealer(BaseModel):
    """One dealer's scorecard for the reporting month."""

    dealer_id: int
    dealer_name: str
    region: str
    size_class: str
    units_sold: int

    target_units: int | None = Field(
        description="Monthly target units. Null when the dealer has no target row."
    )

    achievement_pct: float | None = Field(
        description="Sales achievement versus target. Null when the target is missing or zero."
    )

    available_units: int
    aged_units: int

    avg_days_available: float | None = Field(
        description="Average days in stock for available units. Null when no units are available."
    )

    aged_pct: float | None = Field(
        description="Percent of available units older than 90 days. Null when no units are available."
    )

    months_of_supply: float | None = Field(
        description="Available units divided by monthly sales. Null when inventory exists but sales are zero."
    )

    high_supply: bool
    inventory_risk: bool
    sales_risk: bool
    combined_risk: bool
    early_overstock_watch: bool


class RegionSummary(BaseModel):
    """Risk summary for one dealer region."""

    region: str = Field(description="Dealer region.")
    dealers: int = Field(description="Number of dealers in the region.")
    sales_risk_dealers: int = Field(
        description="Dealers with September achievement below 80%."
    )
    inventory_risk_dealers: int = Field(
        description="Dealers meeting the inventory-risk rule."
    )
    combined_risk_dealers: int = Field(
        description="Dealers with both sales risk and inventory risk."
    )
    early_overstock_watch_dealers: int = Field(
        description="Dealers on the early-overstock watch list."
    )


class RankedDealer(Dealer):
    """Dealer ranked by management urgency."""

    rank: int = Field(description="Global urgency rank; 1 is the most urgent dealer.")
    risk_tier: int = Field(
        description=(
            "Risk tier: 1 = combined risk, "
            "2 = early overstock watch, "
            "3 = sales risk only, "
            "4 = inventory risk only."
        )
    )


class MonthlyPerformance(BaseModel):
    """Sales and target performance for one dealer and month."""

    dealer_id: int
    dealer_name: str
    month: str
    units_sold: int
    target_units: int | None = Field(
        description="Monthly target units. Null when the dealer has no target row."
    )
    achievement_pct: float | None = Field(
        description="Sales achievement versus target. Null when the target is missing or zero."
    )


class DealerMonthlyFunnel(BaseModel):
    """Lead-funnel performance for one dealer and month."""

    dealer_id: int
    dealer_name: str
    month: str

    leads: int | None = Field(
        ...,
        description="Monthly leads. Null when the dealer has no lead row.",
    )
    test_drives: int | None = Field(
        ...,
        description="Monthly test drives. Null when the dealer has no lead row.",
    )
    units_sold: int | None = Field(
        ...,
        description="Monthly units sold. Null when the dealer has no sales rows.",
    )
    test_drive_rate_pct: float | None = Field(
        ...,
        description=(
            "Test drives as a percentage of leads. "
            "Null when leads are missing or zero."
        ),
    )
    drive_to_sale_pct: float | None = Field(
        ...,
        description=(
            "Units sold as a percentage of test drives. "
            "Null when sales are missing or test drives are missing or zero."
        ),
    )
    lead_to_sale_pct: float | None = Field(
        ...,
        description=(
            "Units sold as a percentage of leads. "
            "Null when sales are missing or leads are missing or zero."
        ),
    )


class ModelMonthlyPerformance(BaseModel):
    """Network sales performance for one vehicle model and month."""

    model: str
    segment: str
    msrp: int
    units_sold: int

    share_pct: float | None = Field(
        description=(
            "Share of network units sold for the requested month. "
            "Null when total network units are zero."
        )
    )

    avg_sale_price: float | None = Field(
        description=(
            "Unit-weighted average sale price using only rows with "
            "a non-null price. Null when priced units total zero."
        )
    )


class NetworkMonthlyFunnel(BaseModel):
    """Network-wide lead-funnel performance for one month."""

    month: str

    leads: int | None = Field(
        ...,
        description=("Network leads. Null when any dealer is missing its lead row."),
    )

    test_drives: int | None = Field(
        ...,
        description=(
            "Network test drives. Null when any dealer is missing its lead row."
        ),
    )

    units_sold: int | None = Field(
        ...,
        description=(
            "Network units sold. Null when any dealer is missing its sales rows."
        ),
    )

    test_drive_rate_pct: float | None = Field(
        ...,
        description=(
            "Network test drives as a percentage of leads. "
            "Null when lead data is incomplete or leads are zero."
        ),
    )

    drive_to_sale_pct: float | None = Field(
        ...,
        description=(
            "Network units sold as a percentage of test drives. "
            "Null when lead or sales data is incomplete or test drives are zero."
        ),
    )

    lead_to_sale_pct: float | None = Field(
        ...,
        description=(
            "Network units sold as a percentage of leads. "
            "Null when lead or sales data is incomplete or leads are zero."
        ),
    )


class RegionalFunnel(BaseModel):
    """Regional lead funnel metrics for one requested month."""

    region: str

    leads: int | None = Field(
        description="Total leads for the region. Null when regional lead data is incomplete."
    )
    test_drives: int | None = Field(
        description=(
            "Total test drives for the region. "
            "Null when regional lead data is incomplete."
        )
    )
    units_sold: int | None = Field(
        description=(
            "Total units sold for the region. "
            "Null when regional sales data is incomplete."
        )
    )
    test_drive_rate_pct: float | None = Field(
        description=(
            "Test drives as a percentage of leads using regional sums. "
            "Null when lead data is incomplete or regional leads are zero."
        )
    )
    drive_to_sale_pct: float | None = Field(
        description=(
            "Units sold as a percentage of test drives using regional sums. "
            "Null when lead or sales data is incomplete or regional test drives are zero."
        )
    )
    lead_to_sale_pct: float | None = Field(
        description=(
            "Units sold as a percentage of leads using regional sums. "
            "Null when lead or sales data is incomplete or regional leads are zero."
        )
    )


class RankedMonthlyPerformance(BaseModel):
    """One dealer's ranked performance for a required month."""

    dealer_id: int
    dealer_name: str
    month: str
    units_sold: int
    target_units: int = Field(description="Monthly target units for a rankable dealer.")
    achievement_pct: float = Field(
        description="Sales achievement versus target for a rankable dealer."
    )
    rank: int = Field(
        description="Monthly performance rank; 1 is the highest achievement."
    )


class RegionMonthlyPerformance(BaseModel):
    """Aggregated sales and target performance for one region and month."""

    region: str
    month: str
    dealer_count: int
    units_sold: int
    target_units: int | None = Field(
        description=(
            "Regional monthly target units. Null when any contributing "
            "dealer has no target."
        )
    )
    achievement_pct: float | None = Field(
        description=(
            "Regional sales achievement based on total units divided by "
            "total target. Null when a target is missing or the total target "
            "is zero."
        )
    )


class NetworkMonthlyPerformance(BaseModel):
    """Aggregated sales and target performance for the full dealer network."""

    month: str
    dealer_count: int
    units_sold: int
    target_units: int | None = Field(
        description=(
            "Network monthly target units. Null when any contributing "
            "dealer has no target."
        )
    )
    achievement_pct: float | None = Field(
        description=(
            "Network sales achievement based on total units divided by "
            "total target. Null when a target is missing or the total target "
            "is zero."
        )
    )


class RankedDealerFunnel(BaseModel):
    """One dealer's ranked lead-funnel performance for a month."""

    dealer_id: int
    dealer_name: str
    region: str
    month: str
    leads: int
    test_drives: int
    units_sold: int
    test_drive_rate_pct: float
    drive_to_sale_pct: float | None = Field(
        ...,
        description="Sales per 100 test drives. Null when test drives are zero.",
    )
    lead_to_sale_pct: float
    rank: int = Field(
        description="Monthly conversion rank; 1 is the highest conversion."
    )
