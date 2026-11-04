# Program: src/models.py
# Day 13: Pydantic response models
# Created on: 2026-11-03
# Author: Prashanta Paudel
# Purpose: Define validated API response schemas for dealer data.

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
