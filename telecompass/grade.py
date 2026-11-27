"""Grade extracted rules against CCHP's "At a Glance" answers and write the results file (D10).

Plain Python, no model. The same rules always give the same grade.
"""

import json
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from telecompass import extract, rule_store, scope, store
from telecompass.db import Connection
from telecompass.models import GlanceAnswer, Rule

RESULTS_DIR = Path("evals") / "results"

AGREE = "agree"
AGREE_NOTHING_FOUND = "agree_nothing_found"
MISS = "miss"
WRONG = "wrong"

# CCHP's short names for compacts -> ours.
CCHP_COMPACTS = {
    "ASLP": "ASLP",
    "CC": "CC",
    "IMLC": "IMLC",
    "NLC": "NLC",
    "PSY": "PSYPACT",
    "PTC": "PT",
}

Test = Callable[[Rule], bool]


@dataclass(frozen=True)
class KeyLine:
    """One answer-key line and how our rules answer it."""

    section: str
    question: str
    rule_type: str
    yes_if: Test
    no_if: Test | None = None
    how: str = ""


def _medicaid(modality: str) -> KeyLine:
    names = {
        "live_video": "Live Video",
        "store_and_forward": "Store-and-Forward",
        "remote_patient_monitoring": "Remote Patient Monitoring",
        "audio_only": "Audio Only",
    }
    return KeyLine(
        "MEDICAID REIMBURSEMENT",
        names[modality],
        scope.MEDICAID_MODALITY,
        yes_if=lambda r: r.modality == modality and r.effect == "allow",
        no_if=lambda r: r.modality == modality and r.effect == "deny",
        how=f"yes: an allow rule for {modality}. no: a deny rule for it.",
    )


KEY_LINES = [
    _medicaid("live_video"),
    _medicaid("store_and_forward"),
    _medicaid("remote_patient_monitoring"),
    _medicaid("audio_only"),
    KeyLine(
        "PRIVATE PAYER LAW",
        "Law Exists",
        scope.PRIVATE_PAYER_PARITY,
        yes_if=lambda r: True,
        how="yes: any private payer rule that passed the quote check.",
    ),
    KeyLine(
        "PRIVATE PAYER LAW",
        "Payment Parity",
        scope.PRIVATE_PAYER_PARITY,
        yes_if=lambda r: r.aspect == "payment_parity" and r.effect == "require",
        no_if=lambda r: r.aspect == "payment_parity" and r.effect == "deny",
        how="yes: a rule that requires payment parity. no: a rule that rules it out.",
    ),
    KeyLine(
        "PROFESSIONAL REQUIREMENTS",
        "Limited Licensure Exceptions",
        scope.CROSS_STATE_LICENSURE,
        yes_if=lambda r: r.aspect == "licensure_exception" and r.effect == "allow",
        how="yes: an allow rule with aspect licensure_exception.",
    ),
    KeyLine(
        "PROFESSIONAL REQUIREMENTS",
        "Telehealth Specific License/Registration Process",
        scope.CROSS_STATE_LICENSURE,
        yes_if=lambda r: r.aspect == "telehealth_registration" and r.effect != "deny",
        how="yes: an allow or require rule with aspect telehealth_registration.",
    ),
    KeyLine(
        "PROFESSIONAL REQUIREMENTS",
        "Consent Requirements",
        scope.CONSENT,
        yes_if=lambda r: r.effect == "require",
        how="yes: a rule that requires consent.",
    ),
]
COMPACTS_QUESTION = ("PROFESSIONAL REQUIREMENTS", "Licensure Compacts")


def verified(rules: list[Rule]) -> list[Rule]:
    """Rules that carry a quote which passed the check. Only these count towards an answer."""
    return [rule for rule in rules if rule.quote_verified and rule.effect != "silent"]


def our_answer(line: KeyLine, rules: list[Rule]) -> str:
    """yes, no or silent, from verified rules of the line's rule type."""
    relevant = [rule for rule in verified(rules) if rule.rule_type == line.rule_type]
    if any(line.yes_if(rule) for rule in relevant):
        return "yes"
    if line.no_if is not None and any(line.no_if(rule) for rule in relevant):
        return "no"
    return "silent"


def compare(cchp: str, ours: str) -> str:
    """How our answer stands against CCHP's yes or no."""
    if cchp == ours:
        return AGREE
    if ours == "silent":
        return MISS if cchp == "yes" else AGREE_NOTHING_FOUND
    return WRONG


def yes_or_no(answer: str) -> str | None:
    word = answer.strip().lower()
    if word.startswith("yes"):
        return "yes"
    if word.startswith("no"):
        return "no"
    return None


def grade_lines(answers: list[GlanceAnswer], rules: list[Rule]) -> list[dict[str, Any]]:
    """One graded row per answer-key line that the five rule types cover."""
    by_question = {(a.section, a.question): a.answer for a in answers}
    graded = []
    for line in KEY_LINES:
        cchp_text = by_question.get((line.section, line.question))
        cchp = yes_or_no(cchp_text) if cchp_text else None
        if cchp is None:
            continue  # the page has no such line, or it is not a yes/no line
        ours = our_answer(line, rules)
        graded.append(
            {
                "section": line.section,
                "question": line.question,
                "rule_type": line.rule_type,
                "cchp": cchp,
                "ours": ours,
                "outcome": compare(cchp, ours),
                "how": line.how,
            }
        )
    compacts = by_question.get(COMPACTS_QUESTION)
    if compacts:
        graded.append(_grade_compacts(compacts, rules))
    return graded


