import json

import pytest
from sqlalchemy import text

import db

ROLLUP_QUERY = """
    SELECT region, month, dealer_count, units_sold, target_units,
           achievement_pct
    FROM monthly_performance_rollup
    WHERE region = 'Midwest'
    ORDER BY month
"""


def test_rollup_consumer_plan_stays_below_jit_threshold():
    """Analyzed loads should keep this representative rollup plan cheap.

    Without planner statistics, PostgreSQL can substantially overestimate
    the rollup's joins. On a server where JIT is enabled and available, an
    inflated estimated cost can cross jit_above_cost and introduce avoidable
    compilation work.
    """
    with db.get_engine().connect() as connection:
        jit_enabled = str(connection.execute(text("SHOW jit")).scalar()).lower()
        jit_available = bool(
            connection.execute(text("SELECT pg_jit_available()")).scalar()
        )
        threshold = float(connection.execute(text("SHOW jit_above_cost")).scalar())

        if jit_enabled != "on":
            pytest.skip("PostgreSQL JIT is disabled")

        if not jit_available:
            pytest.skip("PostgreSQL JIT is unavailable on this server")

        if threshold < 0:
            pytest.skip("jit_above_cost disables JIT cost triggering")

        raw_plan = connection.execute(
            text(f"EXPLAIN (FORMAT JSON) {ROLLUP_QUERY}")
        ).scalar()

    plan = json.loads(raw_plan) if isinstance(raw_plan, str) else raw_plan

    total_cost = float(plan[0]["Plan"]["Total Cost"])

    assert total_cost < threshold, (
        f"rollup plan cost {total_cost:.0f} is not below "
        f"jit_above_cost {threshold:.0f}; "
        "did the load skip ANALYZE?"
    )
