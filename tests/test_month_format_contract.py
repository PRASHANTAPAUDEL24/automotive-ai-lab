"""
Contract tests for the single strict YYYY-MM month rule.

Day 23 replaces seven copies of the month regular expression with one
definition in src/db.py. These tests keep it that way: every FastAPI month
parameter must use the shared pattern, the rule itself must not drift, and
the regular-expression literal must exist in exactly one source file.
"""

from pathlib import Path

import pytest

import db
from api import app

SRC_DIR = Path(__file__).resolve().parents[1] / "src"

# A literal fragment of the rule; it must appear exactly once in src/.
RULE_FRAGMENT = "0[1-9]|1[0-2]"

MONTH_PARAMETERS = [
    ("/dealers/{dealer_id}/performance", "start"),
    ("/dealers/{dealer_id}/performance", "end"),
    ("/regions/{region}/performance", "start"),
    ("/regions/{region}/performance", "end"),
    ("/performance/trend", "start"),
    ("/performance/trend", "end"),
    ("/performance", "month"),
    ("/performance/ranking", "month"),
    ("/performance/regions", "month"),
    ("/performance/models", "month"),
    ("/performance/funnel", "month"),
    ("/dealers/{dealer_id}/funnel", "start"),
    ("/dealers/{dealer_id}/funnel", "end"),
]


def schema_pattern(schema):
    """Return the regex from a parameter schema, optional or required."""
    if "pattern" in schema:
        return schema["pattern"]

    for option in schema.get("anyOf", []):
        if "pattern" in option:
            return option["pattern"]

    return None


@pytest.mark.parametrize(("path", "name"), MONTH_PARAMETERS)
def test_every_month_parameter_uses_the_shared_pattern(path, name):
    operation = app.openapi()["paths"][path]["get"]
    parameter = next(p for p in operation["parameters"] if p["name"] == name)

    assert schema_pattern(parameter["schema"]) == db.MONTH_QUERY_PATTERN


def test_month_rule_values_are_unchanged():
    assert db.MONTH_FORMAT == r"[0-9]{4}-(0[1-9]|1[0-2])"
    assert db.MONTH_QUERY_PATTERN == r"^[0-9]{4}-(0[1-9]|1[0-2])$"


def test_month_rule_literal_exists_only_in_the_shared_constant():
    counts = {
        path.name: path.read_text(encoding="utf-8").count(RULE_FRAGMENT)
        for path in SRC_DIR.glob("*.py")
    }

    assert {name: count for name, count in counts.items() if count} == {"db.py": 1}
