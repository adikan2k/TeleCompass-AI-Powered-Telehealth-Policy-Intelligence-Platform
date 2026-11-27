"""What changed for you (D23): for chosen states and a line of care, what moved and what is due.

Three lists per state, all read from stored rows by plain code. No model is called.
  page changes   what the latest diff found in the in-scope entries of the state's CCHP page,
                 and where each one stands in review. Only the topic and the kind of change
                 are shown, never CCHP's text (rule 15).
  rule changes   rules added to or retired from the live set after a person approved it, each
                 with its quote and the law it comes from.
  dates          live rules that start or end within the window: what will change on its own.
Medicare rules are federal, so they are listed for every choice of states.
"""

from datetime import date, timedelta
from typing import Any

from telecompass import change_agent, preflight, rule_store, scope
from telecompass.db import Connection
from telecompass.diff import SUBSTANTIVE
from telecompass.fetch import CCHP_STATE_URLS
from telecompass.models import Rule

LOOK_BACK = timedelta(days=90)
LOOK_AHEAD = timedelta(days=730)  # two years: the span a compliance team plans a rollout over
FEDERAL_CODE = "US"
FEDERAL_NAME = "Federal (Medicare)"
STATE_NAMES = {"FL": "Florida"}


def _applies_to(rule: Rule, care: str) -> bool:
    return rule.service_category in ("any", care)


def rule_card(rule: Rule) -> dict[str, Any]:
    """A rule as the site shows it: what it says, the exact quote and where the quote is from."""
    return {
        "id": rule.id,
        "rule_type": rule.rule_type,
        "rule_type_label": scope.RULE_TYPE_LABELS.get(rule.rule_type, rule.rule_type),
        "summary": rule.summary,
        "quote": rule.quote,
        "source_url": rule.source_url,
        "source_fetched_at": rule.source_fetched_at.date().isoformat()
        if rule.source_fetched_at
        else None,
        "effective_from": rule.effective_from.isoformat() if rule.effective_from else None,
        "effective_to": rule.effective_to.isoformat() if rule.effective_to else None,
    }


def _latest_diff(conn: Connection, jurisdiction: str) -> dict[str, Any] | None:
    return conn.execute(
        "SELECT d.id, so.captured_at AS old_at, so.origin AS old_origin, "
        "sn.captured_at AS new_at, sn.origin AS new_origin "
        "FROM diff_run d "
        "JOIN parse_run ro ON ro.id = d.old_parse_run_id "
        "JOIN snapshot so ON so.id = ro.snapshot_id "
        "JOIN parse_run rn ON rn.id = d.new_parse_run_id "
        "JOIN snapshot sn ON sn.id = rn.snapshot_id "
        "WHERE d.jurisdiction = %s ORDER BY d.id DESC LIMIT 1",
        (jurisdiction,),
    ).fetchone()


def review_state(proposals: list[dict], decided: dict[int, dict], applied: set[int]) -> str:
    """Where one page change stands, in a few words."""
    if not proposals:
        return "not yet read"
    kinds = {p["kind"] for p in proposals}
    acting = [p for p in proposals if p["kind"] in ("add", "retire")]
    if any(p["id"] not in decided for p in acting):
        return "waiting for review"
    if any(p["id"] not in applied for p in acting):
        return "decided, not yet applied"
    approved = [p for p in acting if decided[p["id"]]["decision"] == "approved"]
    if any(p["kind"] == "add" for p in approved):
        return "rule added"
    if any(p["kind"] == "retire" for p in approved):
        return "rule retired"
    if acting:
        return "rejected by the reviewer"
    if "unreadable" in kinds:
        return "the cited law could not be read"
    if "already_live" in kinds:
        return "already covered by a live rule"
    return "the cited law holds no rule on it"


def _applied_proposals(
    conn: Connection, proposals: list[dict], decided: dict[int, dict]
) -> set[int]:
    """Proposals whose decision has been carried out. Turning down a retirement changes
    nothing live, so it has nothing to carry out."""
    reviewed = rule_store.latest_rule_reviews(
        conn, [p["rule_id"] for p in proposals if p["kind"] == "add" and p["rule_id"]]
    )
    retired = {
        row["proposal_id"]
        for row in conn.execute(
            "SELECT proposal_id FROM rule_retirement WHERE proposal_id = ANY(%s)",
            ([p["id"] for p in proposals],),
        ).fetchall()
    }
    return {
        p["id"]
        for p in proposals
        if (p["kind"] == "add" and p["rule_id"] in reviewed)
        or p["id"] in retired
        or (p["kind"] == "retire" and decided.get(p["id"], {}).get("decision") == "rejected")
    }


