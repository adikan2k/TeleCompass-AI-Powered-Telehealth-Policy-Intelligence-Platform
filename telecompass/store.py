"""Read and write the M1 tables. Insert only: nothing here updates or deletes a row."""

from datetime import datetime

from psycopg.types.json import Jsonb

from telecompass.db import Connection
from telecompass.models import (
    Entry,
    FetchedPage,
    GlanceAnswer,
    ParsedPage,
    ParseRun,
    Snapshot,
    SourceText,
    StoredEntry,
)


def log_request(conn: Connection, host: str, url: str, at: datetime, status: int | None) -> None:
    """Record one outgoing request. The wait between requests is worked out from these rows."""
    conn.execute(
        "INSERT INTO fetch_log (host, url, requested_at, status) VALUES (%s, %s, %s, %s)",
        (host, url, at, status),
    )
    conn.commit()


def last_request_at(conn: Connection, host: str) -> datetime | None:
    """When we last sent any request to this host, or None if never."""
    row = conn.execute(
        "SELECT max(requested_at) AS at FROM fetch_log WHERE host = %s", (host,)
    ).fetchone()
    return row["at"] if row else None


def save_snapshot(conn: Connection, jurisdiction: str, page: FetchedPage) -> Snapshot:
    """Store a fetched page as a new snapshot row."""
    row = conn.execute(
        "INSERT INTO snapshot (jurisdiction, url, fetched_at, sha256, http_status, raw_page) "
        "VALUES (%s, %s, %s, %s, %s, %s) RETURNING *",
        (jurisdiction, page.url, page.fetched_at, page.sha256, page.status, page.body),
    ).fetchone()
    conn.commit()
    return Snapshot.model_validate(row)


def latest_snapshot(conn: Connection, jurisdiction: str) -> Snapshot | None:
    """The newest snapshot for a jurisdiction, or None."""
    row = conn.execute(
        "SELECT * FROM snapshot WHERE jurisdiction = %s ORDER BY fetched_at DESC, id DESC LIMIT 1",
        (jurisdiction,),
    ).fetchone()
    return Snapshot.model_validate(row) if row else None


def save_parse(
    conn: Connection, snapshot: Snapshot, parsed: ParsedPage, parser_version: str, at: datetime
) -> ParseRun:
    """Store one parser pass: a parse_run row, then its entries and answers."""
    run = conn.execute(
        "INSERT INTO parse_run "
        "(snapshot_id, parser_version, parsed_at, entry_count, answer_count, problems) "
        "VALUES (%s, %s, %s, %s, %s, %s) RETURNING *",
        (
            snapshot.id,
            parser_version,
            at,
            len(parsed.entries),
            len(parsed.answers),
            Jsonb(parsed.problems),
        ),
    ).fetchone()
    for position, entry in enumerate(parsed.entries):
        _insert_entry(conn, run["id"], snapshot, position, entry)
    for position, answer in enumerate(parsed.answers):
        _insert_answer(conn, run["id"], snapshot, position, answer)
    conn.commit()
    return ParseRun.model_validate(run)


def _insert_entry(
    conn: Connection, run_id: int, snapshot: Snapshot, position: int, entry: Entry
) -> None:
    conn.execute(
        "INSERT INTO entry (parse_run_id, snapshot_id, jurisdiction, position, category, topic, "
        "subtopic, text, no_reference_found, source_name, source_url, source_links, accessed, "
        "last_updated) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
        (
            run_id,
            snapshot.id,
            snapshot.jurisdiction,
            position,
            entry.category,
            entry.topic,
            entry.subtopic,
            entry.text,
            entry.no_reference_found,
            entry.source_name,
            entry.source_url,
            Jsonb([link.model_dump() for link in entry.source_links]),
            entry.accessed,
            entry.last_updated,
        ),
    )


