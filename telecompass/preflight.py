"""Run the engine for one visit: load the rules, decide, store the decision, print it (D13)."""

import secrets
from datetime import date, datetime

from psycopg.types.json import Jsonb

from telecompass import rule_store, scope
from telecompass.db import Connection
from telecompass.engine import Decision, Evidence, Line, Prescription, Verdict, Visit, decide
from telecompass.models import Rule
from telecompass.review import distinct_quoted_rules

QUOTE_CHARS = 400
ITEMS_SHOWN = 4
VERDICT_WORDS = {
    Verdict.ALLOWED: "ALLOWED",
    Verdict.CONDITIONS: "ALLOWED WITH CONDITIONS",
    Verdict.NOT_ALLOWED: "NOT ALLOWED",
    Verdict.SILENT: "SILENT (we hold no rule on this)",
    Verdict.NOT_APPLICABLE: "DOES NOT APPLY",
}


def demo_visit(on: date) -> Visit:
    """The plan's example: an invented visit, not a real patient."""
    return Visit(
        profession="psychiatrist",
        licensed_in=["NY"],
        patient_state="FL",
        modality="audio_only",
        payer="medicaid",
        service="psychiatric medication management",
        service_category="behavioral_health",
        prescription=Prescription(drug="a stimulant", schedule="II", renewal=True),
        visit_date=on,
    )


def rules_for(conn: Connection, jurisdiction: str) -> list[Rule]:
    """The distinct rules of a jurisdiction's newest extraction run. Empty if it has none."""
    run = rule_store.latest_run(conn, jurisdiction)
    if run is None:
        return []
    reviews = rule_store.latest_reviews(conn, run["id"])
    rules = distinct_quoted_rules(rule_store.rules_for(conn, run["id"]))
    return [
        rule.model_copy(update={"auto_review": reviews.get(rule.id, {}).get("verdict")})
        for rule in rules
    ]


def decide_visit(conn: Connection, visit: Visit) -> Decision:
    """Decide a visit from the stored rules, without storing anything."""
    jurisdiction = scope.STATE_JURISDICTIONS.get(visit.patient_state.upper())
    state_rules = rules_for(conn, jurisdiction) if jurisdiction else []
    return decide(visit, state_rules, rules_for(conn, scope.FEDERAL))


def run_preflight(conn: Connection, visit: Visit, now: datetime) -> tuple[Decision, int, str]:
    """Decide a visit from the stored rules and store the decision.

    Returns the decision, its row id and its public id. The public id is random, so a share
    link cannot be guessed from another one.
    """
    decision = decide_visit(conn, visit)
    public_id = secrets.token_urlsafe(9)
    row = conn.execute(
        "INSERT INTO decision (visit, visit_date, answer, rule_ids, created_at, public_id) "
        "VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
        (
            Jsonb(visit.model_dump(mode="json")),
            visit.visit_date,
            Jsonb([line.model_dump(mode="json") for line in decision.lines]),
            decision.rule_ids,
            now,
            public_id,
        ),
    ).fetchone()
    conn.commit()
    return decision, row["id"], public_id


def describe(visit: Visit) -> str:
    parts = [
        f"{visit.profession} licensed in {', '.join(visit.licensed_in) or 'no state'}",
        f"patient in {visit.patient_state}",
        visit.modality.replace("_", " "),
        f"payer {visit.payer}",
    ]
    if visit.registered_in:
        parts.insert(1, f"telehealth registration in {', '.join(visit.registered_in)}")
    if visit.service:
        parts.append(f"service: {visit.service} ({visit.service_category.replace('_', ' ')})")
    if visit.prescription:
        drug = visit.prescription
        detail = f"Schedule {drug.schedule}" if drug.schedule else "not a controlled substance"
        notes = [] if detail in drug.drug else [detail]
        notes += ["renewal"] if drug.renewal else []
        parts.append(f"prescription: {drug.drug}" + (f" ({', '.join(notes)})" if notes else ""))
    return "; ".join(parts) + f"; on {visit.visit_date}"


def _excerpt(text: str) -> str:
    one_line = " ".join(text.split())
    return one_line if len(one_line) <= QUOTE_CHARS else one_line[:QUOTE_CHARS].rstrip() + "..."


def _item_lines(item: Evidence) -> list[str]:
    dates = ""
    if item.effective_from or item.effective_to:
        dates = f" In force {item.effective_from or 'from an unstated date'} to "
        dates += f"{item.effective_to or 'no stated end'}."
    state = "approved" if item.status == "approved" else "draft, not yet approved by a person"
    return [
        f"     - {item.summary}{dates}",
        f'       Law: "{_excerpt(item.quote)}"',
        f"       Source: {item.source_url} (fetched {item.source_fetched})",
        f"       [rule {item.rule_id}, {state}]",
    ]


def _block(heading: str, items: list[Evidence]) -> list[str]:
    if not items:
        return []
    lines = [f"   {heading}"]
    for item in items[:ITEMS_SHOWN]:
        lines += _item_lines(item)
    if len(items) > ITEMS_SHOWN:
        lines.append(
            f"     ... and {len(items) - ITEMS_SHOWN} more rule(s), stored with the decision."
        )
    return lines


def _line_text(number: int, line: Line) -> list[str]:
    out = [f"{number}. {line.title}: {VERDICT_WORDS[line.verdict]}", f"   {line.reason}"]
    out += _block("Based on:", line.evidence)
    out += _block("Conditions:", line.conditions)
    out += _block("Would be allowed if:", line.would_allow)
    return out + [""]


def render(decision: Decision, decision_id: int, sources_fetched: str) -> str:
    """The decision as plain text. Verdicts are words, never colour."""
    out = ["TeleCompass preflight", f"Visit: {describe(decision.visit)}", ""]
    for number, line in enumerate(decision.lines, start=1):
        out += _line_text(number, line)
    out += [
        f"Decision {decision_id} stored with the {len(decision.rule_ids)} rule(s) it rests on.",
        "State rules are shown as fetched. A rule with no stated start date is treated as in "
        "force on any date, so only dated rules change when the date changes.",
        f"Not legal advice. Sources last fetched {sources_fetched}.",
    ]
    return "\n".join(out)
