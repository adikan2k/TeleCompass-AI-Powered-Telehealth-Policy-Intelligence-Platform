"""The change agent (D21): from a diff between two snapshots to rule changes a person approves.

Three steps, run by LangGraph with its state kept in Postgres:

1. propose  Read each real change in the five rule types. For a new or changed entry, fetch the
            law it cites (where the site allows it), read it into rules with the same extractor
            and quote check as everything else, and compare them with the live rules. For a
            removed entry, offer to retire the live rules it supported.
2. review   Pause. Nothing more happens until a person has decided on the proposals on the review
            page and asked for the decisions to be applied.
3. apply    Carry out exactly what was decided: approve or reject each new rule, retire the rules
            whose retirement was approved. Nothing else.

The model only reads law into rules (rule 9). Every decision is a person's click (rule 13).
"""

from collections.abc import Callable
from datetime import datetime
from decimal import Decimal
from typing import Any, TypedDict

from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from telecompass import diff, extract, preflight, rule_store, sources, store
from telecompass.db import Connection
from telecompass.extract import Extractor, normalise
from telecompass.fetch import Fetcher, utc_now
from telecompass.llm import EXTRACTION_MODEL, ModelGate
from telecompass.models import Rule, StoredEntry

CHANGE_CAP_USD = Decimal("2.00")
UNREADABLE_OUTCOMES = {
    extract.SOURCE_NOT_FETCHABLE,
    extract.SOURCE_NOT_FETCHED,
    extract.MODEL_FAILED,
    extract.CAP_REACHED,
    extract.NO_SOURCE_LINE,
}


class ChangeState(TypedDict, total=False):
    diff_run_id: int
    jurisdiction: str
    change_run_id: int
    proposal_ids: list[int]
    reviewer: str
    applied: dict[str, int]


def thread_id(diff_run_id: int) -> str:
    return f"changes-{diff_run_id}"


def _config(diff_run_id: int) -> dict[str, Any]:
    return {"configurable": {"thread_id": thread_id(diff_run_id)}}


def _key(rule: Rule) -> tuple[str, str]:
    return (rule.effect, normalise(rule.quote or ""))


def _propose(
    conn: Connection,
    diff_run_id: int,
    run_id: int,
    extractor: Extractor,
    fetcher: Fetcher,
    now: Callable[[], datetime],
) -> list[int]:
    """Write the proposals for one diff and return their ids."""
    row = conn.execute("SELECT * FROM diff_run WHERE id = %s", (diff_run_id,)).fetchone()
    jurisdiction = row["jurisdiction"]
    changes = conn.execute(
        "SELECT * FROM entry_change WHERE diff_run_id = %s AND rule_type IS NOT NULL "
        "AND kind = ANY(%s) ORDER BY id",
        (diff_run_id, list(diff.SUBSTANTIVE)),
    ).fetchall()
    live = preflight.rules_for(conn, jurisdiction)
    live_by_key = {_key(rule): rule for rule in live}
    overrides = sources.load_overrides(conn=conn)
    new_entries = {
        entry.id: entry for entry in store.stored_entries_for(conn, row["new_parse_run_id"])
    }
    thread = thread_id(diff_run_id)
    ids: list[int] = []

    def propose(change: dict, kind: str, rule: int | None, matched: int | None, note: str | None):
        made = conn.execute(
            "INSERT INTO change_proposal (diff_run_id, entry_change_id, kind, rule_id, "
            "matched_rule_id, note, thread_id, created_at) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING id",
            (diff_run_id, change["id"], kind, rule, matched, note, thread, now()),
        ).fetchone()
        conn.commit()
        ids.append(made["id"])

    for change in changes:
        supported = [
            r for r in live if change["old_entry_id"] and r.entry_id == change["old_entry_id"]
        ]
        entry: StoredEntry | None = new_entries.get(change["new_entry_id"])
        matched_live: set[int] = set()
        if entry is not None and not entry.no_reference_found:
            for link in entry.source_links:
                sources.fetch_source(conn, fetcher, link.url, overrides)
            extractor.extract_entry(entry, change["rule_type"])
            read = [
                r
                for r in rule_store.rules_for(conn, run_id)
                if r.entry_id == entry.id and r.effect != "silent" and r.quote
            ]
            verified = [r for r in read if r.quote_verified]
            item = conn.execute(
                "SELECT outcome, note FROM extraction_item WHERE run_id = %s AND entry_id = %s "
                "ORDER BY id DESC LIMIT 1",
                (run_id, entry.id),
            ).fetchone()
            if not verified:
                outcome = item["outcome"] if item else None
                if outcome in UNREADABLE_OUTCOMES:
                    propose(change, "unreadable", None, None, item["note"] or outcome)
                else:
                    unverified = len(read) - len(verified)
                    note = (
                        f"{unverified} rule(s) read, but no quote was found word for word."
                        if unverified
                        else "The law was read and holds no rule on this point."
                    )
                    propose(change, "no_rules", None, None, note)
            for rule in verified:
                same = live_by_key.get(_key(rule))
                if same is not None:
                    matched_live.add(same.id)
                    propose(change, "already_live", rule.id, same.id, None)
                else:
                    propose(change, "add", rule.id, None, None)
        for rule in supported:
            if rule.id not in matched_live:
                note = (
                    "The entry this rule came from was removed."
                    if change["kind"] == diff.REMOVED
                    else "The entry changed and this rule was not read from it again."
                )
                propose(change, "retire", None, rule.id, note)
    return ids


