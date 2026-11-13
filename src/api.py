# Program: src/api.py
# Day 10: FastAPI dealer analytics endpoints
# Created on: 2026-10-30
# Author: Prashanta Paudel
# Purpose: Expose dealer scorecard data through HTTP endpoints.

from fastapi import FastAPI, HTTPException, Query

from db import (
    DealerNotFoundError,
    InvalidFilterError,
    InvalidMonthError,
    InvalidMonthRangeError,
    MonthNotFoundError,
    get_at_risk_dealers,
    get_dealer,
    get_dealer_performance_history,
    get_monthly_performance,
    get_region_summary,
    get_scorecard,
    to_records,
)
from models import Dealer, MonthlyPerformance, RankedDealer, RegionSummary

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


@app.get(
    "/dealers/{dealer_id}/performance",
    response_model=list[MonthlyPerformance],
)
def dealer_performance_history(
    dealer_id: int,
    start: str | None = Query(
        default=None,
        pattern=r"^[0-9]{4}-(0[1-9]|1[0-2])$",
    ),
    end: str | None = Query(
        default=None,
        pattern=r"^[0-9]{4}-(0[1-9]|1[0-2])$",
    ),
):
    """
    Return monthly sales and target history for one dealer.

    Optional start and end bounds are inclusive. Unknown dealers return 404,
    malformed query bounds return 422 through FastAPI validation, and a
    reversed range returns 422.
    """
    try:
        history = get_dealer_performance_history(
            dealer_id,
            start=start,
            end=end,
        )
    except DealerNotFoundError as error:
        raise HTTPException(
            status_code=404,
            detail=str(error),
        ) from error
    except (InvalidMonthError, InvalidMonthRangeError) as error:
        raise HTTPException(
            status_code=422,
            detail=str(error),
        ) from error

    return to_records(history)


@app.get("/dealers/at-risk", response_model=list[RankedDealer])
def at_risk_dealers(
    limit: int | None = Query(default=None, ge=1),
):
    dealers = get_at_risk_dealers(limit=limit)
    return to_records(dealers)


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


@app.get("/performance", response_model=list[MonthlyPerformance])
def monthly_performance(
    month: str = Query(
        ...,
        pattern=r"^[0-9]{4}-(0[1-9]|1[0-2])$",
        description="Month in YYYY-MM format.",
    ),
):
    try:
        performance = get_monthly_performance(month)
    except MonthNotFoundError as error:
        raise HTTPException(
            status_code=404,
            detail=str(error),
        ) from error
    except InvalidMonthError as error:
        raise HTTPException(
            status_code=422,
            detail=str(error),
        ) from error

    return to_records(performance)
