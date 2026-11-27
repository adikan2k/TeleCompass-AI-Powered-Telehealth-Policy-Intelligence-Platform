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
M3_TABLES = {"decision", "rate_counter", "rule_review"}
M5_TABLES = {
    "diff_run",
    "entry_change",
    "source_change",
    "change_proposal",
    "change_decision",
    "rule_retirement",
    "override_confirmation",
}


def test_migrate_creates_every_table(conn: Connection) -> None:
    rows = conn.execute(
        "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public' "
        "AND table_name NOT LIKE 'checkpoint%%'"
    ).fetchall()
    assert {row["table_name"] for row in rows} == M1_TABLES | M2_TABLES | M3_TABLES | M5_TABLES


def test_migrate_twice_applies_nothing_new(conn: Connection) -> None:
    assert migrate(conn) == []