def _grade_compacts(cchp_text: str, rules: list[Rule]) -> dict[str, Any]:
    listed = [part.strip() for part in cchp_text.split("(")[0].split(",") if part.strip()]
    theirs = {CCHP_COMPACTS.get(name, name) for name in listed}
    ours = {
        rule.compact
        for rule in verified(rules)
        if rule.aspect == "compact_membership" and rule.effect != "deny" and rule.compact
    }
    if ours == theirs:
        outcome = AGREE
    elif ours <= theirs:
        outcome = MISS
    else:
        outcome = WRONG
    return {
        "section": COMPACTS_QUESTION[0],
        "question": COMPACTS_QUESTION[1],
        "rule_type": scope.CROSS_STATE_LICENSURE,
        "cchp": sorted(theirs),
        "ours": sorted(ours),
        "outcome": outcome,
        "how": "agree: our verified compact_membership rules name exactly CCHP's compacts.",
    }


def rule_counts(rules: list[Rule]) -> dict[str, Any]:
    quoted = [rule for rule in rules if rule.effect != "silent"]
    passed = sum(1 for rule in quoted if rule.quote_verified)
    return {
        "total": len(rules),
        "silent": len(rules) - len(quoted),
        "by_status": dict(Counter(rule.status for rule in rules)),
        "by_rule_type": dict(Counter(rule.rule_type for rule in rules)),
        "quote_check": {
            "checked": len(quoted),
            "passed": passed,
            "pass_rate": round(passed / len(quoted), 4) if quoted else None,
        },
    }


def entry_counts(items: list[dict[str, Any]]) -> dict[str, Any]:
    gaps = [extract.SOURCE_NOT_FETCHABLE, extract.SOURCE_NOT_FETCHED, extract.MODEL_FAILED,
            extract.CAP_REACHED, extract.NO_SOURCE_LINE]  # fmt: skip
    return {
        "in_scope": len(items),
        "by_outcome": dict(Counter(item["outcome"] for item in items)),
        "sources_cut_to_fit": sum(1 for item in items if item["source_cut"]),
        "without_rules": [
            {
                "category": item["category"],
                "topic": item["topic"],
                "subtopic": item["subtopic"],
                "outcome": item["outcome"],
                "note": item["note"],
            }
            for item in items
            if item["outcome"] in gaps
        ],
    }


def label_summary(conn: Connection, run_id: int, rules: list[Rule]) -> dict[str, Any]:
    """The person's labels for the run's sample. Empty until someone has labelled."""
    sample = rule_store.sample_for(conn, run_id)
    labels = rule_store.latest_labels(conn, run_id)
    by_id = {rule.id: rule for rule in rules}
    items = [
        {
            "rule_id": rule_id,
            "rule_type": by_id[rule_id].rule_type,
            "verdict": labels[rule_id]["verdict"],
            "note": labels[rule_id]["note"],
            "labeller": labels[rule_id]["labeller"],
            "labelled_at": labels[rule_id]["labelled_at"].isoformat(),
        }
        for rule_id in sample
        if rule_id in labels and rule_id in by_id
    ]
    verdicts = Counter(item["verdict"] for item in items)
    return {
        "sample_size": len(sample),
        "labelled": len(items),
        "right": verdicts.get("right", 0),
        "wrong": verdicts.get("wrong", 0),
        "cannot_tell": verdicts.get("cannot_tell", 0),
        "labellers": sorted({item["labeller"] for item in items}),
        "items": items,
        "note": "Labels are written only by a person using the labelling page.",
    }


def build_results(conn: Connection, jurisdiction: str, now: datetime) -> dict[str, Any]:
    """Everything the results file holds, read from the database."""
    run = rule_store.latest_run(conn, jurisdiction)
    if run is None:
        raise LookupError(f"No extraction run for {jurisdiction} yet. Run: extract {jurisdiction}")
    snapshot = store.latest_snapshot(conn, jurisdiction)
    rules = rule_store.rules_for(conn, run["id"])
    lines = grade_lines(store.answers_for(conn, run["parse_run_id"]), rules)
    outcomes = Counter(line["outcome"] for line in lines)
    totals = rule_store.call_totals(conn, run["id"])
    fetched = f"{snapshot.fetched_at:%Y-%m-%d}" if snapshot else "unknown"
    return {
        "jurisdiction": jurisdiction,
        "generated_at": now.isoformat(),
        "not_legal_advice": f"Not legal advice. Sources last fetched {fetched}.",
        "run": {
            "id": run["id"],
            "model": run["model"],
            "started_at": run["started_at"].isoformat(),
            "cap_usd": float(run["cap_usd"]),
            "parse_run_id": run["parse_run_id"],
        },
        "cost": {
            "model_calls": totals["calls"],
            "failed_calls": totals["failed"],
            "input_tokens": int(totals["input_tokens"]),
            "cached_tokens": int(totals["cached_tokens"]),
            "output_tokens": int(totals["output_tokens"]),
            "cost_usd": float(totals["cost_usd"]),
        },
        "entries": entry_counts(rule_store.items_for(conn, run["id"])),
        "rules": rule_counts(rules),
        "answer_key": {
            "lines": lines,
            "counts": {
                name: outcomes.get(name, 0) for name in (AGREE, AGREE_NOTHING_FOUND, MISS, WRONG)
            },
            "matched": outcomes.get(AGREE, 0) + outcomes.get(AGREE_NOTHING_FOUND, 0),
            "total": len(lines),
            "caveat": (
                "One state and at most ten lines: too few for an interval. 'agree_nothing_found' "
                "means CCHP says No and we found no rule, which is agreement by absence. Online "
                "prescribing has no answer-key line and is covered by the labels only."
            ),
        },
        "labels": label_summary(conn, run["id"], rules),
    }


def write_results(results: dict[str, Any], directory: Path = RESULTS_DIR) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"extraction_{results['jurisdiction']}.json"
    path.write_text(json.dumps(results, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path
