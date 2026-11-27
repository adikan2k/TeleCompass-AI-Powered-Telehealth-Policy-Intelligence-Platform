"""Moving the database: every row arrives, ids are kept, and new rows do not collide."""

from collections.abc import Iterator
from datetime import date

import psycopg
import pytest

from fakes import AT
from telecompass import copy_db, preflight
from telecompass.db import Connection, connect, migrate
from test_preflight import seed_rules


@pytest.fixture
def target(postgres_url: str) -> Iterator[Connection]:
    """A second, empty, migrated database in the same test container."""
    base = postgres_url.rsplit("/", 1)[0]
    with psycopg.connect(postgres_url, autocommit=True) as admin:
        admin.execute("DROP DATABASE IF EXISTS copy_target")
        admin.execute("CREATE DATABASE copy_target")
    with connect(f"{base}/copy_target") as connection:
        migrate(connection)
        yield connection


def test_every_row_arrives_with_its_id_and_new_rows_do_not_collide(
    conn: Connection, target: Connection
) -> None:
    seed_rules(conn)
    _, decision_id, public_id = preflight.run_preflight(
        conn, preflight.demo_visit(date(2026, 12, 1)), AT
    )

    copied = copy_db.copy_all(conn, target)

    assert copied == copy_db.row_counts(conn)
    assert copied["rule"] == 2 and copied["decision"] == 1 and copied["entry"] > 0
    moved = target.execute("SELECT id FROM decision WHERE public_id = %s", (public_id,)).fetchone()
    assert moved["id"] == decision_id  # the share link still points at the same decision
    _, new_id, _ = preflight.run_preflight(target, preflight.demo_visit(date(2026, 12, 2)), AT)
    assert new_id == decision_id + 1


def test_copy_refuses_a_target_that_already_has_rows(conn: Connection, target: Connection) -> None:
    seed_rules(conn)
    copy_db.copy_all(conn, target)

    with pytest.raises(copy_db.TargetNotEmpty, match="already has rows"):
        copy_db.copy_all(conn, target)


def test_every_table_with_data_is_on_the_copy_list(conn: Connection) -> None:
    rows = conn.execute(
        "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'"
    ).fetchall()
    names = {row["table_name"] for row in rows} - {"schema_migration"}
    names = {name for name in names if not name.startswith(copy_db.CHECKPOINT_PREFIX)}
    assert names == set(copy_db.TABLES)
