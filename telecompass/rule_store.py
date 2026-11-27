"""Read and write extraction runs, rules, labels and the label sample. Insert only."""

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from psycopg.types.json import Jsonb

from telecompass.db import Connection
from telecompass.models import Rule


def start_run(
    conn: Connection,
    jurisdiction: str,
    parse_run_id: int,
    model: str,
    cap: Decimal,
    at: datetime,
    prompt_version: str = "v1",
) -> int:
    row = conn.execute(
        "INSERT INTO extraction_run "
        "(jurisdiction, parse_run_id, model, cap_usd, started_at, prompt_version) "
        "VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
        (jurisdiction, parse_run_id, model, cap, at, prompt_version),
    ).fetchone()
    conn.commit()
    return row["id"]


def runs_for(conn: Connection, jurisdiction: str) -> list[dict[str, Any]]:
    """Every extraction run for a jurisdiction, oldest first."""
    return conn.execute(
        "SELECT * FROM extraction_run WHERE jurisdiction = %s ORDER BY id", (jurisdiction,)
    ).fetchall()


def latest_run(conn: Connection, jurisdiction: str) -> dict[str, Any] | None:
    """The newest extraction run for a jurisdiction, or None."""
    return conn.execute(
        "SELECT * FROM extraction_run WHERE jurisdiction = %s ORDER BY id DESC LIMIT 1",
        (jurisdiction,),
    ).fetchone()


def save_item(
    conn: Connection,
    run_id: int,
    entry_id: int,
    rule_type: str,
    outcome: str,
    note: str | None = None,
    source_cut: bool = False,
) -> None:
    """Record what happened to one in-scope entry in a run."""
    conn.execute(
        "INSERT INTO extraction_item (run_id, entry_id, rule_type, outcome, source_cut, note) "
        "VALUES (%s, %s, %s, %s, %s, %s)",
        (run_id, entry_id, rule_type, outcome, source_cut, note),
    )
    conn.commit()


def items_for(conn: Connection, run_id: int) -> list[dict[str, Any]]:
    return conn.execute(
        "SELECT i.*, e.category, e.topic, e.subtopic FROM extraction_item i "
        "JOIN entry e ON e.id = i.entry_id WHERE i.run_id = %s ORDER BY i.id",
        (run_id,),
    ).fetchall()


def save_rule(
    conn: Connection,
    *,
    run_id: int,
    entry_id: int,
    jurisdiction: str,
    rule_type: str,
    aspect: str,
    effect: str,
    summary: str,
    status: str,
    quote_verified: bool,
    created_at: datetime,
    profession: str | None = None,
    payer: str | None = None,
    modality: str | None = None,
    service: str | None = None,
    service_category: str = "any",
    compact: str | None = None,
    conditions: list[str] | None = None,
    quote: str | None = None,
    quote_note: str | None = None,
    source_text_id: int | None = None,
    source_url: str | None = None,
    source_fetched_at: datetime | None = None,
    effective_from: date | None = None,
    effective_to: date | None = None,
) -> Rule:
    """Insert one rule. A changed rule is always a new row, never an update."""
    row = conn.execute(
        "INSERT INTO rule (extraction_run_id, entry_id, jurisdiction, rule_type, aspect, effect, "
        "profession, payer, modality, service, service_category, compact, conditions, summary, "
        "quote, "
        "quote_verified, quote_note, source_text_id, source_url, source_fetched_at, "
        "effective_from, effective_to, status, created_at) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, "
        "%s, %s, %s, %s) RETURNING *",
        (
            run_id,
            entry_id,
            jurisdiction,
            rule_type,
            aspect,
            effect,
            profession,
            payer,
            modality,
            service,
            service_category,
            compact,
            Jsonb(conditions or []),
            summary,
            quote,
            quote_verified,
            quote_note,
            source_text_id,
            source_url,
            source_fetched_at,
            effective_from,
            effective_to,
            status,
            created_at,
        ),
    ).fetchone()
    conn.commit()
    return Rule.model_validate(row)


