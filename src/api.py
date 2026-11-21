# Program: src/api.py
# Day 10: FastAPI dealer analytics endpoints
# Created on: 2026-10-30
# Author: Prashanta Paudel
# Purpose: Expose dealer scorecard data through HTTP endpoints.

from fastapi import FastAPI, HTTPException, Query

from db import (
    MAX_LIMIT,
    MONTH_QUERY_PATTERN,
    DealerNotFoundError,
    InvalidFilterError,
    InvalidLimitError,
    InvalidMonthError,
    InvalidMonthRangeError,
    MonthNotFoundError,
    RegionNotFoundError,
    get_at_risk_dealers,
    get_dealer,
    get_dealer_performance_history,
    get_model_performance,
    get_monthly_dealer_ranking,
    get_monthly_performance,
    get_network_performance_history,
    get_region_performance_history,
    get_region_summary,
    get_regional_funnel_snapshot,
    get_regional_performance_snapshot,
    get_scorecard,
    to_records,
)
from models import (
    Dealer,
    ModelMonthlyPerformance,
    MonthlyPerformance,
    NetworkMonthlyPerformance,
    RankedDealer,
    RankedMonthlyPerformance,
    RegionalFunnel,
    RegionMonthlyPerformance,
    RegionSummary,
)

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
        pattern=MONTH_QUERY_PATTERN,
    ),
    end: str | None = Query(
        default=None,
        pattern=MONTH_QUERY_PATTERN,
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
    limit: int | None = Query(
        default=None,
        ge=1,
        le=MAX_LIMIT,
    ),
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


@app.get(
    "/regions/{region}/performance",
    response_model=list[RegionMonthlyPerformance],
)
def region_performance_history(
    region: str,
    start: str | None = Query(
        default=None,
        pattern=MONTH_QUERY_PATTERN,
    ),
    end: str | None = Query(
        default=None,
        pattern=MONTH_QUERY_PATTERN,
    ),
):
    """
    Return monthly sales and target performance for one region.

    Optional start and end bounds are inclusive. Region names are exact and
    case-sensitive. Unknown regions return 404, while a real region with no
    rows in the requested window returns an empty list. Malformed query bounds
    return 422 through FastAPI validation, and a reversed range returns 422.
    """
    try:
        history = get_region_performance_history(
            region,
            start=start,
            end=end,
        )
    except RegionNotFoundError as error:
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


@app.get(
    "/performance/trend",
    response_model=list[NetworkMonthlyPerformance],
)
def network_performance_history(
    start: str | None = Query(
        default=None,
        pattern=MONTH_QUERY_PATTERN,
    ),
    end: str | None = Query(
        default=None,
        pattern=MONTH_QUERY_PATTERN,
    ),
):
    """
    Return monthly sales and target performance for the full dealer network.

    Optional start and end bounds are inclusive. A valid range with no data
    returns an empty list. Malformed query bounds return 422 through FastAPI
    validation, and a reversed range returns 422.
    """
    try:
        history = get_network_performance_history(
            start=start,
            end=end,
        )
    except (InvalidMonthError, InvalidMonthRangeError) as error:
        raise HTTPException(
            status_code=422,
            detail=str(error),
        ) from error

    return to_records(history)


@app.get(
    "/performance/ranking",
    response_model=list[RankedMonthlyPerformance],
)
def monthly_performance_ranking(
    month: str = Query(
        ...,
        pattern=MONTH_QUERY_PATTERN,
        description="Month in YYYY-MM format.",
    ),
    limit: int | None = Query(
        default=None,
        ge=1,
        le=MAX_LIMIT,
    ),
):
    """Return dealers ranked by achievement for one month."""
    try:
        ranking = get_monthly_dealer_ranking(
            month,
            limit=limit,
        )
    except (InvalidMonthError, InvalidLimitError) as error:
        raise HTTPException(
            status_code=422,
            detail=str(error),
        ) from error
    except MonthNotFoundError as error:
        raise HTTPException(
            status_code=404,
            detail=str(error),
        ) from error

    return to_records(ranking)


@app.get(
    "/performance/regions",
    response_model=list[RegionMonthlyPerformance],
)
def regional_performance_snapshot(
    month: str = Query(
        ...,
        pattern=MONTH_QUERY_PATTERN,
        description="Month in YYYY-MM format.",
    ),
):
    """Return one weighted performance row per region for one month."""
    try:
        snapshot = get_regional_performance_snapshot(month)
    except InvalidMonthError as error:
        raise HTTPException(
            status_code=422,
            detail=str(error),
        ) from error
    except MonthNotFoundError as error:
        raise HTTPException(
            status_code=404,
            detail=str(error),
        ) from error

    return to_records(snapshot)


@app.get(
    "/performance/funnel",
    response_model=list[RegionalFunnel],
)
def regional_funnel(
    month: str = Query(
        ...,
        pattern=MONTH_QUERY_PATTERN,
        description="Month in YYYY-MM format.",
    ),
):
    """Return one lead-funnel row per dealer region for one month."""

    try:
        funnel = get_regional_funnel_snapshot(month)
    except InvalidMonthError as error:
        raise HTTPException(
            status_code=422,
            detail=str(error),
        ) from error
    except MonthNotFoundError as error:
        raise HTTPException(
            status_code=404,
            detail=str(error),
        ) from error

    return to_records(funnel)


@app.get(
    "/performance/models",
    response_model=list[ModelMonthlyPerformance],
)
def model_performance(
    month: str = Query(
        ...,
        pattern=MONTH_QUERY_PATTERN,
        description="Month in YYYY-MM format.",
    ),
):
    """Return network sales performance by vehicle model for one month."""

    try:
        performance = get_model_performance(month)
    except InvalidMonthError as error:
        raise HTTPException(
            status_code=422,
            detail=str(error),
        ) from error
    except MonthNotFoundError as error:
        raise HTTPException(
            status_code=404,
            detail=str(error),
        ) from error

    return to_records(performance)


@app.get("/performance", response_model=list[MonthlyPerformance])
def monthly_performance(
    month: str = Query(
        ...,
        pattern=MONTH_QUERY_PATTERN,
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
