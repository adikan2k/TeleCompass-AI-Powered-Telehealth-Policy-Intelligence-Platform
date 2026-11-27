from telecompass.db import Connection, migrate

M1_TABLES = {"fetch_log", "snapshot", "parse_run", "entry", "glance_answer", "schema_migration"}
M2_TABLES = {
    "source_text",
    "extraction_run",
    "model_call",
    "extraction_item",
    "rule",
    "label_sample",
    "label",
    "auto_review",
}


def test_migrate_creates_every_table(conn: Connection) -> None:
    rows = conn.execute(
        "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'"
    ).fetchall()
    assert {row["table_name"] for row in rows} == M1_TABLES | M2_TABLES


def test_migrate_twice_applies_nothing_new(conn: Connection) -> None:
    assert migrate(conn) == []
