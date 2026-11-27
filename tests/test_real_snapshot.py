"""Guard against the invented fixture drifting from the real page.

If the local database holds the Florida snapshot these counts were taken from, the parser is
run over it and the counts are checked. Anywhere else (CI, a fresh clone) the test is skipped,
because CCHP's page is not, and must not be, in this repository.
"""

import os

import psycopg
import pytest
from dotenv import dotenv_values, find_dotenv
from psycopg.rows import dict_row

from telecompass.parse_cchp import parse_state_page

FLORIDA_SHA256 = "3fc293ecbd1114c789d25c19639645cdaf945d6080a0a1a9c40da6670f517450"


def stored_florida_page() -> str:
    url = os.environ.get("DATABASE_URL") or dotenv_values(find_dotenv(usecwd=True)).get(
        "DATABASE_URL"
    )
    if not url:
        pytest.skip("DATABASE_URL is not set, so there is no stored snapshot to check.")
    try:
        with psycopg.connect(url, connect_timeout=3, row_factory=dict_row) as conn:
            row = conn.execute(
                "SELECT raw_page FROM snapshot WHERE sha256 = %s LIMIT 1", (FLORIDA_SHA256,)
            ).fetchone()
    except (psycopg.OperationalError, psycopg.errors.UndefinedTable):
        pytest.skip("The local database is not running or has no snapshot table.")
    if row is None:
        pytest.skip("The local database does not hold the Florida snapshot these counts are for.")
    return row["raw_page"]


def test_parser_counts_on_the_stored_florida_snapshot() -> None:
    parsed = parse_state_page(stored_florida_page())
    entries = parsed.entries

    assert len(parsed.answers) == 19
    assert len(entries) == 86
    assert len({(entry.category, entry.topic) for entry in entries}) == 28
    assert sum(1 for entry in entries if entry.source_name) == 66
    assert sum(1 for entry in entries if entry.no_reference_found) == 14
    assert all(entry.last_updated is not None for entry in entries)
    assert parsed.problems == []