def _insert_answer(
    conn: Connection, run_id: int, snapshot: Snapshot, position: int, answer: GlanceAnswer
) -> None:
    conn.execute(
        "INSERT INTO glance_answer "
        "(parse_run_id, snapshot_id, jurisdiction, position, section, question, answer) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s)",
        (
            run_id,
            snapshot.id,
            snapshot.jurisdiction,
            position,
            answer.section,
            answer.question,
            answer.answer,
        ),
    )


def latest_parse_run(conn: Connection, snapshot_id: int) -> ParseRun | None:
    """The newest parser pass over a snapshot, or None."""
    row = conn.execute(
        "SELECT * FROM parse_run WHERE snapshot_id = %s ORDER BY id DESC LIMIT 1", (snapshot_id,)
    ).fetchone()
    return ParseRun.model_validate(row) if row else None


def entries_for(conn: Connection, parse_run_id: int) -> list[Entry]:
    """The entries written by one parser pass, in page order."""
    rows = conn.execute(
        "SELECT * FROM entry WHERE parse_run_id = %s ORDER BY position", (parse_run_id,)
    ).fetchall()
    return [Entry.model_validate(row) for row in rows]


def answers_for(conn: Connection, parse_run_id: int) -> list[GlanceAnswer]:
    """The answer key written by one parser pass, in page order."""
    rows = conn.execute(
        "SELECT * FROM glance_answer WHERE parse_run_id = %s ORDER BY position", (parse_run_id,)
    ).fetchall()
    return [GlanceAnswer.model_validate(row) for row in rows]


def stored_entries_for(conn: Connection, parse_run_id: int) -> list[StoredEntry]:
    """The entries of one parser pass with their row ids, in page order."""
    rows = conn.execute(
        "SELECT * FROM entry WHERE parse_run_id = %s ORDER BY position", (parse_run_id,)
    ).fetchall()
    return [StoredEntry.model_validate(row) for row in rows]


def save_source_text(
    conn: Connection,
    *,
    url: str,
    fetch_url: str,
    fetched_at: datetime,
    outcome: str,
    final_url: str | None = None,
    http_status: int | None = None,
    content_type: str | None = None,
    sha256: str | None = None,
    raw_body: bytes | None = None,
    text: str | None = None,
    note: str | None = None,
) -> SourceText:
    """Record one attempt to get a cited document."""
    row = conn.execute(
        "INSERT INTO source_text (url, fetch_url, final_url, fetched_at, outcome, http_status, "
        "content_type, sha256, raw_body, text, note) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
        "RETURNING id, url, fetch_url, final_url, fetched_at, outcome, http_status, content_type, "
        "sha256, text, note",
        (
            url,
            fetch_url,
            final_url,
            fetched_at,
            outcome,
            http_status,
            content_type,
            sha256,
            raw_body,
            text,
            note,
        ),
    ).fetchone()
    conn.commit()
    return SourceText.model_validate(row)


def latest_source_text(conn: Connection, url: str) -> SourceText | None:
    """The newest attempt for a cited link, or None if it was never tried."""
    row = conn.execute(
        "SELECT id, url, fetch_url, final_url, fetched_at, outcome, http_status, content_type, "
        "sha256, text, note FROM source_text WHERE url = %s ORDER BY id DESC LIMIT 1",
        (url,),
    ).fetchone()
    return SourceText.model_validate(row) if row else None


def source_raw_body(conn: Connection, source_text_id: int) -> bytes | None:
    """The stored bytes of a fetched document, or None if none were kept."""
    row = conn.execute(
        "SELECT raw_body FROM source_text WHERE id = %s", (source_text_id,)
    ).fetchone()
    return bytes(row["raw_body"]) if row and row["raw_body"] is not None else None


def source_text_by_id(conn: Connection, source_text_id: int) -> SourceText | None:
    row = conn.execute(
        "SELECT id, url, fetch_url, final_url, fetched_at, outcome, http_status, content_type, "
        "sha256, text, note FROM source_text WHERE id = %s",
        (source_text_id,),
    ).fetchone()
    return SourceText.model_validate(row) if row else None
