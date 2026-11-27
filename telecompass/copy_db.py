"""Copy everything from one TeleCompass database to another, for the move to Neon (D15).

The target must be migrated and empty. Rows keep their ids, so every link between tables,
and every share link, still works after the move. Nothing is fetched or re-run.
"""

from telecompass.db import Connection

# Parents before children, so every row's references already exist when it arrives.
TABLES = [
    "fetch_log",
    "snapshot",
    "parse_run",
    "entry",
    "glance_answer",
    "source_text",
    "extraction_run",
    "model_call",
    "extraction_item",
    "rule",
    "label_sample",
    "label",
    "auto_review",
    "rule_review",
    "decision",
    "rate_counter",
]


class TargetNotEmpty(RuntimeError):
    """The target already holds rows, so nothing was copied."""


def row_counts(conn: Connection) -> dict[str, int]:
    return {
        table: conn.execute(f"SELECT count(*) AS n FROM {table}").fetchone()["n"]  # noqa: S608
        for table in TABLES
    }


def copy_all(source: Connection, target: Connection) -> dict[str, int]:
    """Copy every table. Returns the number of rows copied per table."""
    filled = {table: count for table, count in row_counts(target).items() if count}
    if filled:
        raise TargetNotEmpty(f"The target already has rows in: {', '.join(filled)}.")
    for table in TABLES:
        read = f"COPY {table} TO STDOUT (FORMAT BINARY)"
        write = f"COPY {table} FROM STDIN (FORMAT BINARY)"
        with source.cursor().copy(read) as out, target.cursor().copy(write) as into:
            for block in out:
                into.write(block)
        _advance_id(target, table)
    target.commit()
    source.rollback()
    return row_counts(target)


def _advance_id(conn: Connection, table: str) -> None:
    """Move a table's id counter past the copied rows, so new rows do not collide."""
    has_id = conn.execute(
        "SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' "
        "AND table_name = %s AND column_name = 'id'",
        (table,),
    ).fetchone()
    if not has_id:  # a table without an id column has no counter to move
        return
    sequence = conn.execute("SELECT pg_get_serial_sequence(%s, 'id') AS name", (table,)).fetchone()
    if sequence and sequence["name"]:
        conn.execute(
            f"SELECT setval(%s, greatest((SELECT coalesce(max(id), 0) FROM {table}), 1))",  # noqa: S608
            (sequence["name"],),
        )
