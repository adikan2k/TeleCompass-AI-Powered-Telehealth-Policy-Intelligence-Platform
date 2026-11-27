"""The results file for one change review (rule 19): what a diff found, what the agent proposed,
what a person decided, what went live, and what it cost. Read from stored rows only."""

import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

from telecompass import change_agent, preflight
from telecompass.db import Connection
from telecompass.diff import SUBSTANTIVE

RESULTS = Path(__file__).resolve().parents[1] / "evals" / "results"


def build_report(conn: Connection, diff_id: int, now: datetime) -> dict[str, Any]:
    diff = conn.execute(
        "SELECT d.jurisdiction, so.captured_at AS old_at, so.origin AS old_origin, "
        "sn.captured_at AS new_at, sn.origin AS new_origin FROM diff_run d "
        "JOIN parse_run ro ON ro.id = d.old_parse_run_id "
        "JOIN snapshot so ON so.id = ro.snapshot_id "
        "JOIN parse_run rn ON rn.id = d.new_parse_run_id "
        "JOIN snapshot sn ON sn.id = rn.snapshot_id WHERE d.id = %s",
        (diff_id,),
    ).fetchone()
    kinds = conn.execute(
        "SELECT kind, rule_type IS NOT NULL AS in_scope FROM entry_change WHERE diff_run_id = %s",
        (diff_id,),
    ).fetchall()
    proposals = conn.execute(
        "SELECT id, kind, rule_id, matched_rule_id FROM change_proposal WHERE diff_run_id = %s",
        (diff_id,),
    ).fetchall()
    decided = change_agent.latest_decisions(conn, [p["id"] for p in proposals])
    cost = conn.execute(
        "SELECT coalesce(sum(c.cost_usd), 0) AS usd, count(c.id) AS calls FROM extraction_run r "
        "LEFT JOIN model_call c ON c.run_id = r.id WHERE r.kind = 'change' AND r.diff_run_id = %s",
        (diff_id,),
    ).fetchone()
    retired = conn.execute(
        "SELECT count(*) AS n FROM rule_retirement t JOIN change_proposal p "
        "ON p.id = t.proposal_id WHERE p.diff_run_id = %s",
        (diff_id,),
    ).fetchone()["n"]
    approved_adds = [
        p
        for p in proposals
        if p["kind"] == "add" and decided.get(p["id"], {}).get("decision") == "approved"
    ]
    live_adds = conn.execute(
        "SELECT count(DISTINCT rule_id) AS n FROM rule_review WHERE rule_id = ANY(%s) "
        "AND decision = 'approved'",
        ([p["rule_id"] for p in approved_adds],),
    ).fetchone()["n"]
    live_ids = {rule.id for rule in preflight.rules_for(conn, diff["jurisdiction"])}
    now_live = sum(1 for p in approved_adds if p["rule_id"] in live_ids)
    return {
        "jurisdiction": diff["jurisdiction"],
        "diff_id": diff_id,
        "compared": {
            "from": {
                "captured_at": diff["old_at"].date().isoformat(),
                "origin": diff["old_origin"],
            },
            "to": {"captured_at": diff["new_at"].date().isoformat(), "origin": diff["new_origin"]},
        },
        "entries_by_kind": dict(Counter(row["kind"] for row in kinds)),
        "real_changes_in_scope": sum(
            1 for row in kinds if row["in_scope"] and row["kind"] in SUBSTANTIVE
        ),
        "proposals_by_kind": dict(Counter(p["kind"] for p in proposals)),
        "decided_by_a_person": {
            "approved": sum(1 for d in decided.values() if d["decision"] == "approved"),
            "rejected": sum(1 for d in decided.values() if d["decision"] == "rejected"),
            "reviewers": sorted({d["reviewer"] for d in decided.values()}),
        },
        "applied": {
            "rule_rows_approved": live_adds,
            "distinct_rules_now_live": now_live,  # the same rule read twice is used once
            "rules_retired": retired,
        },
        "model_calls": cost["calls"],
        "cost_usd": float(cost["usd"]),
        "written_at": now.isoformat(timespec="seconds"),
    }


def write_report(report: dict[str, Any], folder: Path = RESULTS) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"changes_{report['jurisdiction']}.json"
    path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return path