def latest_decisions(conn: Connection, proposal_ids: list[int]) -> dict[int, dict]:
    """The newest decision a person made on each proposal, by proposal id."""
    if not proposal_ids:
        return {}
    rows = conn.execute(
        "SELECT DISTINCT ON (proposal_id) proposal_id, decision, note, reviewer, decided_at "
        "FROM change_decision WHERE proposal_id = ANY(%s) ORDER BY proposal_id, id DESC",
        (proposal_ids,),
    ).fetchall()
    return {row["proposal_id"]: row for row in rows}


def save_decision(
    conn: Connection, proposal_id: int, decision: str, note: str | None, reviewer: str, at: datetime
) -> None:
    """Record a person's decision on a proposal. Called only by the review page."""
    conn.execute(
        "INSERT INTO change_decision (proposal_id, decision, note, reviewer, decided_at) "
        "VALUES (%s, %s, %s, %s, %s)",
        (proposal_id, decision, note, reviewer, at),
    )
    conn.commit()


def _apply(conn: Connection, diff_run_id: int, now: Callable[[], datetime]) -> dict[str, int]:
    """Carry out the decisions made on a diff's proposals."""
    proposals = conn.execute(
        "SELECT p.*, s.captured_at FROM change_proposal p "
        "JOIN diff_run d ON d.id = p.diff_run_id "
        "JOIN parse_run r ON r.id = d.new_parse_run_id JOIN snapshot s ON s.id = r.snapshot_id "
        "WHERE p.diff_run_id = %s ORDER BY p.id",
        (diff_run_id,),
    ).fetchall()
    decided = latest_decisions(conn, [p["id"] for p in proposals])
    applied = {"approved": 0, "rejected": 0, "retired": 0}
    for proposal in proposals:
        decision = decided.get(proposal["id"])
        if decision is None:
            continue
        if proposal["kind"] == "add":
            rule_store.save_rule_review(
                conn,
                proposal["rule_id"],
                decision["decision"],
                decision["note"],
                decision["reviewer"],
                now(),
            )
            applied[decision["decision"]] += 1
        elif proposal["kind"] == "retire" and decision["decision"] == "approved":
            conn.execute(
                "INSERT INTO rule_retirement (rule_id, proposal_id, retired_on, reviewer, "
                "recorded_at) VALUES (%s, %s, %s, %s, %s)",
                (
                    proposal["matched_rule_id"],
                    proposal["id"],
                    proposal["captured_at"].date(),
                    decision["reviewer"],
                    now(),
                ),
            )
            conn.commit()
            applied["retired"] += 1
    return applied


def build_graph(
    conn: Connection,
    checkpointer: PostgresSaver,
    fetcher: Fetcher | None = None,
    gate_factory: Callable[[int], ModelGate] | None = None,
    now: Callable[[], datetime] = utc_now,
):
    """The three-step graph. The fetcher and model are needed only for the first step."""

    def propose_node(state: ChangeState) -> ChangeState:
        if fetcher is None or gate_factory is None:
            raise RuntimeError("Proposing changes needs a fetcher and a model.")
        diff_row = conn.execute(
            "SELECT * FROM diff_run WHERE id = %s", (state["diff_run_id"],)
        ).fetchone()
        run_id = rule_store.start_run(
            conn,
            diff_row["jurisdiction"],
            diff_row["new_parse_run_id"],
            EXTRACTION_MODEL,
            CHANGE_CAP_USD,
            now(),
            extract.PROMPT_VERSION,
            kind="change",
            diff_run_id=state["diff_run_id"],
        )
        extractor = Extractor(conn, gate_factory(run_id), run_id, diff_row["jurisdiction"], now)
        ids = _propose(conn, state["diff_run_id"], run_id, extractor, fetcher, now)
        return {
            "jurisdiction": diff_row["jurisdiction"],
            "change_run_id": run_id,
            "proposal_ids": ids,
        }

    def review_node(state: ChangeState) -> ChangeState:
        answer = interrupt(
            {"diff_run_id": state["diff_run_id"], "proposal_ids": state.get("proposal_ids", [])}
        )
        return {"reviewer": answer["reviewer"]}

    def apply_node(state: ChangeState) -> ChangeState:
        return {"applied": _apply(conn, state["diff_run_id"], now)}

    graph = StateGraph(ChangeState)
    graph.add_node("propose", propose_node)
    graph.add_node("review", review_node)
    graph.add_node("apply", apply_node)
    graph.add_edge(START, "propose")
    graph.add_edge("propose", "review")
    graph.add_edge("review", "apply")
    graph.add_edge("apply", END)
    return graph.compile(checkpointer=checkpointer)


def status(graph, diff_run_id: int) -> str:
    """'not started', 'waiting for review' or 'done'."""
    snapshot = graph.get_state(_config(diff_run_id))
    if not snapshot.values or snapshot.next == ("propose",):
        return "not started"  # never run, or the first step failed and may be run again
    if snapshot.next:
        return "waiting for review"
    return "done"


def start(graph, diff_run_id: int) -> list[int]:
    """Run the first step for a diff and pause. Returns the proposal ids."""
    if status(graph, diff_run_id) != "not started":
        raise RuntimeError(f"Diff {diff_run_id} already has a change review.")
    graph.invoke({"diff_run_id": diff_run_id}, _config(diff_run_id))
    return graph.get_state(_config(diff_run_id)).values.get("proposal_ids", [])


def finish(graph, diff_run_id: int, reviewer: str) -> dict[str, int]:
    """Resume a paused review: apply the decisions a person made. Returns what was applied."""
    if status(graph, diff_run_id) != "waiting for review":
        raise RuntimeError(f"Diff {diff_run_id} is not waiting for review.")
    result = graph.invoke(Command(resume={"reviewer": reviewer}), _config(diff_run_id))
    return result.get("applied", {})
