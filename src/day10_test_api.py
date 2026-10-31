# Program: src/day10_test_api.py
# Day 10: FastAPI endpoint tests
# Created on: 2026-10-30
# Author: Prashanta Paudel
# Purpose: Validate the FastAPI health and dealer endpoints
# without starting the Uvicorn development server.

import pandas as pd

from fastapi.testclient import TestClient

from api import app, to_records


client = TestClient(app)

# NULL values must become JSON null, not NaN, which JSON cannot represent.
nan_records = to_records(
    pd.DataFrame(
        {
            "x": [1.5, float("nan")],
        }
    )
)

assert nan_records == [
    {"x": 1.5},
    {"x": None},
], f"Unexpected NaN conversion: {nan_records}"

print("NaN conversion test passed.")


# Health endpoint should confirm that the API is running.
response = client.get("/health")

assert response.status_code == 200, f"Expected HTTP 200, got {response.status_code}"

assert response.json() == {
    "status": "ok"
}, f"Unexpected health response: {response.json()}"


# The unfiltered dealer endpoint should return all 40 dealers.
response = client.get("/dealers")

assert response.status_code == 200, f"Expected HTTP 200, got {response.status_code}"

assert len(response.json()) == 40, f"Expected 40 dealers, got {len(response.json())}"


# Region filtering should return the 8 West-region dealers.
response = client.get(
    "/dealers",
    params={"region": "West"},
)

assert response.status_code == 200
assert (
    len(response.json()) == 8
), f"Expected 8 West-region dealers, got {len(response.json())}"


# Combined-risk filtering should return dealer 111 only.
response = client.get(
    "/dealers",
    params={"risk": "combined_risk"},
)


assert response.status_code == 200
assert len(response.json()) == 1
assert response.json()[0]["dealer_id"] == 111


# Invalid risk filters should return a client error.
response = client.get(
    "/dealers",
    params={"risk": "dealer_name"},
)

assert response.status_code == 400, f"Expected HTTP 400, got {response.status_code}"

assert response.json()["detail"] == ("Invalid risk filter: dealer_name")


# Unknown regions are valid queries but should return no dealers.
response = client.get(
    "/dealers",
    params={"region": "Atlantis"},
)

assert response.status_code == 200
assert response.json() == []


# Injection-like input must be treated only as a region value.
response = client.get(
    "/dealers",
    params={"region": "West' OR '1'='1"},
)

assert response.status_code == 200
assert response.json() == []


print("Health endpoint test passed.")
print("Dealer endpoint test passed.")
print("Region filter test passed.")
print("Risk filter test passed.")
print("Invalid-filter test passed.")
print("Unknown-region test passed.")
print("Injection test passed.")
print("Day 10 API validation passed.")
