"""The review page's connection: no open transactions, and it survives a dropped connection."""

import psycopg
import pytest

from telecompass import db


def test_it_leaves_no_transaction_open(postgres_url: str) -> None:
    conn = db.LongLivedConnection(postgres_url)
    conn.execute("SELECT 1")
    assert conn.info.transaction_status == psycopg.pq.TransactionStatus.IDLE


def test_it_reconnects_when_the_server_drops_it(postgres_url: str) -> None:
    conn = db.LongLivedConnection(postgres_url)
    pid = conn.execute("SELECT pg_backend_pid() AS pid").fetchone()["pid"]
    with db.connect(postgres_url) as other:
        other.execute("SELECT pg_terminate_backend(%s)", (pid,))
        other.commit()

    row = conn.execute("SELECT pg_backend_pid() AS pid").fetchone()

    assert row["pid"] != pid


def test_a_bad_statement_is_still_an_error(postgres_url: str) -> None:
    conn = db.LongLivedConnection(postgres_url)
    with pytest.raises(psycopg.Error):
        conn.execute("SELECT * FROM no_such_table")
    assert conn.execute("SELECT 1 AS one").fetchone()["one"] == 1
