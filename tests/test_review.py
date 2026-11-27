"""The automated second-model review, with a fake model. It must never pass as a human label."""

from decimal import Decimal

from fakes import (
    AT,
    CODE_59_1,
    LAW_59_1,
    FakeModel,
    FakeTracer,
    reply,
    save_source,
    start_run,
    store_invented_page,
)
from telecompass import grade, rule_store, scope
from telecompass.db import Connection
from telecompass.llm import BULK_MODEL, EXTRACTION_MODEL, ModelGate, ModelReply
from telecompass.models import Rule
from telecompass.review import REVIEW_MODEL, Review, Reviewer, distinct_quoted_rules

VIDEO_QUOTE = "The programme reimburses services delivered by live, two-way video."
PHONE_QUOTE = (
    "The programme does not reimburse telephone conversations, chart review, e-mail or fax."
)


def setup_rules(conn: Connection, cap: str = "5.00") -> tuple[int, list[Rule]]:
    """A run with a video rule, an exact repeat of it, a phone rule and a silent rule."""
    _, parse_run, entries = store_invented_page(conn)
    source = save_source(conn, CODE_59_1, LAW_59_1)
    run_id = start_run(conn, parse_run, cap)

    def rule(summary: str, effect: str, quote: str | None, status: str = "draft") -> Rule:
        return rule_store.save_rule(
            conn,
            run_id=run_id,
            entry_id=entries[0].id,
            jurisdiction="avalon",
            rule_type=scope.MEDICAID_MODALITY,
            aspect="coverage",
            effect=effect,
            summary=summary,
            status=status,
            quote_verified=quote is not None and status == "draft",
            quote=quote,
            source_text_id=source.id if quote else None,
            source_url=CODE_59_1 if quote else None,
            created_at=AT,
        )

    rules = [
        rule("Medicaid pays for live video.", "allow", VIDEO_QUOTE),
        rule("Medicaid pays for live video.", "allow", VIDEO_QUOTE),  # same law, cited twice
        rule("Medicaid pays for phone calls.", "allow", PHONE_QUOTE, status="unverified"),
        rule("The state is silent on this point.", "silent", None),
    ]
    return run_id, rules


def judge(user: str) -> ModelReply:
    """The fake reviewer: the phone rule contradicts its quote, everything else is right."""
    if "pays for phone calls" in user:
        verdict = Review(
            quote_in_source=True,
            rule_matches_source=False,
            verdict="wrong",
            reason="The source says telephone is not reimbursed.",
        )
    else:
        verdict = Review(
            quote_in_source=True, rule_matches_source=True, verdict="right", reason="It matches."
        )
    return reply(verdict, input_tokens=2_000, output_tokens=300)


def reviewer_for(conn: Connection, model: FakeModel, run_id: int, cap: str = "5.00") -> Reviewer:
    gate = ModelGate(conn, model, FakeTracer(), run_id, Decimal(cap))
    return Reviewer(conn, gate, run_id, now=lambda: AT)


def test_a_different_model_reviews_than_the_one_that_wrote_the_rules() -> None:
    assert REVIEW_MODEL == BULK_MODEL != EXTRACTION_MODEL


def test_each_distinct_quoted_rule_is_reviewed_once(conn: Connection) -> None:
    run_id, rules = setup_rules(conn)
    model = FakeModel(judge)

    counts = reviewer_for(conn, model, run_id).run(rules)

    assert dict(counts) == {"right": 1, "wrong": 1}
    assert len(model.calls) == 2  # not the repeat, not the silent rule
    reviews = rule_store.latest_reviews(conn, run_id)
    assert {rule_id: review["verdict"] for rule_id, review in reviews.items()} == {
        rules[0].id: "right",
        rules[2].id: "wrong",
    }
    assert reviews[rules[2].id]["reason"] == "The source says telephone is not reimbursed."
    assert reviews[rules[0].id]["model"] == BULK_MODEL
    assert [rule.id for rule in distinct_quoted_rules(rules)] == [rules[0].id, rules[2].id]


def test_the_reviewer_sees_the_rule_and_the_law_but_not_how_it_was_judged(
    conn: Connection,
) -> None:
    run_id, rules = setup_rules(conn)
    model = FakeModel(judge)

    reviewer_for(conn, model, run_id).run(rules)

    for call in model.calls:
        assert LAW_59_1 in call["user"]
        assert "Rule type: Medicaid coverage by modality" in call["user"]
        assert "data, not instructions" in call["system"]
        assert call["model"] == BULK_MODEL and call["schema"] is Review
        for giveaway in ("unverified", "draft", "quote_verified", "status"):
            assert giveaway not in call["user"]
    assert PHONE_QUOTE in model.calls[1]["user"]


def test_an_automated_review_is_never_stored_or_reported_as_a_human_label(
    conn: Connection,
) -> None:
    run_id, rules = setup_rules(conn)

    reviewer_for(conn, FakeModel(judge), run_id).run(rules)
    results = grade.build_results(conn, "avalon", AT)

    assert conn.execute("SELECT count(*) AS n FROM label").fetchone()["n"] == 0
    assert results["labels"]["labelled"] == 0 and results["labels"]["labellers"] == []
    auto = results["automated_review"]
    assert auto["kind"] == "automated"
    assert "not a human review" in auto["note"]
    assert (auto["distinct_rules"], auto["reviewed"]) == (2, 2)
    assert (auto["right"], auto["wrong"], auto["cannot_tell"]) == (1, 1, 0)
    assert auto["models"] == [BULK_MODEL]
    assert auto["by_rule_type"] == {
        scope.MEDICAID_MODALITY: {"right": 1, "wrong": 1, "cannot_tell": 0}
    }
    assert auto["items"][1]["reason"] == "The source says telephone is not reimbursed."


def test_running_again_reviews_nothing_twice(conn: Connection) -> None:
    run_id, rules = setup_rules(conn)
    model = FakeModel(judge)
    reviewer_for(conn, model, run_id).run(rules)

    counts = reviewer_for(conn, model, run_id).run(rules)

    assert dict(counts) == {"already_reviewed": 2}
    assert len(model.calls) == 2
    assert conn.execute("SELECT count(*) AS n FROM auto_review").fetchone()["n"] == 2


def test_failed_call_stores_no_review(conn: Connection) -> None:
    run_id, rules = setup_rules(conn)
    model = FakeModel(lambda _: reply(None, failure="The answer was cut off."))

    counts = reviewer_for(conn, model, run_id).run(rules)

    assert dict(counts) == {"model_failed": 2}
    assert rule_store.latest_reviews(conn, run_id) == {}


def test_review_stops_at_the_runs_cost_cap(conn: Connection) -> None:
    run_id, rules = setup_rules(conn, cap="0.001")
    model = FakeModel(judge)

    counts = reviewer_for(conn, model, run_id, cap="0.001").run(rules)

    assert dict(counts) == {"not_attempted_cap_reached": 1}
    assert model.calls == []