def rules_for(conn: Connection, run_id: int) -> list[Rule]:
    rows = conn.execute(
        "SELECT * FROM rule WHERE extraction_run_id = %s ORDER BY id", (run_id,)
    ).fetchall()
    return [Rule.model_validate(row) for row in rows]


def rule_by_id(conn: Connection, rule_id: int) -> Rule | None:
    row = conn.execute("SELECT * FROM rule WHERE id = %s", (rule_id,)).fetchone()
    return Rule.model_validate(row) if row else None


def call_totals(conn: Connection, run_id: int) -> dict[str, Any]:
    """Number of model calls, failures, tokens and spend for a run."""
    return conn.execute(
        "SELECT count(*) AS calls, count(failure) AS failed, "
        "coalesce(sum(input_tokens), 0) AS input_tokens, "
        "coalesce(sum(cached_tokens), 0) AS cached_tokens, "
        "coalesce(sum(output_tokens), 0) AS output_tokens, "
        "coalesce(sum(cost_usd), 0) AS cost_usd FROM model_call WHERE run_id = %s",
        (run_id,),
    ).fetchone()


def save_sample(
    conn: Connection, run_id: int, rule_ids: list[int], seed: int, at: datetime
) -> None:
    for position, rule_id in enumerate(rule_ids):
        conn.execute(
            "INSERT INTO label_sample (run_id, position, rule_id, seed, created_at) "
            "VALUES (%s, %s, %s, %s, %s)",
            (run_id, position, rule_id, seed, at),
        )
    conn.commit()


def sample_for(conn: Connection, run_id: int) -> list[int]:
    """The rule ids of a run's label sample, in order. Empty if none was drawn yet."""
    rows = conn.execute(
        "SELECT rule_id FROM label_sample WHERE run_id = %s ORDER BY position", (run_id,)
    ).fetchall()
    return [row["rule_id"] for row in rows]


def save_label(
    conn: Connection,
    run_id: int,
    rule_id: int,
    verdict: str,
    note: str | None,
    labeller: str,
    at: datetime,
) -> None:
    """Store one label. Called only by the labelling page, on a person's click."""
    conn.execute(
        "INSERT INTO label (run_id, rule_id, verdict, note, labeller, labelled_at) "
        "VALUES (%s, %s, %s, %s, %s, %s)",
        (run_id, rule_id, verdict, note, labeller, at),
    )
    conn.commit()


def latest_labels(conn: Connection, run_id: int) -> dict[int, dict[str, Any]]:
    """The newest label for each labelled rule of a run, by rule id."""
    rows = conn.execute(
        "SELECT DISTINCT ON (rule_id) rule_id, verdict, note, labeller, labelled_at "
        "FROM label WHERE run_id = %s ORDER BY rule_id, id DESC",
        (run_id,),
    ).fetchall()
    return {row["rule_id"]: row for row in rows}


def save_review(
    conn: Connection, run_id: int, rule_id: int, model: str, review: Any, at: datetime
) -> None:
    """Store one automated review. Never written to `label`, which is for people only."""
    conn.execute(
        "INSERT INTO auto_review (run_id, rule_id, model, verdict, quote_in_source, "
        "rule_matches_source, reason, reviewed_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
        (
            run_id,
            rule_id,
            model,
            review.verdict,
            review.quote_in_source,
            review.rule_matches_source,
            review.reason,
            at,
        ),
    )
    conn.commit()


def latest_reviews(conn: Connection, run_id: int) -> dict[int, dict[str, Any]]:
    """The newest automated review for each reviewed rule of a run, by rule id."""
    rows = conn.execute(
        "SELECT DISTINCT ON (rule_id) rule_id, model, verdict, quote_in_source, "
        "rule_matches_source, reason, reviewed_at "
        "FROM auto_review WHERE run_id = %s ORDER BY rule_id, id DESC",
        (run_id,),
    ).fetchall()
    return {row["rule_id"]: row for row in rows}
