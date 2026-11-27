"""Open a Postgres connection and apply the numbered SQL files under migrations/."""

from importlib import resources

import psycopg
from psycopg.rows import dict_row

Connection = psycopg.Connection


def connect(url: str) -> Connection:
    """Open a connection whose rows come back as dicts."""
    return psycopg.connect(url, row_factory=dict_row)


class LongLivedConnection:
    """A connection for a page that stays open for hours, such as the local review page.

    It commits each statement as it runs, so no transaction is ever left open (Neon closes those
    after five minutes), and if the server has dropped the connection it opens a new one and runs
    the statement again. Everything else is passed to the underlying connection.
    """

    def __init__(self, url: str) -> None:
        self._url = url
        self._conn = self._open()

    def _open(self) -> Connection:
        conn = connect(self._url)
        conn.autocommit = True
        return conn

    def execute(self, *args, **kwargs):
        try:
            return self._conn.execute(*args, **kwargs)
        except psycopg.OperationalError:
            if not self._conn.closed and not self._conn.broken:
                raise  # a real error in the statement, not a dropped connection
            self._conn = self._open()
            return self._conn.execute(*args, **kwargs)

    def __getattr__(self, name: str):
        return getattr(self._conn, name)


def migration_files() -> list[tuple[str, str]]:
    """Return (name, sql) for every migration file, in name order."""
    folder = resources.files("telecompass") / "migrations"
    files = sorted(
        (item for item in folder.iterdir() if item.name.endswith(".sql")),
        key=lambda item: item.name,
    )
    return [(item.name, item.read_text(encoding="utf-8")) for item in files]


def migrate(conn: Connection) -> list[str]:
    """Apply migrations that have not run yet. Return the names applied this time."""
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migration ("
        "name text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now())"
    )
    done = {row["name"] for row in conn.execute("SELECT name FROM schema_migration")}
    applied = []
    for name, sql in migration_files():
        if name in done:
            continue
        conn.execute(sql)
        conn.execute("INSERT INTO schema_migration (name) VALUES (%s)", (name,))
        applied.append(name)
    conn.commit()
    return applied
