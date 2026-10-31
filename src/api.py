# Program: src/api.py
# Day 10: FastAPI dealer analytics endpoints
# Created on: 2026-10-30
# Author: Prashanta Paudel
# Purpose: Expose dealer scorecard data through HTTP endpoints.

from fastapi import FastAPI, HTTPException

from db import InvalidFilterError, get_scorecard


app = FastAPI(
    title="Automotive Dealer Analytics API",
    version="0.1.0",
)


def to_records(df):
    """Convert a DataFrame to JSON-safe records (NaN becomes None)."""
    return df.astype(object).where(df.notna(), None).to_dict(orient="records")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/dealers")
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
