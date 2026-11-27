"""Shared test fixtures. Database tests run against a throwaway Postgres container."""

from collections.abc import Iterator

import pytest

from telecompass.db import Connection, connect, migrate

POSTGRES_IMAGE = "pgvector/pgvector:pg17"


@pytest.fixture(scope="session")
def postgres_url() -> Iterator[str]:
    """Start one Postgres container for the whole test run and remove it afterwards."""
    from testcontainers.community.postgres import PostgresContainer

    container = PostgresContainer(POSTGRES_IMAGE, driver=None)
    try:
        container.start()
    except Exception as error:  # noqa: BLE001 - any Docker failure gets the same plain message
        pytest.fail(f"Database tests need Docker to be running. Could not start Postgres: {error}")
    try:
        yield container.get_connection_url()
    finally:
        container.stop()


@pytest.fixture
def conn(postgres_url: str) -> Iterator[Connection]:
    """A connection to an empty, freshly migrated database."""
    with connect(postgres_url) as connection:
        connection.execute("DROP SCHEMA public CASCADE")
        connection.execute("CREATE SCHEMA public")
        connection.commit()
        migrate(connection)
        yield connection
