import re
from pathlib import Path

LOAD_SQL = Path(__file__).resolve().parents[1] / "sql" / "02_load.sql"


def test_load_script_analyzes_after_the_last_copy():
    """The load must leave planner statistics behind.

    Without statistics the planner can substantially overestimate the
    rollup view's joins. Autovacuum may eventually correct that, but a
    freshly built database such as CI's can be queried before it does.
    """
    sql = LOAD_SQL.read_text()

    copy_starts = [
        match.start()
        for match in re.finditer(
            r"^\s*\\copy\b",
            sql,
            flags=re.IGNORECASE | re.MULTILINE,
        )
    ]
    analyze_starts = [
        match.start()
        for match in re.finditer(
            r"^\s*analyze\s*;",
            sql,
            flags=re.IGNORECASE | re.MULTILINE,
        )
    ]

    assert copy_starts, "02_load.sql contains no \\copy commands"
    assert analyze_starts, "02_load.sql has no ANALYZE statement"
    assert max(analyze_starts) > max(
        copy_starts
    ), "ANALYZE must come after the final \\copy command"
