# Program: src/api.py
# Day 10: FastAPI dealer analytics endpoints
# Created on: 2026-10-30
# Author: Prashanta Paudel
# Purpose: Expose dealer scorecard data through HTTP endpoints.

from fastapi import FastAPI, HTTPException

from db import (
    InvalidFilterError,
    get_dealer,
    get_region_summary,
    get_scorecard,
    to_records,
)
from models import Dealer, RegionSummary

app = FastAPI(
    title="Automotive Dealer Analytics API",
    version="0.1.0",
)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/dealers", response_model=list[Dealer])
def dealers(region: str | None = None, risk: str | None = None):
    try:
        scorecard = get_scorecard(
            region=region,
            risk=risk,
        )
    except InvalidFilterError as error:
        raise HTTPException(
            status_code=400,
            detail=str(error),
        ) from error

    return to_records(scorecard)


@app.get("/dealers/{dealer_id}", response_model=Dealer)
def dealer_by_id(dealer_id: int):
    dealer = get_dealer(dealer_id)

    if dealer is None:
        raise HTTPException(
            status_code=404,
            detail=f"Dealer {dealer_id} not found",
        )

    return dealer


@app.get("/regions/summary", response_model=list[RegionSummary])
def region_summary():
    summary = get_region_summary()
    return to_records(summary)