def page_changes(conn: Connection, jurisdiction: str) -> dict[str, Any] | None:
    """The latest diff of a state's page: the two capture dates and each real change."""
    diff = _latest_diff(conn, jurisdiction)
    if diff is None:
        return None
    changes = conn.execute(
        "SELECT id, kind, category, topic, subtopic, rule_type, fields FROM entry_change "
        "WHERE diff_run_id = %s AND kind = ANY(%s) AND rule_type IS NOT NULL ORDER BY id",
        (diff["id"], list(SUBSTANTIVE)),
    ).fetchall()
    proposals = conn.execute(
        "SELECT id, entry_change_id, kind, rule_id FROM change_proposal WHERE diff_run_id = %s",
        (diff["id"],),
    ).fetchall()
    decided = change_agent.latest_decisions(conn, [p["id"] for p in proposals])
    applied = _applied_proposals(conn, proposals, decided)
    items = []
    for change in changes:
        own = [p for p in proposals if p["entry_change_id"] == change["id"]]
        items.append(
            {
                "kind": change["kind"],
                "category": change["category"],
                "topic": change["topic"],
                "subtopic": change["subtopic"],
                "rule_type_label": scope.RULE_TYPE_LABELS.get(change["rule_type"] or "", None),
                "fields": change["fields"],
                "review": review_state(own, decided, applied),
            }
        )
    return {
        "from": {"captured_at": diff["old_at"].date().isoformat(), "origin": diff["old_origin"]},
        "to": {"captured_at": diff["new_at"].date().isoformat(), "origin": diff["new_origin"]},
        "page_url": CCHP_STATE_URLS.get(jurisdiction),
        "changes": items,
    }


def rule_changes(conn: Connection, jurisdiction: str, live: list[Rule], care: str) -> list[dict]:
    """Rules a person added to or retired from the live set through the change queue."""
    run = rule_store.latest_run(conn, jurisdiction)
    if run is None:
        return []
    added = [r for r in live if r.extraction_run_id != run["id"] and _applies_to(r, care)]
    reviews = rule_store.latest_rule_reviews(conn, [r.id for r in added])
    out = [
        {
            "change": "added",
            "on": reviews[r.id]["reviewed_at"].date().isoformat() if r.id in reviews else None,
            "by": reviews.get(r.id, {}).get("reviewer"),
            "rule": rule_card(r),
        }
        for r in added
    ]
    retired = conn.execute(
        "SELECT t.rule_id, t.retired_on, t.reviewer FROM rule_retirement t "
        "JOIN rule r ON r.id = t.rule_id WHERE r.jurisdiction = %s ORDER BY t.id",
        (jurisdiction,),
    ).fetchall()
    for row in retired:
        rule = rule_store.rule_by_id(conn, row["rule_id"])
        if rule is not None and _applies_to(rule, care):
            out.append(
                {
                    "change": "retired",
                    "on": row["retired_on"].isoformat(),
                    "by": row["reviewer"],
                    "rule": rule_card(rule),
                }
            )
    return sorted(out, key=lambda item: item["on"] or "", reverse=True)


def dates_ahead(live: list[Rule], care: str, today: date) -> list[dict]:
    """Live rules that start or end within the window, soonest first."""
    first, last = today - LOOK_BACK, today + LOOK_AHEAD
    events = []
    for rule in live:
        if not _applies_to(rule, care):
            continue
        for event, on in (("starts", rule.effective_from), ("ends", rule.effective_to)):
            if on is not None and first <= on <= last:
                events.append(
                    {
                        "event": event,
                        "on": on.isoformat(),
                        "past": on < today,
                        "rule": rule_card(rule),
                    }
                )
    return sorted(events, key=lambda item: (item["on"], item["rule"]["id"]))


def source_changes(conn: Connection, live: list[Rule]) -> list[dict]:
    """Cited documents that read differently at the monthly re-check."""
    urls = sorted({r.source_url for r in live if r.source_url})
    rows = conn.execute(
        "SELECT url, max(detected_at) AS at FROM source_change WHERE url = ANY(%s) GROUP BY url",
        (urls,),
    ).fetchall()
    return [{"url": row["url"], "detected_at": row["at"].date().isoformat()} for row in rows]


def _place(conn: Connection, code: str, name: str, jurisdiction: str, care: str, today: date):
    live = preflight.rules_for(conn, jurisdiction)
    return {
        "code": code,
        "name": name,
        "page": page_changes(conn, jurisdiction) if jurisdiction != scope.FEDERAL else None,
        "rule_changes": rule_changes(conn, jurisdiction, live, care),
        "dates": dates_ahead(live, care, today),
        "law_changed": source_changes(conn, live),
    }


def what_changed(conn: Connection, states: list[str], care: str, today: date) -> dict[str, Any]:
    """Everything that moved or is due for these states and this line of care."""
    held = [code for code in states if code in scope.STATE_JURISDICTIONS]
    places = [
        _place(
            conn, code, STATE_NAMES.get(code, code), scope.STATE_JURISDICTIONS[code], care, today
        )
        for code in held
    ]
    places.append(_place(conn, FEDERAL_CODE, FEDERAL_NAME, scope.FEDERAL, care, today))
    return {
        "care": care,
        "today": today.isoformat(),
        "window": {
            "from": (today - LOOK_BACK).isoformat(),
            "to": (today + LOOK_AHEAD).isoformat(),
        },
        "not_held": [code for code in states if code not in scope.STATE_JURISDICTIONS],
        "places": places,
    }
